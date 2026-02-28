#!/usr/bin/env python3
"""CLI entrypoint for code-autopsy xray mode."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
from datetime import datetime, timezone

from xray_core import XrayConfig, discover_source_files, run_xray

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_BASE = SKILL_ROOT / ".autopsy-outputs"
SIMULATION_DEFAULT_WORKSPACE_SUBDIR = "simulations"


def _resolve_executable(binary_name: str, *, env_override: str | None = None) -> tuple[str | None, str | None]:
    if env_override:
        override = os.environ.get(env_override, "").strip()
        if override:
            override_path = Path(override).expanduser()
            if override_path.exists() and os.access(override_path, os.X_OK):
                return override_path.as_posix(), None
            return None, (
                f"{binary_name} override from {env_override} is not executable: {override_path}"
            )

    resolved = shutil.which(binary_name)
    if resolved is not None:
        return resolved, None

    shell_path = os.environ.get("SHELL", "").strip()
    if shell_path:
        shell = Path(shell_path).expanduser()
        if shell.exists() and os.access(shell, os.X_OK):
            completed = subprocess.run(
                [shell.as_posix(), "-lc", f"command -v {binary_name}"],
                check=False,
                capture_output=True,
                text=True,
                shell=False,
            )
            candidate = (completed.stdout or "").strip().splitlines()
            if completed.returncode == 0 and candidate:
                executable = Path(candidate[-1]).expanduser()
                if executable.exists() and os.access(executable, os.X_OK):
                    return executable.as_posix(), None

    hint = f"Set {env_override} to an absolute executable path." if env_override else ""
    detail = f"{binary_name} not found in PATH or login shell."
    if hint:
        detail = f"{detail} {hint}"
    return None, detail


def _build_node_tool_env(*, npm_cmd: str, node_cmd: str, extra_env: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    path_parts: list[str] = []

    for cmd in (node_cmd, npm_cmd):
        parent = Path(cmd).resolve().parent.as_posix()
        if parent not in path_parts:
            path_parts.append(parent)

    current_path = env.get("PATH", "")
    for system_path in ("/usr/bin", "/bin", "/usr/sbin", "/sbin"):
        if system_path not in path_parts:
            path_parts.append(system_path)
    if current_path:
        path_parts.append(current_path)

    env["PATH"] = os.pathsep.join(path_parts)
    if extra_env:
        env.update(extra_env)
    return env


@dataclass
class PreparedSource:
    repo_path: Path
    repo_name: str
    output_root: Path
    cleanup_path: Path | None


def _is_github_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.netloc.lower() != "github.com":
        return False
    parts = [part for part in parsed.path.split("/") if part]
    return len(parts) >= 2


def _parse_github_source(source: str) -> tuple[str, str, str]:
    parsed = urlparse(source.strip())
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise ValueError(f"Invalid GitHub source URL: {source}")

    owner = parts[0]
    repo = parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]

    ref = "HEAD"
    if len(parts) >= 4 and parts[2] == "tree":
        ref = "/".join(parts[3:]) or "HEAD"

    return owner, repo, ref


def _repo_name_from_source(source: str, repo_path: Path | None = None) -> str:
    if repo_path is not None:
        return repo_path.resolve().name

    if _is_github_url(source):
        _, repo, _ = _parse_github_source(source)
        safe_repo = "".join(ch for ch in repo if ch.isalnum() or ch in {"-", "_", "."}).strip("._-")
        return safe_repo or "repository"

    text = source.strip().rstrip("/")
    name = text.split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    safe = "".join(ch for ch in name if ch.isalnum() or ch in {"-", "_", "."}).strip("._-")
    return safe or "repository"


def _resolve_output_base(output: str) -> Path:
    base = Path(output)
    if not base.is_absolute():
        base = SKILL_ROOT / base
    return base


def _safe_extract_tar(archive: tarfile.TarFile, target_dir: Path) -> None:
    base = target_dir.resolve()
    for member in archive.getmembers():
        member_path = (target_dir / member.name).resolve()
        if member_path != base and base not in member_path.parents:
            raise RuntimeError("Unsafe archive path detected while extracting GitHub source.")
    archive.extractall(target_dir)


def _download_github_archive(source: str, source_root: Path) -> Path:
    owner, repo, ref = _parse_github_source(source)
    archive_url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/{quote(ref, safe='')}"

    download_path = source_root / f"{repo}-{int(time.time() * 1000)}.tar.gz"
    request = Request(archive_url, headers={"User-Agent": "code-autopsy-xray"})
    with urlopen(request, timeout=40) as response, download_path.open("wb") as handle:
        shutil.copyfileobj(response, handle)

    unpack_root = Path(tempfile.mkdtemp(prefix=f"{repo}-", dir=source_root.as_posix()))
    with tarfile.open(download_path, "r:gz") as archive:
        _safe_extract_tar(archive, unpack_root)
    download_path.unlink(missing_ok=True)

    extracted_dirs = [path for path in unpack_root.iterdir() if path.is_dir()]
    if len(extracted_dirs) == 1:
        return extracted_dirs[0]
    return unpack_root


def _prepare_source(source: str, output_base: Path, keep_clone: bool) -> PreparedSource:
    output_base.mkdir(parents=True, exist_ok=True)

    if _is_github_url(source):
        repo_name = _repo_name_from_source(source)
        source_root = output_base / "_sources"
        source_root.mkdir(parents=True, exist_ok=True)

        temp_repo_root = Path(
            tempfile.mkdtemp(prefix=f"{repo_name}-", dir=source_root.as_posix())
        )
        temp_dir = temp_repo_root
        try:
            temp_dir = _download_github_archive(source, source_root=temp_repo_root)
        except Exception as exc:  # noqa: BLE001
            print(f"Archive download failed ({exc}). Falling back to shallow git clone.")
            shutil.rmtree(temp_repo_root, ignore_errors=True)
            temp_repo_root = Path(
                tempfile.mkdtemp(prefix=f"{repo_name}-", dir=source_root.as_posix())
            )
            temp_dir = temp_repo_root
            cmd = ["git", "clone", "--depth", "1", source, temp_dir.as_posix()]
            completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
            if completed.returncode != 0:
                raise RuntimeError(
                    "Failed to fetch repository from GitHub URL. "
                    "Archive download and shallow clone both failed.\n"
                    f"clone stdout:\n{completed.stdout}\nclone stderr:\n{completed.stderr}"
                ) from exc

        output_root = output_base / repo_name
        cleanup_path = None if keep_clone else temp_repo_root
        return PreparedSource(
            repo_path=temp_dir,
            repo_name=repo_name,
            output_root=output_root,
            cleanup_path=cleanup_path,
        )

    repo_path = Path(source).resolve()
    if not repo_path.exists() or not repo_path.is_dir():
        raise FileNotFoundError(f"Repository path not found or not a directory: {repo_path}")
    repo_name = _repo_name_from_source(source, repo_path=repo_path)
    output_root = output_base / repo_name
    return PreparedSource(repo_path=repo_path, repo_name=repo_name, output_root=output_root, cleanup_path=None)


def _resolve_simulation_context(provided: str | None) -> Path | None:
    if provided:
        explicit = Path(provided).expanduser().resolve()
        if explicit.exists():
            return explicit
        raise FileNotFoundError(f"Simulation context file does not exist: {explicit}")

    candidates = [
        SKILL_ROOT / "simulation_context.md",
        SKILL_ROOT / ".." / "simulation_context.md",
        Path(__file__).resolve().parents[2] / "simulation_context.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def _make_simulation_run_name(repo_name: str, provided: str | None) -> str:
    if provided:
        return provided

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{repo_name}-{timestamp}-sim"


def _load_simulation_manifest(manifest_path: Path) -> dict[str, object]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    return payload


def _build_ui_checkpoint_rows(manifest: dict[str, object]) -> list[dict[str, object]]:
    raw_checkpoints = manifest.get("checkpoints")
    if not isinstance(raw_checkpoints, list):
        return []

    checkpoints: list[dict[str, object]] = []
    for item in raw_checkpoints:
        if not isinstance(item, dict):
            continue

        raw_iteration = item.get("iteration", 0)
        try:
            iteration = int(raw_iteration)
        except (TypeError, ValueError):
            iteration = 0
        status = str(item.get("status", ""))
        notes = str(item.get("notes", ""))
        changed_files = item.get("files_changed")
        file_count = len(changed_files) if isinstance(changed_files, list) else 0

        checkpoints.append(
            {
                "iteration": iteration,
                "tag": str(item.get("tag", "")),
                "feature": str(item.get("feature", "")),
                "status": status,
                "commit": str(item.get("commit", "")),
                "timestamp_utc": str(item.get("timestamp_utc", "")),
                "notes": notes,
                "changed_files": file_count,
                "red_team_report": str(item.get("red_team_report", "")),
                "blue_team_report": str(item.get("blue_team_report", "")),
                "refactorer_report": str(item.get("refactorer_report", "")),
                "historian_report": str(item.get("historian_report", "")),
            }
        )

    return [entry for entry in checkpoints if entry.get("iteration", 0) > 0]


def _run_simulation_agent(prepared: PreparedSource, args: argparse.Namespace) -> dict[str, object]:
    if args.simulation_max_iterations < 1:
        raise ValueError("--simulation-max-iterations must be >= 1")

    simulation_root = (
        Path(args.simulation_workspace)
        if args.simulation_workspace
        else prepared.output_root / SIMULATION_DEFAULT_WORKSPACE_SUBDIR
    )
    simulation_root.mkdir(parents=True, exist_ok=True)

    run_name = _make_simulation_run_name(prepared.repo_name, args.simulation_run_name)
    simulation_workspace = simulation_root / run_name
    if simulation_workspace.exists():
        simulation_workspace = _next_simulation_dir(simulation_workspace)
        run_name = simulation_workspace.name

    simulate_agent = SKILL_ROOT / "scripts" / "simulate_agent.py"
    if not simulate_agent.exists():
        simulate_agent = SKILL_ROOT.parent / "simulate_agent.py"
    if not simulate_agent.exists():
        raise FileNotFoundError(f"simulate_agent.py not found: {simulate_agent}")

    command = [
        sys.executable,
        str(simulate_agent),
        "--source",
        str(prepared.repo_path),
        "--run-name",
        run_name,
        "--workspace",
        str(simulation_root),
        "--max-iterations",
        str(args.simulation_max_iterations),
        "--weeks-per-iteration",
        "2",
    ]

    if args.simulation_agent_context:
        command.extend(["--agent-context", args.simulation_agent_context])
    else:
        fallback_context = _resolve_simulation_context(None)
        if fallback_context:
            command.extend(["--agent-context", str(fallback_context)])

    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=prepared.repo_path,
        check=False,
    )

    output = (process.stdout or "") + (process.stderr or "")
    manifest_path = simulation_workspace / "run_manifest.json"
    report_path = simulation_workspace / "simulation_report.md"
    if manifest_path.exists():
        manifest = _load_simulation_manifest(manifest_path)
    else:
        manifest = {}
        manifest["status"] = "failed" if process.returncode else "completed"

    summary = {
        "enabled": True,
        "run_name": run_name,
        "status": manifest.get("status", "failed" if process.returncode else "completed"),
        "run_workspace": str(simulation_root),
        "run_dir": str(simulation_workspace),
        "manifest_path": str(manifest_path),
        "report_path": str(report_path),
        "features_requested": len(manifest.get("features_requested", [])) if isinstance(manifest.get("features_requested"), list) else None,
        "features_simulated": manifest.get("features_simulated", 0),
        "simulation_weeks": manifest.get("simulation_weeks"),
        "weeks_per_iteration": manifest.get("weeks_per_iteration", 2),
        "created_at_utc": manifest.get("created_at_utc"),
        "exit_code": process.returncode,
        "command": " ".join(command),
    }

    if process.returncode != 0:
        summary["error"] = output.strip() or "simulation command failed"
        return summary

    if manifest:
        summary["status"] = manifest.get("status", "completed")
        summary["status_note"] = manifest.get("status", "")
        summary["features_requested"] = len(manifest.get("features_requested", []))
        summary["features_simulated"] = manifest.get("features_simulated", 0)
        summary["top_hotspots"] = manifest.get("top_hotspots", [])
        summary["source"] = manifest.get("source", "")
        summary["simulation_start_iso"] = manifest.get("simulation_start_iso")
        summary["checkpoints"] = _build_ui_checkpoint_rows(manifest)
        simulation_summary = manifest.get("simulation_summary")
        if isinstance(simulation_summary, dict):
            summary["summary"] = simulation_summary
    else:
        summary["status"] = "completed"
        summary["status_note"] = "simulation finished but manifest was not generated"

    return summary


def _next_simulation_dir(base: Path) -> Path:
    for index in range(1, 50):
        candidate = base.with_name(f"{base.name}-{index}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not allocate simulation run directory for {base}")


def _write_simulation_into_dashboard(output_root: Path, simulation_summary: dict[str, object]) -> None:
    dashboard_path = output_root / "dashboard_state.json"
    if not dashboard_path.exists():
        return

    payload = json.loads(dashboard_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return

    payload["simulation"] = simulation_summary
    if isinstance(payload.get("kiv"), dict):
        payload["kiv"]["simulation_attached"] = True
    else:
        payload["kiv"] = {"graph_3d": "Deferred to Phase 2", "simulation_attached": True}
    with dashboard_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _run_node_script(script_path: Path, args: list[str], cwd: Path) -> tuple[bool, str]:
    node_cmd, resolve_error = _resolve_executable("node", env_override="AUTOPSY_NODE_BIN")
    if node_cmd is None:
        return False, f"Node.js not found. Install Node 18+ to run viewer tooling. {resolve_error}"

    cmd = [node_cmd, script_path.as_posix(), *args]
    try:
        completed = subprocess.run(
            cmd,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return False, f"Failed to launch Node script: {exc}"

    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode != 0:
        return False, output.strip() or f"Script failed with exit code {completed.returncode}"
    return True, output.strip()


def export_images(output_root: Path) -> list[str]:
    warnings: list[str] = []
    viewer_dir = SKILL_ROOT / "viewer"
    script_path = viewer_dir / "scripts" / "export-images.mjs"

    if not script_path.exists():
        warnings.append("Image export script missing; skipped PNG generation.")
        return warnings

    images_dir = output_root / "images"
    ok, message = _run_node_script(
        script_path,
        ["--source", output_root.as_posix(), "--target", images_dir.as_posix()],
        viewer_dir,
    )
    if not ok:
        warnings.append(f"PNG export skipped: {message}")
    elif message:
        print(message)

    return warnings


def _snapshot(files: Iterable[Path]) -> dict[str, float]:
    result = {}
    for path in files:
        try:
            result[path.as_posix()] = path.stat().st_mtime
        except OSError:
            continue
    return result


def _is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.6)
        return sock.connect_ex((host, port)) == 0


def _run_npm_install(viewer_dir: Path) -> tuple[bool, str]:
    npm_cmd, resolve_error = _resolve_executable("npm", env_override="AUTOPSY_NPM_BIN")
    if npm_cmd is None:
        return False, f"npm not found. Install Node.js/npm to launch the viewer. {resolve_error}"
    node_cmd, node_error = _resolve_executable("node", env_override="AUTOPSY_NODE_BIN")
    if node_cmd is None:
        return False, f"node not found for npm execution. Install Node.js. {node_error}"

    completed = subprocess.run(
        [npm_cmd, "install"],
        cwd=viewer_dir,
        check=False,
        capture_output=True,
        text=True,
        shell=False,
        env=_build_node_tool_env(npm_cmd=npm_cmd, node_cmd=node_cmd),
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode != 0:
        return False, output.strip() or "npm install failed"
    return True, output.strip()


def _start_viewer_server(viewer_dir: Path, port: int, output_base: Path) -> tuple[bool, str]:
    npm_cmd, resolve_error = _resolve_executable("npm", env_override="AUTOPSY_NPM_BIN")
    if npm_cmd is None:
        return False, f"npm not found. Install Node.js/npm to launch the viewer. {resolve_error}"
    node_cmd, node_error = _resolve_executable("node", env_override="AUTOPSY_NODE_BIN")
    if node_cmd is None:
        return False, f"node not found for npm execution. Install Node.js. {node_error}"

    if _is_port_open("127.0.0.1", port):
        return True, f"Viewer already running on port {port}."

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )

    try:
        env = _build_node_tool_env(
            npm_cmd=npm_cmd,
            node_cmd=node_cmd,
            extra_env={"AUTOPSY_OUTPUT_ROOT": output_base.as_posix()},
        )
        log_dir = output_base / "_viewer-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"viewer-{port}.log"
        log_handle = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            [npm_cmd, "run", "dev", "--", "--port", str(port)],
            cwd=viewer_dir,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            shell=False,
            env=env,
            creationflags=creationflags,
            start_new_session=True,
        )
        log_handle.close()
    except OSError as exc:
        return False, f"Unable to launch viewer dev server: {exc}"

    deadline = time.time() + 60
    while time.time() < deadline:
        if _is_port_open("127.0.0.1", port):
            return True, f"Viewer started on port {port}."
        if process.poll() is not None:
            detail = f"Viewer process exited with code {process.returncode}. Log: {log_path}"
            try:
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                if lines:
                    tail = "\n".join(lines[-20:])
                    detail = f"{detail}\nLast output:\n{tail}"
            except OSError:
                pass
            return False, detail
        time.sleep(0.4)

    detail = f"Viewer did not start on port {port} within timeout. Log: {log_path}"
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if lines:
            tail = "\n".join(lines[-20:])
            detail = f"{detail}\nLast output:\n{tail}"
    except OSError:
        pass
    return False, detail


def _open_viewer_url(viewer_url: str) -> tuple[bool, str]:
    browser_error = ""
    try:
        if webbrowser.open(viewer_url, new=2):
            return True, "Browser opened via Python webbrowser."
    except Exception as exc:  # noqa: BLE001
        browser_error = str(exc)

    if sys.platform == "darwin":
        fallback_cmd = ["open", viewer_url]
    elif sys.platform == "win32":
        fallback_cmd = ["cmd", "/c", "start", "", viewer_url]
    else:
        fallback_cmd = ["xdg-open", viewer_url]

    binary = fallback_cmd[0]
    if binary != "cmd" and shutil.which(binary) is None:
        detail = f"Fallback launcher '{binary}' not found."
        if browser_error:
            detail = f"{detail} webbrowser error: {browser_error}"
        return False, detail

    completed = subprocess.run(
        fallback_cmd,
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    if completed.returncode == 0:
        return True, f"Browser opened via fallback launcher '{binary}'."

    detail = (completed.stderr or completed.stdout or "").strip()
    if not detail:
        detail = f"Fallback launcher '{binary}' exited with code {completed.returncode}."
    if browser_error:
        detail = f"{detail} webbrowser error: {browser_error}"
    return False, detail


def _launch_viewer(repo_name: str, port: int, open_browser: bool, output_base: Path) -> None:
    viewer_dir = SKILL_ROOT / "viewer"

    if not viewer_dir.exists():
        raise RuntimeError("Viewer directory missing; cannot launch UI.")

    ok, install_message = _run_npm_install(viewer_dir)
    if not ok:
        raise RuntimeError(f"Viewer dependency install failed: {install_message}")
    if install_message:
        print(install_message)

    ok, start_message = _start_viewer_server(viewer_dir, port, output_base)
    if not ok:
        raise RuntimeError(start_message)
    print(start_message)

    viewer_url = f"http://localhost:{port}/?repo={quote(repo_name)}&tab=architecture_services"
    print(f"Viewer URL: {viewer_url}")

    if open_browser:
        opened, open_message = _open_viewer_url(viewer_url)
        if not opened:
            raise RuntimeError(
                "Viewer started but browser could not be opened automatically. "
                f"Open this URL manually: {viewer_url}. Details: {open_message}"
            )
        print(open_message)


def run_once(args: argparse.Namespace) -> tuple[Path, list[str], list[str]]:
    output_base = _resolve_output_base(args.output)
    prepared = _prepare_source(args.source, output_base, keep_clone=args.keep_clone)

    prepared.output_root.mkdir(parents=True, exist_ok=True)

    lang_hints = {hint.strip().lower() for hint in args.lang_hints.split(",") if hint.strip()}
    source_is_github = _is_github_url(args.source)
    source_reference = args.source.strip() if source_is_github else prepared.repo_path.as_posix()
    source_kind = "github_url" if source_is_github else "local_path"
    config = XrayConfig(
        repo_path=prepared.repo_path,
        output_root=prepared.output_root,
        lang_hints=lang_hints,
        max_files=args.max_files,
        source_reference=source_reference,
        source_kind=source_kind,
    )

    started = time.time()
    result = run_xray(config)
    elapsed = time.time() - started
    simulation_summary: dict[str, object] | None = None

    warnings = list(result.get("warnings", []))
    if args.run_simulation:
        try:
            simulation_summary = _run_simulation_agent(prepared, args)
            if isinstance(simulation_summary, dict):
                _write_simulation_into_dashboard(prepared.output_root, simulation_summary)
                status = simulation_summary.get("status")
                exit_code = simulation_summary.get("exit_code")
                if status:
                    warnings.append(f"Simulation status: {status}")
                if exit_code is not None:
                    warnings.append(f"Simulation command exited with code {exit_code}")
        except Exception as error:  # noqa: BLE001
            warnings.append(f"Simulation pipeline failed: {error}")

    if args.viewer:
        _launch_viewer(prepared.repo_name, args.viewer_port, args.open_viewer, output_base)
    elif args.open_viewer:
        warnings.append("--open-viewer has no effect when --no-viewer is set.")
    if args.export_images:
        warnings.extend(export_images(prepared.output_root))

    start_here = result.get("start_here", [])

    print(f"\nGenerated Code-Autopsy X-Ray artifacts at: {prepared.output_root}")
    print(f"Analysis runtime: {elapsed:.2f}s")
    print("3D graph mode: KIV (Phase 2)")

    if start_here:
        print("\nStart Here:")
        for idx, item in enumerate(start_here, start=1):
            print(f"  {idx}. {item}")

    if warnings:
        print("\nWarnings:")
        for warning in warnings:
            print(f"  - {warning}")

    if prepared.cleanup_path is not None:
        shutil.rmtree(prepared.cleanup_path, ignore_errors=True)

    return prepared.output_root, start_here, warnings


def run_watch_loop(args: argparse.Namespace) -> int:
    if _is_github_url(args.source):
        print("Error: watch mode is only supported for local repository paths.")
        return 1

    repo_path = Path(args.source).resolve()
    print("Watch mode enabled (best effort). Press Ctrl+C to stop.")

    files = discover_source_files(
        repo_path,
        max_files=args.max_files,
        lang_hints={hint.strip().lower() for hint in args.lang_hints.split(",") if hint.strip()},
    )
    baseline = _snapshot(files)

    run_once(args)
    loop_args = argparse.Namespace(**vars(args))
    loop_args.viewer = False
    loop_args.open_viewer = False

    try:
        while True:
            time.sleep(max(1.0, args.watch_interval))
            files = discover_source_files(
                repo_path,
                max_files=args.max_files,
                lang_hints={hint.strip().lower() for hint in args.lang_hints.split(",") if hint.strip()},
            )
            current = _snapshot(files)
            if current != baseline:
                print("\nChange detected. Regenerating artifacts...")
                run_once(loop_args)
                baseline = current
    except KeyboardInterrupt:
        print("\nWatch stopped.")
        return 0


def _add_bool_flag(
    parser: argparse.ArgumentParser,
    *,
    name: str,
    default: bool,
    help_text: str,
) -> None:
    dest = name.lstrip("-").replace("-", "_")
    if hasattr(argparse, "BooleanOptionalAction"):
        parser.add_argument(
            name,
            action=argparse.BooleanOptionalAction,
            default=default,
            help=help_text,
        )
        return

    negated = f"--no-{name.lstrip('-')}"
    group = parser.add_mutually_exclusive_group()
    group.add_argument(name, dest=dest, action="store_true", help=help_text)
    group.add_argument(negated, dest=dest, action="store_false", help=f"Disable {name.lstrip('-')}.")
    parser.set_defaults(**{dest: default})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Code-Autopsy X-Ray")
    parser.add_argument("source", help="Local repository path or GitHub URL to analyze")
    parser.add_argument("--mode", default="xray", choices=["xray"], help="Analysis mode")
    parser.add_argument(
        "--output",
        default=".autopsy-outputs",
        help="Output base directory (default: code-autopsy/.autopsy-outputs)",
    )
    _add_bool_flag(
        parser,
        name="--viewer",
        default=True,
        help_text="Install/start viewer frontend after generation (default: true)",
    )
    parser.add_argument("--viewer-port", type=int, default=3000, help="Viewer dev server port")
    _add_bool_flag(
        parser,
        name="--open-viewer",
        default=True,
        help_text="Open browser to viewer URL after launch (default: true)",
    )
    parser.add_argument("--export-images", action="store_true", help="Export PNG snapshots via Playwright")
    parser.add_argument("--watch", action="store_true", help="Best-effort watch mode (regenerate on changes)")
    parser.add_argument("--watch-interval", type=float, default=2.0, help="Polling interval in seconds for watch mode")
    parser.add_argument("--lang-hints", default="", help="Comma-separated language hints, e.g. 'ts,python'")
    parser.add_argument("--max-files", type=int, default=1200, help="Maximum number of source files to analyze")
    parser.add_argument(
        "--keep-clone",
        action="store_true",
        help="Keep temporary downloaded/cloned repository when source is a GitHub URL.",
    )
    _add_bool_flag(
        parser,
        name="--run-simulation",
        default=False,
        help_text="Run the simulation agent after X-Ray analysis.",
    )
    parser.add_argument("--simulation-max-iterations", type=int, default=9, help="Maximum iterations for simulation runs.")
    parser.add_argument(
        "--simulation-workspace",
        default="",
        help="Base folder for simulation runs. Defaults to <output>/{repo}/simulations.",
    )
    parser.add_argument("--simulation-run-name", default="", help="Optional run folder name for simulation output.")
    parser.add_argument("--simulation-agent-context", default="", help="Optional path to simulation agent context file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.watch:
        return run_watch_loop(args)

    try:
        run_once(args)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

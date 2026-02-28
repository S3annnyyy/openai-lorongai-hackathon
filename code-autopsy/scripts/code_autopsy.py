#!/usr/bin/env python3
"""CLI entrypoint for code-autopsy xray mode."""

from __future__ import annotations

import argparse
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

from xray_core import XrayConfig, discover_source_files, run_xray

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_BASE = SKILL_ROOT / ".autopsy-outputs"


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


def _run_node_script(script_path: Path, args: list[str], cwd: Path) -> tuple[bool, str]:
    if shutil.which("node") is None:
        return False, "Node.js not found. Install Node 18+ to run viewer tooling."

    cmd = ["node", script_path.as_posix(), *args]
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
    npm_cmd = shutil.which("npm")
    if npm_cmd is None:
        return False, "npm not found. Install Node.js/npm to launch the viewer."

    completed = subprocess.run(
        [npm_cmd, "install"],
        cwd=viewer_dir,
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode != 0:
        return False, output.strip() or "npm install failed"
    return True, output.strip()


def _start_viewer_server(viewer_dir: Path, port: int, output_base: Path) -> tuple[bool, str]:
    npm_cmd = shutil.which("npm")
    if npm_cmd is None:
        return False, "npm not found. Install Node.js/npm to launch the viewer."

    if _is_port_open("127.0.0.1", port):
        return True, f"Viewer already running on port {port}."

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )

    try:
        env = os.environ.copy()
        env["AUTOPSY_OUTPUT_ROOT"] = output_base.as_posix()
        subprocess.Popen(
            [npm_cmd, "run", "dev", "--", "--port", str(port)],
            cwd=viewer_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            env=env,
            creationflags=creationflags,
        )
    except OSError as exc:
        return False, f"Unable to launch viewer dev server: {exc}"

    deadline = time.time() + 25
    while time.time() < deadline:
        if _is_port_open("127.0.0.1", port):
            return True, f"Viewer started on port {port}."
        time.sleep(0.4)

    return False, f"Viewer did not start on port {port} within timeout."


def _launch_viewer(repo_name: str, port: int, open_browser: bool, output_base: Path) -> list[str]:
    warnings: list[str] = []
    viewer_dir = SKILL_ROOT / "viewer"

    if not viewer_dir.exists():
        warnings.append("Viewer directory missing; skipped viewer launch.")
        return warnings

    ok, install_message = _run_npm_install(viewer_dir)
    if not ok:
        warnings.append(f"Viewer dependency install failed: {install_message}")
        return warnings
    if install_message:
        print(install_message)

    ok, start_message = _start_viewer_server(viewer_dir, port, output_base)
    if not ok:
        warnings.append(start_message)
        return warnings
    print(start_message)

    if open_browser:
        viewer_url = f"http://localhost:{port}/?repo={quote(repo_name)}"
        webbrowser.open(viewer_url)
        print(f"Viewer URL: {viewer_url}")

    return warnings


def run_once(args: argparse.Namespace) -> tuple[Path, list[str], list[str]]:
    output_base = _resolve_output_base(args.output)
    prepared = _prepare_source(args.source, output_base, keep_clone=args.keep_clone)

    prepared.output_root.mkdir(parents=True, exist_ok=True)

    lang_hints = {hint.strip().lower() for hint in args.lang_hints.split(",") if hint.strip()}
    config = XrayConfig(
        repo_path=prepared.repo_path,
        output_root=prepared.output_root,
        lang_hints=lang_hints,
        max_files=args.max_files,
    )

    started = time.time()
    result = run_xray(config)
    elapsed = time.time() - started

    warnings = list(result.get("warnings", []))
    if args.viewer:
        warnings.extend(_launch_viewer(prepared.repo_name, args.viewer_port, args.open_viewer, output_base))
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

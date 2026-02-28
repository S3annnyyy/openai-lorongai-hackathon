#!/usr/bin/env python3
"""Simulate iterative feature improvements on an isolated copy of a codebase."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

DEFAULT_EXCLUDES = [
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".venv",
    "node_modules",
    "dist",
    "build",
]

SUPPORTED_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".java",
    ".go",
    ".rs",
    ".cs",
}

MAX_SCAN_FILES = 2000


@dataclass
class CheckpointRecord:
    iteration: int
    tag: str
    feature: str
    commit: str
    timestamp_utc: str
    status: str
    files_changed: List[str]
    notes: str = ""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_run_name() -> str:
    return f"simulation-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


def sanitize_slug(text: str, max_len: int = 64) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    if not slug:
        slug = "feature"
    return slug[:max_len].rstrip("-")


def symbol_from_slug(slug: str) -> str:
    symbol = re.sub(r"[^a-zA-Z0-9_]", "_", slug)
    if not symbol:
        symbol = "feature"
    if symbol[0].isdigit():
        symbol = f"f_{symbol}"
    return symbol


def is_subpath(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def run_command(args: Sequence[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(args),
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
    )
    if check and completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        details = stderr or stdout or f"exit code {completed.returncode}"
        raise RuntimeError(f"Command failed: {' '.join(args)}\n{details}")
    return completed


def run_shell_command(command: str, cwd: Path) -> Tuple[str, str]:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        shell=True,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        details = "\n".join(part for part in [stdout, stderr] if part)
        raise RuntimeError(f"Iteration command failed ({completed.returncode}): {details}")
    return completed.stdout or "", completed.stderr or ""


def load_features(feature_flags: Iterable[str], features_file: Optional[Path]) -> List[str]:
    features: List[str] = []
    seen = set()

    for feature in feature_flags:
        item = feature.strip()
        if item and item not in seen:
            seen.add(item)
            features.append(item)

    if features_file:
        if not features_file.exists():
            raise ValueError(f"Features file does not exist: {features_file}")
        for line in features_file.read_text(encoding="utf-8-sig").splitlines():
            item = line.strip()
            if not item or item.startswith("#"):
                continue
            if item not in seen:
                seen.add(item)
                features.append(item)

    return features


def detect_preferred_extension(codebase: Path) -> str:
    counts: Dict[str, int] = {}
    scanned = 0

    for file_path in codebase.rglob("*"):
        if not file_path.is_file():
            continue
        ext = file_path.suffix.lower()
        counts[ext] = counts.get(ext, 0) + 1
        scanned += 1
        if scanned >= MAX_SCAN_FILES:
            break

    supported_counts = {ext: count for ext, count in counts.items() if ext in SUPPORTED_EXTENSIONS}
    if not supported_counts:
        return ".txt"

    return max(supported_counts.items(), key=lambda item: item[1])[0]


def build_stub_content(extension: str, index: int, feature: str, slug: str) -> str:
    function_name = f"feature_{index:03d}_{symbol_from_slug(slug)}"

    if extension == ".py":
        return (
            f'"""Simulated feature stub: {feature}"""\n\n'
            f"def {function_name}():\n"
            f"    \"\"\"TODO: implement this feature.\"\"\"\n"
            f"    raise NotImplementedError(\"Implement simulated feature: {feature}\")\n"
        )

    if extension in {".ts", ".tsx"}:
        return (
            f"// Simulated feature stub: {feature}\n"
            f"export function {function_name}(): never {{\n"
            f"  throw new Error(\"TODO: implement simulated feature: {feature}\");\n"
            f"}}\n"
        )

    if extension in {".js", ".jsx"}:
        return (
            f"// Simulated feature stub: {feature}\n"
            f"function {function_name}() {{\n"
            f"  throw new Error(\"TODO: implement simulated feature: {feature}\");\n"
            f"}}\n\n"
            f"module.exports = {{ {function_name} }};\n"
        )

    if extension == ".java":
        class_name = f"Feature{index:03d}{symbol_from_slug(slug).title().replace('_', '')}"
        return (
            f"// Simulated feature stub: {feature}\n"
            f"public class {class_name} {{\n"
            f"    public void run() {{\n"
            f"        throw new UnsupportedOperationException(\"TODO: implement simulated feature: {feature}\");\n"
            f"    }}\n"
            f"}}\n"
        )

    if extension == ".go":
        return (
            "package simulated\n\n"
            f"// Simulated feature stub: {feature}\n"
            f"func {function_name.title().replace('_', '')}() {{\n"
            f"    panic(\"TODO: implement simulated feature: {feature}\")\n"
            "}\n"
        )

    if extension == ".rs":
        return (
            f"// Simulated feature stub: {feature}\n"
            f"pub fn {function_name}() {{\n"
            f"    panic!(\"TODO: implement simulated feature: {feature}\");\n"
            "}\n"
        )

    if extension == ".cs":
        class_name = f"Feature{index:03d}{symbol_from_slug(slug).title().replace('_', '')}"
        return (
            f"// Simulated feature stub: {feature}\n"
            f"public static class {class_name} {{\n"
            "    public static void Run() {\n"
            f"        throw new System.NotImplementedException(\"TODO: implement simulated feature: {feature}\");\n"
            "    }\n"
            "}\n"
        )

    return (
        f"Simulated feature stub: {feature}\n"
        f"Iteration: {index:03d}\n"
        "TODO: implement this feature in the project language.\n"
    )


def append_changelog(codebase: Path, index: int, feature: str, artifact_rel: Path, status: str, notes: str) -> None:
    changelog_path = codebase / "SIMULATION_CHANGELOG.md"
    entry = [
        f"## Iteration {index:03d} - {feature}",
        f"- Timestamp (UTC): {utc_now_iso()}",
        f"- Status: {status}",
        f"- Artifact: {artifact_rel.as_posix()}",
    ]
    if notes:
        entry.append(f"- Notes: {notes}")
    entry.append("")

    with changelog_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(entry))
        handle.write("\n")


def write_iteration_artifacts(
    codebase: Path,
    index: int,
    feature: str,
    slug: str,
    extension: str,
    status: str,
    notes: str,
) -> Path:
    iterations_dir = codebase / ".simulation" / "iterations"
    iterations_dir.mkdir(parents=True, exist_ok=True)

    iteration_note_rel = Path(".simulation") / "iterations" / f"{index:03d}-{slug}.md"
    iteration_note_path = codebase / iteration_note_rel
    iteration_note_path.write_text(
        "\n".join(
            [
                f"# Iteration {index:03d} - {feature}",
                "",
                f"Timestamp (UTC): {utc_now_iso()}",
                f"Status: {status}",
                "",
                "## Summary",
                "- This iteration simulates a feature improvement step.",
                "- Replace placeholder artifacts with real implementation logic.",
                "",
                "## Notes",
                f"- {notes or 'No additional notes.'}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    artifact_dir = codebase / "simulated_features"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_rel = Path("simulated_features") / f"{index:03d}_{slug}{extension}"
    artifact_path = codebase / artifact_rel
    artifact_path.write_text(
        build_stub_content(extension, index, feature, slug),
        encoding="utf-8",
    )

    append_changelog(codebase, index, feature, artifact_rel, status, notes)
    return artifact_rel


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def init_git_repo(codebase: Path) -> None:
    run_command(["git", "init"], cwd=codebase)
    run_command(["git", "config", "user.name", "Simulation Agent"], cwd=codebase)
    run_command(["git", "config", "user.email", "simulation-agent@example.com"], cwd=codebase)


def create_checkpoint(codebase: Path, message: str, tag: str, allow_empty: bool = True) -> Tuple[str, List[str]]:
    run_command(["git", "add", "-A"], cwd=codebase)

    commit_args = ["git", "commit", "-m", message]
    if allow_empty:
        commit_args.insert(2, "--allow-empty")
    run_command(commit_args, cwd=codebase)

    commit_sha = run_command(["git", "rev-parse", "HEAD"], cwd=codebase).stdout.strip()
    changed = run_command(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
        cwd=codebase,
    ).stdout.splitlines()

    run_command(["git", "tag", "-f", tag], cwd=codebase)
    changed_files = [line.strip() for line in changed if line.strip()]
    return commit_sha, changed_files


def copy_source(source: Path, destination: Path, excludes: List[str]) -> None:
    ignore_fn = shutil.ignore_patterns(*excludes)
    shutil.copytree(source, destination, ignore=ignore_fn)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulate iterative feature improvements with checkpoints on a copied codebase.",
    )
    parser.add_argument("--source", required=True, help="Path to the source codebase.")
    parser.add_argument(
        "--workspace",
        default=".simulations",
        help="Directory where simulation runs are created (default: .simulations).",
    )
    parser.add_argument("--run-name", default=None, help="Optional simulation run folder name.")
    parser.add_argument(
        "--feature",
        dest="features",
        action="append",
        default=[],
        help="Feature description. Repeat for multiple features.",
    )
    parser.add_argument(
        "--features-file",
        default=None,
        help="Path to a newline-delimited features file. Lines starting with # are ignored.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Limit the number of features to simulate.",
    )
    parser.add_argument(
        "--iteration-command",
        default=None,
        help=(
            "Optional shell command run each iteration inside the copied codebase. "
            "Supports {feature}, {index}, and {slug} placeholders."
        ),
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Continue remaining iterations even if one iteration command fails.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Additional copy exclude patterns. Repeat flag for multiple values.",
    )
    return parser.parse_args(argv)


def configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    configure_console_encoding()
    args = parse_args(argv)

    source = Path(args.source).expanduser().resolve()
    if not source.exists() or not source.is_dir():
        print(f"Error: source path is not a directory: {source}", file=sys.stderr)
        return 2

    features_file: Optional[Path] = None
    if args.features_file:
        features_file = Path(args.features_file).expanduser().resolve()

    try:
        features = load_features(args.features, features_file)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2

    if not features:
        print("Error: no features provided. Use --feature or --features-file.", file=sys.stderr)
        return 2

    if args.max_iterations is not None:
        if args.max_iterations < 1:
            print("Error: --max-iterations must be >= 1.", file=sys.stderr)
            return 2
        features = features[: args.max_iterations]

    workspace = Path(args.workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    run_name = args.run_name or make_run_name()
    run_dir = workspace / run_name
    if run_dir.exists():
        print(f"Error: run directory already exists: {run_dir}", file=sys.stderr)
        return 2

    codebase_copy = run_dir / "codebase"
    checkpoints_dir = run_dir / "checkpoints"

    excludes = list(dict.fromkeys(DEFAULT_EXCLUDES + list(args.exclude)))
    if is_subpath(run_dir, source):
        excludes.append(workspace.name)
        excludes.append(run_dir.name)
        excludes = list(dict.fromkeys(excludes))

    try:
        run_command(["git", "--version"], cwd=source)
    except RuntimeError as error:
        print(f"Error: git is required but unavailable: {error}", file=sys.stderr)
        return 2

    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        copy_source(source, codebase_copy, excludes)
    except Exception as error:
        print(f"Error: failed to copy source into simulation workspace: {error}", file=sys.stderr)
        return 1

    try:
        init_git_repo(codebase_copy)
    except RuntimeError as error:
        print(f"Error: failed to initialize git checkpoint repo: {error}", file=sys.stderr)
        return 1

    checkpoints: List[CheckpointRecord] = []

    try:
        baseline_sha, baseline_files = create_checkpoint(
            codebase_copy,
            "checkpoint 000: baseline copy",
            "checkpoint-000",
            allow_empty=True,
        )
    except RuntimeError as error:
        print(f"Error: failed to create baseline checkpoint: {error}", file=sys.stderr)
        return 1

    baseline_record = CheckpointRecord(
        iteration=0,
        tag="checkpoint-000",
        feature="Baseline copy",
        commit=baseline_sha,
        timestamp_utc=utc_now_iso(),
        status="ok",
        files_changed=baseline_files,
        notes="Initial isolated snapshot of source codebase.",
    )
    checkpoints.append(baseline_record)
    write_json(checkpoints_dir / "000.json", asdict(baseline_record))

    preferred_extension = detect_preferred_extension(codebase_copy)
    run_failed = False

    for index, feature in enumerate(features, start=1):
        slug = sanitize_slug(feature)
        status = "ok"
        notes = "Simulated feature artifact generated."

        try:
            write_iteration_artifacts(
                codebase_copy,
                index,
                feature,
                slug,
                preferred_extension,
                "planned",
                notes,
            )

            if args.iteration_command:
                stdout, stderr = run_shell_command(
                    args.iteration_command.format(feature=feature, index=index, slug=slug),
                    cwd=codebase_copy,
                )
                log_path = codebase_copy / ".simulation" / "iterations" / f"{index:03d}-{slug}.command.log"
                log_path.write_text(
                    "\n".join(
                        [
                            f"Command: {args.iteration_command}",
                            "",
                            "--- STDOUT ---",
                            stdout.strip(),
                            "",
                            "--- STDERR ---",
                            stderr.strip(),
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
                notes = "Simulated feature artifact generated; iteration command executed."

        except Exception as error:
            status = "failed"
            notes = str(error)
            failure_log = codebase_copy / ".simulation" / "iterations" / f"{index:03d}-{slug}.failure.log"
            failure_log.parent.mkdir(parents=True, exist_ok=True)
            failure_log.write_text(f"{error}\n", encoding="utf-8")
            if not args.keep_going:
                run_failed = True

        try:
            checkpoint_sha, changed_files = create_checkpoint(
                codebase_copy,
                f"checkpoint {index:03d}: {feature}",
                f"checkpoint-{index:03d}",
                allow_empty=True,
            )
        except RuntimeError as error:
            print(f"Error: failed to create checkpoint for iteration {index}: {error}", file=sys.stderr)
            return 1

        record = CheckpointRecord(
            iteration=index,
            tag=f"checkpoint-{index:03d}",
            feature=feature,
            commit=checkpoint_sha,
            timestamp_utc=utc_now_iso(),
            status=status,
            files_changed=changed_files,
            notes=notes,
        )
        checkpoints.append(record)
        write_json(checkpoints_dir / f"{index:03d}.json", asdict(record))

        if run_failed:
            break

    manifest = {
        "source": str(source),
        "workspace": str(workspace),
        "run_dir": str(run_dir),
        "codebase_copy": str(codebase_copy),
        "created_at_utc": utc_now_iso(),
        "features_requested": features,
        "features_simulated": len(checkpoints) - 1,
        "status": "failed" if run_failed else "completed",
        "copy_excludes": excludes,
        "checkpoints": [asdict(item) for item in checkpoints],
    }

    manifest_path = run_dir / "run_manifest.json"
    write_json(manifest_path, manifest)

    print(f"Run directory: {run_dir}")
    print(f"Copied codebase: {codebase_copy}")
    print(f"Manifest: {manifest_path}")
    print("Checkpoints:")
    for item in checkpoints:
        print(
            f"  {item.tag} | {item.commit[:8]} | {item.status} | {item.feature}"
        )

    if run_failed:
        print("Simulation ended early due to iteration failure. Use --keep-going to continue on errors.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

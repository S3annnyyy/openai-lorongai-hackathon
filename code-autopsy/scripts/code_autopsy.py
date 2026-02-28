#!/usr/bin/env python3
"""CLI entrypoint for code-autopsy xray mode."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

from xray_core import XrayConfig, discover_source_files, run_xray


def _resolve_output_root(repo_path: Path, output: str) -> Path:
    base = Path(output)
    if not base.is_absolute():
        base = repo_path / base
    if base.name != "code-autopsy":
        base = base / "code-autopsy"
    return base


def _run_node_script(script_path: Path, args: list[str], cwd: Path) -> tuple[bool, str]:
    if shutil.which("node") is None:
        return False, "Node.js not found. Install Node 18+ to build the viewer and image exports."

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


def build_viewer(output_root: Path) -> list[str]:
    warnings: list[str] = []
    viewer_dir = Path(__file__).resolve().parents[1] / "viewer"
    script_path = viewer_dir / "scripts" / "build-static.mjs"

    if not script_path.exists():
        warnings.append("Viewer build script missing; skipped viewer generation.")
        return warnings

    ok, message = _run_node_script(
        script_path,
        ["--source", output_root.as_posix(), "--target", (output_root / "viewer-static").as_posix()],
        viewer_dir,
    )
    if not ok:
        warnings.append(f"Viewer build failed: {message}")
    elif message:
        print(message)

    return warnings


def export_images(output_root: Path) -> list[str]:
    warnings: list[str] = []
    viewer_dir = Path(__file__).resolve().parents[1] / "viewer"
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


def run_once(args: argparse.Namespace) -> tuple[Path, list[str], list[str]]:
    repo_path = Path(args.repo).resolve()
    output_root = _resolve_output_root(repo_path, args.output)
    output_root.mkdir(parents=True, exist_ok=True)

    lang_hints = {hint.strip().lower() for hint in args.lang_hints.split(",") if hint.strip()}

    config = XrayConfig(
        repo_path=repo_path,
        output_root=output_root,
        lang_hints=lang_hints,
        max_files=args.max_files,
    )

    started = time.time()
    result = run_xray(config)
    elapsed = time.time() - started

    warnings = list(result.get("warnings", []))

    if args.viewer:
        warnings.extend(build_viewer(output_root))

    if args.export_images:
        warnings.extend(export_images(output_root))

    start_here = result.get("start_here", [])

    print(f"\nGenerated Code-Autopsy X-Ray artifacts at: {output_root}")
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

    return output_root, start_here, warnings


def run_watch_loop(args: argparse.Namespace) -> int:
    repo_path = Path(args.repo).resolve()
    print("Watch mode enabled (best effort). Press Ctrl+C to stop.")

    files = discover_source_files(
        repo_path,
        max_files=args.max_files,
        lang_hints={hint.strip().lower() for hint in args.lang_hints.split(",") if hint.strip()},
    )
    baseline = _snapshot(files)

    run_once(args)

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
                run_once(args)
                baseline = current
    except KeyboardInterrupt:
        print("\nWatch stopped.")
        return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Code-Autopsy X-Ray")
    parser.add_argument("repo", help="Local repository path to analyze")
    parser.add_argument("--mode", default="xray", choices=["xray"], help="Analysis mode")
    parser.add_argument("--output", default="docs", help="Output directory root (default: <repo>/docs/code-autopsy)")
    parser.add_argument("--viewer", action="store_true", help="Build interactive Next.js viewer")
    parser.add_argument("--export-images", action="store_true", help="Export PNG snapshots via Playwright")
    parser.add_argument("--watch", action="store_true", help="Best-effort watch mode (regenerate on changes)")
    parser.add_argument("--watch-interval", type=float, default=2.0, help="Polling interval in seconds for watch mode")
    parser.add_argument("--lang-hints", default="", help="Comma-separated language hints, e.g. 'ts,python'")
    parser.add_argument("--max-files", type=int, default=1200, help="Maximum number of source files to analyze")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_path = Path(args.repo).resolve()

    if not repo_path.exists() or not repo_path.is_dir():
        print(f"Error: repository path not found or not a directory: {repo_path}")
        return 1

    if args.watch:
        return run_watch_loop(args)

    run_once(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

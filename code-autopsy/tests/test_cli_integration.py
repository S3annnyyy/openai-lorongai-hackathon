from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_cli_generates_docs_without_viewer(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text(
        "def ping():\n"
        "    return 'pong'\n",
        encoding="utf-8",
    )

    script = Path(__file__).resolve().parents[1] / "scripts" / "code_autopsy.py"

    output_base = tmp_path / "autopsy-out"

    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            str(repo),
            "--mode",
            "xray",
            "--output",
            str(output_base),
            "--no-viewer",
            "--no-open-viewer",
            "--max-files",
            "50",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    output_root = output_base / repo.name
    assert (output_root / "index.md").exists()
    assert "Start Here" in proc.stdout


def test_cli_defaults_attempt_viewer_launch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text(
        "def ping():\n"
        "    return 'pong'\n",
        encoding="utf-8",
    )

    script = Path(__file__).resolve().parents[1] / "scripts" / "code_autopsy.py"
    output_base = tmp_path / "autopsy-out"

    # Force predictable "npm not found" so we can assert default mode hard-fails on UI launch.
    env = {"PATH": "", "SHELL": ""}
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            str(repo),
            "--mode",
            "xray",
            "--output",
            str(output_base),
            "--max-files",
            "50",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert proc.returncode != 0, proc.stderr
    assert "Viewer dependency install failed" in proc.stdout
    assert "npm not found" in proc.stdout

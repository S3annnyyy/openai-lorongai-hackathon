from __future__ import annotations

import subprocess
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

    proc = subprocess.run(
        [
            "python3",
            str(script),
            str(repo),
            "--mode",
            "xray",
            "--output",
            "docs",
            "--max-files",
            "50",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    output_root = repo / "docs" / "code-autopsy"
    assert (output_root / "index.md").exists()
    assert "Start Here" in proc.stdout

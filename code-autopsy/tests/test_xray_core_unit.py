from __future__ import annotations

import json
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from xray_core import XrayConfig, run_xray  # noqa: E402


def test_run_xray_generates_required_artifacts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    (repo / "app.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.get('/health')\n"
        "def health():\n"
        "    return {'ok': True}\n",
        encoding="utf-8",
    )
    (repo / "service.py").write_text(
        "def helper():\n"
        "    return 1\n"
        "def runner():\n"
        "    return helper()\n",
        encoding="utf-8",
    )
    (repo / "schema.prisma").write_text(
        "model User {\n"
        "  id Int @id\n"
        "  email String\n"
        "}\n",
        encoding="utf-8",
    )

    output = repo / "docs" / "code-autopsy"
    config = XrayConfig(repo_path=repo, output_root=output, lang_hints=set(), max_files=100)
    result = run_xray(config)

    assert result["output_root"] == output

    required = [
        "repo.json",
        "graph.json",
        "metrics.json",
        "architecture.mmd",
        "er.mmd",
        "er.dbml",
        "call-graph.mmd",
        "dependencies.mmd",
        "onboarding.md",
        "top-files.md",
        "index.md",
        "dashboard_state.json",
    ]

    for name in required:
        assert (output / name).exists(), f"missing {name}"

    dashboard = json.loads((output / "dashboard_state.json").read_text(encoding="utf-8"))
    assert "kiv" in dashboard
    assert dashboard["kiv"]["graph_3d"].lower().startswith("deferred")

    graph = json.loads((output / "graph.json").read_text(encoding="utf-8"))
    assert graph["edges"]
    assert all("confidence" in edge for edge in graph["edges"])

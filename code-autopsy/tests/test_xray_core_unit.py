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
    assert "terraform_drawio" not in dashboard["diagrams"]

    graph = json.loads((output / "graph.json").read_text(encoding="utf-8"))
    assert graph["edges"]
    assert all("confidence" in edge for edge in graph["edges"])
    assert not (output / "terraform-architecture.drawio").exists()
    assert not (output / "artifacts" / "terraform.json").exists()


def test_run_xray_generates_terraform_drawio_when_tf_present(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    (repo / "main.tf").write_text(
        'provider "aws" {}\n'
        '\n'
        'resource "aws_vpc" "main" {}\n'
        '\n'
        'resource "aws_subnet" "app" {\n'
        "  vpc_id = aws_vpc.main.id\n"
        "  depends_on = [aws_vpc.main]\n"
        "}\n",
        encoding="utf-8",
    )

    output = repo / "docs" / "code-autopsy"
    config = XrayConfig(repo_path=repo, output_root=output, lang_hints=set(), max_files=100)
    run_xray(config)

    drawio = output / "terraform-architecture.drawio"
    terraform_json = output / "artifacts" / "terraform.json"
    assert drawio.exists(), "missing terraform draw.io diagram"
    assert terraform_json.exists(), "missing terraform json artifact"

    drawio_text = drawio.read_text(encoding="utf-8")
    assert "<mxfile" in drawio_text
    assert "Terraform IaC" in drawio_text
    assert "aws_vpc.main" in drawio_text

    terraform = json.loads(terraform_json.read_text(encoding="utf-8"))
    assert terraform["summary"]["providers"] == 1
    assert terraform["summary"]["resources"] == 2
    assert terraform["edges"]

    dashboard = json.loads((output / "dashboard_state.json").read_text(encoding="utf-8"))
    assert "terraform_drawio" in dashboard["diagrams"]
    assert "<mxfile" in dashboard["diagrams"]["terraform_drawio"]

    index_md = (output / "index.md").read_text(encoding="utf-8")
    assert "Terraform IaC (draw.io)" in index_md

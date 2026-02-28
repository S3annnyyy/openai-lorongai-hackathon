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
    (repo / "tests").mkdir()
    (repo / "tests" / "test_health.py").write_text(
        "def test_health_stub():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    (repo / "__init__.py").write_text("", encoding="utf-8")
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
        "architecture.puml",
        "er.mmd",
        "er.puml",
        "er.dbml",
        "call-graph.mmd",
        "call-graph.puml",
        "dependencies.mmd",
        "dependencies.puml",
        "sequence.mmd",
        "sequence.puml",
        "use-case.mmd",
        "use-case.puml",
        "data.json",
        "data.yaml",
        "json-data.puml",
        "yaml-data.puml",
        "onboarding.md",
        "top-files.md",
        "index.md",
        "handoff.md",
        "dashboard_state.json",
    ]

    for name in required:
        assert (output / name).exists(), f"missing {name}"

    dashboard = json.loads((output / "dashboard_state.json").read_text(encoding="utf-8"))
    assert "kiv" in dashboard
    assert dashboard["kiv"]["graph_3d"].lower().startswith("deferred")
    assert "terraform_drawio" not in dashboard["diagrams"]
    assert "diagrams_plantuml" in dashboard
    assert dashboard["diagrams_plantuml"]["architecture"].startswith("@startuml")
    assert dashboard["diagrams_plantuml"]["er"].startswith("@startuml")
    assert dashboard["diagrams_plantuml"]["sequence"].startswith("@startuml")
    assert dashboard["diagrams_plantuml"]["use_case"].startswith("@startuml")
    assert dashboard["diagrams_plantuml"]["json_data"].startswith("@startjson")
    assert dashboard["diagrams_plantuml"]["yaml_data"].startswith("@startyaml")
    assert dashboard["diagrams"]["sequence"].startswith("sequenceDiagram")
    assert dashboard["diagrams"]["use_case"].startswith("flowchart")
    assert "\"repo\"" in dashboard["diagrams"]["json_data"]
    assert "repo:" in dashboard["diagrams"]["yaml_data"]
    assert "__init__.py" not in " ".join(dashboard["onboarding"]["start_here"])
    assert "tests/" not in " ".join(dashboard["onboarding"]["start_here"])
    assert dashboard["onboarding"]["key_flows"]
    assert "Request -> Entry -> Core Module -> Datastore" not in dashboard["onboarding"]["key_flows"][0]["flow"]

    graph = json.loads((output / "graph.json").read_text(encoding="utf-8"))
    assert graph["edges"]
    assert all("confidence" in edge for edge in graph["edges"])
    assert (output / "diagrams" / "architecture.puml").exists()
    assert (output / "diagrams" / "er.puml").exists()
    assert (output / "diagrams" / "sequence.puml").exists()
    assert (output / "diagrams" / "use-case.puml").exists()
    assert (output / "diagrams" / "json-data.puml").exists()
    assert (output / "diagrams" / "yaml-data.puml").exists()
    assert not (output / "terraform-architecture.drawio").exists()
    assert not (output / "artifacts" / "terraform.json").exists()

    handoff_md = (output / "handoff.md").read_text(encoding="utf-8")
    assert "Open First" in handoff_md
    assert "index.md" in handoff_md
    assert "dashboard_state.json" in handoff_md


def test_run_xray_infers_key_flows_without_routes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    (repo / "main.py").write_text(
        "from service import run\n"
        "def main():\n"
        "    return run()\n",
        encoding="utf-8",
    )
    (repo / "service.py").write_text(
        "def run():\n"
        "    return 42\n",
        encoding="utf-8",
    )

    output = repo / "docs" / "code-autopsy"
    run_xray(XrayConfig(repo_path=repo, output_root=output, lang_hints=set(), max_files=100))

    dashboard = json.loads((output / "dashboard_state.json").read_text(encoding="utf-8"))
    flows = dashboard["onboarding"]["key_flows"]
    assert flows
    assert dashboard["analysis"]["counts"]["routes"] == 0
    assert "Request -> Entry -> Core Module -> Datastore" not in " ".join(flow["flow"] for flow in flows)
    assert "main.py" in " ".join(flow["flow"] for flow in flows)


def test_run_xray_uses_stable_source_reference_when_provided(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")

    output = repo / "docs" / "code-autopsy"
    source_ref = "https://github.com/example/project"
    run_xray(
        XrayConfig(
            repo_path=repo,
            output_root=output,
            lang_hints=set(),
            max_files=100,
            source_reference=source_ref,
            source_kind="github_url",
        )
    )

    repo_json = json.loads((output / "repo.json").read_text(encoding="utf-8"))
    dashboard = json.loads((output / "dashboard_state.json").read_text(encoding="utf-8"))
    assert repo_json["root"] == source_ref
    assert repo_json["source_kind"] == "github_url"
    assert repo_json["analysis_workspace"].endswith("/repo")
    assert dashboard["summary"]["repo_root"] == source_ref
    assert dashboard["summary"]["source_kind"] == "github_url"


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
    assert "aws_vpc" in drawio_text
    assert "main" in drawio_text

    terraform = json.loads(terraform_json.read_text(encoding="utf-8"))
    assert terraform["summary"]["providers"] == 1
    assert terraform["summary"]["resources"] == 2
    assert terraform["edges"]

    dashboard = json.loads((output / "dashboard_state.json").read_text(encoding="utf-8"))
    assert "terraform_drawio" in dashboard["diagrams"]
    assert "<mxfile" in dashboard["diagrams"]["terraform_drawio"]

    index_md = (output / "index.md").read_text(encoding="utf-8")
    assert "Terraform IaC (draw.io)" in index_md

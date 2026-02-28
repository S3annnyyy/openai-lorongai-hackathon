from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from xray_core import render_er_mermaid, render_service_architecture_mermaid  # noqa: E402


def test_er_mermaid_contains_entities_and_relations() -> None:
    entities = [
        {
            "name": "User",
            "fields": [{"name": "id", "type": "int"}, {"name": "team_id", "type": "int"}],
            "source": "schema.sql",
        },
        {
            "name": "Team",
            "fields": [{"name": "id", "type": "int"}],
            "source": "schema.sql",
        },
    ]
    relationships = [{"from": "User", "to": "Team", "type": "fk"}]

    mermaid = render_er_mermaid(entities, relationships)

    assert mermaid.startswith("erDiagram")
    assert "User" in mermaid
    assert "Team" in mermaid
    assert "||--o{" in mermaid


def test_service_architecture_includes_key_service_modules() -> None:
    parsed_files = [
        {"path": "api/server.py"},
        {"path": "api/auth/handlers.py"},
        {"path": "api/orders/service.py"},
        {"path": "core/domain.py"},
    ]
    edges = [
        {"from": "file:api/server.py", "to": "file:core/domain.py", "type": "calls"},
        {"from": "file:api/server.py", "to": "file:api/auth/handlers.py", "type": "calls"},
        {"from": "file:api/auth/handlers.py", "to": "file:core/domain.py", "type": "calls"},
    ]
    routes = [
        {"file": "api/server.py", "method": "GET", "path": "/health"},
        {"file": "api/server.py", "method": "POST", "path": "/auth/login"},
    ]
    mermaid = render_service_architecture_mermaid(
        parsed_files=parsed_files,
        edges=edges,
        frameworks=[],
        routes=routes,
        entities=[],
        entrypoints=["api/server.py"],
    )

    assert "API Service (3) - key:" in mermaid
    assert "api/server.py" in mermaid

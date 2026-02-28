from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from xray_core import render_er_mermaid  # noqa: E402


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

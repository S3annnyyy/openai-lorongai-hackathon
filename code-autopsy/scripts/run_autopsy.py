#!/usr/bin/env python3
"""Run a baseline CodeAutopsy pass from a GitHub URL or local repository path."""

import argparse
import json
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path


CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".java",
    ".cs",
    ".rb",
    ".php",
    ".rs",
    ".cpp",
    ".c",
    ".h",
}

IMPORT_PATTERNS = [
    re.compile(r"^\s*import\s+([a-zA-Z0-9_./-]+)", re.MULTILINE),
    re.compile(r"^\s*from\s+([a-zA-Z0-9_./-]+)\s+import", re.MULTILINE),
    re.compile(r'^\s*const\s+.+?=\s*require\(["\'](.+?)["\']\)', re.MULTILINE),
    re.compile(r'^\s*import\s+.+?\s+from\s+["\'](.+?)["\']', re.MULTILINE),
]

ENTRYPOINT_NAMES = {
    "main.py",
    "app.py",
    "server.py",
    "index.js",
    "index.ts",
    "main.go",
    "Program.cs",
}


def is_github_url(source: str) -> bool:
    return bool(re.match(r"^https://github\.com/[^/]+/[^/]+(?:\.git)?/?$", source.strip()))


def normalize_repo_name(source: str, override: str | None, source_is_github: bool) -> str:
    if override:
        return override
    if source_is_github:
        raw = source.rstrip("/").split("/")[-1]
        if raw.endswith(".git"):
            raw = raw[:-4]
        return re.sub(r"[^a-zA-Z0-9_.-]", "-", raw) or "repository"

    raw = Path(source).resolve().name
    return re.sub(r"[^a-zA-Z0-9_.-]", "-", raw) or "repository"


def clone_repo(source: str, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--depth", "1", source, str(target)], check=True)


def detect_languages(files: list[Path]) -> list[str]:
    lang_by_ext = {
        ".py": "Python",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".go": "Go",
        ".java": "Java",
        ".cs": "C#",
        ".rb": "Ruby",
        ".php": "PHP",
        ".rs": "Rust",
        ".cpp": "C++",
        ".c": "C/C++",
        ".h": "C/C++",
    }
    langs = {lang_by_ext.get(p.suffix.lower(), "Other") for p in files}
    return sorted(langs)


def safe_read_text(path: Path, max_bytes: int = 512_000) -> str:
    try:
        if path.stat().st_size > max_bytes:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def file_complexity(text: str) -> float:
    if not text:
        return 0.0
    tokens = [
        " if ",
        " for ",
        " while ",
        " switch ",
        " case ",
        " try",
        " catch",
        "&&",
        "||",
    ]
    count = sum(text.count(token) for token in tokens)
    line_count = max(1, text.count("\n") + 1)
    return min(1.0, count / max(20, line_count / 3))


def imports_from_text(text: str) -> set[str]:
    imports: set[str] = set()
    for pattern in IMPORT_PATTERNS:
        for match in pattern.findall(text):
            value = match.strip().strip(".")
            if value:
                imports.add(value)
    return imports


def build_graph(repo_path: Path) -> tuple[dict, dict]:
    files = [p for p in repo_path.rglob("*") if p.is_file() and p.suffix.lower() in CODE_EXTENSIONS]
    nodes = []
    edges = []
    module_metrics = []
    import_index = defaultdict(set)

    for file_path in files:
        rel = file_path.relative_to(repo_path).as_posix()
        node_id = f"module:{rel}"
        text = safe_read_text(file_path)
        complexity = file_complexity(text)
        imports = imports_from_text(text)

        nodes.append(
            {
                "id": node_id,
                "type": "module",
                "label": rel,
                "owner": None,
                "criticality": round(min(1.0, complexity + (0.15 if file_path.name in ENTRYPOINT_NAMES else 0.0)), 4),
            }
        )

        for imp in imports:
            import_index[node_id].add(imp)

        coupling_out = len(imports)
        module_metrics.append(
            {
                "module": rel,
                "complexity": round(complexity, 4),
                "coupling_in": 0,
                "coupling_out": coupling_out,
                "test_coverage_proxy": 0.35,
                "ownership_risk": 0.5,
                "dependency_fragility": round(min(1.0, coupling_out / 20), 4),
                "hotspot_score": round(min(1.0, 0.35 * complexity + 0.45 * min(1.0, coupling_out / 20) + 0.2 * 0.5), 4),
            }
        )

    # Link imports to known modules by loose suffix matching.
    module_by_stem = {}
    for node in nodes:
        rel = node["label"]
        stem = rel.rsplit(".", 1)[0].replace("/", ".")
        module_by_stem[stem] = node["id"]

    for src_node, imports in import_index.items():
        for imp in imports:
            candidate = imp.replace("/", ".")
            dst_node = module_by_stem.get(candidate)
            if dst_node:
                edges.append({"from": src_node, "to": dst_node, "type": "imports", "weight": 1.0})

    coupling_in_map = defaultdict(int)
    for edge in edges:
        coupling_in_map[edge["to"]] += 1

    for metric in module_metrics:
        node_id = f"module:{metric['module']}"
        metric["coupling_in"] = coupling_in_map[node_id]

    graph = {"nodes": nodes, "edges": edges}
    metrics = {"module_metrics": module_metrics}
    return graph, metrics


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run baseline CodeAutopsy artifact generation")
    parser.add_argument(
        "--source",
        required=True,
        help="GitHub repository URL or local repository path.",
    )
    parser.add_argument(
        "--workspace-root",
        default=".",
        help="Root where .codeAutopsy/<repo_name> is created (default: current directory).",
    )
    parser.add_argument("--repo-name", default=None, help="Optional override for output folder name.")
    parser.add_argument(
        "--keep-clone",
        action="store_true",
        help="Keep temporary cloned source when input is a GitHub URL.",
    )
    args = parser.parse_args()

    source = args.source.strip()
    workspace_root = Path(args.workspace_root).resolve()
    source_is_github = is_github_url(source)
    repo_name = normalize_repo_name(source, args.repo_name, source_is_github)
    out_dir = workspace_root / ".codeAutopsy" / repo_name
    diagrams_dir = out_dir / "diagrams"
    fixes_dir = out_dir / "fixes"

    if source_is_github:
        clone_dir = workspace_root / ".codeAutopsy" / "_sources" / repo_name
        clone_repo(source, clone_dir)
        repo_path = clone_dir
        source_kind = "github_url"
    else:
        repo_path = Path(source).resolve()
        if not repo_path.exists() or not repo_path.is_dir():
            raise FileNotFoundError(f"Local repository path not found: {repo_path}")
        source_kind = "local_path"

    graph, metrics = build_graph(repo_path)
    files_indexed = len(metrics.get("module_metrics", []))
    langs = detect_languages([repo_path / m["module"] for m in metrics["module_metrics"] if (repo_path / m["module"]).exists()])
    entrypoints = [m["module"] for m in metrics["module_metrics"] if Path(m["module"]).name in ENTRYPOINT_NAMES]

    repo_json = {
        "name": repo_name,
        "root": str(repo_path),
        "source_kind": source_kind,
        "languages": langs,
        "frameworks": [],
        "entrypoints": entrypoints,
        "indexing": {"strategy": "full", "files_indexed": files_indexed, "files_skipped": 0},
    }

    write_json(out_dir / "repo.json", repo_json)
    write_json(out_dir / "graph.json", graph)
    write_json(out_dir / "metrics.json", metrics)

    # Write baseline placeholders for downstream agents.
    write_json(out_dir / "attack_surface.json", {"entrypoints": entrypoints, "trust_boundaries": [], "sinks": [], "critical_paths": []})
    write_json(
        out_dir / "failure_simulation.json",
        {
            "scenarios": [
                {"name": "traffic_x10", "first_break_modules": [], "blast_radius_nodes": [], "confidence": 0.5, "causal_chain": []},
                {"name": "dep_update", "first_break_modules": [], "blast_radius_nodes": [], "confidence": 0.45, "causal_chain": []},
                {"name": "hotspot_change", "first_break_modules": [], "blast_radius_nodes": [], "confidence": 0.55, "causal_chain": []},
            ]
        },
    )
    write_json(out_dir / "blast_radius.json", {"paths": []})
    write_json(out_dir / "security_posture.json", {"before": 0.45, "after": 0.65, "notes": "Baseline placeholders. Replace with Agent 2 outputs."})
    write_json(out_dir / "hiring_pain_index.json", {"critical_modules": [], "score": 0.5})
    write_json(out_dir / "dashboard_state.json", {"repo_name": repo_name, "artifacts_root": str(out_dir), "version": 1})

    (out_dir / "case_file.md").write_text(
        "# Case File\n\n- Source mode: " + source_kind + "\n- Repository: " + str(repo_path) + "\n- Notes: Baseline autopsy generated by scripts/run_autopsy.py\n",
        encoding="utf-8",
    )
    (out_dir / "exploit_stories.md").write_text("# Top 5 Exploit Stories\n\nPopulate from Agent 1 findings.\n", encoding="utf-8")
    (out_dir / "recommended_next_prs.md").write_text("# Recommended Next PRs\n\nPopulate from Agent 2 findings.\n", encoding="utf-8")
    (out_dir / "refactor_roadmap.md").write_text("# Refactor Roadmap (3 Phases)\n\nPopulate from Agent 3 findings.\n", encoding="utf-8")
    (out_dir / "scaffolding_pr_plan.md").write_text("# Scaffolding PR Plan\n\nPopulate from Agent 3 findings.\n", encoding="utf-8")
    (out_dir / "evolution_narrative.md").write_text("# Evolution Narrative\n\nPopulate from Agent 4 findings.\n", encoding="utf-8")

    fixes_dir.mkdir(parents=True, exist_ok=True)
    diagrams_dir.mkdir(parents=True, exist_ok=True)

    # Generate decay forecast.
    subprocess.run(
        [
            "python",
            str(Path(__file__).with_name("score_decay.py")),
            "--metrics",
            str(out_dir / "metrics.json"),
            "--out",
            str(out_dir / "decay_forecast.json"),
        ],
        check=True,
    )

    # Generate Mermaid architecture diagram.
    subprocess.run(
        [
            "python",
            str(Path(__file__).with_name("render_mermaid_from_graph.py")),
            "--graph",
            str(out_dir / "graph.json"),
            "--out",
            str(diagrams_dir / "architecture.mmd"),
        ],
        check=True,
    )

    if source_is_github and not args.keep_clone:
        shutil.rmtree(repo_path, ignore_errors=True)

    print(f"CodeAutopsy artifacts generated at: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

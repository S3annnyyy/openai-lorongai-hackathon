#!/usr/bin/env python3
"""Core extraction and rendering pipeline for code-autopsy xray mode."""

from __future__ import annotations

import ast
import html
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SUPPORTED_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
DEFAULT_IGNORE_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "coverage",
    ".next",
    ".turbo",
    ".cache",
    "__pycache__",
}

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}
SQL_SCALARS = {
    "int",
    "integer",
    "bigint",
    "smallint",
    "varchar",
    "char",
    "text",
    "boolean",
    "bool",
    "float",
    "double",
    "decimal",
    "timestamp",
    "datetime",
    "date",
    "json",
    "jsonb",
}
TERRAFORM_REF_IGNORES = {"var", "local", "path", "count", "each", "self", "terraform"}


@dataclass
class XrayConfig:
    repo_path: Path
    output_root: Path
    lang_hints: set[str]
    max_files: int


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _is_test_file(rel_path: str) -> bool:
    lower = rel_path.lower()
    return (
        "/test" in lower
        or "/tests" in lower
        or lower.startswith("test")
        or lower.endswith("_test.py")
        or lower.endswith(".test.ts")
        or lower.endswith(".test.js")
        or lower.endswith(".spec.ts")
        or lower.endswith(".spec.js")
    )


def _should_skip(path: Path, repo_path: Path) -> bool:
    try:
        rel_parts = path.relative_to(repo_path).parts
        parts = set(rel_parts)
    except ValueError:
        return True
    rel_path = "/".join(rel_parts).lower()
    if bool(parts.intersection(DEFAULT_IGNORE_DIRS)):
        return True
    if rel_path.endswith(".min.js"):
        return True
    if "/docs/site/" in rel_path:
        return True
    return False


def discover_source_files(repo_path: Path, max_files: int, lang_hints: set[str]) -> list[Path]:
    allowed = set(SUPPORTED_EXTENSIONS)
    if lang_hints:
        hint_ext = set()
        if "python" in lang_hints or "py" in lang_hints:
            hint_ext.add(".py")
        if lang_hints.intersection({"ts", "typescript", "js", "javascript", "node", "ts/node"}):
            hint_ext.update({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"})
        if hint_ext:
            allowed = hint_ext

    files: list[Path] = []
    for path in sorted(repo_path.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in allowed:
            continue
        if _should_skip(path, repo_path):
            continue
        files.append(path)
        if len(files) >= max_files:
            break
    return files


def discover_terraform_files(repo_path: Path, max_files: int = 600) -> list[Path]:
    files: list[Path] = []
    for path in sorted(repo_path.rglob("*.tf")):
        if not path.is_file():
            continue
        if _should_skip(path, repo_path):
            continue
        files.append(path)
        if len(files) >= max_files:
            break
    return files


def detect_languages(files: Iterable[Path]) -> list[str]:
    found = set()
    for path in files:
        if path.suffix == ".py":
            found.add("Python")
        elif path.suffix in {".ts", ".tsx"}:
            found.add("TypeScript")
        elif path.suffix in {".js", ".jsx", ".mjs", ".cjs"}:
            found.add("JavaScript")
    return sorted(found)


def detect_frameworks(repo_path: Path, files: list[Path]) -> list[str]:
    frameworks = set()

    package_json = repo_path / "package.json"
    if package_json.exists():
        payload = _read_text(package_json).lower()
        if "next" in payload:
            frameworks.add("Next.js")
        if "express" in payload:
            frameworks.add("Express")
        if "fastify" in payload:
            frameworks.add("Fastify")
        if "nestjs" in payload or "@nestjs" in payload:
            frameworks.add("NestJS")
        if "prisma" in payload:
            frameworks.add("Prisma")

    py_files = {f.name.lower() for f in files if f.suffix == ".py"}
    file_text_sample = "\n".join(_read_text(p)[:4000].lower() for p in files[:25])
    if "manage.py" in py_files or "django" in file_text_sample:
        frameworks.add("Django")
    if "fastapi" in file_text_sample:
        frameworks.add("FastAPI")
    if "flask" in file_text_sample:
        frameworks.add("Flask")
    if "sqlalchemy" in file_text_sample:
        frameworks.add("SQLAlchemy")

    return sorted(frameworks)


def detect_entrypoints(repo_path: Path, files: list[Path]) -> list[str]:
    candidates = {
        "main.py",
        "app.py",
        "manage.py",
        "server.py",
        "main.ts",
        "index.ts",
        "server.ts",
        "main.js",
        "index.js",
        "server.js",
        "bin/www",
    }
    entrypoints: list[str] = []

    for path in files:
        rel = path.relative_to(repo_path).as_posix()
        name = path.name
        if name in candidates or rel in candidates or rel.startswith("src/main."):
            entrypoints.append(rel)

    package_json = repo_path / "package.json"
    if package_json.exists():
        try:
            pkg = json.loads(_read_text(package_json) or "{}")
            scripts = pkg.get("scripts", {})
            for key in ("start", "dev"):
                value = scripts.get(key)
                if isinstance(value, str):
                    match = re.search(r"(?:node|tsx|ts-node|python)\s+([\w./-]+)", value)
                    if match:
                        entrypoints.append(match.group(1))
        except json.JSONDecodeError:
            pass

    unique = []
    seen = set()
    for item in entrypoints:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique[:10]


def _module_name_for_python(rel_path: str) -> str:
    name = rel_path
    if name.endswith(".py"):
        name = name[:-3]
    if name.endswith("/__init__"):
        name = name[: -len("/__init__")]
    return name.replace("/", ".")


def _module_name_for_js(rel_path: str) -> str:
    name = rel_path
    for suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    if name.endswith("/index"):
        name = name[: -len("/index")]
    return name


def _extract_py_calls(tree: ast.AST) -> list[tuple[str, str, int]]:
    calls: list[tuple[str, str, int]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.context = "<module>"

        def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
            previous = self.context
            self.context = node.name
            self.generic_visit(node)
            self.context = previous

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
            previous = self.context
            self.context = node.name
            self.generic_visit(node)
            self.context = previous

        def visit_Call(self, node: ast.Call) -> Any:
            callee = None
            if isinstance(node.func, ast.Name):
                callee = node.func.id
            elif isinstance(node.func, ast.Attribute):
                callee = node.func.attr
            if callee:
                calls.append((self.context, callee, getattr(node, "lineno", 0)))
            self.generic_visit(node)

    Visitor().visit(tree)
    return calls


def parse_python_file(path: Path, repo_path: Path) -> dict[str, Any]:
    rel = path.relative_to(repo_path).as_posix()
    text = _read_text(path)
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return {
            "path": rel,
            "lang": "python",
            "imports": [],
            "functions": [],
            "classes": [],
            "calls": [],
            "routes": [],
            "errors": [f"SyntaxError: {exc.msg}"],
        }

    imports: list[str] = []
    functions: list[dict[str, Any]] = []
    classes: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorators = []
            for deco in node.decorator_list:
                if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute):
                    method = deco.func.attr.lower()
                    if method in HTTP_METHODS and deco.args:
                        route_value = deco.args[0]
                        route_path = route_value.value if isinstance(route_value, ast.Constant) else "<dynamic>"
                        routes.append(
                            {
                                "method": method.upper(),
                                "path": route_path,
                                "handler": node.name,
                                "file": rel,
                                "line": getattr(node, "lineno", 0),
                            }
                        )
                    decorators.append(deco.func.attr)
                elif isinstance(deco, ast.Attribute):
                    decorators.append(deco.attr)
                elif isinstance(deco, ast.Name):
                    decorators.append(deco.id)

            functions.append(
                {
                    "name": node.name,
                    "line": getattr(node, "lineno", 0),
                    "end_line": getattr(node, "end_lineno", getattr(node, "lineno", 0)),
                    "decorators": decorators,
                }
            )
        elif isinstance(node, ast.ClassDef):
            classes.append(
                {
                    "name": node.name,
                    "line": getattr(node, "lineno", 0),
                    "bases": [
                        base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
                        for base in node.bases
                    ],
                }
            )

    calls = [
        {
            "caller": caller,
            "callee": callee,
            "line": line,
            "file": rel,
            "confidence": "high",
            "reason": "python-ast",
        }
        for caller, callee, line in _extract_py_calls(tree)
    ]

    models: list[dict[str, Any]] = []
    for cls in classes:
        if cls["name"].endswith("Model") or any("base" in b.lower() for b in cls.get("bases", [])):
            models.append({"entity": cls["name"], "file": rel, "source": "python-heuristic"})

    return {
        "path": rel,
        "lang": "python",
        "imports": sorted(set(imports)),
        "functions": functions,
        "classes": classes,
        "calls": calls,
        "routes": routes,
        "models": models,
        "errors": [],
    }


def parse_js_ts_file(path: Path, repo_path: Path) -> dict[str, Any]:
    rel = path.relative_to(repo_path).as_posix()
    text = _read_text(path)
    imports: list[str] = []

    import_patterns = [
        r"import\s+[^\n]*?from\s+[\"']([^\"']+)[\"']",
        r"require\(\s*[\"']([^\"']+)[\"']\s*\)",
    ]
    for pattern in import_patterns:
        imports.extend(re.findall(pattern, text))

    function_names = set(re.findall(r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", text))
    function_names.update(re.findall(r"\bconst\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>", text))
    function_names.update(re.findall(r"\blet\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>", text))
    function_names.update(re.findall(r"\bvar\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>", text))

    class_names = re.findall(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)", text)

    calls = []
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", text):
        callee = match.group(1)
        if callee in {"if", "for", "while", "switch", "return", "catch", "function", "require", "import"}:
            continue
        calls.append(
            {
                "caller": "<module>",
                "callee": callee,
                "line": text[: match.start()].count("\n") + 1,
                "file": rel,
                "confidence": "medium",
                "reason": "regex-callsite",
            }
        )

    routes = []
    for match in re.finditer(
        r"\b(?:app|router|server)\.(get|post|put|patch|delete)\s*\(\s*[`\"']([^`\"']+)[`\"']",
        text,
        re.IGNORECASE,
    ):
        method = match.group(1).upper()
        route_path = match.group(2)
        routes.append(
            {
                "method": method,
                "path": route_path,
                "handler": "<module>",
                "file": rel,
                "line": text[: match.start()].count("\n") + 1,
            }
        )

    models = []
    if "sequelize" in text.lower():
        for model in re.findall(r"sequelize\.define\(\s*[\"']([A-Za-z0-9_]+)[\"']", text):
            models.append({"entity": model, "file": rel, "source": "sequelize"})

    functions = [{"name": name, "line": 0, "end_line": 0, "decorators": []} for name in sorted(function_names)]
    classes = [{"name": name, "line": 0, "bases": []} for name in class_names]

    return {
        "path": rel,
        "lang": "typescript" if path.suffix in {".ts", ".tsx"} else "javascript",
        "imports": sorted(set(imports)),
        "functions": functions,
        "classes": classes,
        "calls": calls,
        "routes": routes,
        "models": models,
        "errors": [],
    }


def parse_code_files(repo_path: Path, files: list[Path]) -> tuple[list[dict[str, Any]], list[str]]:
    parsed = []
    errors = []
    for path in files:
        if path.suffix == ".py":
            data = parse_python_file(path, repo_path)
        else:
            data = parse_js_ts_file(path, repo_path)
        parsed.append(data)
        for err in data.get("errors", []):
            errors.append(f"{data['path']}: {err}")
    return parsed, errors


def _build_module_indexes(parsed_files: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, str]]:
    python_index: dict[str, str] = {}
    js_index: dict[str, str] = {}

    for item in parsed_files:
        rel = item["path"]
        if rel.endswith(".py"):
            module_name = _module_name_for_python(rel)
            python_index[module_name] = rel
        else:
            module_name = _module_name_for_js(rel)
            js_index[module_name] = rel
            js_index[module_name + "/index"] = rel

    return python_index, js_index


def _resolve_python_import(import_name: str, python_index: dict[str, str]) -> tuple[str | None, str]:
    if import_name in python_index:
        return python_index[import_name], "high"
    prefix = import_name.split(".")[0]
    for candidate_name, path in python_index.items():
        if candidate_name == prefix or candidate_name.startswith(import_name):
            return path, "medium"
    return None, "low"


def _normalize_js_import(base_rel: str, import_name: str) -> str:
    base_dir = Path(base_rel).parent
    if import_name.startswith("."):
        return (base_dir / import_name).as_posix().replace("//", "/")
    return import_name


def _resolve_js_import(base_rel: str, import_name: str, js_index: dict[str, str]) -> tuple[str | None, str]:
    normalized = _normalize_js_import(base_rel, import_name)

    candidates = [normalized]
    for suffix in ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        candidates.append(normalized + suffix)
    candidates.append(normalized + "/index")

    for candidate in candidates:
        if candidate in js_index:
            return js_index[candidate], "high"
        if candidate in {v for v in js_index.values()}:
            return candidate, "high"

    # Compare by basename as a best-effort fallback.
    base = Path(normalized).name
    for module_name, rel in js_index.items():
        if Path(module_name).name == base:
            return rel, "medium"

    return None, "low"


def build_import_edges(parsed_files: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    python_index, js_index = _build_module_indexes(parsed_files)

    internal_edges = []
    external_edges = []

    for item in parsed_files:
        source = item["path"]
        for raw_import in item.get("imports", []):
            target = None
            confidence = "low"
            reason = "unresolved"

            if item.get("lang") == "python":
                target, confidence = _resolve_python_import(raw_import, python_index)
                reason = "python-module-index" if target else "python-external"
            else:
                target, confidence = _resolve_js_import(source, raw_import, js_index)
                reason = "js-module-index" if target else "js-external"

            edge = {
                "from": source,
                "type": "imports",
                "raw_import": raw_import,
                "confidence": confidence,
                "reason": reason,
            }
            if target:
                edge["to"] = target
                internal_edges.append(edge)
            else:
                edge["to"] = f"external:{raw_import}"
                external_edges.append(edge)

    return internal_edges, external_edges


def build_call_edges(parsed_files: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    function_index: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for item in parsed_files:
        for fn in item.get("functions", []):
            function_index[fn["name"]].append((item["path"], fn["name"]))

    module_calls = []
    function_calls = []

    for item in parsed_files:
        source = item["path"]
        for call in item.get("calls", []):
            callee = call.get("callee")
            if not callee:
                continue
            targets = function_index.get(callee, [])
            if not targets:
                module_calls.append(
                    {
                        "from": source,
                        "to": f"external_fn:{callee}",
                        "type": "calls",
                        "line": call.get("line", 0),
                        "confidence": "low",
                        "reason": "callee-not-indexed",
                    }
                )
                continue

            target_file, target_fn = targets[0]
            confidence = call.get("confidence", "medium")
            reason = call.get("reason", "function-index")
            if len(targets) > 1:
                confidence = "medium"
                reason = "multiple-callee-candidates"

            module_calls.append(
                {
                    "from": source,
                    "to": target_file,
                    "type": "calls",
                    "line": call.get("line", 0),
                    "confidence": confidence,
                    "reason": reason,
                }
            )
            function_calls.append(
                {
                    "from": f"{source}::{call.get('caller', '<module>')}",
                    "to": f"{target_file}::{target_fn}",
                    "callee": callee,
                    "line": call.get("line", 0),
                    "confidence": confidence,
                    "reason": reason,
                }
            )

    return module_calls, function_calls


def parse_prisma_models(repo_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    entities = []
    relationships = []

    for schema_path in repo_path.rglob("schema.prisma"):
        text = _read_text(schema_path)
        models = re.findall(r"model\s+(\w+)\s*\{(.*?)\}", text, flags=re.DOTALL)
        known = {name for name, _ in models}
        for model_name, body in models:
            fields = []
            for raw in body.splitlines():
                line = raw.strip()
                if not line or line.startswith("//"):
                    continue
                tokens = line.split()
                if len(tokens) < 2:
                    continue
                field_name, field_type = tokens[0], tokens[1]
                attrs = " ".join(tokens[2:])
                fields.append(
                    {
                        "name": field_name,
                        "type": field_type,
                        "attributes": attrs,
                    }
                )
                if field_type.replace("?", "").replace("[]", "") in known:
                    relationships.append(
                        {
                            "from": model_name,
                            "to": field_type.replace("?", "").replace("[]", ""),
                            "type": "relation",
                            "source": schema_path.relative_to(repo_path).as_posix(),
                            "confidence": "high",
                        }
                    )
            entities.append(
                {
                    "name": model_name,
                    "fields": fields,
                    "source": schema_path.relative_to(repo_path).as_posix(),
                    "format": "prisma",
                }
            )

    return entities, relationships


def parse_sql_entities(repo_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    entities = []
    relationships = []

    for sql_path in repo_path.rglob("*.sql"):
        rel_path = sql_path.relative_to(repo_path).as_posix()
        lower_path = rel_path.lower()
        if "migration" not in lower_path and "schema" not in lower_path:
            continue

        text = _read_text(sql_path)

        for table_name, body in re.findall(
            r"create\s+table\s+(?:if\s+not\s+exists\s+)?([\w\".]+)\s*\((.*?)\);",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            clean_name = table_name.strip('"').split(".")[-1]
            fields = []
            for raw_line in body.splitlines():
                line = raw_line.strip().rstrip(",")
                if not line:
                    continue
                fk_match = re.search(
                    r"foreign\s+key\s*\((\w+)\)\s+references\s+([\w\".]+)\s*\((\w+)\)",
                    line,
                    flags=re.IGNORECASE,
                )
                if fk_match:
                    relationships.append(
                        {
                            "from": clean_name,
                            "to": fk_match.group(2).strip('"').split(".")[-1],
                            "type": "fk",
                            "field": fk_match.group(1),
                            "target_field": fk_match.group(3),
                            "source": rel_path,
                            "confidence": "high",
                        }
                    )
                    continue

                col_match = re.match(r"(\w+)\s+([A-Za-z0-9_()]+)", line)
                if col_match:
                    fields.append({"name": col_match.group(1), "type": col_match.group(2)})

            entities.append(
                {
                    "name": clean_name,
                    "fields": fields,
                    "source": rel_path,
                    "format": "sql",
                }
            )

    return entities, relationships


def merge_entities_and_relationships(
    prisma_entities: list[dict[str, Any]],
    prisma_relationships: list[dict[str, Any]],
    sql_entities: list[dict[str, Any]],
    sql_relationships: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_name: dict[str, dict[str, Any]] = {}

    for entity in prisma_entities + sql_entities:
        existing = by_name.get(entity["name"])
        if not existing:
            by_name[entity["name"]] = dict(entity)
            continue

        existing_fields = {(f["name"], f.get("type", "")) for f in existing.get("fields", [])}
        for field in entity.get("fields", []):
            key = (field["name"], field.get("type", ""))
            if key not in existing_fields:
                existing.setdefault("fields", []).append(field)
        existing["source"] = ", ".join(sorted({existing.get("source", ""), entity.get("source", "")} - {""}))

    relationships = prisma_relationships + sql_relationships
    dedup = {}
    for rel in relationships:
        key = (rel.get("from"), rel.get("to"), rel.get("type"), rel.get("field"))
        dedup[key] = rel

    return sorted(by_name.values(), key=lambda item: item["name"]), sorted(
        dedup.values(), key=lambda item: (item.get("from", ""), item.get("to", ""), item.get("type", ""))
    )


def build_nodes(parsed_files: list[dict[str, Any]], external_refs: Iterable[str]) -> list[dict[str, Any]]:
    nodes = []
    for item in parsed_files:
        rel = item["path"]
        nodes.append(
            {
                "id": f"file:{rel}",
                "type": "module",
                "label": rel,
                "criticality": 0.0,
                "lang": item.get("lang", "unknown"),
            }
        )

    for ext in sorted(set(external_refs)):
        nodes.append(
            {
                "id": f"external:{ext}",
                "type": "external",
                "label": ext,
                "criticality": 0.2,
                "lang": "external",
            }
        )

    return nodes


def build_graph_edges(
    import_edges: list[dict[str, Any]],
    external_import_edges: list[dict[str, Any]],
    module_call_edges: list[dict[str, Any]],
    entrypoints: list[str],
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []

    for edge in import_edges:
        edges.append(
            {
                "from": f"file:{edge['from']}",
                "to": f"file:{edge['to']}",
                "type": "imports",
                "weight": 1.0,
                "confidence": edge["confidence"],
                "reason": edge["reason"],
            }
        )

    for edge in external_import_edges:
        external_name = edge["to"].replace("external:", "")
        edges.append(
            {
                "from": f"file:{edge['from']}",
                "to": f"external:{external_name}",
                "type": "depends_on",
                "weight": 1.0,
                "confidence": edge["confidence"],
                "reason": edge["reason"],
            }
        )

    for edge in module_call_edges:
        to_node = edge["to"]
        if to_node.startswith("external_fn:"):
            ext = to_node.replace("external_fn:", "")
            to_node_id = f"external:{ext}"
        else:
            to_node_id = f"file:{to_node}"
        edges.append(
            {
                "from": f"file:{edge['from']}",
                "to": to_node_id,
                "type": "calls",
                "weight": 1.0,
                "confidence": edge["confidence"],
                "reason": edge["reason"],
            }
        )

    entrypoint_set = {f"file:{item}" for item in entrypoints}
    for edge in list(edges):
        if edge["from"] in entrypoint_set and edge["to"].startswith("external:"):
            trust_edge = dict(edge)
            trust_edge["type"] = "trust_boundary_crossing"
            trust_edge["confidence"] = "medium"
            trust_edge["reason"] = "entrypoint-to-external"
            edges.append(trust_edge)

    dedup = {}
    for edge in edges:
        key = (edge["from"], edge["to"], edge["type"])
        if key not in dedup:
            dedup[key] = edge

    return sorted(dedup.values(), key=lambda item: (item["from"], item["to"], item["type"]))


def _fan_counts(edges: list[dict[str, Any]]) -> tuple[Counter, Counter]:
    fan_out = Counter()
    fan_in = Counter()
    for edge in edges:
        fan_out[edge["from"]] += 1
        fan_in[edge["to"]] += 1
    return fan_in, fan_out


def score_modules(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fan_in, fan_out = _fan_counts(edges)

    scored = []
    for node in nodes:
        if node["type"] != "module":
            continue
        node_id = node["id"]
        in_val = fan_in.get(node_id, 0)
        out_val = fan_out.get(node_id, 0)
        complexity = min(1.0, (in_val + out_val) / 20.0)
        coupling_out = min(1.0, out_val / 12.0)
        dependency_fragility = min(1.0, out_val / 15.0)
        ownership_risk = 0.65 if _is_test_file(node["label"]) else 0.45
        test_coverage_proxy = 0.85 if _is_test_file(node["label"]) else 0.35

        hotspot = min(
            1.0,
            0.35 * complexity
            + 0.25 * coupling_out
            + 0.20 * dependency_fragility
            + 0.20 * ownership_risk,
        )

        scored.append(
            {
                "module": node["label"],
                "module_id": node_id,
                "complexity": round(complexity, 4),
                "coupling_in": in_val,
                "coupling_out": out_val,
                "test_coverage_proxy": round(test_coverage_proxy, 4),
                "ownership_risk": round(ownership_risk, 4),
                "dependency_fragility": round(dependency_fragility, 4),
                "hotspot_score": round(hotspot, 4),
            }
        )

    scored.sort(key=lambda item: item["hotspot_score"], reverse=True)
    return scored


def apply_criticality(nodes: list[dict[str, Any]], module_metrics: list[dict[str, Any]]) -> None:
    by_id = {item["module_id"]: item for item in module_metrics}
    for node in nodes:
        metric = by_id.get(node["id"])
        if metric:
            node["criticality"] = metric["hotspot_score"]


def _build_module_adjacency(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, set[str]]:
    module_nodes = {node["id"] for node in nodes if node["type"] == "module"}
    adjacency: dict[str, set[str]] = {node: set() for node in module_nodes}

    for edge in edges:
        if edge["from"] in module_nodes and edge["to"] in module_nodes:
            adjacency[edge["from"]].add(edge["to"])

    return adjacency


def detect_cycles(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[list[str]]:
    adjacency = _build_module_adjacency(nodes, edges)
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indexes: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indexes[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for neighbor in adjacency.get(node, set()):
            if neighbor not in indexes:
                strongconnect(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indexes[neighbor])

        if lowlinks[node] == indexes[node]:
            component = []
            while True:
                tail = stack.pop()
                on_stack.remove(tail)
                component.append(tail)
                if tail == node:
                    break
            if len(component) > 1:
                components.append(sorted(component))

    for node in sorted(adjacency.keys()):
        if node not in indexes:
            strongconnect(node)

    components.sort()
    return components


def _pick_route_file(routes: list[dict[str, Any]]) -> str | None:
    if not routes:
        return None
    counts = Counter(route["file"] for route in routes)
    return counts.most_common(1)[0][0]


def _pick_core_file(module_metrics: list[dict[str, Any]]) -> str | None:
    if not module_metrics:
        return None
    return module_metrics[0]["module"]


def _pick_data_file(entities: list[dict[str, Any]], parsed_files: list[dict[str, Any]]) -> str | None:
    if entities:
        source = entities[0].get("source", "")
        if source:
            return source
    for item in parsed_files:
        path = item["path"].lower()
        if any(token in path for token in ("model", "schema", "db", "prisma", "migration")):
            return item["path"]
    return None


def _pick_test_file(parsed_files: list[dict[str, Any]]) -> str | None:
    for item in parsed_files:
        if _is_test_file(item["path"]):
            return item["path"]
    return None


def build_start_here(
    entrypoints: list[str],
    routes: list[dict[str, Any]],
    module_metrics: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    parsed_files: list[dict[str, Any]],
) -> list[str]:
    picks = []

    if entrypoints:
        picks.append(entrypoints[0])

    route_file = _pick_route_file(routes)
    if route_file:
        picks.append(route_file)

    core_file = _pick_core_file(module_metrics)
    if core_file:
        picks.append(core_file)

    data_file = _pick_data_file(entities, parsed_files)
    if data_file:
        picks.append(data_file)

    test_file = _pick_test_file(parsed_files)
    if test_file:
        picks.append(test_file)

    dedup = []
    seen = set()
    for file_path in picks:
        if file_path and file_path not in seen:
            seen.add(file_path)
            dedup.append(file_path)

    if len(dedup) < 5:
        for item in parsed_files:
            if item["path"] not in seen:
                dedup.append(item["path"])
                seen.add(item["path"])
            if len(dedup) >= 5:
                break

    return dedup[:5]


def build_glossary(entities: list[dict[str, Any]], parsed_files: list[dict[str, Any]]) -> list[dict[str, str]]:
    glossary = []
    for entity in entities:
        glossary.append(
            {
                "term": entity["name"],
                "location": entity.get("source", "unknown"),
                "definition": "Domain entity detected from schema/model artifacts.",
            }
        )

    if not glossary:
        for item in parsed_files:
            for cls in item.get("classes", [])[:2]:
                glossary.append(
                    {
                        "term": cls["name"],
                        "location": item["path"],
                        "definition": "Class symbol from source scan.",
                    }
                )
            if len(glossary) >= 6:
                break

    return glossary[:12]


def build_change_safely(repo_path: Path, parsed_files: list[dict[str, Any]]) -> dict[str, Any]:
    commands = []
    if (repo_path / "package.json").exists():
        commands.extend(["npm test", "npm run lint"])
    if any(item.get("lang") == "python" for item in parsed_files):
        commands.append("pytest")

    if not commands:
        commands = ["Run the project test suite before and after edits."]

    invariants = [
        "Keep authentication and authorization middleware in the request path.",
        "Preserve migration ordering and avoid editing applied migration files.",
        "Maintain API contract fields consumed by downstream clients.",
    ]

    return {"tests_to_run": commands, "critical_invariants": invariants}


def _extract_hcl_block_body(text: str, open_brace_index: int) -> tuple[str, int]:
    depth = 0
    idx = open_brace_index
    while idx < len(text):
        char = text[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace_index + 1 : idx], idx
        idx += 1
    return text[open_brace_index + 1 :], len(text) - 1


def build_terraform_graph(repo_path: Path, terraform_files: list[Path]) -> dict[str, Any]:
    block_pattern = re.compile(r'(?m)^\s*(resource|data|module|provider)\s+"([^"]+)"(?:\s+"([^"]+)")?\s*\{')

    nodes: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    file_list = [path.relative_to(repo_path).as_posix() for path in terraform_files]

    for path in terraform_files:
        rel = path.relative_to(repo_path).as_posix()
        text = _read_text(path)
        for match in block_pattern.finditer(text):
            kind = match.group(1)
            first = match.group(2)
            second = match.group(3)
            if kind in {"resource", "data"} and not second:
                continue

            open_brace_index = match.end() - 1
            body, _ = _extract_hcl_block_body(text, open_brace_index)
            line = text[: match.start()].count("\n") + 1

            if kind in {"resource", "data"}:
                label = f"{first}.{second}"
                node_id = f"{kind}:{label}"
            else:
                label = first
                node_id = f"{kind}:{first}"

            if node_id not in seen_ids:
                seen_ids.add(node_id)
                nodes.append(
                    {
                        "id": node_id,
                        "kind": kind,
                        "label": label,
                        "file": rel,
                        "line": line,
                    }
                )

            blocks.append(
                {
                    "id": node_id,
                    "kind": kind,
                    "file": rel,
                    "line": line,
                    "label_1": first,
                    "label_2": second,
                    "body": body,
                }
            )

    provider_nodes: dict[str, str] = {}
    module_nodes: dict[str, str] = {}
    resource_nodes: dict[tuple[str, str], str] = {}
    data_nodes: dict[tuple[str, str], str] = {}
    resource_types: set[str] = set()

    for block in blocks:
        kind = block["kind"]
        first = block["label_1"]
        second = block["label_2"]
        node_id = block["id"]

        if kind == "provider":
            provider_nodes[first] = node_id
        elif kind == "module":
            module_nodes[first] = node_id
        elif kind == "resource" and second:
            resource_nodes[(first, second)] = node_id
            resource_types.add(first)
        elif kind == "data" and second:
            data_nodes[(first, second)] = node_id

    def ref_to_node_id(token: str) -> str | None:
        cleaned = token.strip().strip('"').strip("'")
        if not cleaned:
            return None

        if cleaned.startswith("module."):
            parts = cleaned.split(".")
            if len(parts) >= 2:
                return module_nodes.get(parts[1])
            return None

        if cleaned.startswith("data."):
            parts = cleaned.split(".")
            if len(parts) >= 3:
                return data_nodes.get((parts[1], parts[2]))
            return None

        parts = cleaned.split(".")
        if len(parts) < 2:
            return None
        first, second = parts[0], parts[1]
        if first in TERRAFORM_REF_IGNORES:
            return None
        if first in resource_types:
            return resource_nodes.get((first, second))
        return None

    edges: list[dict[str, Any]] = []
    edge_keys: set[tuple[str, str, str]] = set()

    def add_edge(source: str, target: str | None, edge_type: str, reason: str) -> None:
        if not target or source == target:
            return
        key = (source, target, edge_type)
        if key in edge_keys:
            return
        edge_keys.add(key)
        edges.append({"from": source, "to": target, "type": edge_type, "reason": reason})

    for block in blocks:
        source_id = block["id"]
        kind = block["kind"]
        body = block["body"]

        if kind in {"resource", "data"}:
            provider_hint = (block["label_1"] or "").split("_", 1)[0]
            add_edge(source_id, provider_nodes.get(provider_hint), "provider_binding", "type-prefix")

        for depends_match in re.finditer(r"depends_on\s*=\s*\[([^\]]*)\]", body, flags=re.DOTALL):
            section = depends_match.group(1)
            for token_match in re.finditer(
                r'"([^"]+)"|\'([^\']+)\'|([A-Za-z0-9_]+\.[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)',
                section,
            ):
                token = token_match.group(1) or token_match.group(2) or token_match.group(3) or ""
                add_edge(source_id, ref_to_node_id(token), "depends_on", "explicit")

        for data_match in re.finditer(r"\bdata\.([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\b", body):
            ref = f"data.{data_match.group(1)}.{data_match.group(2)}"
            add_edge(source_id, ref_to_node_id(ref), "references", "implicit")

        for module_match in re.finditer(r"\bmodule\.([A-Za-z0-9_]+)\b", body):
            ref = f"module.{module_match.group(1)}"
            add_edge(source_id, ref_to_node_id(ref), "references", "implicit")

        for resource_match in re.finditer(r"\b([A-Za-z][A-Za-z0-9_]*)\.([A-Za-z][A-Za-z0-9_]*)\b", body):
            first, second = resource_match.group(1), resource_match.group(2)
            if first in TERRAFORM_REF_IGNORES:
                continue
            ref = f"{first}.{second}"
            add_edge(source_id, ref_to_node_id(ref), "references", "implicit")

    nodes.sort(key=lambda item: (item["kind"], item["label"], item["id"]))
    edges.sort(key=lambda item: (item["type"], item["from"], item["to"]))

    return {
        "files": file_list,
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "providers": len([node for node in nodes if node["kind"] == "provider"]),
            "resources": len([node for node in nodes if node["kind"] == "resource"]),
            "data_sources": len([node for node in nodes if node["kind"] == "data"]),
            "modules": len([node for node in nodes if node["kind"] == "module"]),
        },
    }


def render_terraform_drawio(terraform_graph: dict[str, Any], repo_name: str) -> str:
    nodes = terraform_graph.get("nodes", [])
    edges = terraform_graph.get("edges", [])
    generated_at = datetime.now(timezone.utc).isoformat()

    styles = {
        "provider": "rounded=1;whiteSpace=wrap;html=1;fillColor=#dbeafe;strokeColor=#1d4ed8;fontStyle=1;",
        "module": "rounded=1;whiteSpace=wrap;html=1;fillColor=#ffedd5;strokeColor=#c2410c;",
        "data": "rounded=1;whiteSpace=wrap;html=1;fillColor=#e2e8f0;strokeColor=#475569;",
        "resource": "rounded=1;whiteSpace=wrap;html=1;fillColor=#dcfce7;strokeColor=#15803d;",
    }
    risk_scores = {"provider": 0.35, "module": 0.5, "data": 0.45, "resource": 0.7}

    columns = {"provider": 40, "module": 350, "data": 660, "resource": 970}
    row_height = 110
    row_state = {key: 0 for key in columns}

    ordered_nodes = sorted(
        nodes,
        key=lambda item: (
            {"provider": 0, "module": 1, "data": 2, "resource": 3}.get(item.get("kind", "resource"), 9),
            item.get("label", ""),
        ),
    )

    cell_ids: dict[str, str] = {}
    lines = [
        '<mxfile host="app.diagrams.net" type="device">',
        f'  <diagram id="terraform-iac" name="Terraform IaC - {html.escape(repo_name, quote=True)}">',
        '    <mxGraphModel dx="1800" dy="1000" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="2200" pageHeight="1400" math="0" shadow="0">',
        "      <root>",
        '        <mxCell id="0" />',
        '        <mxCell id="1" parent="0" />',
    ]

    next_id = 2
    if not ordered_nodes:
        lines.append(
            '        <mxCell id="2" value="Terraform files detected&#xa;No provider/resource/module/data blocks found" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#fef3c7;strokeColor=#b45309;" vertex="1" parent="1">'
        )
        lines.append('          <mxGeometry x="120" y="80" width="520" height="80" as="geometry" />')
        lines.append("        </mxCell>")
        next_id = 3

    for node in ordered_nodes:
        kind = node.get("kind", "resource")
        x = columns.get(kind, 970)
        y = 50 + row_state.get(kind, 0) * row_height
        row_state[kind] = row_state.get(kind, 0) + 1

        risk = risk_scores.get(kind, 0.5)
        value = f"{node.get('label', node.get('id', 'node'))}\n[{kind}]\nrisk:{risk:.2f}"
        escaped_value = html.escape(value, quote=True).replace("\n", "&#xa;")
        cell_id = str(next_id)
        next_id += 1
        cell_ids[node["id"]] = cell_id

        lines.append(
            f'        <mxCell id="{cell_id}" value="{escaped_value}" style="{styles.get(kind, styles["resource"])}" vertex="1" parent="1">'
        )
        lines.append(f'          <mxGeometry x="{x}" y="{y}" width="260" height="72" as="geometry" />')
        lines.append("        </mxCell>")

    for edge in edges:
        source = cell_ids.get(edge.get("from", ""))
        target = cell_ids.get(edge.get("to", ""))
        if not source or not target:
            continue

        edge_id = str(next_id)
        next_id += 1
        value = html.escape(edge.get("type", "link"), quote=True)
        style = (
            "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;"
            "html=1;endArrow=block;endFill=1;strokeColor=#64748b;"
        )
        lines.append(
            f'        <mxCell id="{edge_id}" value="{value}" style="{style}" edge="1" parent="1" source="{source}" target="{target}">'
        )
        lines.append('          <mxGeometry relative="1" as="geometry" />')
        lines.append("        </mxCell>")

    lines.extend(
        [
            "      </root>",
            "    </mxGraphModel>",
            "  </diagram>",
            "</mxfile>",
            f"<!-- generated_at: {generated_at} -->",
        ]
    )
    return "\n".join(lines) + "\n"


def _top_function_hotspots(function_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fan_in = Counter(edge["to"] for edge in function_calls)
    fan_out = Counter(edge["from"] for edge in function_calls)
    function_ids = sorted(set(fan_in.keys()) | set(fan_out.keys()))

    rows = []
    for fn in function_ids:
        in_count = fan_in.get(fn, 0)
        out_count = fan_out.get(fn, 0)
        score = in_count + out_count
        if score == 0:
            continue
        rows.append(
            {
                "function": fn,
                "fan_in": in_count,
                "fan_out": out_count,
                "hotspot_score": score,
            }
        )
    rows.sort(key=lambda item: item["hotspot_score"], reverse=True)
    return rows[:25]


def build_core_leaf_tags(module_metrics: list[dict[str, Any]]) -> dict[str, str]:
    if not module_metrics:
        return {}
    top_count = max(1, math.ceil(len(module_metrics) * 0.2))
    tags = {}
    for i, row in enumerate(module_metrics):
        if row["coupling_out"] == 0:
            tags[row["module"]] = "leaf"
        elif i < top_count:
            tags[row["module"]] = "core"
        else:
            tags[row["module"]] = "middle"
    return tags


def render_architecture_mermaid(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    entrypoints: list[str],
    core_leaf_tags: dict[str, str],
) -> str:
    lines = ["flowchart LR"]
    entrypoint_ids = {f"file:{item}" for item in entrypoints}

    for node in nodes:
        label = node["label"].replace('"', "'")
        node_id = _sanitize(node["id"])
        lines.append(f"    {node_id}[\"{_short(label, 44)}\"]")

    for edge in edges:
        source = _sanitize(edge["from"])
        target = _sanitize(edge["to"])
        label = edge["type"]
        if edge.get("confidence"):
            label += f" ({edge['confidence']})"
        lines.append(f"    {source} -->|{label}| {target}")

    lines.append("    classDef entry fill:#0f766e,stroke:#134e4a,color:#f0fdfa;")
    lines.append("    classDef external fill:#334155,stroke:#0f172a,color:#e2e8f0;")
    lines.append("    classDef core fill:#2563eb,stroke:#1d4ed8,color:#eff6ff;")
    lines.append("    classDef leaf fill:#cbd5e1,stroke:#64748b,color:#0f172a;")

    for node in nodes:
        node_id = _sanitize(node["id"])
        if node["id"] in entrypoint_ids:
            lines.append(f"    class {node_id} entry;")
        elif node["type"] == "external":
            lines.append(f"    class {node_id} external;")
        else:
            rel = node["label"]
            tag = core_leaf_tags.get(rel)
            if tag == "core":
                lines.append(f"    class {node_id} core;")
            elif tag == "leaf":
                lines.append(f"    class {node_id} leaf;")

    return "\n".join(lines) + "\n"


def render_dependency_mermaid(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    cycles: list[list[str]],
) -> str:
    lines = ["flowchart LR"]
    for node in nodes:
        if node["type"] != "module":
            continue
        lines.append(f"    {_sanitize(node['id'])}[\"{_short(node['label'], 36)}\"]")

    for edge in edges:
        if edge["type"] not in {"imports", "depends_on"}:
            continue
        if not edge["from"].startswith("file:") or not edge["to"].startswith("file:"):
            continue
        lines.append(f"    {_sanitize(edge['from'])} --> {_sanitize(edge['to'])}")

    lines.append("    classDef cycle fill:#fca5a5,stroke:#7f1d1d,color:#111827;")
    lines.append("    classDef default fill:#dbeafe,stroke:#1d4ed8,color:#0f172a;")

    cycle_nodes = {node for component in cycles for node in component}
    for node in cycle_nodes:
        lines.append(f"    class {_sanitize(node)} cycle;")

    return "\n".join(lines) + "\n"


def render_call_mermaid(function_calls: list[dict[str, Any]]) -> str:
    lines = ["flowchart LR"]
    edges = function_calls[:120]

    seen = set()
    for edge in edges:
        source = _sanitize(edge["from"])
        target = _sanitize(edge["to"])
        if source not in seen:
            lines.append(f"    {source}[\"{_short(edge['from'].split('::')[-1], 30)}\"]")
            seen.add(source)
        if target not in seen:
            lines.append(f"    {target}[\"{_short(edge['to'].split('::')[-1], 30)}\"]")
            seen.add(target)

        label = edge.get("confidence", "")
        connector = f" -->|{label}| " if label else " --> "
        lines.append(f"    {source}{connector}{target}")

    if len(lines) == 1:
        lines.append("    no_calls[\"No call graph data detected\"]")

    return "\n".join(lines) + "\n"


def render_er_mermaid(entities: list[dict[str, Any]], relationships: list[dict[str, Any]]) -> str:
    if not entities:
        return "erDiagram\n    NO_SCHEMA {\n      string note\n    }\n"

    lines = ["erDiagram"]
    for entity in entities:
        lines.append(f"    {entity['name']} {{")
        for field in entity.get("fields", [])[:12]:
            field_type = field.get("type", "string").lower()
            if field_type not in SQL_SCALARS:
                field_type = "string"
            lines.append(f"      {field_type} {field['name']}")
        lines.append("    }")

    for relation in relationships:
        left = relation.get("from")
        right = relation.get("to")
        if left and right:
            lines.append(f"    {left} ||--o{{ {right} : {relation.get('type', 'rel')}")

    return "\n".join(lines) + "\n"


def render_dbml(entities: list[dict[str, Any]], relationships: list[dict[str, Any]]) -> str:
    if not entities:
        return "// No schema detected\n"

    lines = []
    for entity in entities:
        lines.append(f"Table {entity['name']} {{")
        for field in entity.get("fields", [])[:20]:
            lines.append(f"  {field['name']} {field.get('type', 'varchar')}")
        lines.append("}")
        lines.append("")

    for relation in relationships:
        left = relation.get("from")
        right = relation.get("to")
        field = relation.get("field", "id")
        target_field = relation.get("target_field", "id")
        if left and right:
            lines.append(f"Ref: {left}.{field} > {right}.{target_field}")

    return "\n".join(lines).strip() + "\n"


def build_key_flows(
    routes: list[dict[str, Any]],
    module_call_edges: list[dict[str, Any]],
    entities: list[dict[str, Any]],
) -> list[dict[str, str]]:
    by_source = defaultdict(list)
    for edge in module_call_edges:
        by_source[edge["from"]].append(edge["to"])

    data_target = entities[0]["name"] if entities else "datastore"

    flows = []
    for route in routes[:8]:
        source = route["file"]
        middle = by_source[source][0] if by_source[source] else source
        flows.append(
            {
                "name": f"{route['method']} {route['path']}",
                "flow": f"Request -> {source} -> {middle} -> {data_target}",
            }
        )

    if not flows:
        flows.append({"name": "default", "flow": "Request -> Entry -> Core Module -> Datastore"})
    return flows


def render_onboarding_markdown(
    start_here: list[str],
    flows: list[dict[str, str]],
    glossary: list[dict[str, str]],
    change_safely: dict[str, Any],
) -> str:
    lines = ["# Onboarding Map", "", "## Start Here (5 files)", ""]
    for idx, path in enumerate(start_here, start=1):
        lines.append(f"{idx}. `{path}`")

    lines.extend(["", "## Key Flows", ""])
    for flow in flows:
        lines.append(f"- **{flow['name']}**: {flow['flow']}")

    lines.extend(["", "## Glossary", ""])
    for item in glossary[:10]:
        lines.append(f"- **{item['term']}** (`{item['location']}`): {item['definition']}")

    lines.extend(["", "## Change Safely", ""])
    lines.append("Tests to run:")
    for command in change_safely.get("tests_to_run", []):
        lines.append(f"- `{command}`")

    lines.append("")
    lines.append("Critical invariants:")
    for invariant in change_safely.get("critical_invariants", []):
        lines.append(f"- {invariant}")

    return "\n".join(lines) + "\n"


def render_top_files_markdown(module_metrics: list[dict[str, Any]], core_leaf_tags: dict[str, str]) -> str:
    lines = ["# Top Files", "", "| File | Hotspot Score | Coupling In | Coupling Out | Tag |", "| --- | ---: | ---: | ---: | --- |"]
    for row in module_metrics[:15]:
        tag = core_leaf_tags.get(row["module"], "middle")
        lines.append(
            f"| `{row['module']}` | {row['hotspot_score']:.2f} | {row['coupling_in']} | {row['coupling_out']} | {tag} |"
        )
    return "\n".join(lines) + "\n"


def render_index_markdown(summary: dict[str, Any], terraform_drawio_file: str | None = None) -> str:
    sections = [
        "# Code Autopsy X-Ray",
        "",
        f"Generated at: `{summary['generated_at']}`",
        "",
        "## Summary",
        "",
        f"- Repository: `{summary['repo_name']}`",
        f"- Languages: {', '.join(summary['languages']) if summary['languages'] else 'Not detected'}",
        f"- Frameworks: {', '.join(summary['frameworks']) if summary['frameworks'] else 'Not detected'}",
        f"- Entrypoints: {', '.join(summary['entrypoints']) if summary['entrypoints'] else 'Not detected'}",
        f"- Files Indexed: {summary['files_indexed']}",
        f"- Files Skipped: {summary['files_skipped']}",
        "",
        "## Artifacts",
        "",
        "- [System Architecture](architecture.mmd)",
        "- [ER Diagram](er.mmd)",
        "- [Call Graph](call-graph.mmd)",
        "- [Dependency Graph](dependencies.mmd)",
        "- [Onboarding Map](onboarding.md)",
        "- [Top Files](top-files.md)",
        "- [Dashboard State](dashboard_state.json)",
        "",
        "## Notes",
        "",
        "- 3D graph mode is KIV (Phase 2) and not part of this MVP.",
        "- If no DB schema is detected, ER outputs include explicit placeholder sections.",
    ]
    if terraform_drawio_file:
        insert_at = sections.index("- [Dashboard State](dashboard_state.json)")
        sections.insert(insert_at, f"- [Terraform IaC (draw.io)]({terraform_drawio_file})")
    return "\n".join(sections) + "\n"


def render_case_file(errors: list[str], skipped: int, confidence_notes: list[str]) -> str:
    lines = [
        "# Case File",
        "",
        "## Scope & Assumptions",
        "",
        "- Local repository analysis only.",
        "- Static extraction for TS/JS and Python with deterministic heuristics.",
        "- 3D graph rendering is deferred to Phase 2.",
        f"- Files skipped due to limits/filters: {skipped}.",
        "",
        "## Confidence Notes",
        "",
    ]

    if confidence_notes:
        for note in confidence_notes:
            lines.append(f"- {note}")
    else:
        lines.append("- High confidence for syntax-level symbols and route regex matches.")

    lines.extend(["", "## Parser/Extraction Issues", ""])
    if errors:
        for err in errors[:100]:
            lines.append(f"- {err}")
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"


def _short(text: str, limit: int = 40) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _sanitize(value: str) -> str:
    return "n_" + re.sub(r"[^a-zA-Z0-9_]", "_", value)


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def run_xray(config: XrayConfig) -> dict[str, Any]:
    repo_path = config.repo_path
    output_root = config.output_root

    all_possible_files = [
        p
        for p in sorted(repo_path.rglob("*"))
        if p.is_file() and p.suffix in SUPPORTED_EXTENSIONS and not _should_skip(p, repo_path)
    ]
    files = all_possible_files[: config.max_files]
    skipped = max(0, len(all_possible_files) - len(files))

    languages = detect_languages(files)
    frameworks = detect_frameworks(repo_path, files)
    entrypoints = detect_entrypoints(repo_path, files)

    parsed_files, parser_errors = parse_code_files(repo_path, files)
    routes = [route for item in parsed_files for route in item.get("routes", [])]
    models = [model for item in parsed_files for model in item.get("models", [])]

    import_edges, external_import_edges = build_import_edges(parsed_files)
    module_call_edges, function_call_edges = build_call_edges(parsed_files)

    prisma_entities, prisma_relationships = parse_prisma_models(repo_path)
    sql_entities, sql_relationships = parse_sql_entities(repo_path)
    entities, relationships = merge_entities_and_relationships(
        prisma_entities,
        prisma_relationships,
        sql_entities,
        sql_relationships,
    )

    external_nodes = [edge["to"].replace("external:", "") for edge in external_import_edges]
    external_nodes.extend(
        edge["to"].replace("external_fn:", "")
        for edge in module_call_edges
        if edge["to"].startswith("external_fn:")
    )

    nodes = build_nodes(parsed_files, external_nodes)
    edges = build_graph_edges(import_edges, external_import_edges, module_call_edges, entrypoints)

    module_metrics = score_modules(nodes, edges)
    apply_criticality(nodes, module_metrics)
    cycles = detect_cycles(nodes, edges)
    function_hotspots = _top_function_hotspots(function_call_edges)
    core_leaf_tags = build_core_leaf_tags(module_metrics)

    start_here = build_start_here(entrypoints, routes, module_metrics, entities, parsed_files)
    glossary = build_glossary(entities, parsed_files)
    change_safely = build_change_safely(repo_path, parsed_files)
    key_flows = build_key_flows(routes, module_call_edges, entities)
    terraform_files = discover_terraform_files(repo_path)
    terraform_graph = build_terraform_graph(repo_path, terraform_files)

    terraform_drawio_file = None
    terraform_drawio = ""
    if terraform_graph.get("files"):
        terraform_drawio_file = "terraform-architecture.drawio"
        terraform_drawio = render_terraform_drawio(terraform_graph, repo_path.name)

    architecture_mmd = render_architecture_mermaid(nodes, edges, entrypoints, core_leaf_tags)
    er_mmd = render_er_mermaid(entities, relationships)
    dbml = render_dbml(entities, relationships)
    call_mmd = render_call_mermaid(function_call_edges)
    dependency_mmd = render_dependency_mermaid(nodes, edges, cycles)

    confidence_notes = [
        "Dynamic dispatch and reflection calls are approximated as low confidence.",
        "JSImport resolution uses heuristic path matching for package aliases.",
    ]

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_name": repo_path.name,
        "repo_root": repo_path.as_posix(),
        "languages": languages,
        "frameworks": frameworks,
        "entrypoints": entrypoints,
        "files_indexed": len(files),
        "files_skipped": skipped,
        "mode": "xray",
        "terraform_detected": bool(terraform_graph.get("files")),
        "terraform_files": len(terraform_graph.get("files", [])),
    }

    repo_json = {
        "name": repo_path.name,
        "root": repo_path.as_posix(),
        "languages": languages,
        "frameworks": frameworks,
        "entrypoints": entrypoints,
        "indexing": {
            "strategy": "full" if skipped == 0 else "tiered",
            "files_indexed": len(files),
            "files_skipped": skipped,
        },
    }

    graph_json = {
        "nodes": nodes,
        "edges": edges,
    }

    metrics_json = {
        "module_metrics": [
            {
                "module": row["module"],
                "complexity": row["complexity"],
                "coupling_in": row["coupling_in"],
                "coupling_out": row["coupling_out"],
                "test_coverage_proxy": row["test_coverage_proxy"],
                "ownership_risk": row["ownership_risk"],
                "dependency_fragility": row["dependency_fragility"],
                "hotspot_score": row["hotspot_score"],
            }
            for row in module_metrics
        ]
    }

    onboarding_md = render_onboarding_markdown(start_here, key_flows, glossary, change_safely)
    top_files_md = render_top_files_markdown(module_metrics, core_leaf_tags)
    index_md = render_index_markdown(summary, terraform_drawio_file=terraform_drawio_file)
    case_file_md = render_case_file(parser_errors, skipped, confidence_notes)

    diagram_payload: dict[str, str] = {
        "architecture": architecture_mmd,
        "er": er_mmd,
        "call_graph": call_mmd,
        "dependencies": dependency_mmd,
    }
    if terraform_drawio:
        diagram_payload["terraform_drawio"] = terraform_drawio

    dashboard_state = {
        "generated_at": summary["generated_at"],
        "summary": summary,
        "graphs": {
            "nodes": nodes,
            "edges": edges,
            "cycles": cycles,
            "hotspots": module_metrics[:30],
            "function_hotspots": function_hotspots,
            "core_leaf_tags": core_leaf_tags,
        },
        "diagrams": diagram_payload,
        "onboarding": {
            "start_here": start_here,
            "key_flows": key_flows,
            "glossary": glossary,
            "change_safely": change_safely,
        },
        "kiv": {
            "graph_3d": "Deferred to Phase 2",
        },
        "iac": {
            "terraform": {
                "detected": bool(terraform_graph.get("files")),
                "file_count": len(terraform_graph.get("files", [])),
                "drawio_file": terraform_drawio_file,
                "resources": terraform_graph.get("summary", {}).get("resources", 0),
                "modules": terraform_graph.get("summary", {}).get("modules", 0),
                "data_sources": terraform_graph.get("summary", {}).get("data_sources", 0),
                "providers": terraform_graph.get("summary", {}).get("providers", 0),
            }
        },
    }

    artifacts_dir = output_root / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    _json_dump(output_root / "repo.json", repo_json)
    _json_dump(output_root / "graph.json", graph_json)
    _json_dump(output_root / "metrics.json", metrics_json)
    _json_dump(output_root / "dashboard_state.json", dashboard_state)

    _json_dump(artifacts_dir / "entrypoints.json", {"entrypoints": entrypoints})
    _json_dump(artifacts_dir / "routes.json", {"routes": routes})
    _json_dump(artifacts_dir / "models.json", {"models": models})
    _json_dump(artifacts_dir / "imports.json", {"imports": import_edges, "external_imports": external_import_edges})
    _json_dump(artifacts_dir / "calls.json", {"module_calls": module_call_edges, "function_calls": function_call_edges})
    _json_dump(artifacts_dir / "entities.json", {"entities": entities, "relationships": relationships})
    _json_dump(artifacts_dir / "cycles.json", {"cycles": cycles})
    _json_dump(
        artifacts_dir / "hotspots.json",
        {"modules": module_metrics[:30], "functions": function_hotspots},
    )
    _json_dump(artifacts_dir / "glossary.json", {"glossary": glossary})
    if terraform_graph.get("files"):
        _json_dump(artifacts_dir / "terraform.json", terraform_graph)

    (output_root / "architecture.mmd").write_text(architecture_mmd, encoding="utf-8")
    (output_root / "er.mmd").write_text(er_mmd, encoding="utf-8")
    (output_root / "er.dbml").write_text(dbml, encoding="utf-8")
    (output_root / "call-graph.mmd").write_text(call_mmd, encoding="utf-8")
    (output_root / "dependencies.mmd").write_text(dependency_mmd, encoding="utf-8")
    (output_root / "onboarding.md").write_text(onboarding_md, encoding="utf-8")
    (output_root / "top-files.md").write_text(top_files_md, encoding="utf-8")
    (output_root / "index.md").write_text(index_md, encoding="utf-8")
    (output_root / "case_file.md").write_text(case_file_md, encoding="utf-8")
    if terraform_drawio_file and terraform_drawio:
        (output_root / terraform_drawio_file).write_text(terraform_drawio, encoding="utf-8")

    return {
        "output_root": output_root,
        "summary": summary,
        "start_here": start_here,
        "warnings": parser_errors,
    }

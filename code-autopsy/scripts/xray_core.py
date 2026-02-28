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
IAC_EXTENSIONS = {".tf", ".hcl", ".tfvars", ".bicep", ".yaml", ".yml", ".json"}
IAC_YAML_EXTENSIONS = {".yaml", ".yml"}
DEFAULT_IGNORE_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "coverage",
    ".next",
    "_next",
    ".turbo",
    ".cache",
    "__pycache__",
    "viewer-static",
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
NON_SIGNAL_CALLEES = {
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "options",
    "head",
    "json",
    "var",
    "async",
}
API_FRAMEWORKS = {"FastAPI", "Express", "Django", "Flask", "NestJS", "Fastify"}
IAC_PROVIDER_ALIASES = {
    "aws": "AWS",
    "google": "GCP",
    "gcp": "GCP",
    "azurerm": "Azure",
    "azure": "Azure",
    "kubernetes": "Kubernetes",
    "helm": "Helm",
    "docker": "Docker",
    "pulumi": "Pulumi",
}
TERRAFORM_REF_IGNORES = {"var", "local", "path", "count", "each", "self", "terraform"}


@dataclass
class XrayConfig:
    repo_path: Path
    output_root: Path
    lang_hints: set[str]
    max_files: int
    source_reference: str | None = None
    source_kind: str = "local_path"


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
    if rel_path.startswith("docs/code-autopsy/") or "/docs/code-autopsy/" in rel_path:
        return True
    if rel_path.startswith("viewer-static/") or "/viewer-static/" in rel_path:
        return True
    if rel_path.startswith("_next/") or "/_next/" in rel_path:
        return True
    if "/docs/site/" in rel_path:
        return True
    return False


def _is_iac_candidate(path: Path, repo_path: Path) -> bool:
    if path.suffix.lower() not in IAC_EXTENSIONS:
        return False
    if _should_skip(path, repo_path):
        return False

    rel = path.relative_to(repo_path).as_posix().lower()
    name = path.name.lower()
    suffix = path.suffix.lower()

    if suffix in {".tf", ".hcl", ".tfvars", ".bicep"}:
        return True
    if name in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml", "pulumi.yaml", "pulumi.yml"}:
        return True
    if any(token in rel for token in ("k8s/", "kubernetes/", "/manifests/", "/helm/", "/charts/")) and suffix in IAC_YAML_EXTENSIONS:
        return True
    if suffix in IAC_YAML_EXTENSIONS and any(token in rel for token in ("cloudformation", "cfn", "sam", "template", "infra")):
        return True
    if suffix == ".json" and any(token in rel for token in ("cloudformation", "cfn", "template")):
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
            if callee.lower() in NON_SIGNAL_CALLEES:
                # Skip noisy call tokens that are not meaningful cross-file dependencies.
                continue
            caller_name = call.get("caller", "<module>")
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
                function_calls.append(
                    {
                        "from": f"{source}::{caller_name}",
                        "to": f"external::{callee}",
                        "callee": callee,
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
            if source == target_file and caller_name == "<module>" and reason in {
                "regex-callsite",
                "function-index",
            }:
                # Avoid self-loop noise from regex-level JS call extraction.
                continue

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
                    "from": f"{source}::{caller_name}",
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


def _normalize_iac_provider(raw_provider: str) -> str:
    token = raw_provider.strip().lower()
    return IAC_PROVIDER_ALIASES.get(token, token.upper() if len(token) <= 5 else token.title())


def _classify_iac_layer(kind: str) -> str:
    token = kind.lower()
    if any(
        key in token
        for key in (
            "vpc",
            "subnet",
            "network",
            "route",
            "gateway",
            "ingress",
            "loadbalancer",
            "load_balancer",
            "dns",
            "cdn",
            "nat",
            "firewall",
        )
    ):
        return "network"
    if any(
        key in token
        for key in (
            "iam",
            "policy",
            "role",
            "rbac",
            "serviceaccount",
            "securitygroup",
            "security_group",
            "secret",
            "kms",
            "keyvault",
            "networkpolicy",
        )
    ):
        return "security"
    if any(
        key in token
        for key in (
            "db",
            "database",
            "rds",
            "sql",
            "dynamodb",
            "redis",
            "cache",
            "bucket",
            "storage",
            "s3",
            "persistentvolume",
            "persistentvolumeclaim",
            "spanner",
        )
    ):
        return "data"
    if any(
        key in token
        for key in (
            "deployment",
            "statefulset",
            "daemonset",
            "job",
            "cronjob",
            "pod",
            "service",
            "container",
            "instance",
            "lambda",
            "function",
            "ecs",
            "eks",
            "gke",
            "vm",
            "compute",
            "cloudrun",
            "appservice",
        )
    ):
        return "compute"
    if any(key in token for key in ("monitor", "alert", "log", "cloudwatch", "prometheus", "grafana", "insight")):
        return "observability"
    return "platform"


def _looks_like_compose(name: str, text: str) -> bool:
    if name in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}:
        return True
    return bool(re.search(r"(?mi)^\s*services\s*:\s*$", text))


def _looks_like_k8s_yaml(text: str) -> bool:
    return bool(re.search(r"(?mi)^\s*apiVersion\s*:\s*\S+", text) and re.search(r"(?mi)^\s*kind\s*:\s*\S+", text))


def _looks_like_cloudformation(text: str) -> bool:
    return bool("awstemplateformatversion" in text.lower() or re.search(r"(?mi)^\s*resources\s*:\s*$", text))


def parse_iac_artifacts(repo_path: Path) -> dict[str, Any]:
    files: list[str] = []
    resources: list[dict[str, Any]] = []
    providers: Counter = Counter()
    source_types: Counter = Counter()
    errors: list[str] = []

    candidates = [path for path in sorted(repo_path.rglob("*")) if path.is_file() and _is_iac_candidate(path, repo_path)]
    for path in candidates[:500]:
        rel = path.relative_to(repo_path).as_posix()
        suffix = path.suffix.lower()
        name = path.name.lower()
        text = _read_text(path)
        if not text:
            continue
        files.append(rel)

        try:
            if suffix in {".tf", ".hcl", ".tfvars"}:
                source_types["terraform"] += 1
                for raw in re.findall(r'provider\s+"([^"]+)"', text):
                    providers[_normalize_iac_provider(raw)] += 1
                for resource_type, resource_name in re.findall(r'resource\s+"([^"]+)"\s+"([^"]+)"', text):
                    provider_hint = resource_type.split("_", 1)[0]
                    providers[_normalize_iac_provider(provider_hint)] += 1
                    resources.append(
                        {
                            "name": resource_name,
                            "kind": resource_type,
                            "layer": _classify_iac_layer(resource_type),
                            "provider": _normalize_iac_provider(provider_hint),
                            "source": rel,
                            "confidence": "high",
                        }
                    )
                for module_name in re.findall(r'module\s+"([^"]+)"', text):
                    resources.append(
                        {
                            "name": module_name,
                            "kind": "terraform_module",
                            "layer": "platform",
                            "provider": "Terraform",
                            "source": rel,
                            "confidence": "medium",
                        }
                    )
                    providers["Terraform"] += 1
                continue

            if suffix == ".bicep":
                source_types["bicep"] += 1
                providers["Azure"] += 1
                for name_token, type_token in re.findall(r"resource\s+(\w+)\s+['\"]([^'\"]+)['\"]", text):
                    kind = type_token.split("@", 1)[0]
                    resources.append(
                        {
                            "name": name_token,
                            "kind": kind,
                            "layer": _classify_iac_layer(kind),
                            "provider": "Azure",
                            "source": rel,
                            "confidence": "medium",
                        }
                    )
                continue

            if _looks_like_compose(name, text):
                source_types["compose"] += 1
                providers["Docker"] += 1
                block = re.search(r"(?ms)^\s*services:\s*\n(.*?)(?:^\S|\Z)", text)
                if block:
                    for service_name in re.findall(r"(?m)^\s{2}([A-Za-z0-9._-]+)\s*:\s*$", block.group(1)):
                        resources.append(
                            {
                                "name": service_name,
                                "kind": "compose_service",
                                "layer": "compute",
                                "provider": "Docker",
                                "source": rel,
                                "confidence": "medium",
                            }
                        )
                continue

            if suffix in IAC_YAML_EXTENSIONS and _looks_like_k8s_yaml(text):
                source_types["kubernetes"] += 1
                providers["Kubernetes"] += 1
                docs = re.split(r"\n---\s*\n", text)
                for doc in docs:
                    kind_match = re.search(r"(?mi)^\s*kind\s*:\s*([A-Za-z0-9._-]+)", doc)
                    if not kind_match:
                        continue
                    kind = kind_match.group(1)
                    name_match = re.search(r"(?mi)^\s*name\s*:\s*([A-Za-z0-9._-]+)", doc)
                    name_token = name_match.group(1) if name_match else kind.lower()
                    resources.append(
                        {
                            "name": name_token,
                            "kind": kind,
                            "layer": _classify_iac_layer(kind),
                            "provider": "Kubernetes",
                            "source": rel,
                            "confidence": "high",
                        }
                    )
                continue

            if suffix in IAC_YAML_EXTENSIONS.union({".json"}) and _looks_like_cloudformation(text):
                source_types["cloudformation"] += 1
                providers["AWS"] += 1
                found_types = re.findall(r"(?mi)^\s*Type\s*:\s*([A-Za-z0-9:._/-]+)\s*$", text)
                if not found_types:
                    found_types = ["AWS::CloudFormation::Stack"]
                for index, resource_type in enumerate(found_types, start=1):
                    resources.append(
                        {
                            "name": f"resource_{index}",
                            "kind": resource_type,
                            "layer": _classify_iac_layer(resource_type),
                            "provider": "AWS",
                            "source": rel,
                            "confidence": "medium",
                        }
                    )
                continue

            if name in {"pulumi.yaml", "pulumi.yml"}:
                source_types["pulumi"] += 1
                providers["Pulumi"] += 1
                resources.append(
                    {
                        "name": "pulumi_stack",
                        "kind": "pulumi_project",
                        "layer": "platform",
                        "provider": "Pulumi",
                        "source": rel,
                        "confidence": "medium",
                    }
                )
                continue
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{rel}: {exc}")

    layer_counts = Counter(item["layer"] for item in resources)

    return {
        "files": sorted(set(files)),
        "resources": resources[:500],
        "providers": dict(sorted(providers.items())),
        "source_types": dict(sorted(source_types.items())),
        "layer_counts": dict(sorted(layer_counts.items())),
        "errors": errors[:100],
    }


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
        if source and not _is_low_signal_handoff_file(source):
            return source
    for item in parsed_files:
        path = item["path"].lower()
        if any(token in path for token in ("model", "schema", "db", "prisma", "migration")):
            if not _is_low_signal_handoff_file(item["path"]):
                return item["path"]
    return None


def _is_low_signal_handoff_file(path: str) -> bool:
    lower = path.lower()
    if _is_test_file(lower):
        return True
    name = Path(lower).name
    if name in {"__init__.py", "conftest.py"}:
        return True
    if "/migrations/" in lower or lower.startswith("migrations/"):
        return True
    return False


def _pick_entrypoint_file(entrypoints: list[str]) -> str | None:
    for entry in entrypoints:
        if not _is_low_signal_handoff_file(entry):
            return entry
    return entrypoints[0] if entrypoints else None


def build_start_here(
    entrypoints: list[str],
    routes: list[dict[str, Any]],
    module_metrics: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    parsed_files: list[dict[str, Any]],
) -> list[str]:
    picks = []

    entry_file = _pick_entrypoint_file(entrypoints)
    if entry_file:
        picks.append(entry_file)

    route_file = _pick_route_file(routes)
    if route_file and not _is_low_signal_handoff_file(route_file):
        picks.append(route_file)

    core_file = next(
        (row["module"] for row in module_metrics if not _is_low_signal_handoff_file(row["module"])),
        _pick_core_file(module_metrics),
    )
    if core_file:
        picks.append(core_file)

    data_file = _pick_data_file(entities, parsed_files)
    if data_file:
        picks.append(data_file)

    dedup = []
    seen = set()
    for file_path in picks:
        if file_path and file_path not in seen:
            seen.add(file_path)
            dedup.append(file_path)

    if len(dedup) < 5:
        for item in parsed_files:
            if item["path"] not in seen and not _is_low_signal_handoff_file(item["path"]):
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
        parts = Path(rel).parts
        bucket = "root"
        if "modules" in parts:
            idx = parts.index("modules")
            if idx + 1 < len(parts):
                bucket = f"module:{parts[idx + 1]}"
        elif "envs" in parts:
            idx = parts.index("envs")
            if idx + 1 < len(parts):
                bucket = f"env:{parts[idx + 1]}"

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
                        "scope": bucket,
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


def _terraform_display_label(label: str, kind: str, max_length: int = 36) -> str:
    if kind in {"resource", "data"} and "." in label:
        service, name = label.split(".", 1)
        text = f"{service}\n{name}"
    else:
        text = label

    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "..."


def _render_text_cell(
    cell_id: int,
    value: str,
    x: int,
    y: int,
    width: int = 260,
    height: int = 28,
) -> list[str]:
    escaped = html.escape(value, quote=True)
    return [
        f'        <mxCell id="{cell_id}" value="{escaped}" '
        'style="text;align=center;verticalAlign=middle;whiteSpace=wrap;html=1;'
        'strokeColor=none;fillColor=none;fontSize=12;fontStyle=1;" '
        'vertex="1" parent="1">',
        f'          <mxGeometry x="{x}" y="{y}" width="{width}" height="{height}" as="geometry" />',
        "        </mxCell>",
    ]


def _scope_groups(nodes: list[dict[str, Any]], kind: str) -> list[tuple[str, list[dict[str, Any]]]]:
    groups = {}
    order = []
    for node in [item for item in nodes if item.get("kind") == kind]:
        scope = node.get("scope") or "root"
        if scope not in groups:
            groups[scope] = []
            order.append(scope)
        groups[scope].append(node)
    return [(scope, sorted(groups[scope], key=lambda item: item.get("label", ""))) for scope in order]


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
    edge_styles = {
        "depends_on": "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=block;endFill=1;strokeColor=#b91c1c;",
        "references": "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=block;endFill=1;strokeColor=#64748b;",
        "provider_binding": "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;endArrow=block;endFill=1;strokeColor=#6d28d9;dashed=1;",
    }
    section_titles = {
        "provider": "Providers",
        "module": "Modules",
        "data": "Data Sources",
        "resource": "Resources",
    }

    lines = [
        '<mxfile host="app.diagrams.net" type="device">',
        f'  <diagram id="terraform-iac" name="Terraform IaC - {html.escape(repo_name, quote=True)}">',
        '    <mxGraphModel dx="1800" dy="1000" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" math="0" shadow="0">',
        "      <root>",
        '        <mxCell id="0" />',
        '        <mxCell id="1" parent="0" />',
    ]

    next_id = 2
    if not nodes:
        lines.append(
            '        <mxCell id="2" value="Terraform files detected&#xa;No provider/resource/module/data blocks found" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#fef3c7;strokeColor=#b45309;" vertex="1" parent="1">'
        )
        lines.append('          <mxGeometry x="120" y="80" width="520" height="80" as="geometry" />')
        lines.append("        </mxCell>")
        lines.extend([
            "      </root>",
            "    </mxGraphModel>",
            "  </diagram>",
            "</mxfile>",
            f"<!-- generated_at: {generated_at} -->",
        ])
        return "\n".join(lines) + "\n"

    row_height = 88
    nodes_per_row = 24
    column_width = 320
    max_x = 2000
    max_y = 140

    lane_x = {
        "provider": 40,
        "module": 320,
        "data": 600,
        "resource": 880,
    }

    ordered_kinds = ["provider", "module", "data", "resource"]
    cell_ids: dict[str, str] = {}

    for kind in ordered_kinds:
        kind_nodes = [node for node in nodes if node.get("kind") == kind]
        if not kind_nodes:
            continue

        if kind == "resource":
            title_x = lane_x[kind]
            for row in _render_text_cell(next_id, section_titles[kind], title_x, 8, width=260, height=24):
                lines.append(row)
            next_id += 1

            scope_col = 0
            for scope, scope_nodes in _scope_groups(kind_nodes, "resource"):
                scope_nodes_sorted = sorted(scope_nodes, key=lambda item: item.get("label", ""))
                display_scope = scope.replace("module:", "module:").replace("env:", "env:")
                for chunk_start in range(0, len(scope_nodes_sorted), nodes_per_row):
                    chunk = scope_nodes_sorted[chunk_start:chunk_start + nodes_per_row]
                    chunk_x = lane_x[kind] + scope_col * column_width
                    section_label = f"{display_scope} ({len(scope_nodes_sorted)})"
                    if chunk_start == 0:
                        for row in _render_text_cell(
                            next_id,
                            section_label,
                            chunk_x,
                            36,
                            width=260,
                            height=22,
                        ):
                            lines.append(row)
                        next_id += 1

                    for offset, node in enumerate(chunk):
                        y = 66 + offset * row_height
                        risk = risk_scores.get(kind, 0.5)
                        value = (
                            f"{_terraform_display_label(node.get('label', node.get('id', 'node')), kind)}\n"
                            f"[{kind}] risk:{risk:.2f}"
                        )
                        escaped_value = html.escape(value, quote=True).replace("\n", "&#xa;")
                        cell_id = str(next_id)
                        next_id += 1
                        cell_ids[node["id"]] = cell_id
                        lines.append(
                            f'        <mxCell id="{cell_id}" value="{escaped_value}" style="{styles.get(kind, styles["resource"])}" vertex="1" parent="1">'
                        )
                        lines.append(
                            f'          <mxGeometry x="{chunk_x}" y="{y}" width="250" height="72" as="geometry" />'
                        )
                        lines.append("        </mxCell>")
                        max_x = max(max_x, chunk_x + 250)
                        max_y = max(max_y, y + 72 + 20)

                    scope_col += 1
        else:
            title_x = lane_x[kind]
            for row in _render_text_cell(next_id, section_titles[kind], title_x, 8, width=260, height=24):
                lines.append(row)
            next_id += 1
            for offset, node in enumerate(sorted(kind_nodes, key=lambda item: item.get("label", ""))):
                y = 40 + offset * row_height
                risk = risk_scores.get(kind, 0.5)
                value = f"{_terraform_display_label(node.get('label', node.get('id', 'node')), kind)}\n[{kind}] risk:{risk:.2f}"
                escaped_value = html.escape(value, quote=True).replace("\n", "&#xa;")
                cell_id = str(next_id)
                next_id += 1
                cell_ids[node["id"]] = cell_id
                lines.append(
                    f'        <mxCell id="{cell_id}" value="{escaped_value}" style="{styles.get(kind, styles["resource"])}" vertex="1" parent="1">'
                )
                lines.append(f'          <mxGeometry x="{title_x}" y="{y}" width="250" height="72" as="geometry" />')
                lines.append("        </mxCell>")
                max_x = max(max_x, title_x + 250)
                max_y = max(max_y, y + 72 + 20)

    for edge in edges:
        source = cell_ids.get(edge.get("from", ""))
        target = cell_ids.get(edge.get("to", ""))
        if not source or not target:
            continue

        edge_id = str(next_id)
        next_id += 1
        value = html.escape(edge.get("type", "link"), quote=True)
        edge_style = edge_styles.get(edge.get("type", "references"), edge_styles["references"])
        lines.append(
            f'        <mxCell id="{edge_id}" value="{value}" style="{edge_style}" edge="1" parent="1" source="{source}" target="{target}">'
        )
        lines.append("          <mxGeometry relative=\"1\" as=\"geometry\" />")
        lines.append("        </mxCell>")

    lines[3] = f'    <mxGraphModel dx="1800" dy="1000" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{max(2200, max_x + 300)}" pageHeight="{max(1200, max_y + 200)}" math="0" shadow="0">'

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


def _classify_arch_layer(rel_path: str) -> str:
    lower = rel_path.lower()
    if (
        lower.startswith("api/")
        or "/api/" in lower
        or lower.endswith("/route.ts")
        or lower.endswith("/route.js")
        or lower.endswith("/route.py")
    ):
        return "api"
    if lower.startswith(("app/", "src/app/", "pages/", "src/pages/", "components/", "src/components/")):
        return "web"
    if any(token in lower for token in ("/worker", "worker/", "/jobs", "/job", "/queue", "/queues", "/cron")):
        return "worker"
    if "config" in lower:
        return "config"
    return "core"


def render_architecture_mermaid(
    parsed_files: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    frameworks: list[str],
    routes: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    entrypoints: list[str],
) -> str:
    lines = ["flowchart LR"]
    module_layers: dict[str, str] = {}
    layer_counts = Counter()
    for item in parsed_files:
        module_id = f"file:{item['path']}"
        layer = _classify_arch_layer(item["path"])
        module_layers[module_id] = layer
        if layer != "config":
            layer_counts[layer] += 1

    if "Next.js" in frameworks:
        layer_counts["web"] = max(1, layer_counts["web"])
    if routes or any(fw in API_FRAMEWORKS for fw in frameworks):
        layer_counts["api"] = max(1, layer_counts["api"])
    if entrypoints and layer_counts["core"] == 0:
        layer_counts["core"] = 1

    layer_nodes = {
        "web": "n_web_app",
        "api": "n_api_service",
        "worker": "n_worker",
        "core": "n_core",
    }
    layer_titles = {
        "web": "Web App",
        "api": "API Service",
        "worker": "Worker",
        "core": "Core Modules",
    }

    lines.append('    n_client["Client / Browser"]')
    present_layers = [layer for layer in ("web", "api", "worker", "core") if layer_counts.get(layer, 0) > 0]
    for layer in present_layers:
        count = layer_counts[layer]
        title = f"{layer_titles[layer]} ({count})"
        lines.append(f'    {layer_nodes[layer]}["{_mermaid_safe_text(title)}"]')

    has_datastore = bool(entities)
    if has_datastore:
        lines.append('    n_datastore[("Datastore")]')

    external_by_layer: dict[str, Counter] = defaultdict(Counter)
    cross_layer_counts: Counter = Counter()
    for edge in edges:
        if not edge["from"].startswith("file:"):
            continue
        src_layer = module_layers.get(edge["from"])
        if not src_layer or src_layer == "config":
            continue
        target = edge["to"]
        if target.startswith("file:"):
            dst_layer = module_layers.get(target)
            if dst_layer and dst_layer != src_layer and dst_layer != "config":
                cross_layer_counts[(src_layer, dst_layer, edge["type"])] += 1
        elif target.startswith("external:"):
            external_by_layer[src_layer][target.replace("external:", "")] += 1

    rendered_edges: set[tuple[str, str, str]] = set()

    def add_edge(src: str, dst: str, label: str) -> None:
        key = (src, dst, label)
        if key in rendered_edges:
            return
        rendered_edges.add(key)
        lines.append(f"    {src} -->|{_mermaid_edge_label(label)}| {dst}")

    if "web" in present_layers:
        add_edge("n_client", layer_nodes["web"], "request")
    elif "api" in present_layers:
        add_edge("n_client", layer_nodes["api"], "request")
    elif "core" in present_layers:
        add_edge("n_client", layer_nodes["core"], "request")

    if "web" in present_layers and "api" in present_layers:
        add_edge(layer_nodes["web"], layer_nodes["api"], "api_call")

    for src_layer, dst_layer, edge_type in sorted(cross_layer_counts.keys()):
        if src_layer in layer_nodes and dst_layer in layer_nodes:
            if src_layer in present_layers and dst_layer in present_layers:
                add_edge(layer_nodes[src_layer], layer_nodes[dst_layer], edge_type)

    if has_datastore:
        if "api" in present_layers:
            add_edge(layer_nodes["api"], "n_datastore", "read_write")
        elif "core" in present_layers:
            add_edge(layer_nodes["core"], "n_datastore", "read_write")
        elif "worker" in present_layers:
            add_edge(layer_nodes["worker"], "n_datastore", "read_write")

    external_totals = Counter()
    for counter in external_by_layer.values():
        external_totals.update(counter)
    top_externals = [name for name, _ in external_totals.most_common(8)]
    for ext in top_externals:
        ext_id = _sanitize(f"external:{ext}")
        lines.append(f'    {ext_id}["{_short(_mermaid_safe_text(ext), 34)}"]')
        for layer in present_layers:
            count = external_by_layer[layer].get(ext, 0)
            if count > 0 and layer in layer_nodes:
                add_edge(layer_nodes[layer], ext_id, "depends_on")

    if routes and "api" in present_layers:
        route_node_id = "n_routes"
        lines.append(f'    {route_node_id}["Routes ({len(routes)})"]')
        add_edge(layer_nodes["api"], route_node_id, "serves")

    if entrypoints:
        entry_id = "n_entrypoints"
        lines.append(f'    {entry_id}["Entrypoints ({len(entrypoints)})"]')
        if "api" in present_layers:
            add_edge(entry_id, layer_nodes["api"], "boot")
        elif "web" in present_layers:
            add_edge(entry_id, layer_nodes["web"], "boot")
        elif "core" in present_layers:
            add_edge(entry_id, layer_nodes["core"], "boot")

    lines.append("    classDef client fill:#0ea5e9,stroke:#0f172a,color:#082f49;")
    lines.append("    classDef service fill:#2563eb,stroke:#1e3a8a,color:#eff6ff;")
    lines.append("    classDef data fill:#22c55e,stroke:#166534,color:#052e16;")
    lines.append("    classDef external fill:#334155,stroke:#0f172a,color:#e2e8f0;")
    lines.append("    classDef aux fill:#f8fafc,stroke:#64748b,color:#0f172a;")

    lines.append("    class n_client client;")
    for layer in present_layers:
        lines.append(f"    class {layer_nodes[layer]} service;")
    if has_datastore:
        lines.append("    class n_datastore data;")
    if routes:
        lines.append("    class n_routes aux;")
    if entrypoints:
        lines.append("    class n_entrypoints aux;")
    for ext in top_externals:
        lines.append(f"    class {_sanitize(f'external:{ext}')} external;")

    return "\n".join(lines) + "\n"


def _classify_external_domain(name: str) -> str:
    token = name.lower()
    if any(key in token for key in ("db", "sql", "postgres", "mysql", "mongo", "redis", "dynamodb", "rds", "cache", "storage", "s3")):
        return "datastore"
    if any(key in token for key in ("kafka", "rabbit", "sqs", "pubsub", "queue", "stream")):
        return "messaging"
    if any(key in token for key in ("auth", "oauth", "jwt", "cognito", "auth0", "okta", "clerk")):
        return "auth"
    if any(key in token for key in ("log", "monitor", "sentry", "datadog", "prometheus", "grafana")):
        return "observability"
    return "third_party"


def _compact_module_path(path: str, depth: int = 2) -> str:
    parts = [part for part in str(path).split("/") if part]
    if len(parts) <= depth:
        return str(path)
    return "/".join(parts[-depth:])


def _rank_key_service_modules(
    parsed_files: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    entrypoints: list[str],
    module_role: dict[str, str],
    *,
    top_k: int = 3,
) -> dict[str, list[str]]:
    module_scores: Counter[str] = Counter()

    for item in parsed_files:
        path = item.get("path")
        if isinstance(path, str) and path:
            module_scores[path] += 1

    for edge in edges:
        src = edge.get("from", "")
        dst = edge.get("to", "")
        if isinstance(src, str) and src.startswith("file:"):
            module_scores[src.replace("file:", "", 1)] += 1
        if isinstance(dst, str) and dst.startswith("file:"):
            module_scores[dst.replace("file:", "", 1)] += 1

    route_files = Counter(
        route.get("file")
        for route in routes
        if isinstance(route.get("file"), str) and route.get("file")
    )
    for path, count in route_files.items():
        module_scores[path] += count * 3

    for entry in entrypoints:
        if isinstance(entry, str) and entry:
            module_scores[entry] += 4

    role_members: dict[str, list[str]] = defaultdict(list)
    for module_id, role in module_role.items():
        if not module_id.startswith("file:"):
            continue
        role_members[role].append(module_id.replace("file:", "", 1))

    role_highlights: dict[str, list[str]] = {}
    for role, members in role_members.items():
        ranked = sorted(members, key=lambda module: (-module_scores.get(module, 0), module))
        compacted: list[str] = []
        seen: set[str] = set()
        for module_path in ranked[:top_k]:
            compact = _compact_module_path(module_path)
            label = compact if compact not in seen else module_path
            if label in seen:
                continue
            compacted.append(label)
            seen.add(label)
        if compacted:
            role_highlights[role] = compacted

    if "api" not in role_highlights and route_files:
        role_highlights["api"] = [_compact_module_path(path) for path, _ in route_files.most_common(top_k)]

    return role_highlights


def render_service_architecture_mermaid(
    parsed_files: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    frameworks: list[str],
    routes: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    entrypoints: list[str],
) -> str:
    role_to_node = {
        "web": "n_service_frontend",
        "api": "n_service_api",
        "worker": "n_service_worker",
        "core": "n_service_shared",
    }
    role_to_label = {
        "web": "Frontend Service",
        "api": "API Service",
        "worker": "Worker Service",
        "core": "Shared/Core Service",
    }

    module_role: dict[str, str] = {}
    role_counts = Counter()
    for item in parsed_files:
        role = _classify_arch_layer(item["path"])
        if role == "config":
            continue
        module_id = f"file:{item['path']}"
        module_role[module_id] = role
        role_counts[role] += 1

    if "Next.js" in frameworks:
        role_counts["web"] = max(1, role_counts["web"])
    if routes or any(fw in API_FRAMEWORKS for fw in frameworks):
        role_counts["api"] = max(1, role_counts["api"])

    role_highlights = _rank_key_service_modules(
        parsed_files,
        edges,
        routes,
        entrypoints,
        module_role,
        top_k=3,
    )

    lines = ["flowchart LR"]
    lines.append('    n_users["Users / Clients"]')

    present_roles = [role for role in ("web", "api", "worker", "core") if role_counts.get(role, 0) > 0]
    for role in present_roles:
        base = f"{role_to_label[role]} ({role_counts[role]})"
        key_modules = role_highlights.get(role, [])
        if key_modules:
            label = _short(f"{base} - key: {', '.join(key_modules)}", 96)
        else:
            label = base
        lines.append(f'    {role_to_node[role]}["{_mermaid_safe_text(label)}"]')

    rendered_edges: set[tuple[str, str, str]] = set()

    def add_edge(src: str, dst: str, label: str) -> None:
        key = (src, dst, label)
        if key in rendered_edges:
            return
        rendered_edges.add(key)
        lines.append(f"    {src} -->|{_mermaid_edge_label(label)}| {dst}")

    if "web" in present_roles:
        add_edge("n_users", role_to_node["web"], "http")
    elif "api" in present_roles:
        add_edge("n_users", role_to_node["api"], "http")
    elif "core" in present_roles:
        add_edge("n_users", role_to_node["core"], "request")

    if "web" in present_roles and "api" in present_roles:
        add_edge(role_to_node["web"], role_to_node["api"], "api_calls")
    if "api" in present_roles and "core" in present_roles:
        add_edge(role_to_node["api"], role_to_node["core"], "business_logic")
    if "worker" in present_roles and "api" in present_roles:
        add_edge(role_to_node["api"], role_to_node["worker"], "async_jobs")

    role_domain_counts: dict[str, Counter] = defaultdict(Counter)
    cross_role_edges = Counter()
    for edge in edges:
        if not edge["from"].startswith("file:"):
            continue
        from_role = module_role.get(edge["from"])
        if not from_role:
            continue

        if edge["to"].startswith("file:"):
            to_role = module_role.get(edge["to"])
            if to_role and to_role != from_role:
                cross_role_edges[(from_role, to_role)] += 1
        elif edge["to"].startswith("external:"):
            domain = _classify_external_domain(edge["to"].replace("external:", ""))
            role_domain_counts[from_role][domain] += 1

    for (from_role, to_role), count in sorted(cross_role_edges.items()):
        if from_role in role_to_node and to_role in role_to_node and from_role in present_roles and to_role in present_roles:
            add_edge(role_to_node[from_role], role_to_node[to_role], f"calls_{count}")

    if entities:
        role_domain_counts["api"]["datastore"] += len(entities)
        if "worker" in present_roles:
            role_domain_counts["worker"]["datastore"] += len(entities)

    domain_to_node = {
        "datastore": "n_domain_data",
        "messaging": "n_domain_msg",
        "auth": "n_domain_auth",
        "observability": "n_domain_obs",
        "third_party": "n_domain_3p",
    }
    domain_to_label = {
        "datastore": "Datastore",
        "messaging": "Message Broker",
        "auth": "Auth Provider",
        "observability": "Observability",
        "third_party": "Third-party APIs",
    }

    present_domains: set[str] = set()
    for domain_counts in role_domain_counts.values():
        for domain, count in domain_counts.items():
            if count > 0:
                present_domains.add(domain)

    for domain in ("datastore", "messaging", "auth", "observability", "third_party"):
        if domain in present_domains:
            lines.append(f'    {domain_to_node[domain]}["{domain_to_label[domain]}"]')

    for role in present_roles:
        for domain, count in role_domain_counts.get(role, Counter()).items():
            if count > 0 and domain in domain_to_node:
                add_edge(role_to_node[role], domain_to_node[domain], f"uses_{count}")

    if routes and "api" in present_roles:
        lines.append(f'    n_service_routes["API Routes ({len(routes)})"]')
        add_edge(role_to_node["api"], "n_service_routes", "exposes")
    if entrypoints:
        lines.append(f'    n_service_entry["Entrypoints ({len(entrypoints)})"]')
        if "api" in present_roles:
            add_edge("n_service_entry", role_to_node["api"], "boot")
        elif "web" in present_roles:
            add_edge("n_service_entry", role_to_node["web"], "boot")
        elif "core" in present_roles:
            add_edge("n_service_entry", role_to_node["core"], "boot")

    lines.append("    classDef client fill:#0ea5e9,stroke:#0f172a,color:#082f49;")
    lines.append("    classDef service fill:#2563eb,stroke:#1e3a8a,color:#eff6ff;")
    lines.append("    classDef infra fill:#334155,stroke:#0f172a,color:#e2e8f0;")
    lines.append("    classDef data fill:#22c55e,stroke:#166534,color:#052e16;")
    lines.append("    classDef aux fill:#f8fafc,stroke:#64748b,color:#0f172a;")

    lines.append("    class n_users client;")
    for role in present_roles:
        lines.append(f"    class {role_to_node[role]} service;")
    for domain in present_domains:
        class_name = "data" if domain == "datastore" else "infra"
        lines.append(f"    class {domain_to_node[domain]} {class_name};")
    if routes:
        lines.append("    class n_service_routes aux;")
    if entrypoints:
        lines.append("    class n_service_entry aux;")

    return "\n".join(lines) + "\n"


def render_iac_architecture_mermaid(iac: dict[str, Any]) -> str:
    resources = iac.get("resources", []) if isinstance(iac, dict) else []
    layer_counts = dict(iac.get("layer_counts") or {}) if isinstance(iac, dict) else {}
    provider_counts = Counter(iac.get("providers") or {}) if isinstance(iac, dict) else Counter()
    source_types = sorted((iac.get("source_types") or {}).keys()) if isinstance(iac, dict) else []

    if not resources:
        return (
            "flowchart LR\n"
            '    n_no_iac["No IaC Artifacts Detected"]\n'
            '    n_hint["Scan Terraform/CloudFormation/Kubernetes/Compose/Bicep files"]\n'
            "    n_no_iac --> n_hint\n"
        )

    lines = ["flowchart LR"]
    source_label = "IaC Source"
    if source_types:
        source_label = f"IaC Source ({', '.join(source_types)})"
    lines.append(f'    n_iac["{_mermaid_safe_text(_short(source_label, 60))}"]')
    lines.append('    n_pipeline["Provisioning / Deploy"]')
    lines.append("    n_iac -->|plan_apply| n_pipeline")

    layer_nodes = {
        "network": "n_layer_network",
        "security": "n_layer_security",
        "compute": "n_layer_compute",
        "data": "n_layer_data",
        "observability": "n_layer_observability",
        "platform": "n_layer_platform",
    }
    layer_labels = {
        "network": "Network",
        "security": "Security / IAM",
        "compute": "Compute / Runtime",
        "data": "Data Stores",
        "observability": "Observability",
        "platform": "Platform",
    }

    present_layers = [layer for layer in layer_nodes if dict(layer_counts).get(layer, 0) > 0]
    for layer in present_layers:
        count = layer_counts.get(layer, 0)
        lines.append(f'    {layer_nodes[layer]}["{layer_labels[layer]} ({count})"]')
        lines.append(f"    n_pipeline -->|manages_{count}| {layer_nodes[layer]}")

    if "compute" in present_layers and "data" in present_layers:
        lines.append(f"    {layer_nodes['compute']} -->|reads_writes| {layer_nodes['data']}")
    if "security" in present_layers and "compute" in present_layers:
        lines.append(f"    {layer_nodes['security']} -->|guards| {layer_nodes['compute']}")
    if "network" in present_layers and "compute" in present_layers:
        lines.append(f"    {layer_nodes['network']} -->|routes_to| {layer_nodes['compute']}")

    top_providers = [name for name, _ in provider_counts.most_common(8)]
    for provider in top_providers:
        provider_id = _sanitize(f"iac_provider:{provider}")
        lines.append(f'    {provider_id}["{_mermaid_safe_text(provider)}"]')
        lines.append(f"    n_pipeline -->|provider| {provider_id}")

    lines.append("    classDef iac fill:#0ea5e9,stroke:#0f172a,color:#082f49;")
    lines.append("    classDef platform fill:#2563eb,stroke:#1e3a8a,color:#eff6ff;")
    lines.append("    classDef data fill:#22c55e,stroke:#166534,color:#052e16;")
    lines.append("    classDef provider fill:#334155,stroke:#0f172a,color:#e2e8f0;")

    lines.append("    class n_iac iac;")
    lines.append("    class n_pipeline iac;")
    for layer in present_layers:
        class_name = "data" if layer == "data" else "platform"
        lines.append(f"    class {layer_nodes[layer]} {class_name};")
    for provider in top_providers:
        lines.append(f"    class {_sanitize(f'iac_provider:{provider}')} provider;")

    return "\n".join(lines) + "\n"


def render_architecture_plantuml(
    parsed_files: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    frameworks: list[str],
    routes: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    entrypoints: list[str],
) -> str:
    lines = [
        "@startuml",
        "left to right direction",
        "skinparam componentStyle rectangle",
    ]
    module_layers: dict[str, str] = {}
    layer_counts = Counter()
    for item in parsed_files:
        module_id = f"file:{item['path']}"
        layer = _classify_arch_layer(item["path"])
        module_layers[module_id] = layer
        if layer != "config":
            layer_counts[layer] += 1

    if "Next.js" in frameworks:
        layer_counts["web"] = max(1, layer_counts["web"])
    if routes or any(fw in API_FRAMEWORKS for fw in frameworks):
        layer_counts["api"] = max(1, layer_counts["api"])
    if entrypoints and layer_counts["core"] == 0:
        layer_counts["core"] = 1

    layer_nodes = {
        "web": "n_web_app",
        "api": "n_api_service",
        "worker": "n_worker",
        "core": "n_core",
    }
    layer_titles = {
        "web": "Web App",
        "api": "API Service",
        "worker": "Worker",
        "core": "Core Modules",
    }

    lines.append('actor "Client / Browser" as n_client')
    present_layers = [layer for layer in ("web", "api", "worker", "core") if layer_counts.get(layer, 0) > 0]
    for layer in present_layers:
        count = layer_counts[layer]
        title = f"{layer_titles[layer]} ({count})"
        lines.append(f'component "{_plantuml_safe_text(title)}" as {layer_nodes[layer]}')

    has_datastore = bool(entities)
    if has_datastore:
        lines.append('database "Datastore" as n_datastore')

    external_by_layer: dict[str, Counter] = defaultdict(Counter)
    cross_layer_counts: Counter = Counter()
    for edge in edges:
        if not edge["from"].startswith("file:"):
            continue
        src_layer = module_layers.get(edge["from"])
        if not src_layer or src_layer == "config":
            continue
        target = edge["to"]
        if target.startswith("file:"):
            dst_layer = module_layers.get(target)
            if dst_layer and dst_layer != src_layer and dst_layer != "config":
                cross_layer_counts[(src_layer, dst_layer, edge["type"])] += 1
        elif target.startswith("external:"):
            external_by_layer[src_layer][target.replace("external:", "")] += 1

    rendered_edges: set[tuple[str, str, str]] = set()

    def add_edge(src: str, dst: str, label: str) -> None:
        key = (src, dst, label)
        if key in rendered_edges:
            return
        rendered_edges.add(key)
        lines.append(f"{src} --> {dst} : {_plantuml_edge_label(label)}")

    if "web" in present_layers:
        add_edge("n_client", layer_nodes["web"], "request")
    elif "api" in present_layers:
        add_edge("n_client", layer_nodes["api"], "request")
    elif "core" in present_layers:
        add_edge("n_client", layer_nodes["core"], "request")

    if "web" in present_layers and "api" in present_layers:
        add_edge(layer_nodes["web"], layer_nodes["api"], "api_call")

    for src_layer, dst_layer, edge_type in sorted(cross_layer_counts.keys()):
        if src_layer in layer_nodes and dst_layer in layer_nodes:
            if src_layer in present_layers and dst_layer in present_layers:
                add_edge(layer_nodes[src_layer], layer_nodes[dst_layer], edge_type)

    if has_datastore:
        if "api" in present_layers:
            add_edge(layer_nodes["api"], "n_datastore", "read_write")
        elif "core" in present_layers:
            add_edge(layer_nodes["core"], "n_datastore", "read_write")
        elif "worker" in present_layers:
            add_edge(layer_nodes["worker"], "n_datastore", "read_write")

    external_totals = Counter()
    for counter in external_by_layer.values():
        external_totals.update(counter)
    top_externals = [name for name, _ in external_totals.most_common(8)]
    for ext in top_externals:
        ext_id = _sanitize(f"external:{ext}")
        lines.append(f'cloud "{_short(_plantuml_safe_text(ext), 34)}" as {ext_id}')
        for layer in present_layers:
            count = external_by_layer[layer].get(ext, 0)
            if count > 0 and layer in layer_nodes:
                add_edge(layer_nodes[layer], ext_id, "depends_on")

    if routes and "api" in present_layers:
        route_node_id = "n_routes"
        lines.append(f'component "Routes ({len(routes)})" as {route_node_id}')
        add_edge(layer_nodes["api"], route_node_id, "serves")

    if entrypoints:
        entry_id = "n_entrypoints"
        lines.append(f'component "Entrypoints ({len(entrypoints)})" as {entry_id}')
        if "api" in present_layers:
            add_edge(entry_id, layer_nodes["api"], "boot")
        elif "web" in present_layers:
            add_edge(entry_id, layer_nodes["web"], "boot")
        elif "core" in present_layers:
            add_edge(entry_id, layer_nodes["core"], "boot")

    lines.append("@enduml")
    return "\n".join(lines) + "\n"


def render_service_architecture_plantuml(
    parsed_files: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    frameworks: list[str],
    routes: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    entrypoints: list[str],
) -> str:
    role_to_node = {
        "web": "n_service_frontend",
        "api": "n_service_api",
        "worker": "n_service_worker",
        "core": "n_service_shared",
    }
    role_to_label = {
        "web": "Frontend Service",
        "api": "API Service",
        "worker": "Worker Service",
        "core": "Shared/Core Service",
    }

    module_role: dict[str, str] = {}
    role_counts = Counter()
    for item in parsed_files:
        role = _classify_arch_layer(item["path"])
        if role == "config":
            continue
        module_id = f"file:{item['path']}"
        module_role[module_id] = role
        role_counts[role] += 1

    if "Next.js" in frameworks:
        role_counts["web"] = max(1, role_counts["web"])
    if routes or any(fw in API_FRAMEWORKS for fw in frameworks):
        role_counts["api"] = max(1, role_counts["api"])

    role_highlights = _rank_key_service_modules(
        parsed_files,
        edges,
        routes,
        entrypoints,
        module_role,
        top_k=3,
    )

    lines = [
        "@startuml",
        "left to right direction",
        "skinparam componentStyle rectangle",
        'actor "Users / Clients" as n_users',
    ]

    present_roles = [role for role in ("web", "api", "worker", "core") if role_counts.get(role, 0) > 0]
    for role in present_roles:
        base = f"{role_to_label[role]} ({role_counts[role]})"
        key_modules = role_highlights.get(role, [])
        if key_modules:
            label = _short(f"{base} - key: {', '.join(key_modules)}", 96)
        else:
            label = base
        lines.append(f'component "{_plantuml_safe_text(label)}" as {role_to_node[role]}')

    rendered_edges: set[tuple[str, str, str]] = set()

    def add_edge(src: str, dst: str, label: str) -> None:
        key = (src, dst, label)
        if key in rendered_edges:
            return
        rendered_edges.add(key)
        lines.append(f"{src} --> {dst} : {_plantuml_edge_label(label)}")

    if "web" in present_roles:
        add_edge("n_users", role_to_node["web"], "http")
    elif "api" in present_roles:
        add_edge("n_users", role_to_node["api"], "http")
    elif "core" in present_roles:
        add_edge("n_users", role_to_node["core"], "request")

    if "web" in present_roles and "api" in present_roles:
        add_edge(role_to_node["web"], role_to_node["api"], "api_calls")
    if "api" in present_roles and "core" in present_roles:
        add_edge(role_to_node["api"], role_to_node["core"], "business_logic")
    if "worker" in present_roles and "api" in present_roles:
        add_edge(role_to_node["api"], role_to_node["worker"], "async_jobs")

    role_domain_counts: dict[str, Counter] = defaultdict(Counter)
    cross_role_edges = Counter()
    for edge in edges:
        if not edge["from"].startswith("file:"):
            continue
        from_role = module_role.get(edge["from"])
        if not from_role:
            continue

        if edge["to"].startswith("file:"):
            to_role = module_role.get(edge["to"])
            if to_role and to_role != from_role:
                cross_role_edges[(from_role, to_role)] += 1
        elif edge["to"].startswith("external:"):
            domain = _classify_external_domain(edge["to"].replace("external:", ""))
            role_domain_counts[from_role][domain] += 1

    for (from_role, to_role), count in sorted(cross_role_edges.items()):
        if from_role in role_to_node and to_role in role_to_node and from_role in present_roles and to_role in present_roles:
            add_edge(role_to_node[from_role], role_to_node[to_role], f"calls_{count}")

    if entities:
        role_domain_counts["api"]["datastore"] += len(entities)
        if "worker" in present_roles:
            role_domain_counts["worker"]["datastore"] += len(entities)

    domain_to_node = {
        "datastore": "n_domain_data",
        "messaging": "n_domain_msg",
        "auth": "n_domain_auth",
        "observability": "n_domain_obs",
        "third_party": "n_domain_3p",
    }
    domain_to_label = {
        "datastore": "Datastore",
        "messaging": "Message Broker",
        "auth": "Auth Provider",
        "observability": "Observability",
        "third_party": "Third-party APIs",
    }

    present_domains: set[str] = set()
    for domain_counts in role_domain_counts.values():
        for domain, count in domain_counts.items():
            if count > 0:
                present_domains.add(domain)

    for domain in ("datastore", "messaging", "auth", "observability", "third_party"):
        if domain in present_domains:
            keyword = "database" if domain == "datastore" else "cloud"
            lines.append(f'{keyword} "{domain_to_label[domain]}" as {domain_to_node[domain]}')

    for role in present_roles:
        for domain, count in role_domain_counts.get(role, Counter()).items():
            if count > 0 and domain in domain_to_node:
                add_edge(role_to_node[role], domain_to_node[domain], f"uses_{count}")

    if routes and "api" in present_roles:
        lines.append(f'component "API Routes ({len(routes)})" as n_service_routes')
        add_edge(role_to_node["api"], "n_service_routes", "exposes")
    if entrypoints:
        lines.append(f'component "Entrypoints ({len(entrypoints)})" as n_service_entry')
        if "api" in present_roles:
            add_edge("n_service_entry", role_to_node["api"], "boot")
        elif "web" in present_roles:
            add_edge("n_service_entry", role_to_node["web"], "boot")
        elif "core" in present_roles:
            add_edge("n_service_entry", role_to_node["core"], "boot")

    lines.append("@enduml")
    return "\n".join(lines) + "\n"


def render_iac_architecture_plantuml(iac: dict[str, Any]) -> str:
    resources = iac.get("resources", []) if isinstance(iac, dict) else []
    layer_counts = dict(iac.get("layer_counts") or {}) if isinstance(iac, dict) else {}
    provider_counts = Counter(iac.get("providers") or {}) if isinstance(iac, dict) else Counter()
    source_types = sorted((iac.get("source_types") or {}).keys()) if isinstance(iac, dict) else []

    if not resources:
        return (
            "@startuml\n"
            "left to right direction\n"
            "skinparam componentStyle rectangle\n"
            'component "No IaC Artifacts Detected" as n_no_iac\n'
            'note right of n_no_iac : Scan Terraform/CloudFormation/Kubernetes/Compose/Bicep files\n'
            "@enduml\n"
        )

    lines = [
        "@startuml",
        "left to right direction",
        "skinparam componentStyle rectangle",
    ]
    source_label = "IaC Source"
    if source_types:
        source_label = f"IaC Source ({', '.join(source_types)})"
    lines.append(f'component "{_plantuml_safe_text(_short(source_label, 60))}" as n_iac')
    lines.append('component "Provisioning / Deploy" as n_pipeline')
    lines.append("n_iac --> n_pipeline : plan_apply")

    layer_nodes = {
        "network": "n_layer_network",
        "security": "n_layer_security",
        "compute": "n_layer_compute",
        "data": "n_layer_data",
        "observability": "n_layer_observability",
        "platform": "n_layer_platform",
    }
    layer_labels = {
        "network": "Network",
        "security": "Security / IAM",
        "compute": "Compute / Runtime",
        "data": "Data Stores",
        "observability": "Observability",
        "platform": "Platform",
    }

    present_layers = [layer for layer in layer_nodes if dict(layer_counts).get(layer, 0) > 0]
    for layer in present_layers:
        count = layer_counts.get(layer, 0)
        lines.append(f'component "{layer_labels[layer]} ({count})" as {layer_nodes[layer]}')
        lines.append(f"n_pipeline --> {layer_nodes[layer]} : manages_{count}")

    if "compute" in present_layers and "data" in present_layers:
        lines.append(f"{layer_nodes['compute']} --> {layer_nodes['data']} : reads_writes")
    if "security" in present_layers and "compute" in present_layers:
        lines.append(f"{layer_nodes['security']} --> {layer_nodes['compute']} : guards")
    if "network" in present_layers and "compute" in present_layers:
        lines.append(f"{layer_nodes['network']} --> {layer_nodes['compute']} : routes_to")

    top_providers = [name for name, _ in provider_counts.most_common(8)]
    for provider in top_providers:
        provider_id = _sanitize(f"iac_provider:{provider}")
        lines.append(f'cloud "{_plantuml_safe_text(provider)}" as {provider_id}')
        lines.append(f"n_pipeline --> {provider_id} : provider")

    lines.append("@enduml")
    return "\n".join(lines) + "\n"


def render_dependency_mermaid(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    cycles: list[list[str]],
) -> str:
    lines = ["flowchart LR"]
    for node in nodes:
        if node["type"] not in {"module", "external"}:
            continue
        lines.append(f"    {_sanitize(node['id'])}[\"{_short(_mermaid_safe_text(node['label']), 36)}\"]")

    for edge in edges:
        if edge["type"] not in {"imports", "depends_on", "trust_boundary_crossing"}:
            continue
        if not edge["from"].startswith("file:"):
            continue
        if not (edge["to"].startswith("file:") or edge["to"].startswith("external:")):
            continue
        label = _mermaid_edge_label(edge["type"], edge.get("confidence"))
        lines.append(f"    {_sanitize(edge['from'])} -->|{label}| {_sanitize(edge['to'])}")

    lines.append("    classDef cycle fill:#fca5a5,stroke:#7f1d1d,color:#111827;")
    lines.append("    classDef default fill:#dbeafe,stroke:#1d4ed8,color:#0f172a;")
    lines.append("    classDef external fill:#94a3b8,stroke:#334155,color:#0f172a;")

    cycle_nodes = {node for component in cycles for node in component}
    for node in cycle_nodes:
        lines.append(f"    class {_sanitize(node)} cycle;")
    for node in nodes:
        if node["type"] == "external":
            lines.append(f"    class {_sanitize(node['id'])} external;")

    return "\n".join(lines) + "\n"


def render_dependency_plantuml(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    cycles: list[list[str]],
) -> str:
    cycle_nodes = {node for component in cycles for node in component}
    lines = [
        "@startuml",
        "left to right direction",
        "skinparam componentStyle rectangle",
        "skinparam component<<cycle>> {",
        "  BackgroundColor #fca5a5",
        "  BorderColor #7f1d1d",
        "}",
        "skinparam component<<external>> {",
        "  BackgroundColor #94a3b8",
        "  BorderColor #334155",
        "}",
    ]
    declared: set[str] = set()
    for node in nodes:
        if node["type"] not in {"module", "external"}:
            continue
        alias = _sanitize(node["id"])
        if alias in declared:
            continue
        declared.add(alias)
        stereotypes: list[str] = []
        if node["id"] in cycle_nodes:
            stereotypes.append("cycle")
        if node["type"] == "external":
            stereotypes.append("external")
        stereotype = f" {' '.join(f'<<{item}>>' for item in stereotypes)}" if stereotypes else ""
        lines.append(f'component "{_short(_plantuml_safe_text(node["label"]), 36)}" as {alias}{stereotype}')

    for edge in edges:
        if edge["type"] not in {"imports", "depends_on", "trust_boundary_crossing"}:
            continue
        if not edge["from"].startswith("file:"):
            continue
        if not (edge["to"].startswith("file:") or edge["to"].startswith("external:")):
            continue
        src = _sanitize(edge["from"])
        dst = _sanitize(edge["to"])
        lines.append(f"{src} --> {dst} : {_plantuml_edge_label(edge['type'], edge.get('confidence'))}")

    lines.append("@enduml")
    return "\n".join(lines) + "\n"


def render_call_mermaid(function_calls: list[dict[str, Any]]) -> str:
    lines = ["flowchart LR"]
    deduped: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for edge in function_calls:
        key = (edge.get("from", ""), edge.get("to", ""), edge.get("confidence", ""))
        if key in seen_edges:
            continue
        seen_edges.add(key)
        deduped.append(edge)
        if len(deduped) >= 120:
            break
    edges = deduped

    seen = set()
    for edge in edges:
        source = _sanitize(edge["from"])
        target = _sanitize(edge["to"])
        if source not in seen:
            source_label = _display_call_node_label(edge["from"])
            lines.append(f"    {source}[\"{_short(_mermaid_safe_text(source_label), 30)}\"]")
            seen.add(source)
        if target not in seen:
            target_label = _display_call_node_label(edge["to"])
            lines.append(f"    {target}[\"{_short(_mermaid_safe_text(target_label), 30)}\"]")
            seen.add(target)

        label = _mermaid_edge_label("calls", edge.get("confidence"))
        connector = f" -->|{label}| " if label else " --> "
        lines.append(f"    {source}{connector}{target}")

    if len(lines) == 1:
        lines.append("    no_calls[\"No call graph data detected\"]")

    return "\n".join(lines) + "\n"


def render_call_plantuml(function_calls: list[dict[str, Any]]) -> str:
    lines = [
        "@startuml",
        "left to right direction",
        "skinparam componentStyle rectangle",
    ]
    deduped: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for edge in function_calls:
        key = (edge.get("from", ""), edge.get("to", ""), edge.get("confidence", ""))
        if key in seen_edges:
            continue
        seen_edges.add(key)
        deduped.append(edge)
        if len(deduped) >= 120:
            break
    edges = deduped

    seen: set[str] = set()
    for edge in edges:
        source = _sanitize(edge["from"])
        target = _sanitize(edge["to"])
        if source not in seen:
            source_label = _display_call_node_label(edge["from"])
            lines.append(f'component "{_short(_plantuml_safe_text(source_label), 30)}" as {source}')
            seen.add(source)
        if target not in seen:
            target_label = _display_call_node_label(edge["to"])
            lines.append(f'component "{_short(_plantuml_safe_text(target_label), 30)}" as {target}')
            seen.add(target)

        label = _plantuml_edge_label("calls", edge.get("confidence"))
        lines.append(f"{source} --> {target} : {label}")

    if len(edges) == 0:
        lines.append('component "No call graph data detected" as no_calls')

    lines.append("@enduml")
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


def render_er_plantuml(entities: list[dict[str, Any]], relationships: list[dict[str, Any]]) -> str:
    if not entities:
        return (
            "@startuml\n"
            "hide circle\n"
            "skinparam classAttributeIconSize 0\n"
            'class "NO_SCHEMA" as no_schema {\n'
            "  note : No schema detected\n"
            "}\n"
            "@enduml\n"
        )

    lines = [
        "@startuml",
        "hide circle",
        "skinparam classAttributeIconSize 0",
    ]

    entity_aliases: dict[str, str] = {}
    for entity in entities:
        name = str(entity.get("name") or "Entity")
        alias = _sanitize(f"entity:{name}")
        entity_aliases[name] = alias
        lines.append(f'class "{_plantuml_safe_text(name)}" as {alias} {{')
        for field in entity.get("fields", [])[:12]:
            field_name = _plantuml_safe_text(field.get("name", "field"))
            field_type = str(field.get("type", "string")).lower()
            if field_type not in SQL_SCALARS:
                field_type = "string"
            lines.append(f"  {field_name} : {field_type}")
        lines.append("}")

    for relation in relationships:
        left = str(relation.get("from", "")).strip()
        right = str(relation.get("to", "")).strip()
        if left and right and left in entity_aliases and right in entity_aliases:
            rel_type = _plantuml_edge_label(relation.get("type", "rel"))
            lines.append(f"{entity_aliases[left]} --> {entity_aliases[right]} : {rel_type}")

    lines.append("@enduml")
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


def build_data_snapshot(
    summary: dict[str, Any],
    routes: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    module_metrics: list[dict[str, Any]],
    function_hotspots: list[dict[str, Any]],
    cycles: list[list[str]],
    iac: dict[str, Any],
) -> dict[str, Any]:
    route_rows = []
    for route in routes[:20]:
        route_rows.append(
            {
                "method": route.get("method", "GET"),
                "path": route.get("path", "/"),
                "file": route.get("file", "unknown"),
            }
        )

    entity_rows = []
    for entity in entities[:20]:
        field_names = [field.get("name", "field") for field in entity.get("fields", [])[:10]]
        entity_rows.append(
            {
                "name": entity.get("name", "Entity"),
                "source": entity.get("source", "unknown"),
                "format": entity.get("format", "unknown"),
                "fields": field_names,
            }
        )

    relationship_rows = []
    for relation in relationships[:30]:
        relationship_rows.append(
            {
                "from": relation.get("from", ""),
                "to": relation.get("to", ""),
                "type": relation.get("type", "rel"),
                "confidence": relation.get("confidence", "medium"),
            }
        )

    hotspot_rows = []
    for row in module_metrics[:20]:
        hotspot_rows.append(
            {
                "module": row["module"],
                "hotspot_score": round(float(row["hotspot_score"]), 2),
                "coupling_in": row["coupling_in"],
                "coupling_out": row["coupling_out"],
            }
        )

    function_rows = []
    for row in function_hotspots[:20]:
        function_rows.append(
            {
                "function": row["function"],
                "fan_in": row["fan_in"],
                "fan_out": row["fan_out"],
                "hotspot_score": round(float(row["hotspot_score"]), 2),
            }
        )

    cycle_rows = []
    for component in cycles[:12]:
        cycle_rows.append(component[:8])

    return {
        "repo": {
            "name": summary.get("repo_name", "repository"),
            "generated_at": summary.get("generated_at", ""),
            "languages": summary.get("languages", []),
            "frameworks": summary.get("frameworks", []),
            "entrypoints": summary.get("entrypoints", []),
            "files_indexed": summary.get("files_indexed", 0),
            "files_skipped": summary.get("files_skipped", 0),
        },
        "analysis": {
            "routes": route_rows,
            "entities": entity_rows,
            "relationships": relationship_rows,
            "hotspots": hotspot_rows,
            "function_hotspots": function_rows,
            "cycles": cycle_rows,
            "iac": {
                "files": len(iac.get("files", [])),
                "resources": len(iac.get("resources", [])),
                "providers": dict(iac.get("providers", {})),
                "layer_counts": dict(iac.get("layer_counts", {})),
            },
        },
    }


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return json.dumps(str(value))
        return str(value)
    return json.dumps(str(value))


def _render_yaml_lines(value: Any, indent: int = 0) -> list[str]:
    prefix = "  " * indent
    if isinstance(value, dict):
        if not value:
            return [f"{prefix}{{}}"]
        lines: list[str] = []
        for key in sorted(value.keys()):
            key_text = str(key)
            child = value[key]
            if isinstance(child, (dict, list)):
                lines.append(f"{prefix}{key_text}:")
                lines.extend(_render_yaml_lines(child, indent + 1))
            else:
                lines.append(f"{prefix}{key_text}: {_yaml_scalar(child)}")
        return lines
    if isinstance(value, list):
        if not value:
            return [f"{prefix}[]"]
        lines: list[str] = []
        for child in value:
            if isinstance(child, (dict, list)):
                lines.append(f"{prefix}-")
                lines.extend(_render_yaml_lines(child, indent + 1))
            else:
                lines.append(f"{prefix}- {_yaml_scalar(child)}")
        return lines
    return [f"{prefix}{_yaml_scalar(value)}"]


def render_data_yaml(payload: dict[str, Any]) -> str:
    return "\n".join(_render_yaml_lines(payload)) + "\n"


def render_json_plantuml(json_source: str) -> str:
    lines = ["@startjson"]
    lines.extend(json_source.strip().splitlines())
    lines.append("@endjson")
    return "\n".join(lines) + "\n"


def render_yaml_plantuml(yaml_source: str) -> str:
    lines = ["@startyaml"]
    lines.extend(yaml_source.strip().splitlines())
    lines.append("@endyaml")
    return "\n".join(lines) + "\n"


def render_sequence_mermaid(
    routes: list[dict[str, Any]],
    key_flows: list[dict[str, str]],
    entities: list[dict[str, Any]],
) -> str:
    datastore = entities[0]["name"] if entities else "Datastore"
    lines = [
        "sequenceDiagram",
        "    autonumber",
        "    actor Client",
        "    participant Edge as API / Entrypoint",
        "    participant App as App Core",
        f"    participant Data as {_mermaid_safe_text(datastore)}",
    ]

    scenario_count = max(len(routes[:6]), len(key_flows[:6]))
    if scenario_count == 0:
        scenario_count = 1

    for idx in range(scenario_count):
        route = routes[idx] if idx < len(routes) else None
        flow = key_flows[idx] if idx < len(key_flows) else None
        method = route.get("method", "REQUEST") if route else "REQUEST"
        path = route.get("path", "/") if route else "/"
        file_name = Path(route.get("file", "handler")).name if route else "entrypoint"
        flow_name = flow.get("name", f"{method} {path}") if flow else f"{method} {path}"
        lines.append(f"    Note over Client,Edge: {_mermaid_safe_text(_short(flow_name, 90))}")
        lines.append(f"    Client->>Edge: {_mermaid_safe_text(method)} {_mermaid_safe_text(path)}")
        lines.append(f"    Edge->>App: handle {_mermaid_safe_text(file_name)}")
        lines.append(f"    App->>Data: read_write {_mermaid_safe_text(datastore)}")
        lines.append("    Data-->>App: data result")
        lines.append("    App-->>Edge: response payload")
        lines.append("    Edge-->>Client: HTTP response")

    return "\n".join(lines) + "\n"


def render_sequence_plantuml(
    routes: list[dict[str, Any]],
    key_flows: list[dict[str, str]],
    entities: list[dict[str, Any]],
) -> str:
    datastore = entities[0]["name"] if entities else "Datastore"
    lines = [
        "@startuml",
        "autonumber",
        'actor "Client" as client',
        'participant "API / Entrypoint" as edge',
        'participant "App Core" as app',
        f'participant "{_plantuml_safe_text(_short(datastore, 40))}" as data',
    ]

    scenario_count = max(len(routes[:6]), len(key_flows[:6]))
    if scenario_count == 0:
        scenario_count = 1

    for idx in range(scenario_count):
        route = routes[idx] if idx < len(routes) else None
        flow = key_flows[idx] if idx < len(key_flows) else None
        method = route.get("method", "REQUEST") if route else "REQUEST"
        path = route.get("path", "/") if route else "/"
        file_name = Path(route.get("file", "handler")).name if route else "entrypoint"
        flow_name = flow.get("name", f"{method} {path}") if flow else f"{method} {path}"
        lines.append(f'note over client,edge : {_plantuml_safe_text(_short(flow_name, 92))}')
        lines.append(f'client -> edge : {_plantuml_safe_text(method)} {_plantuml_safe_text(path)}')
        lines.append(f'edge -> app : handle {_plantuml_safe_text(file_name)}')
        lines.append(f'app -> data : read_write {_plantuml_safe_text(datastore)}')
        lines.append("data --> app : data result")
        lines.append("app --> edge : response payload")
        lines.append("edge --> client : HTTP response")

    lines.append("@enduml")
    return "\n".join(lines) + "\n"


def render_use_case_mermaid(routes: list[dict[str, Any]], entrypoints: list[str]) -> str:
    lines = [
        "flowchart LR",
        '    actor_client["User / Client"]',
    ]
    route_rows = routes[:14]
    if route_rows:
        for idx, route in enumerate(route_rows):
            node = f"uc_{idx}"
            method = route.get("method", "GET")
            path = route.get("path", "/")
            label = _short(f"{method} {path}", 48)
            lines.append(f'    {node}(["{_mermaid_safe_text(label)}"])')
            lines.append(f"    actor_client --> {node}")
    else:
        lines.append('    uc_default(["Access application capability"])')
        lines.append("    actor_client --> uc_default")

    if entrypoints:
        lines.append('    actor_operator["Operator / Developer"]')
        lines.append('    uc_boot(["Bootstrap runtime"])')
        lines.append("    actor_operator --> uc_boot")

    return "\n".join(lines) + "\n"


def render_use_case_plantuml(routes: list[dict[str, Any]], entrypoints: list[str]) -> str:
    lines = [
        "@startuml",
        "left to right direction",
        'actor "User / Client" as actor_client',
    ]

    route_rows = routes[:14]
    if route_rows:
        for idx, route in enumerate(route_rows):
            method = route.get("method", "GET")
            path = route.get("path", "/")
            label = _short(f"{method} {path}", 64)
            alias = f"uc_{idx}"
            lines.append(f'usecase "{_plantuml_safe_text(label)}" as {alias}')
            lines.append(f"actor_client --> {alias}")
    else:
        lines.append('usecase "Access application capability" as uc_default')
        lines.append("actor_client --> uc_default")

    if entrypoints:
        lines.append('actor "Operator / Developer" as actor_operator')
        lines.append('usecase "Bootstrap runtime" as uc_boot')
        lines.append("actor_operator --> uc_boot")

    lines.append("@enduml")
    return "\n".join(lines) + "\n"


def build_key_flows(
    routes: list[dict[str, Any]],
    module_call_edges: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    entrypoints: list[str],
    module_metrics: list[dict[str, Any]],
    parsed_files: list[dict[str, Any]],
) -> list[dict[str, str]]:
    by_source = defaultdict(list)
    for edge in module_call_edges:
        by_source[edge["from"]].append((edge["to"], edge.get("confidence", "medium")))

    for source in list(by_source.keys()):
        by_source[source] = sorted(
            by_source[source],
            key=lambda item: (
                item[1] != "high",
                item[1] != "medium",
                item[0].startswith("external_fn:"),
                item[0],
            ),
        )

    data_target = entities[0]["name"] if entities else "datastore"

    flows = []
    for route in routes[:8]:
        source = route["file"]
        candidates = by_source[source]
        if candidates:
            preferred = next((value for value, _ in candidates if not value.startswith("external_fn:")), candidates[0][0])
            middle = _display_flow_target(preferred)
        else:
            middle = source
        flows.append(
            {
                "name": f"{route['method']} {route['path']}",
                "flow": f"Request -> {source} -> {middle} -> {data_target}",
            }
        )

    if not flows:
        seed_candidates: list[str] = []
        for entry in entrypoints:
            if entry and not _is_low_signal_handoff_file(entry):
                seed_candidates.append(entry)
        for row in module_metrics[:12]:
            module_name = row.get("module")
            if module_name and not _is_low_signal_handoff_file(module_name):
                seed_candidates.append(module_name)
        if not seed_candidates:
            for item in parsed_files:
                path = item.get("path", "")
                if path and not _is_low_signal_handoff_file(path):
                    seed_candidates.append(path)

        seen_seeds: set[str] = set()
        deduped_seeds: list[str] = []
        for seed in seed_candidates:
            if seed not in seen_seeds:
                deduped_seeds.append(seed)
                seen_seeds.add(seed)
            if len(deduped_seeds) >= 4:
                break

        for seed in deduped_seeds:
            chain = ["Request", seed]
            current = seed
            seen_nodes = {seed}
            for _ in range(3):
                candidates = by_source.get(current, [])
                if not candidates:
                    break
                selected = None
                for target, _confidence in candidates:
                    target_name = _display_flow_target(target)
                    if target_name in seen_nodes:
                        continue
                    if target.startswith("external_fn:") or not _is_low_signal_handoff_file(target):
                        selected = target
                        break
                if selected is None:
                    break
                target_label = _display_flow_target(selected)
                chain.append(target_label)
                if selected.startswith("external_fn:"):
                    break
                seen_nodes.add(target_label)
                current = selected
            if chain[-1] != data_target:
                chain.append(data_target)
            flow_name = f"Runtime path: {Path(seed).name}"
            flows.append({"name": flow_name, "flow": " -> ".join(chain)})

    if not flows:
        fallback = entrypoints[0] if entrypoints else "entrypoint"
        flows.append({"name": "default", "flow": f"Request -> {fallback} -> {data_target}"})
    return flows[:8]


def render_onboarding_markdown(
    start_here: list[str],
    flows: list[dict[str, str]],
    glossary: list[dict[str, str]],
    change_safely: dict[str, Any],
) -> str:
    lines = ["# Onboarding Map", "", f"## Start Here ({len(start_here)} files)", ""]
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
        "- [Architecture (Services)](architecture-services.mmd)",
        "- [Architecture (Code)](architecture-code.mmd)",
        "- [Architecture (IaC)](architecture-iac.mmd)",
        "- [System Architecture (Legacy Alias)](architecture.mmd)",
        "- [ER Diagram](er.mmd)",
        "- [Call Graph](call-graph.mmd)",
        "- [Dependency Graph](dependencies.mmd)",
        "- [Sequence Diagram](sequence.mmd)",
        "- [Use Case Diagram](use-case.mmd)",
        "- [Architecture (Services, PlantUML)](architecture-services.puml)",
        "- [Architecture (Code, PlantUML)](architecture-code.puml)",
        "- [Architecture (IaC, PlantUML)](architecture-iac.puml)",
        "- [System Architecture (PlantUML)](architecture.puml)",
        "- [ER Diagram (PlantUML)](er.puml)",
        "- [Call Graph (PlantUML)](call-graph.puml)",
        "- [Dependency Graph (PlantUML)](dependencies.puml)",
        "- [Sequence Diagram (PlantUML)](sequence.puml)",
        "- [Use Case Diagram (PlantUML)](use-case.puml)",
        "- [JSON Data Snapshot](data.json)",
        "- [YAML Data Snapshot](data.yaml)",
        "- [JSON Data (PlantUML)](json-data.puml)",
        "- [YAML Data (PlantUML)](yaml-data.puml)",
        "- [Onboarding Map](onboarding.md)",
        "- [Repo Summary](repo-summary.md)",
        "- [Top Files](top-files.md)",
        "- [Handoff Brief](handoff.md)",
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


def _mermaid_safe_text(value: Any) -> str:
    text = str(value)
    text = text.replace("\n", " ").replace("\r", " ")
    text = text.replace('"', "'")
    text = text.replace("<", "[").replace(">", "]")
    text = text.replace("|", "/")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _mermaid_edge_label(edge_type: str, confidence: str | None = None) -> str:
    edge_token = re.sub(r"[^a-zA-Z0-9]+", "_", str(edge_type or "rel")).strip("_").lower()
    conf_token = re.sub(r"[^a-zA-Z0-9]+", "_", str(confidence or "")).strip("_").lower()
    if conf_token:
        return f"{edge_token}_{conf_token}"
    return edge_token


def _plantuml_safe_text(value: Any) -> str:
    text = str(value)
    text = text.replace("\n", " ").replace("\r", " ")
    text = text.replace('"', "'")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _plantuml_edge_label(edge_type: Any, confidence: Any = None) -> str:
    edge_token = re.sub(r"[^a-zA-Z0-9]+", "_", str(edge_type or "rel")).strip("_").lower()
    conf_token = re.sub(r"[^a-zA-Z0-9]+", "_", str(confidence or "")).strip("_").lower()
    if conf_token:
        return f"{edge_token}_{conf_token}"
    return edge_token


def _ensure_required_plantuml(diagram: str, title: str) -> str:
    source = (diagram or "").strip()
    if source.startswith("@start") and source.endswith("@enduml"):
        return source + "\n"
    if source.startswith("@start"):
        return source + "\n"
    return (
        "@startuml\n"
        "left to right direction\n"
        "skinparam componentStyle rectangle\n"
        f'component "{_plantuml_safe_text(title)} unavailable" as n_missing\n'
        "@enduml\n"
    )


def _display_call_node_label(raw: str) -> str:
    text = raw.strip()
    if "::" in text:
        owner, symbol = text.split("::", 1)
        if owner == "external":
            return symbol or "external_fn"
        owner_name = Path(owner).name if owner else "unknown"
        if symbol == "<module>":
            return f"{owner_name}::module_scope"
        return f"{owner_name}::{symbol}"
    if text == "<module>":
        return "module_scope"
    return text


def _display_flow_target(target: str) -> str:
    if target.startswith("external_fn:"):
        return f"external:{target.replace('external_fn:', '')}"
    return target


def render_repo_summary_markdown(
    summary: dict[str, Any],
    module_metrics: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    cycles: list[list[str]],
    function_hotspots: list[dict[str, Any]],
) -> str:
    lines = [
        "# Repo Summary",
        "",
        "## Overview",
        "",
        f"- Repository: `{summary.get('repo_name', 'unknown')}`",
        f"- Languages: {', '.join(summary.get('languages', [])) or 'Not detected'}",
        f"- Frameworks: {', '.join(summary.get('frameworks', [])) or 'Not detected'}",
        f"- Entrypoints: {', '.join(summary.get('entrypoints', [])) or 'Not detected'}",
        f"- Routes Detected: {len(routes)}",
        f"- Entities Detected: {len(entities)}",
        f"- Dependency Cycles: {len(cycles)}",
        "",
        "## Hotspots",
        "",
    ]
    for row in module_metrics[:8]:
        lines.append(
            f"- `{row['module']}` (hotspot={row['hotspot_score']:.2f}, in={row['coupling_in']}, out={row['coupling_out']})"
        )

    lines.extend(["", "## Function Hotspots", ""])
    if function_hotspots:
        for row in function_hotspots[:10]:
            lines.append(f"- `{row['function']}` (fan-in={row['fan_in']}, fan-out={row['fan_out']})")
    else:
        lines.append("- No function-level hotspots detected.")

    lines.extend(
        [
            "",
            "## Agent Handoff Notes",
            "",
            "- Use this file plus `dashboard_state.json` as context for downstream analyst/refactor/security agents.",
            "- Prioritize reviewing top hotspot modules before implementing broad changes.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def render_handoff_markdown(
    summary: dict[str, Any],
    start_here: list[str],
    key_flows: list[dict[str, str]],
    module_metrics: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    parser_errors: list[str],
    required_artifact_status: dict[str, bool],
) -> str:
    lines = [
        "# Handoff Brief",
        "",
        "## Open First",
        "",
        "1. `index.md`",
        "2. `onboarding.md`",
        "3. `repo-summary.md`",
        "4. `dashboard_state.json`",
        "",
        "## Quick Context",
        "",
        f"- Repository: `{summary.get('repo_name', 'unknown')}`",
        f"- Source Reference: `{summary.get('repo_root', 'unknown')}`",
        f"- Source Kind: `{summary.get('source_kind', 'unknown')}`",
        f"- Files Indexed: {summary.get('files_indexed', 0)}",
        f"- Files Skipped: {summary.get('files_skipped', 0)}",
        "",
        "## Architecture Ramp (Start Here)",
        "",
    ]

    if start_here:
        for idx, path in enumerate(start_here[:5], start=1):
            lines.append(f"{idx}. `{path}`")
    else:
        lines.append("1. No focused module path detected.")

    lines.extend(["", "## Concrete Runtime Flows", ""])
    if key_flows:
        for flow in key_flows[:6]:
            lines.append(f"- **{flow.get('name', 'flow')}**: {flow.get('flow', 'n/a')}")
    else:
        lines.append("- No runtime flow extracted.")

    lines.extend(["", "## Hot Modules", ""])
    if module_metrics:
        for row in module_metrics[:5]:
            lines.append(
                f"- `{row['module']}` (hotspot={row['hotspot_score']:.2f}, in={row['coupling_in']}, out={row['coupling_out']})"
            )
    else:
        lines.append("- No module hotspots detected.")

    lines.extend(["", "## Required Artifact Check", ""])
    for artifact, present in required_artifact_status.items():
        status = "present" if present else "missing"
        lines.append(f"- `{artifact}`: {status}")

    lines.extend(["", "## Blind Spots", ""])
    blind_spots = []
    if len(routes) == 0:
        blind_spots.append("Route extraction returned 0 routes; runtime behavior inferred from entrypoints/call graph.")
    if summary.get("files_skipped", 0):
        blind_spots.append("Some files were skipped due to limits/filters; architecture may be partial.")
    if parser_errors:
        blind_spots.append(f"Parser/extraction issues detected: {len(parser_errors)} (see `case_file.md`).")

    missing = [name for name, present in required_artifact_status.items() if not present]
    if missing:
        blind_spots.append(f"Missing required artifacts: {', '.join(missing)}.")

    if blind_spots:
        for note in blind_spots:
            lines.append(f"- {note}")
    else:
        lines.append("- No critical blind spots flagged for initial ramp-up.")

    return "\n".join(lines) + "\n"


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
    iac = parse_iac_artifacts(repo_path)

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
    key_flows = build_key_flows(routes, module_call_edges, entities, entrypoints, module_metrics, parsed_files)
    terraform_files = discover_terraform_files(repo_path)
    terraform_graph = build_terraform_graph(repo_path, terraform_files)

    terraform_drawio_file = None
    terraform_drawio = ""
    if terraform_graph.get("files"):
        terraform_drawio_file = "terraform-architecture.drawio"
        terraform_drawio = render_terraform_drawio(terraform_graph, repo_path.name)

    architecture_service_mmd = render_service_architecture_mermaid(
        parsed_files,
        edges,
        frameworks,
        routes,
        entities,
        entrypoints,
    )
    architecture_code_mmd = render_architecture_mermaid(parsed_files, edges, frameworks, routes, entities, entrypoints)
    architecture_iac_mmd = render_iac_architecture_mermaid(iac)
    architecture_mmd = architecture_service_mmd
    er_mmd = render_er_mermaid(entities, relationships)
    dbml = render_dbml(entities, relationships)
    call_mmd = render_call_mermaid(function_call_edges)
    dependency_mmd = render_dependency_mermaid(nodes, edges, cycles)
    architecture_service_puml = render_service_architecture_plantuml(
        parsed_files,
        edges,
        frameworks,
        routes,
        entities,
        entrypoints,
    )
    architecture_code_puml = render_architecture_plantuml(parsed_files, edges, frameworks, routes, entities, entrypoints)
    architecture_iac_puml = render_iac_architecture_plantuml(iac)
    architecture_puml = _ensure_required_plantuml(architecture_service_puml, "System Architecture")
    er_puml = _ensure_required_plantuml(render_er_plantuml(entities, relationships), "ER Diagram")
    call_puml = _ensure_required_plantuml(render_call_plantuml(function_call_edges), "Call Graph")
    dependency_puml = _ensure_required_plantuml(
        render_dependency_plantuml(nodes, edges, cycles), "Dependency Graph"
    )
    architecture_service_puml = _ensure_required_plantuml(architecture_service_puml, "Architecture Services")
    architecture_code_puml = _ensure_required_plantuml(architecture_code_puml, "Architecture Code")
    architecture_iac_puml = _ensure_required_plantuml(architecture_iac_puml, "Architecture IaC")
    sequence_mmd = render_sequence_mermaid(routes, key_flows, entities)
    sequence_puml = render_sequence_plantuml(routes, key_flows, entities)
    use_case_mmd = render_use_case_mermaid(routes, entrypoints)
    use_case_puml = render_use_case_plantuml(routes, entrypoints)

    confidence_notes = [
        "Dynamic dispatch and reflection calls are approximated as low confidence.",
        "JSImport resolution uses heuristic path matching for package aliases.",
    ]

    source_reference = (config.source_reference or repo_path.as_posix()).strip() or repo_path.as_posix()
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_name": repo_path.name,
        "repo_root": source_reference,
        "analysis_workspace": repo_path.as_posix(),
        "source_kind": config.source_kind,
        "languages": languages,
        "frameworks": frameworks,
        "entrypoints": entrypoints,
        "files_indexed": len(files),
        "files_skipped": skipped,
        "mode": "xray",
        "terraform_detected": bool(terraform_graph.get("files")),
        "terraform_files": len(terraform_graph.get("files", [])),
    }
    data_snapshot = build_data_snapshot(
        summary,
        routes,
        entities,
        relationships,
        module_metrics,
        function_hotspots,
        cycles,
        iac,
    )
    data_json_source = json.dumps(data_snapshot, indent=2, sort_keys=True) + "\n"
    data_yaml_source = render_data_yaml(data_snapshot)
    data_json_puml = render_json_plantuml(data_json_source)
    data_yaml_puml = render_yaml_plantuml(data_yaml_source)

    repo_json = {
        "name": repo_path.name,
        "root": source_reference,
        "analysis_workspace": repo_path.as_posix(),
        "source_kind": config.source_kind,
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
    repo_summary_md = render_repo_summary_markdown(
        summary,
        module_metrics,
        routes,
        entities,
        cycles,
        function_hotspots,
    )
    index_md = render_index_markdown(summary, terraform_drawio_file=terraform_drawio_file)
    case_file_md = render_case_file(parser_errors, skipped, confidence_notes)
    required_artifact_status = {
        "architecture.puml": bool(architecture_puml.strip()),
        "er.puml": bool(er_puml.strip()),
        "call-graph.puml": bool(call_puml.strip()),
        "dependencies.puml": bool(dependency_puml.strip()),
    }
    handoff_md = render_handoff_markdown(
        summary,
        start_here,
        key_flows,
        module_metrics,
        routes,
        parser_errors,
        required_artifact_status,
    )
    confidence_distribution = Counter(edge.get("confidence", "unknown") for edge in edges)

    dashboard_state = {
        "generated_at": summary["generated_at"],
        "summary": summary,
        "analysis": {
            "routes": routes,
            "models": models,
            "entities": entities,
            "relationships": relationships,
            "iac": {
                "files": len(iac.get("files", [])),
                "resources": len(iac.get("resources", [])),
                "providers": iac.get("providers", {}),
                "source_types": iac.get("source_types", {}),
                "layer_counts": iac.get("layer_counts", {}),
            },
            "confidence_distribution": dict(confidence_distribution),
            "counts": {
                "modules": sum(1 for node in nodes if node["type"] == "module"),
                "externals": sum(1 for node in nodes if node["type"] == "external"),
                "edges": len(edges),
                "routes": len(routes),
                "entities": len(entities),
                "cycles": len(cycles),
                "iac_files": len(iac.get("files", [])),
                "iac_resources": len(iac.get("resources", [])),
            },
        },
        "graphs": {
            "nodes": nodes,
            "edges": edges,
            "cycles": cycles,
            "hotspots": module_metrics[:30],
            "function_hotspots": function_hotspots,
            "core_leaf_tags": core_leaf_tags,
        },
        "diagrams": {
            "architecture": architecture_mmd,
            "architecture_services": architecture_service_mmd,
            "architecture_code": architecture_code_mmd,
            "architecture_iac": architecture_iac_mmd,
            "er": er_mmd,
            "call_graph": call_mmd,
            "dependencies": dependency_mmd,
            "sequence": sequence_mmd,
            "use_case": use_case_mmd,
            "json_data": data_json_source,
            "yaml_data": data_yaml_source,
        },
        "diagrams_plantuml": {
            "architecture": architecture_puml,
            "architecture_services": architecture_service_puml,
            "architecture_code": architecture_code_puml,
            "architecture_iac": architecture_iac_puml,
            "er": er_puml,
            "call_graph": call_puml,
            "dependencies": dependency_puml,
            "sequence": sequence_puml,
            "use_case": use_case_puml,
            "json_data": data_json_puml,
            "yaml_data": data_yaml_puml,
        },
        "onboarding": {
            "start_here": start_here,
            "key_flows": key_flows,
            "glossary": glossary,
            "change_safely": change_safely,
        },
        "narrative": {
            "repo_summary_markdown": repo_summary_md,
            "handoff_markdown": handoff_md,
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
    if terraform_drawio:
        dashboard_state["diagrams"]["terraform_drawio"] = terraform_drawio

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
    _json_dump(artifacts_dir / "iac.json", iac)
    if terraform_graph.get("files"):
        _json_dump(artifacts_dir / "terraform.json", terraform_graph)
    _json_dump(artifacts_dir / "cycles.json", {"cycles": cycles})
    _json_dump(
        artifacts_dir / "hotspots.json",
        {"modules": module_metrics[:30], "functions": function_hotspots},
    )
    _json_dump(artifacts_dir / "glossary.json", {"glossary": glossary})

    diagrams_dir = output_root / "diagrams"
    diagrams_dir.mkdir(parents=True, exist_ok=True)

    (output_root / "architecture-services.mmd").write_text(architecture_service_mmd, encoding="utf-8")
    (output_root / "architecture-code.mmd").write_text(architecture_code_mmd, encoding="utf-8")
    (output_root / "architecture-iac.mmd").write_text(architecture_iac_mmd, encoding="utf-8")
    (output_root / "architecture.mmd").write_text(architecture_mmd, encoding="utf-8")
    (output_root / "architecture-services.puml").write_text(architecture_service_puml, encoding="utf-8")
    (output_root / "architecture-code.puml").write_text(architecture_code_puml, encoding="utf-8")
    (output_root / "architecture-iac.puml").write_text(architecture_iac_puml, encoding="utf-8")
    (output_root / "architecture.puml").write_text(architecture_puml, encoding="utf-8")
    (output_root / "er.mmd").write_text(er_mmd, encoding="utf-8")
    (output_root / "er.puml").write_text(er_puml, encoding="utf-8")
    (output_root / "er.dbml").write_text(dbml, encoding="utf-8")
    (output_root / "call-graph.mmd").write_text(call_mmd, encoding="utf-8")
    (output_root / "call-graph.puml").write_text(call_puml, encoding="utf-8")
    (output_root / "dependencies.mmd").write_text(dependency_mmd, encoding="utf-8")
    (output_root / "dependencies.puml").write_text(dependency_puml, encoding="utf-8")
    (output_root / "sequence.mmd").write_text(sequence_mmd, encoding="utf-8")
    (output_root / "sequence.puml").write_text(sequence_puml, encoding="utf-8")
    (output_root / "use-case.mmd").write_text(use_case_mmd, encoding="utf-8")
    (output_root / "use-case.puml").write_text(use_case_puml, encoding="utf-8")
    (output_root / "data.json").write_text(data_json_source, encoding="utf-8")
    (output_root / "data.yaml").write_text(data_yaml_source, encoding="utf-8")
    (output_root / "json-data.puml").write_text(data_json_puml, encoding="utf-8")
    (output_root / "yaml-data.puml").write_text(data_yaml_puml, encoding="utf-8")
    (output_root / "onboarding.md").write_text(onboarding_md, encoding="utf-8")
    (output_root / "repo-summary.md").write_text(repo_summary_md, encoding="utf-8")
    (output_root / "top-files.md").write_text(top_files_md, encoding="utf-8")
    (output_root / "index.md").write_text(index_md, encoding="utf-8")
    (output_root / "handoff.md").write_text(handoff_md, encoding="utf-8")
    (output_root / "case_file.md").write_text(case_file_md, encoding="utf-8")

    (diagrams_dir / "architecture.mmd").write_text(architecture_mmd, encoding="utf-8")
    (diagrams_dir / "architecture-services.mmd").write_text(architecture_service_mmd, encoding="utf-8")
    (diagrams_dir / "architecture-code.mmd").write_text(architecture_code_mmd, encoding="utf-8")
    (diagrams_dir / "architecture-iac.mmd").write_text(architecture_iac_mmd, encoding="utf-8")
    (diagrams_dir / "architecture-services.puml").write_text(architecture_service_puml, encoding="utf-8")
    (diagrams_dir / "architecture-code.puml").write_text(architecture_code_puml, encoding="utf-8")
    (diagrams_dir / "architecture-iac.puml").write_text(architecture_iac_puml, encoding="utf-8")
    (diagrams_dir / "architecture.puml").write_text(architecture_puml, encoding="utf-8")
    (diagrams_dir / "er.mmd").write_text(er_mmd, encoding="utf-8")
    (diagrams_dir / "er.puml").write_text(er_puml, encoding="utf-8")
    (diagrams_dir / "call-graph.mmd").write_text(call_mmd, encoding="utf-8")
    (diagrams_dir / "call-graph.puml").write_text(call_puml, encoding="utf-8")
    (diagrams_dir / "dependencies.mmd").write_text(dependency_mmd, encoding="utf-8")
    (diagrams_dir / "dependencies.puml").write_text(dependency_puml, encoding="utf-8")
    (diagrams_dir / "sequence.mmd").write_text(sequence_mmd, encoding="utf-8")
    (diagrams_dir / "sequence.puml").write_text(sequence_puml, encoding="utf-8")
    (diagrams_dir / "use-case.mmd").write_text(use_case_mmd, encoding="utf-8")
    (diagrams_dir / "use-case.puml").write_text(use_case_puml, encoding="utf-8")
    (diagrams_dir / "json-data.puml").write_text(data_json_puml, encoding="utf-8")
    (diagrams_dir / "yaml-data.puml").write_text(data_yaml_puml, encoding="utf-8")
    if terraform_drawio_file and terraform_drawio:
        (output_root / terraform_drawio_file).write_text(terraform_drawio, encoding="utf-8")

    return {
        "output_root": output_root,
        "summary": summary,
        "start_here": start_here,
        "warnings": parser_errors,
    }

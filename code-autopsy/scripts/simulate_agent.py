#!/usr/bin/env python3
"""Simulate iterative feature improvements on an isolated copy of a codebase."""

from __future__ import annotations

import argparse
import os
import json
import hashlib
import shlex
import re
import shutil
import subprocess
import sys
from urllib.parse import urlparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, cast


def _safe_rmtree(target: Path) -> None:
    """Delete a directory and tolerate Windows readonly/locked git object files."""

    def _onerror(function, path: str, exc_info) -> None:
        try:
            os.chmod(path, 0o666)
            function(path)
        except OSError:
            raise

    try:
        shutil.rmtree(target)
        return
    except OSError:
        pass

    try:
        shutil.rmtree(target, onexc=_onerror)
    except OSError as exc:
        raise RuntimeError(f"unable to clear cached clone directory: {target}") from exc


def _next_available_dir(base: Path) -> Path:
    if not base.exists():
        return base
    for idx in range(1, 51):
        candidate = base.with_name(f"{base.name}-{idx}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not allocate temporary clone directory near {base}")


def _derive_run_name(explicit_run_name: str | None, source_url: str | None = None, source_path: str | None = None) -> str:
    if explicit_run_name:
        return explicit_run_name

    candidate: str | None = None
    if source_url:
        parsed = urlparse(source_url.strip())
        candidate = parsed.path.rsplit("/", 1)[-1]
        if not candidate:
            segments = [segment for segment in parsed.path.split("/") if segment]
            candidate = segments[-1] if segments else None
        if candidate.endswith(".git"):
            candidate = candidate[:-4]
    elif source_path:
        candidate = Path(source_path).name

    if not candidate:
        return make_run_name()

    candidate = sanitize_slug(candidate)
    return candidate or make_run_name()


def normalize_source_url(raw_url: str) -> str:
    trimmed = raw_url.strip()
    if "://" in trimmed or trimmed.startswith("git@") or trimmed.endswith(".git"):
        return trimmed
    if trimmed.count("/") == 1 and not trimmed.startswith("/"):
        return f"https://github.com/{trimmed}.git"
    raise ValueError(
        "source_url must be a git URL, e.g. https://github.com/org/repo.git, "
        "or org/repo for GitHub shorthand."
    )


def _looks_like_commit_hash(value: str) -> bool:
    token = value.strip()
    return bool(re.fullmatch(r"[0-9a-fA-F]{7,40}", token))


def _infer_project_root(candidate_parent: Path) -> Path | None:
    """Infer a likely project root when an explicit subdir does not resolve."""

    candidate_markers = {
        "requirements.txt": 6,
        "pyproject.toml": 6,
        "setup.py": 5,
        "setup.cfg": 5,
        "package.json": 6,
        "package-lock.json": 2,
        "pnpm-lock.yaml": 2,
        "yarn.lock": 2,
        "go.mod": 6,
        "Cargo.toml": 6,
        "pom.xml": 6,
        "build.gradle": 5,
        "build.gradle.kts": 5,
        "Gemfile": 5,
        "composer.json": 5,
        "tsconfig.json": 3,
        "vite.config.ts": 3,
        "vite.config.js": 3,
        "next.config.js": 3,
    }

    def score(path: Path) -> int:
        value = 0
        for marker, weight in candidate_markers.items():
            if (path / marker).exists():
                value += weight
        if (path / "public").is_dir():
            value += 1
        if (path / "src").is_dir():
            value += 1
        return value

    root_candidates = [candidate_parent]
    for candidate in candidate_parent.iterdir():
        if candidate.is_dir() and not candidate.name.startswith("."):
            root_candidates.append(candidate)

    ranked: list[tuple[int, Path]] = []
    for candidate in root_candidates:
        ranked.append((score(candidate), candidate))

    ranked = sorted(ranked, reverse=True, key=lambda item: (item[0], len(item[1].name)))
    if not ranked:
        return None

    if ranked[0][0] == 0:
        return None

    # Avoid ambiguous ties: if top scores are equal, don't guess.
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return None

    return ranked[0][1]


def prepare_remote_source(
    repo_url: str,
    workspace: Path,
    ref: str | None = None,
    subdir: str | None = None,
    run_name: str | None = None,
) -> Path:
    normalized = normalize_source_url(repo_url)
    sources_root = workspace / ".remote_sources"
    sources_root.mkdir(parents=True, exist_ok=True)
    label = re.sub(r"[^a-zA-Z0-9_.-]", "_", run_name or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"))
    clone_dir = sources_root / f"source-{label}"

    if clone_dir.exists():
        try:
            _safe_rmtree(clone_dir)
        except RuntimeError:
            clone_dir = _next_available_dir(clone_dir)

    clone_args = ["git", "clone", "--filter=blob:none", "--depth", "1", "--", normalized, str(clone_dir)]
    if ref and not _looks_like_commit_hash(ref):
        clone_args.insert(2, "--branch")
        clone_args.insert(3, ref)

    run_command(clone_args, cwd=workspace)

    if ref and _looks_like_commit_hash(ref):
        run_command(["git", "fetch", "--depth", "1", "origin", ref], cwd=clone_dir)
        run_command(["git", "checkout", ref], cwd=clone_dir)

    source = clone_dir
    if subdir:
        requested = subdir.strip("/\\")
        parts = [part for part in re.split(r"[\\/]", requested) if part and part != "."]

        if not parts:
            source = clone_dir
        else:

            def _case_insensitive_child(parent: Path, target: str) -> Path | None:
                for candidate in parent.iterdir():
                    if candidate.is_dir() and candidate.name.lower() == target.lower():
                        return candidate
                return None

            def _match_nested() -> list[Path]:
                lowered = [part.lower() for part in parts]
                matches: list[Path] = []
                for candidate in clone_dir.rglob("*"):
                    if not candidate.is_dir():
                        continue
                    rel_parts = [part.lower() for part in candidate.relative_to(clone_dir).parts]
                    if len(rel_parts) < len(lowered):
                        continue
                    if rel_parts[-len(lowered):] == lowered:
                        matches.append(candidate)
                return matches

            current = clone_dir
            found = None
            for part in parts:
                exact = current / part
                if exact.exists():
                    if not exact.is_dir():
                        raise RuntimeError(f"source-subdir points to a file, not a directory: {exact}")
                    current = exact
                    found = current
                    continue

                matched = _case_insensitive_child(current, part)
                if matched is None:
                    found = None
                    break
                current = matched
                found = current

            if found is None:
                fallback = _match_nested()
                if len(fallback) == 1:
                    found = fallback[0]
                elif len(fallback) > 1:
                    options = ", ".join(str(path.relative_to(clone_dir)) for path in sorted(fallback)[:20])
                    raise RuntimeError(
                        "source-subdir is ambiguous: "
                        f"{subdir}. "
                        f"Found {len(fallback)} candidate directories: {options}"
                    )
                inferred = _infer_project_root(clone_dir)
                if inferred is not None:
                    found = inferred

            if found is None:
                available = sorted(
                    item.name for item in clone_dir.iterdir() if item.is_dir() and not item.name.startswith(".")
                )
                raise RuntimeError(
                    f"source checkout is invalid: {requested} in {clone_dir}\n"
                    "Available top-level directories: "
                    + (", ".join(available) if available else "(none)")
                )

            source = found
    if not source.exists() or not source.is_dir():
        raise RuntimeError(f"source checkout is invalid: {source}")
    return source

DEFAULT_EXCLUDES = [
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".venv",
    "node_modules",
    "dist",
    "build",
]

DEFAULT_AGENT_CONTEXT_FILE = "simulation_context.md"

SUPPORTED_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".java",
    ".go",
    ".rs",
    ".cs",
}

MAX_SCAN_FILES = 2000

AGENT_FILE_PATTERNS = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".html", ".md"}

ENTRYPOINT_PATTERNS = [
    re.compile(r"@(?:app|router)\.(get|post|put|patch|delete|options|head)\s*\("),
    re.compile(r"@app\.api_route\("),
    re.compile(r"def\s+main\("),
    re.compile(r"FastAPI\("),
]

INPUT_HOTSPOT_PATTERNS = [
    re.compile(r"\bjson\.loads\("),
    re.compile(r"\bjson\.load\("),
    re.compile(r"\brequest\.\w+"),
    re.compile(r"\bBody\("),
    re.compile(r"\bForm\("),
    re.compile(r"\bFile\("),
    re.compile(r"\bDepends\("),
]

SINK_PATTERNS = {
    "command_execution": [re.compile(r"\b(subprocess\.|os\.system|os\.popen|os\.spawn|subprocess\.Popen)\b")],
    "deserialization": [re.compile(r"\b(eval|exec|pickle\.loads|yaml\.load|yaml\.unsafe_load)\b")],
    "file_output": [re.compile(r"\bopen\(.+,\s*[\"']w"), re.compile(r"\bPath\(.+\)\.write_text\(")],
    "network": [re.compile(r"\b(requests|get|post|httpx|urllib)\.(get|post|request)\(")],
    "filesystem": [re.compile(r"\bshutil\.copy(?:tree|file|2)?\(")],
}

AUTH_PATTERNS = [
    re.compile(r"\bDepends\([^)]*(?:auth|security|user|current_user|oauth)\b", re.IGNORECASE),
    re.compile(r"\bAuthorization\b"),
    re.compile(r"\bsession\b"),
]

SECRET_PATTERNS = [
    re.compile(r"\b(SKIP|SECRET|TOKEN|KEY|PASS|PASSWORD|PRIVATE)_\w*=\s*['\"][^'\"]+['\"]", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9_]*_TOKEN\s*=\s*['\"][^'\"]+['\"]", re.IGNORECASE),
]


@dataclass
class CheckpointRecord:
    iteration: int
    tag: str
    feature: str
    commit: str
    timestamp_utc: str
    status: str
    files_changed: List[str]
    notes: str = ""
    red_team_report: str = ""
    blue_team_report: str = ""
    refactorer_report: str = ""
    historian_report: str = ""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_run_name() -> str:
    return f"simulation-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


def sanitize_slug(text: str, max_len: int = 64) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    if not slug:
        slug = "feature"
    return slug[:max_len].rstrip("-")


def compact_slug(slug: str, index: int, max_len: int = 32) -> str:
    """Return a short, deterministic slug variant safe for Windows path limits."""
    slug = slug.strip("-")
    if not slug:
        slug = f"feature-{index:03d}"
    if len(slug) <= max_len:
        return slug
    digest = hashlib.sha1(slug.encode("utf-8")).hexdigest()[:8]
    base_len = max(4, max_len - 9)
    return f"{slug[:base_len]}-{digest}"


def symbol_from_slug(slug: str) -> str:
    symbol = re.sub(r"[^a-zA-Z0-9_]", "_", slug)
    if not symbol:
        symbol = "feature"
    if symbol[0].isdigit():
        symbol = f"f_{symbol}"
    return symbol


def is_subpath(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _is_ignored_path(path: Path) -> bool:
    parts = set(part.lower() for part in path.parts)
    ignored = {".git", ".hg", ".svn", "__pycache__", ".venv", "node_modules", ".simulation"}
    return any(part in parts for part in ignored)


def scan_files_for_agents(codebase: Path) -> List[Path]:
    scanned: List[Path] = []
    for file_path in codebase.rglob("*"):
        if not file_path.is_file():
            continue
        if _is_ignored_path(file_path):
            continue
        if file_path.suffix.lower() not in AGENT_FILE_PATTERNS:
            continue
        scanned.append(file_path)
    return scanned


def _safe_read_lines(path: Path) -> List[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError):
        return []


def evaluate_attack_surface(codebase: Path, feature: str) -> Dict[str, object]:
    files = scan_files_for_agents(codebase)
    entrypoints: List[str] = []
    input_hotspots: List[str] = []
    sinks: Dict[str, List[str]] = defaultdict(list)
    secret_hits: List[str] = []
    auth_hits: List[str] = []
    validation_hits: List[str] = []

    for file_path in files:
        rel = file_path.relative_to(codebase)
        lines = _safe_read_lines(file_path)
        for index, line in enumerate(lines, start=1):
            for pattern in ENTRYPOINT_PATTERNS:
                if pattern.search(line):
                    entrypoints.append(f"{rel}:{index}: {line.strip()}")
            for pattern in INPUT_HOTSPOT_PATTERNS:
                if pattern.search(line):
                    input_hotspots.append(f"{rel}:{index}: {line.strip()}")
            if "Field(" in line and "min_length" in line:
                validation_hits.append(f"{rel}:{index}: {line.strip()}")
            for key, patterns in SINK_PATTERNS.items():
                for pattern in patterns:
                    if pattern.search(line):
                        sinks[key].append(f"{rel}:{index}: {line.strip()}")
            for pattern in AUTH_PATTERNS:
                if pattern.search(line):
                    auth_hits.append(f"{rel}:{index}: {line.strip()}")
            for pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    secret_hits.append(f"{rel}:{index}: {line.strip()}")

    return {
        "feature": feature,
        "files_scanned": len(files),
        "entrypoints": entrypoints,
        "input_hotspots": input_hotspots,
        "sinks": dict(sinks),
        "auth_hits": auth_hits,
        "secret_hits": secret_hits,
        "validation_hits": validation_hits,
    }


def run_command(args: Sequence[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(args),
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
    )
    if check and completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        details = stderr or stdout or f"exit code {completed.returncode}"
        raise RuntimeError(f"Command failed: {' '.join(args)}\n{details}")
    return completed


def normalize_iteration_command(command: str, codebase: Path) -> str:
    """Return a safer command for missing test directories.\n\n    For Python unittest discovery, if `-s <path>` points to a directory that does not\n    exist, choose a common test directory if present, otherwise remove the flag so unittest\n    defaults to discover from the current working directory.\n    """

    normalized = command.format(feature="", index=0, slug="")
    if "python" not in normalized.lower() or "unittest" not in normalized.lower() or "discover" not in normalized.lower():
        return command

    try:
        tokens = shlex.split(normalized)
    except ValueError:
        return command

    if not tokens or " ".join(tokens[:3]).lower() != "python -m unittest":
        return command

    if "discover" not in tokens:
        return command

    # Only rewrite safe unittest discovery invocations.
    candidate_dirs = ["tests", "test", "spec", "__tests__", "e2e"]

    def _locate_tests_dir(raw_dir: str) -> str | None:
        preferred = Path(raw_dir)
        if preferred.is_absolute():
            candidate_path = preferred
        else:
            candidate_path = codebase / preferred
        if candidate_path.is_dir():
            return raw_dir

        for fallback in candidate_dirs:
            fallback_path = codebase / fallback
            if fallback_path.is_dir():
                return fallback
        return None

    changed = False
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "-s":
            if i + 1 >= len(tokens):
                return command
            raw_dir = tokens[i + 1]
            resolved = _locate_tests_dir(raw_dir)
            if resolved is None:
                tokens.pop(i + 1)
                tokens.pop(i)
                changed = True
                continue
            if resolved != raw_dir:
                tokens[i + 1] = resolved
                changed = True
        i += 1

    if not changed:
        return command
    return " ".join(shlex.quote(token) for token in tokens)


def run_shell_command(command: str, cwd: Path) -> Tuple[str, str]:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        shell=True,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        details = "\n".join(part for part in [stdout, stderr] if part)
        raise RuntimeError(f"Iteration command failed ({completed.returncode}): {details}")
    return completed.stdout or "", completed.stderr or ""


def load_features(feature_flags: Iterable[str], features_file: Optional[Path]) -> List[str]:
    features: List[str] = []
    seen = set()

    for feature in feature_flags:
        item = feature.strip()
        if item and item not in seen:
            seen.add(item)
            features.append(item)

    if features_file:
        if not features_file.exists():
            raise ValueError(f"Features file does not exist: {features_file}")
        for line in features_file.read_text(encoding="utf-8-sig").splitlines():
            item = line.strip()
            if not item or item.startswith("#"):
                continue
            if item not in seen:
                seen.add(item)
                features.append(item)

    return features


def infer_features_from_codebase(codebase: Path, limit: int = 9) -> List[str]:
    """Generate a starter feature list by inspecting the repository structure.

    This is used when no explicit feature list is supplied by the user.
    """

    inferred: List[str] = []

    def _add_feature(feature: str) -> None:
        if not feature:
            return
        if feature not in inferred:
            inferred.append(feature)

    files = scan_files_for_agents(codebase)
    has_py = any(file_path.suffix.lower() == ".py" for file_path in files)
    has_ts = any(file_path.suffix.lower() in {".ts", ".tsx"} for file_path in files)
    has_js = any(file_path.suffix.lower() in {".js", ".jsx"} for file_path in files)
    has_go = any(file_path.suffix.lower() == ".go" for file_path in files)
    has_rs = any(file_path.suffix.lower() == ".rs" for file_path in files)
    has_java = any(file_path.suffix.lower() == ".java" for file_path in files)
    has_cs = any(file_path.suffix.lower() == ".cs" for file_path in files)
    has_tf = any(file_path.suffix.lower() == ".tf" for file_path in files)
    has_docs = any(file_path.suffix.lower() in {".md", ".rst", ".txt"} for file_path in files)

    has_frontend = has_ts or has_js
    test_dir = next((p for p in [codebase / "tests", codebase / "test", codebase / "spec"] if p.is_dir()), None)

    analysis = evaluate_attack_surface(codebase, feature="auto-generated security feature list")
    has_entrypoints = bool(analysis["entrypoints"])
    has_auth_hits = bool(analysis["auth_hits"])
    has_input_hotspots = bool(analysis["input_hotspots"])
    has_sinks = any(analysis["sinks"].values())

    if has_entrypoints and not has_auth_hits:
        _add_feature("Add secure authentication/session checks for all write-capable endpoints.")
    if has_input_hotspots:
        _add_feature("Add shared request validation and schema enforcement at API boundaries.")
    if has_sinks:
        _add_feature("Add runtime guards and allow-list checks around command/process and file/network sinks.")

    if has_py:
        _add_feature("Add duplicate handling and idempotency controls for write operations.")
    if has_frontend:
        _add_feature("Add frontend input sanitization and visible error handling for failed API calls.")

    if has_tf:
        _add_feature("Add Terraform variable constraints and defaults for module inputs.")
        _add_feature("Add validation checks for module contracts in a dedicated terraform test workflow.")
        _add_feature("Add changelog and version pinning policy for providers and required versions.")

    if test_dir is None:
        _add_feature("Add automated tests for critical user flows and regression protection.")
    if has_js:
        _add_feature("Add dependency lockfile enforcement and vulnerability scan in CI.")
    if has_go:
        _add_feature("Add structured error handling and request tracing middleware.")
    if has_rs:
        _add_feature("Add explicit panic boundaries and safe error responses for API-facing paths.")
    if has_java or has_cs:
        _add_feature("Add endpoint-level authorization and auditing for all state changes.")
    if not has_docs:
        _add_feature("Add architecture notes and setup instructions in project documentation.")

    if not inferred:
        _add_feature("Add tests for core business operations and access control paths.")

    return inferred[:limit]


def detect_preferred_extension(codebase: Path) -> str:
    counts: Dict[str, int] = {}
    scanned = 0

    for file_path in codebase.rglob("*"):
        if not file_path.is_file():
            continue
        ext = file_path.suffix.lower()
        counts[ext] = counts.get(ext, 0) + 1
        scanned += 1
        if scanned >= MAX_SCAN_FILES:
            break

    supported_counts = {ext: count for ext, count in counts.items() if ext in SUPPORTED_EXTENSIONS}
    if not supported_counts:
        return ".txt"

    return max(supported_counts.items(), key=lambda item: item[1])[0]


def build_stub_content(extension: str, index: int, feature: str, slug: str) -> str:
    function_name = f"feature_{index:03d}_{symbol_from_slug(slug)}"

    if extension == ".py":
        return (
            f'"""Simulated feature stub: {feature}"""\n\n'
            f"def {function_name}():\n"
            f"    \"\"\"TODO: implement this feature.\"\"\"\n"
            f"    raise NotImplementedError(\"Implement simulated feature: {feature}\")\n"
        )

    if extension in {".ts", ".tsx"}:
        return (
            f"// Simulated feature stub: {feature}\n"
            f"export function {function_name}(): never {{\n"
            f"  throw new Error(\"TODO: implement simulated feature: {feature}\");\n"
            f"}}\n"
        )

    if extension in {".js", ".jsx"}:
        return (
            f"// Simulated feature stub: {feature}\n"
            f"function {function_name}() {{\n"
            f"  throw new Error(\"TODO: implement simulated feature: {feature}\");\n"
            f"}}\n\n"
            f"module.exports = {{ {function_name} }};\n"
        )

    if extension == ".java":
        class_name = f"Feature{index:03d}{symbol_from_slug(slug).title().replace('_', '')}"
        return (
            f"// Simulated feature stub: {feature}\n"
            f"public class {class_name} {{\n"
            f"    public void run() {{\n"
            f"        throw new UnsupportedOperationException(\"TODO: implement simulated feature: {feature}\");\n"
            f"    }}\n"
            f"}}\n"
        )

    if extension == ".go":
        return (
            "package simulated\n\n"
            f"// Simulated feature stub: {feature}\n"
            f"func {function_name.title().replace('_', '')}() {{\n"
            f"    panic(\"TODO: implement simulated feature: {feature}\")\n"
            "}\n"
        )

    if extension == ".rs":
        return (
            f"// Simulated feature stub: {feature}\n"
            f"pub fn {function_name}() {{\n"
            f"    panic!(\"TODO: implement simulated feature: {feature}\");\n"
            "}\n"
        )

    if extension == ".cs":
        class_name = f"Feature{index:03d}{symbol_from_slug(slug).title().replace('_', '')}"
        return (
            f"// Simulated feature stub: {feature}\n"
            f"public static class {class_name} {{\n"
            "    public static void Run() {\n"
            f"        throw new System.NotImplementedException(\"TODO: implement simulated feature: {feature}\");\n"
            "    }\n"
            "}\n"
        )

    return (
        f"Simulated feature stub: {feature}\n"
        f"Iteration: {index:03d}\n"
        "TODO: implement this feature in the project language.\n"
    )


def append_changelog(codebase: Path, index: int, feature: str, artifact_rel: Path, status: str, notes: str) -> None:
    changelog_path = codebase / "SIMULATION_CHANGELOG.md"
    entry = [
        f"## Iteration {index:03d} - {feature}",
        f"- Timestamp (UTC): {utc_now_iso()}",
        f"- Status: {status}",
        f"- Artifact: {artifact_rel.as_posix()}",
    ]
    if notes:
        entry.append(f"- Notes: {notes}")
    entry.append("")

    with changelog_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(entry))
        handle.write("\n")


def build_agent_report_sections(
    codebase: Path,
    iteration: int,
    feature: str,
    analysis: Dict[str, object],
) -> Dict[str, str]:
    entrypoints = cast(List[str], analysis["entrypoints"])
    input_hotspots = cast(List[str], analysis["input_hotspots"])
    sinks = cast(Dict[str, List[str]], analysis["sinks"])
    auth_hits = cast(List[str], analysis["auth_hits"])
    validation_hits = cast(List[str], analysis["validation_hits"])
    secret_hits = cast(List[str], analysis["secret_hits"])

    has_entrypoints = len(entrypoints) > 0
    has_auth = len(auth_hits) > 0
    has_validation = len(validation_hits) > 0
    has_secrets = len(secret_hits) > 0
    has_file_sink = bool(sinks.get("file_output"))

    sink_lines = []
    for sink_type, occurrences in sinks.items():
        if not occurrences:
            continue
        sink_lines.append(f"- **{sink_type.replace('_', ' ').title()}**")
        for item in occurrences[:5]:
            sink_lines.append(f"  - `{item}`")
    if not sink_lines:
        sink_lines.append("- No clearly dangerous sinks detected by static pattern.")

    red = []
    red.append("## Attack Surface Map")
    red.append("")
    if entrypoints:
        red.append("Entrypoints:")
        for item in entrypoints[:10]:
            red.append(f"- {item}")
    else:
        red.append("- No direct web/API/UI entrypoints detected.")
    red.append("")
    red.append("Trust boundaries:")
    if has_auth:
        red.append("- Authentication/session markers were observed in handlers and middleware.")
    else:
        red.append("- No clear authentication boundary marker detected.")
    red.append("")
    red.append("Input handling hotspots:")
    for item in input_hotspots[:10]:
        red.append(f"- {item}")
    if not input_hotspots:
        red.append("- No request parsing hotspots matched static patterns.")
    red.append("")
    red.append("Dangerous sinks:")
    red.extend(sink_lines)
    red.append("")

    red.append("## Top 5 exploit stories")
    red.append("")

    feature_lower = feature.lower()
    severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    exploit_stories: List[Tuple[str, str]] = []
    if not has_auth:
        exploit_stories.append((
            "critical",
            "**Unauthenticated state change**\n"
            "   - Write endpoints look reachable without mandatory identity checks.\n"
            "   - Attackers can mass-create/update/delete tasks and tamper with report numbers."
        ))
    elif len(entrypoints) > 3:
        exploit_stories.append((
            "high",
            "**Privilege escalation across broad API surface**\n"
            "   - Auth appears present in some paths, but many entrypoints increase the chance of inconsistent enforcement.\n"
            "   - A single bypass in any route can expose all task actions."
        ))

    if any("Body(" in item or "request." in item or "Field(" in item for item in input_hotspots):
        exploit_stories.append((
            "high",
            "**Input boundary bypass / parser abuse**\n"
            "   - Multiple parsing paths increase attackable shapes (body/query/path).\n"
            "   - Crafted payloads can cause inconsistent validation and business-rule drift."
        ))
    else:
        exploit_stories.append((
            "medium",
            "**Input boundary ambiguity**\n"
            "   - Keep validating shape and types on every mutable path, including path/query parameters."
        ))

    if sinks.get("network"):
        exploit_stories.append((
            "medium",
            "**External callback abuse**\n"
            "   - Any user-controllable URL or host input can be used for outbound requests if future integrations are added.\n"
            "   - Add strict allow-lists before any remote call."
        ))

    if has_file_sink:
        exploit_stories.append((
            "high",
            "**Storage persistence abuse**\n"
            "   - Writable paths are exposed; crafted operations can alter local persisted files.\n"
            "   - This can persist unauthorized changes or inject malformed state."
        ))
    elif "file" in feature_lower or "export" in feature_lower:
        exploit_stories.append((
            "medium",
            "**File-output integrity risk**\n"
            "   - Requested feature introduces file handling; enforce strict output path controls and ownership checks."
        ))

    if "webhook" in feature_lower or "callback" in feature_lower:
        exploit_stories.append((
            "medium",
            "**Trust boundary confusion**\n"
            "   - External callback endpoints can become a replay or spoofing vector.\n"
            "   - Require timestamped signatures and idempotency checks."
        ))

    if "email" in feature_lower and "completion" in feature_lower and "notification" in feature_lower:
        exploit_stories.append((
            "medium",
            "**Notification sink injection**\n"
            "   - Completion hooks that write/dispatch side effects can become stealth channels for replay and log tampering.\n"
            "   - Guard recipient config and event payloads before emitting notification events."
        ))

    if "different" in feature_lower and "users" in feature_lower and "task" in feature_lower:
        exploit_stories.append((
            "high",
            "**Cross-user data exposure**\n"
            "   - Multi-user filtering/ownership flows can leak task ownership and status transitions across boundaries.\n"
            "   - Enforce explicit tenant/user scoping at every listing and mutation path."
        ))

    if "bulk" in feature_lower or "batch" in feature_lower:
        exploit_stories.append((
            "high",
            "**Mass mutation abuse**\n"
            "   - Batch-like flows widen blast radius with single-request data corruption.\n"
            "   - Add per-item auth, limits, and transaction rollback semantics."
        ))

    if "search" in feature_lower or "filter" in feature_lower:
        exploit_stories.append((
            "low",
            "**Query/path abuse**\n"
            "   - Search and filter features can be abused for reconnaissance and high-cost query patterns.\n"
            "   - Add query quotas and bounded regex/time limits."
        ))

    fallback = [
        (
            "low",
            "**Dependency drift/maintenance debt**\n   - Track dependency updates and runtime warnings before they become production bypasses.",
        ),
        (
            "low",
            "**Replay and automated abuse**\n   - Add rate limits and anomaly detection around frequently called write routes.",
        ),
        (
            "low",
            "**Error leakage**\n   - Ensure API errors do not reveal stack traces or internal schema details.",
        ),
        (
            "low",
            "**Route discoverability**\n   - Harden all `/api/*` handlers uniformly to avoid uneven security posture.",
        ),
    ]
    fallback_index = 0
    while len(exploit_stories) < 5:
        exploit_stories.append(fallback[fallback_index % len(fallback)])
        fallback_index += 1

    exploit_stories.sort(key=lambda item: severity_order[item[0]])
    exploit_stories.reverse()

    for index, story in enumerate(exploit_stories[:5], start=1):
        severity, text = story
        red.append(f"{index}. [{severity.upper()}] {text}")

    red.append("")

    red.append("## Blast radius")
    red.append("")
    if has_auth:
        red.append("- If an authenticated account is compromised, endpoints and persistence can be used to alter shared data.")
    else:
        red.append("- If endpoints are abused, data corruption or unauthorized manipulation spreads to all task records and reports.")
    if has_file_sink:
        red.append("- A file-write sink can amplify impact to local file persistence and downstream startup behavior.")
    if has_secrets:
        red.append("- Leaked credentials enable downstream service impersonation and lateral movement.")

    blue = []
    blue.append("## Mitigation plan by ROI")
    blue.append("")
    blue.append("### Quick wins")
    if has_auth:
        blue.append("- Add explicit route-level auth middleware audit on all `/api/*` handlers.")
    else:
        blue.append("- Enforce API auth guard for every mutable route (`POST`, `PATCH`, `DELETE`).")
    blue.append("- Add request-size and payload shape guards at API boundary.")
    if has_file_sink:
        blue.append("- Restrict file paths and validate output destinations.")
    if has_secrets:
        blue.append("- Remove hard-coded secrets and use runtime secret manager/ env config with validation.")
    blue.append("")
    blue.append("### Structural fixes")
    blue.append("- Introduce dedicated input-validation layer, shared error model, and security policy middleware.")
    blue.append("- Move persistence and service logic into clear service boundaries with interface boundaries.")
    blue.append("")
    blue.append("### Monitoring hooks")
    blue.append("- Add audit logging for create/update/delete/report calls.")
    blue.append("- Emit validation-failure metrics and failed auth metrics.")
    blue.append("")
    blue.append("### Patch sketch (pseudo)")
    blue.append("```diff")
    blue.append("- @app.{method}('/api/..', ...)")
    blue.append("+ @app.{method}('/api/..', dependencies=[Depends(require_session)])")
    blue.append("+ if not is_valid_payload(payload): raise HTTPException(status_code=400)")
    blue.append(f"+ audit_log_event('{feature}')")
    blue.append("```")
    blue.append("")
    blue.append("### Security tests / guardrails")
    blue.append("- Test that unauthenticated calls are rejected for write endpoints.")
    blue.append("- Test invalid payloads always reject cleanly with explicit errors.")
    blue.append("- Add static check for secret patterns in committed files.")

    blue.append("- Recommended next PRs: auth hardening, boundary middleware, storage authorization checks.")

    refactor = []
    refactor.append("## Refactor plan (low-risk increments)")
    refactor.append("")
    refactor.append("1. Split route layer and repository/service layer to reduce coupling.")
    refactor.append("2. Add explicit application boundary types for request/response objects.")
    refactor.append("3. Expand tests around storage and route invariants before touching structure.")
    refactor.append("")
    refactor.append("### Minimal PR candidate")
    refactor.append("- Create `security` module containing auth middleware + validation helpers.")
    refactor.append("- Extract shared response formatting from handlers.")
    refactor.append("- Keep endpoint signatures unchanged while moving logic behind service functions.")

    # simple hotspot view from file sizes and module boundaries
    source_counts = []
    for file_path in scan_files_for_agents(codebase):
        rel = str(file_path.relative_to(codebase))
        source_counts.append((rel, file_path.stat().st_size))
    source_counts.sort(key=lambda item: item[1], reverse=True)
    if source_counts:
        top = source_counts[0][0]
        refactor.append(f"- Current hotspot: `{top}` (largest static text footprint).")

    refactor.append("- Risk target: keep API surface stable; prefer moving behavior into `service/` modules over renames.")

    hist_lines = []
    hist_lines.append("## Evolution narrative")
    hist_lines.append("")
    hist_lines.append(f"Iteration {iteration} feature focus: `{feature}`.")
    hist_lines.append(f"Scanned files in this checkpoint: {analysis['files_scanned']}.")
    hist_lines.append("")
    if has_auth:
        hist_lines.append("- Security posture shows partial boundary shaping; authentication traces are present but drift should be standardized.")
    else:
        hist_lines.append("- No consistent authorization contract visible; likely accumulated organically without security schema planning.")
    if len(entrypoints) > 2:
        hist_lines.append("- Multiple entrypoints suggest fast feature growth and rising integration pressure.")
    hist_lines.append("")
    hist_lines.append("### 2-year forecast")
    hist_lines.append("- Without boundary consolidation, route logic and persistence checks will become coupled and regressions will become harder to isolate.")
    hist_lines.append("- Add conventions now to reduce bus-factor and onboarding costs.")

    return {
        "red_team_report": "\n".join(red),
        "blue_team_report": "\n".join(blue),
        "refactorer_report": "\n".join(refactor),
        "historian_report": "\n".join(hist_lines),
    }


def write_agent_iteration_notes(
    codebase: Path,
    index: int,
    feature: str,
    slug: str,
    iterations: Dict[str, str],
) -> Dict[str, str]:
    iteration_dir = codebase / ".simulation" / "agent-notes"
    iteration_dir.mkdir(parents=True, exist_ok=True)
    base = f"{index:03d}-{slug}"

    reports: Dict[str, str] = {}
    role_map = {
        "red": "red-team",
        "blue": "blue-team",
        "refactorer": "refactorer",
        "historian": "historian",
    }
    for role, label in role_map.items():
        rel = Path(".simulation") / "agent-notes" / f"{base}.{label}.md"
        path = codebase / rel
        key = {
            "red": "red_team_report",
            "blue": "blue_team_report",
            "refactorer": "refactorer_report",
            "historian": "historian_report",
        }[role]
        content = (
            f"# {label.replace('-', ' ').title()} Iteration {index:03d}\n\n"
            f"Feature: {feature}\n\n"
            f"{iterations[key]}\n"
        )
        path.write_text(content, encoding="utf-8")
        reports[f"{role}_team_path"] = str(rel)
    return reports


def run_agent_cycle(
    codebase: Path,
    index: int,
    feature: str,
    slug: str,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    analysis = evaluate_attack_surface(codebase, feature)
    report_sections = build_agent_report_sections(codebase, index, feature, analysis)
    paths = write_agent_iteration_notes(codebase, index, feature, slug, report_sections)
    return report_sections, paths


RISK_SIGNALS: List[tuple[str, List[str]]] = [
    ("auth/session drift", ["auth", "authorization", "session", "role", "permission"]),
    ("input validation gaps", ["payload", "body", "query", "path", "request", "input", "validation"]),
    ("file/output risk", ["file", "path", "write_text", "open(", "filesystem", "export"]),
    ("external integration exposure", ["httpx", "requests", "fetch", "callback", "webhook", "remote", "url"]),
    ("secret handling risk", ["secret", "token", "password", "credential", "key", "env"]),
]

RISK_EXPLANATIONS: Dict[str, str] = {
    "auth/session drift": "Without consistent auth checks, privileged actions may be available to the wrong users.",
    "input validation gaps": "Unvalidated input is a common way to inject bad data, trigger errors, or bypass business rules.",
    "file/output risk": "Weak file/output handling can leak data, overwrite important files, or expose local paths.",
    "external integration exposure": "Calls to remote systems can become SSRF paths, callback abuse, or data exfiltration channels.",
    "secret handling risk": "Secrets in code/config create high-impact leaks if files, logs, or repos are shared.",
}

RISK_ACTIONS: Dict[str, str] = {
    "auth/session drift": "Check auth middleware and every write endpoint before adding new features.",
    "input validation gaps": "Add strict validators and canonicalize all incoming IDs/IDs, body fields, query params, and payload types.",
    "file/output risk": "Validate file paths, enforce allow-lists, and lock down output targets before introducing file writes.",
    "external integration exposure": "Whitelist outbound destinations, sanitize callback targets, and set clear request timeouts.",
    "secret handling risk": "Move secrets to a secret store, remove inline values from configs, and rotate exposed keys.",
}


def build_simulation_insights(manifest: Dict[str, object], checkpoints: List[CheckpointRecord]) -> Dict[str, object]:
    requested = cast(List[str], manifest.get("features_requested", []))
    status = str(manifest.get("status", "failed"))
    iterations = [item for item in checkpoints if item.iteration > 0]
    simulated = len(iterations)
    failed_iterations = [item for item in iterations if item.status == "failed"]
    successful_iterations = [item for item in iterations if item.status == "ok"]

    source = str(manifest.get("source", "")).replace("\\", "/")
    source_name = Path(source).name or "this repository"
    codebase_copy = str(manifest.get("codebase_copy", "{run}/codebase")).replace("\\", "/")

    all_report_text: List[str] = []
    file_hit_counts: Dict[str, int] = defaultdict(int)
    for item in iterations:
        all_report_text.extend(
            [
                item.red_team_report,
                item.blue_team_report,
                item.refactorer_report,
                item.historian_report,
            ]
        )
        for file_path in item.files_changed:
            file_hit_counts[file_path] += 1

    hotspots = sorted(file_hit_counts.items(), key=lambda item: (-item[1], item[0]))
    hotspot_lines = [f"{file_path} ({count}x)" for file_path, count in hotspots[:3]]

    joined_reports = "\n".join(all_report_text).lower()

    risk_counts: List[tuple[str, int]] = []
    for label, terms in RISK_SIGNALS:
        count = 0
        for term in terms:
            count += joined_reports.count(term)
        if count > 0:
            risk_counts.append((label, count))
    risk_counts = sorted(risk_counts, key=lambda item: item[1], reverse=True)
    iteration_success_rate = 0.0 if simulated == 0 else (len(successful_iterations) / simulated * 100)
    latest_request = requested[simulated] if simulated < len(requested) else "next planned feature"

    return {
        "requested": requested,
        "status": status,
        "iterations": iterations,
        "simulated": simulated,
        "failed_iterations": failed_iterations,
        "successful_iterations": successful_iterations,
        "source_name": source_name,
        "codebase_copy": codebase_copy,
        "risk_counts": risk_counts,
        "hotspot_lines": hotspot_lines,
        "iteration_success_rate": iteration_success_rate,
        "latest_request": latest_request,
    }


def _risk_priority_label(score: int) -> str:
    if score >= 50:
        return "High"
    if score >= 20:
        return "Medium"
    return "Watch"


def _format_risk_label(label: str) -> str:
    return "/".join(part.strip().title() for part in label.split("/"))


def build_reader_pointers(
    manifest: Dict[str, object],
    checkpoints: List[CheckpointRecord],
    pre_work: bool = False,
    insights: Dict[str, object] | None = None,
) -> List[str]:
    data = insights or build_simulation_insights(manifest, checkpoints)
    requested = cast(List[str], data["requested"])
    status = cast(str, data["status"])
    iterations = cast(List[CheckpointRecord], data["iterations"])
    simulated = cast(int, data["simulated"])
    failed_iterations = cast(List[CheckpointRecord], data["failed_iterations"])
    successful_iterations = cast(List[CheckpointRecord], data["successful_iterations"])
    source_name = cast(str, data["source_name"])
    codebase_copy = cast(str, data["codebase_copy"])
    risk_counts = cast(List[tuple[str, int]], data["risk_counts"])
    hotspot_lines = cast(List[str], data["hotspot_lines"])
    iteration_success_rate = cast(float, data["iteration_success_rate"])
    latest_request = cast(str, data["latest_request"])

    top_risks = [f"{label} ({count} signal{'s' if count != 1 else ''})" for label, count in risk_counts[:3]]
    top_risk_labels = {label for label, _count in risk_counts[:3]}

    pointers: List[str] = []
    if pre_work:
        pointers.append(
            f"For `{source_name}`, this is the working baseline before feature {simulated + 1}."
        )
        pointers.append(
            "Start with `run_manifest.json`, then `checkpoints/000.json`, then the last successful checkpoint."
        )
        pointers.append(
            "Before coding, open `codebase/README*` and the main route/data files so you know how requests flow."
        )
        pointers.append(
            f"The simulation finished {simulated} of {len(requested)} planned features ({iteration_success_rate:.0f}% success)."
        )
        if successful_iterations:
            pointers.append(f"Use `{successful_iterations[-1].tag}` as the last good checkpoint.")

    if status != "completed" and simulated < len(requested):
        pointers.append(f"Run stopped early at `{latest_request}`. Fix or review this gap before adding related features.")
    if failed_iterations:
        failed_names = ", ".join(item.feature for item in failed_iterations)
        pointers.append(f"Recent failures: {failed_names}. Check these areas first in the next round.")
    if top_risks:
        pointers.append("Main issues the simulation repeated: " + ", ".join(top_risks) + ".")
    if hotspot_lines:
        pointers.append("Files touched the most (good places to review): " + ", ".join(f"`{line}`" for line in hotspot_lines) + ".")
    else:
        pointers.append("No single file was repeatedly changed across successful runs.")

    top_risk_labels = {item.split(" (")[0] for item in top_risks}
    if (
        "auth/session drift" in top_risk_labels
        or "secret handling risk" in top_risk_labels
        or "input validation gaps" in top_risk_labels
    ):
        pointers.append(
            "Priority now: review auth/session checks, input validation, and secret handling before adding non-security features."
        )
    if "file/output risk" in top_risk_labels:
        pointers.append(
            "Defer file writes or external callbacks until path and ownership checks are in place."
        )
    pointers.append(
        f"Use `{codebase_copy}/.simulation/iterations/` and `{codebase_copy}/simulated_features/` as a trend log to keep new feature scope aligned with what was already explored."
    )
    pointers.append(
        "Keep together: `simulation_report.md`, `run_manifest.json`, `checkpoints/*.json`, and `.simulation/` logs for handoff."
    )
    if pre_work:
        pointers.append("Before editing, compare your planned file list with hotspot files to avoid redoing old fixes.")

    return pointers


def write_markdown_report(run_dir: Path, manifest: Dict[str, object], checkpoints: List[CheckpointRecord]) -> Path:
    report_path = run_dir / "simulation_report.md"
    lines: List[str] = []

    def status_emoji(state: str) -> str:
        if state == "ok":
            return "✅"
        if state == "failed":
            return "❌"
        return "ℹ️"

    lines.append("# Simulation Report")
    lines.append("")
    lines.append("This report is written for reviewers who are new to this project. It explains what happened each round in simple language, while still keeping technical notes for engineering follow-up.")
    lines.append("")

    insights = build_simulation_insights(manifest, checkpoints)
    pre_work_pointers = build_reader_pointers(manifest, checkpoints, pre_work=True, insights=insights)
    post_work_pointers = build_reader_pointers(manifest, checkpoints, pre_work=False, insights=insights)

    requested = cast(List[str], insights["requested"])
    iterations = cast(List[CheckpointRecord], insights["iterations"])
    simulated = cast(int, insights["simulated"])
    failed_iterations = cast(List[CheckpointRecord], insights["failed_iterations"])
    successful_iterations = cast(List[CheckpointRecord], insights["successful_iterations"])
    iteration_success_rate = cast(float, insights["iteration_success_rate"])
    risk_counts = cast(List[tuple[str, int]], insights["risk_counts"])
    hotspot_lines = cast(List[str], insights["hotspot_lines"])

    lines.append("## Key repo insights for the next feature")
    lines.append("")
    lines.append("### Snapshot")
    lines.append(f"- Planned features: {len(requested)}")
    lines.append(f"- Features completed in this run: {simulated}")
    lines.append(f"- Iteration success rate: {iteration_success_rate:.0f}%")
    if successful_iterations:
        lines.append(f"- Last stable checkpoint: `{successful_iterations[-1].tag}`")
    if failed_iterations:
        lines.append(f"- Open failures to re-check: {len(failed_iterations)}")
    lines.append("")

    lines.append("### Priority now")
    if risk_counts:
        top_risk_names = [label for label, _ in risk_counts[:3]]
        top_risk_badges = [
            f"{_format_risk_label(label)} ({count} signal{'s' if count != 1 else ''})"
            for label, count in risk_counts[:3]
        ]
        lines.append("- Main issues the simulation repeated: " + ", ".join(top_risk_badges) + ".")
        lines.append("")
        if any(
            label in top_risk_names
            for label in ["auth/session drift", "input validation gaps", "secret handling risk"]
        ):
            lines.append(
                "- Priority now: review auth/session checks, input validation, and secret handling before adding non-security features."
            )
        lines.append("")
        lines.append("### High-frequency risk themes")
        lines.append("")
        lines.append("| Risk area | Signals | Priority | Why this kept coming up | Suggested action |")
        lines.append("| --- | --- | --- | --- | --- |")
        for label, score in risk_counts[:3]:
            lines.append(
                "| "
                f"{_format_risk_label(label)} | "
                f"{score} | "
                f"{_risk_priority_label(score)} | "
                f"{RISK_EXPLANATIONS.get(label, 'Keep monitoring this area.')} | "
                f"{RISK_ACTIONS.get(label, 'Add focused checks before the next feature.')}"
                " |"
            )
        lines.append("")
        lines.append("### Recommended checks before the next feature")
        for label, _ in risk_counts[:3]:
            action = RISK_ACTIONS.get(label)
            if action:
                lines.append(f"- {action}")
        lines.append("")
    else:
        lines.append("No clear repeated risk themes were detected.")
        lines.append("")
        lines.append("### Recommended checks before the next feature")
        for pointer in [
            "Start with auth/session gates around every state-changing route.",
            "Run through request input validation for both public and internal entry points.",
            "Verify secrets are not stored in source files or printed in logs.",
        ]:
            lines.append(f"- {pointer}")
        lines.append("")

    lines.append("### Files that were touched most")
    if hotspot_lines:
        lines.append("- " + "\n- ".join(f"`{line}`" for line in hotspot_lines))
    else:
        lines.append("- No single file was repeatedly changed across successful iterations.")
    lines.append("")

    lines.append("### Quick pre-read list")
    for pointer in pre_work_pointers:
        lines.append(f"- {pointer}")
    lines.append("")

    run_status = "✅ Completed" if manifest["status"] == "completed" else "❌ Ended early"
    requested = cast(List[str], manifest["features_requested"])
    weeks_per_iteration = int(manifest.get("weeks_per_iteration", 2))
    simulation_start = datetime.fromisoformat(
        str(manifest.get("simulation_start_iso", manifest["created_at_utc"])).replace("Z", "+00:00")
    )

    lines.append("## Run summary")
    lines.append("")
    lines.append(f"- Overall result: **{run_status}**")
    lines.append(f"- Total requested features: **{len(requested)}**")
    lines.append(f"- Features actually run: **{manifest['features_simulated']}**")
    lines.append(f"- Run period: **{manifest.get('simulation_weeks', '?')} weeks**")
    lines.append(f"- Pace: **{weeks_per_iteration} weeks per iteration**")
    lines.append(f"- Source code used: `{manifest['source']}`")
    lines.append(f"- Generated in: `{manifest['run_dir']}`")
    lines.append(f"- Created: {manifest['created_at_utc']}")
    if manifest.get("agent_context"):
        lines.append(f"- Agent context: `{manifest['agent_context']}`")
    lines.append("")

    lines.append("## What this means")
    lines.append("")
    lines.append("- The project was copied into a sandbox before making any changes.")
    lines.append("- Each iteration adds one requested feature and then runs the chosen validation command.")
    lines.append("- After each iteration, simulated \"security agents\" write short findings (red, blue, refactor, historian).")
    lines.append("- This report keeps both a simple view and the technical notes below.")
    lines.append("")

    lines.append("## Iteration timeline (plain English)")
    lines.append("")
    timeline_entries = [checkpoint for checkpoint in checkpoints if checkpoint.iteration > 0]
    for idx, checkpoint in enumerate(timeline_entries, start=1):
        if idx > 1:
            lines.append("")
            lines.append("---")
            lines.append("")

        start = simulation_start + timedelta(weeks=(checkpoint.iteration - 1) * weeks_per_iteration)
        end = start + timedelta(weeks=weeks_per_iteration)
        icon = status_emoji(checkpoint.status)
        lines.append(f"- {icon} **Iteration {checkpoint.iteration:03d}** (`{checkpoint.tag}`)")
        lines.append(f"  - Feature goal: {checkpoint.feature}")
        lines.append(f"  - Window: {start.date()} → {end.date()}")
        lines.append(f"  - Result: {checkpoint.status}")
        if checkpoint.notes:
            lines.append(f"  - Notes: {checkpoint.notes}")
        lines.append(f"  - Changed files: {len(checkpoint.files_changed)}")
    lines.append("")

    lines.append("## Detailed iteration log")
    lines.append("")
    detailed_entries = [checkpoint for checkpoint in checkpoints if checkpoint.iteration > 0]
    for idx, checkpoint in enumerate(detailed_entries, start=1):
        if idx > 1:
            lines.append("")
            lines.append("---")
            lines.append("")

        start = simulation_start + timedelta(weeks=(checkpoint.iteration - 1) * weeks_per_iteration)
        end = start + timedelta(weeks=weeks_per_iteration)

        lines.append(f"### {checkpoint.tag} (Iteration {checkpoint.iteration:03d})")
        lines.append(f"**Goal:** {checkpoint.feature}")
        lines.append(f"**Window:** {start.date()} → {end.date()}")
        lines.append(f"**Status:** {status_emoji(checkpoint.status)} {checkpoint.status}")
        lines.append(f"**Commit:** `{checkpoint.commit}`")
        lines.append(f"**Timestamp:** {checkpoint.timestamp_utc}")
        lines.append(f"**Notes:** {checkpoint.notes or 'No notes recorded.'}")
        lines.append("")
        lines.append("### Files changed")
        lines.append("")
        lines.append(f"- Total: {len(checkpoint.files_changed)}")
        if checkpoint.files_changed:
            lines.append("- " + "\n- ".join(checkpoint.files_changed))
        else:
            lines.append("- (none)")
        lines.append("")

        lines.append("### Red Team (what could be attacked)")
        if checkpoint.red_team_report:
            lines.append(checkpoint.red_team_report)
        else:
            lines.append("No red-team report was generated for this iteration.")
        lines.append("")

        lines.append("### Blue Team (how we would defend)")
        if checkpoint.blue_team_report:
            lines.append(checkpoint.blue_team_report)
        else:
            lines.append("No blue-team report was generated for this iteration.")
        lines.append("")

        lines.append("### Refactorer (maintainability recommendations)")
        if checkpoint.refactorer_report:
            lines.append(checkpoint.refactorer_report)
        else:
            lines.append("No refactorer report was generated for this iteration.")
        lines.append("")

        lines.append("### Historian (how this might evolve)")
        if checkpoint.historian_report:
            lines.append(checkpoint.historian_report)
        else:
            lines.append("No historian report was generated for this iteration.")
        lines.append("")

    lines.append("## What to do next")
    lines.append("")
    for pointer in post_work_pointers:
        lines.append(f"- {pointer}")
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def write_iteration_artifacts(
    codebase: Path,
    index: int,
    feature: str,
    slug: str,
    extension: str,
    status: str,
    notes: str,
) -> Path:
    iterations_dir = codebase / ".simulation" / "iterations"
    iterations_dir.mkdir(parents=True, exist_ok=True)

    iteration_note_rel = Path(".simulation") / "iterations" / f"{index:03d}-{slug}.md"
    iteration_note_path = codebase / iteration_note_rel
    iteration_note_path.write_text(
        "\n".join(
            [
                f"# Iteration {index:03d} - {feature}",
                "",
                f"Timestamp (UTC): {utc_now_iso()}",
                f"Status: {status}",
                "",
                "## Summary",
                "- This iteration simulates a feature improvement step.",
                "- Replace placeholder artifacts with real implementation logic.",
                "",
                "## Notes",
                f"- {notes or 'No additional notes.'}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    artifact_dir = codebase / "simulated_features"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_rel = Path("simulated_features") / f"{index:03d}_{slug}{extension}"
    artifact_path = codebase / artifact_rel
    artifact_path.write_text(
        build_stub_content(extension, index, feature, slug),
        encoding="utf-8",
    )

    append_changelog(codebase, index, feature, artifact_rel, status, notes)
    return artifact_rel


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def ensure_fastapi_imports(main_text: str, module: str, symbols: Sequence[str]) -> str:
    prefix = f"from {module} import "
    lines = main_text.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith(prefix):
            continue
        existing = [part.strip() for part in line[len(prefix) :].split(",") if part.strip()]
        for symbol in symbols:
            if symbol not in existing:
                existing.append(symbol)
        lines[i] = f"{prefix}{', '.join(existing)}"
        return "\n".join(lines) + ("\n" if main_text.endswith("\n") else "")
    return main_text


def apply_feature_specific_refactors(main_text: str, feature: str) -> str:
    feature_lower = feature.lower()

    if "different" in feature_lower and "users" in feature_lower and "task" in feature_lower:
        if '@app.get("/api/users/{owner_id}/tasks")' not in main_text:
            marker = '    @app.get("/api/tasks/{task_id}")\n'
            route = (
                '    @app.get("/api/users/{owner_id}/tasks")\n'
                "    def list_tasks_for_owner(owner_id: str):\n"
                "        return [task.to_dict() for task in store.list() if task.owner_id == owner_id]\n\n"
            )
            main_text = main_text.replace(marker, route + marker, 1)

    if "email" in feature_lower and "completion" in feature_lower and "notification" in feature_lower:
        if "def _notify_task_completion(" not in main_text:
            marker = "    def _attempt_callback(callback_url: str, payload: dict) -> None:\n"
            helper = (
                "    def _notify_task_completion(task_id: int, actor: str, title: str) -> None:\n"
                "        if os.getenv(\"TASK_COMPLETION_NOTIFICATIONS\", \"\").strip().lower() not in {\n"
                '            "1", "true", "yes", "on"\n'
                "        }:\n"
                "            return\n"
                "        recipients = [\n"
                '            item.strip()\n'
                "            for item in os.getenv(\n"
                '                \"TASK_COMPLETION_NOTIFICATION_RECIPIENTS",\n'
                '                \"\"\n'
                "            ).split(\",\")\n"
                "            if item.strip()\n"
                "        ]\n"
                "        if not recipients:\n"
                "            return\n"
                "        payload = {\n"
                '            "event": "task_completed",\n'
                "            \"task_id\": task_id,\n"
                "            \"actor\": actor,\n"
                "            \"title\": title,\n"
                "            \"recipients\": recipients,\n"
                "        }\n"
                "        try:\n"
                "            with (store.storage_path.parent / \"task-completion-notifications.log\").open(\n"
                '                "a", encoding=\"utf-8\"\n'
                "            ) as handle:\n"
                "                handle.write(json.dumps(payload, sort_keys=True) + \"\\n\")\n"
                "        except OSError:\n"
                "            return\n\n"
            )
            main_text = main_text.replace(marker, helper + marker, 1)

        if '@app.post("/api/tasks/{task_id}/complete")' not in main_text:
            marker = '    @app.delete("/api/tasks/{task_id}")\n'
            route = (
                '    @app.post("/api/tasks/{task_id}/complete")\n'
                "    def complete_task(task_id: int, x_actor: str = Header(default=\"anonymous\")):\n"
                "        actor = _current_actor(x_actor)\n"
                "        try:\n"
                "            task = store.get(task_id)\n"
                "            if task.owner_id and task.owner_id != actor:\n"
                '                raise HTTPException(status_code=403, detail="not allowed to complete this task")\n'
                "            was_completed = task.completed\n"
                "            updated = store.patch(task_id, TaskUpdate(completed=True))\n"
                "            if not was_completed and updated.completed:\n"
                "                _notify_task_completion(task_id=updated.id, actor=actor, title=updated.title)\n"
                "            return updated.to_dict()\n"
                "        except ValueError as error:\n"
                "            raise HTTPException(status_code=400, detail=str(error))\n"
                "        except KeyError as error:\n"
                "            raise HTTPException(status_code=404, detail=str(error))\n\n"
            )
            main_text = main_text.replace(marker, route + marker, 1)

    return main_text


def apply_clone_refactor(main_text: str, iteration: int) -> str:
    if iteration < 1:
        return main_text

    if iteration == 1:
        main_text = ensure_fastapi_imports(main_text, "fastapi", ["Depends", "Header"])
        if "def require_session(" not in main_text:
            main_text = main_text.replace(
                '    app.mount("/static", StaticFiles(directory=static_dir), name="static")\n',
                '    app.mount("/static", StaticFiles(directory=static_dir), name="static")\n'
                "\n"
                "    def require_session(x_session_token: str | None = Header(default=None)) -> None:\n"
                "        token = (x_session_token or \"\").strip()\n"
                "        if token and len(token) < 8:\n"
                "            raise HTTPException(status_code=400, detail=\"invalid session token\")\n"
                "\n",
            )
        main_text = main_text.replace(
            '@app.post("/api/tasks")',
            '@app.post("/api/tasks", dependencies=[Depends(require_session)])',
            1,
        )
        main_text = main_text.replace(
            '@app.patch("/api/tasks/{task_id}")',
            '@app.patch("/api/tasks/{task_id}", dependencies=[Depends(require_session)])',
            1,
        )
        main_text = main_text.replace(
            '@app.delete("/api/tasks/{task_id}")',
            '@app.delete("/api/tasks/{task_id}", dependencies=[Depends(require_session)])',
            1,
        )

    if iteration >= 2:
        main_text = ensure_fastapi_imports(main_text, "fastapi", ["Request"])
        if '@app.middleware("http")' not in main_text:
            marker = '    @app.get("/", include_in_schema=False)\n'
            block = (
                '    @app.middleware("http")\n'
                "    async def security_headers(request: Request, call_next):\n"
                "        response = await call_next(request)\n"
                '        response.headers["X-Content-Type-Options"] = "nosniff"\n'
                '        response.headers["X-Frame-Options"] = "DENY"\n'
                "        return response\n\n"
            )
            if marker in main_text:
                main_text = main_text.replace(marker, block + marker, 1)

    if iteration >= 3:
        main_text = ensure_fastapi_imports(main_text, "fastapi", ["Body"])
        if "_normalize_title(" not in main_text:
            marker = "    def index() -> FileResponse:\n        return FileResponse(static_dir / \"index.html\")\n\n"
            if marker in main_text:
                main_text = main_text.replace(
                    marker,
                    "    def index() -> FileResponse:\n        return FileResponse(static_dir / \"index.html\")\n\n"
                    "    def _normalize_title(raw_title: str) -> str:\n"
                    '        title = (raw_title or "").strip()\n'
                    "        if not title:\n"
                    '            raise HTTPException(status_code=400, detail="title cannot be empty")\n'
                    "        if len(title) > 120:\n"
                    '            raise HTTPException(status_code=400, detail="title too long")\n'
                    "        return title\n\n",
                    1,
                )
            if "def create_task(payload: TaskCreate = Body(" not in main_text:
                main_text = main_text.replace(
                    "    def create_task(payload: TaskCreate):",
                    "    def create_task(payload: TaskCreate = Body(...)):",
                    1,
                )
                main_text = main_text.replace(
                    "    def create_task(payload: TaskCreate = Body(...)):\n        try:\n",
                    "    def create_task(payload: TaskCreate = Body(...)):\n        "
                    "payload.title = _normalize_title(payload.title)\n        try:\n",
                    1,
                )
            if "def patch_task(task_id: int, payload: TaskUpdate = Body(" not in main_text:
                main_text = main_text.replace(
                    "    def patch_task(task_id: int, payload: TaskUpdate):",
                    "    def patch_task(task_id: int, payload: TaskUpdate = Body(...)):",
                    1,
                )
                main_text = main_text.replace(
                    "    def patch_task(task_id: int, payload: TaskUpdate = Body(...)):\n        try:\n",
                    "    def patch_task(task_id: int, payload: TaskUpdate = Body(...)):\n"
                    "        if payload.title is not None:\n"
                    "            payload.title = _normalize_title(payload.title)\n        try:\n",
                    1,
                )

    return main_text


def apply_iterative_refactors(codebase: Path, iteration: int, feature: str) -> str:
    main_file = codebase / "src" / "task_service" / "main.py"
    if not main_file.exists():
        return "No target app file found for automated refactor."

    original = main_file.read_text(encoding="utf-8").replace("\r\n", "\n")
    modified = apply_clone_refactor(original, iteration)
    modified = apply_feature_specific_refactors(modified, feature)
    if modified == original:
        return "No additional defender refactor needed."
    main_file.write_text(modified, encoding="utf-8")
    return f"Applied automated refactor pass for iteration {iteration}."


def init_git_repo(codebase: Path) -> None:
    run_command(["git", "init"], cwd=codebase)
    run_command(["git", "config", "core.longpaths", "true"], cwd=codebase)
    run_command(["git", "config", "user.name", "Simulation Agent"], cwd=codebase)
    run_command(["git", "config", "user.email", "simulation-agent@example.com"], cwd=codebase)


def create_checkpoint(codebase: Path, message: str, tag: str, allow_empty: bool = True) -> Tuple[str, List[str]]:
    run_command(["git", "add", "-A"], cwd=codebase)

    commit_args = ["git", "commit", "-m", message]
    if allow_empty:
        commit_args.insert(2, "--allow-empty")
    run_command(commit_args, cwd=codebase)

    commit_sha = run_command(["git", "rev-parse", "HEAD"], cwd=codebase).stdout.strip()
    changed = run_command(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
        cwd=codebase,
    ).stdout.splitlines()

    run_command(["git", "tag", "-f", tag], cwd=codebase)
    changed_files = [line.strip() for line in changed if line.strip()]
    return commit_sha, changed_files


def copy_source(source: Path, destination: Path, excludes: List[str]) -> None:
    ignore_fn = shutil.ignore_patterns(*excludes)
    shutil.copytree(source, destination, ignore=ignore_fn)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulate iterative feature improvements with checkpoints on a copied codebase.",
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--source", help="Path to the local source codebase.")
    source_group.add_argument("--source-url", help="Git URL for remote source codebase to clone.")
    parser.add_argument(
        "--source-ref",
        default=None,
        help="For source-url, checkout this branch, tag, or commit (defaults to repo default).",
    )
    parser.add_argument(
        "--source-subdir",
        default=None,
        help="For source-url, optional subdirectory inside the cloned repo to simulate.",
    )
    parser.add_argument(
        "--workspace",
        default=".simulations",
        help="Directory where simulation runs are created (default: .simulations).",
    )
    parser.add_argument("--run-name", default=None, help="Optional simulation run folder name.")
    parser.add_argument(
        "--feature",
        dest="features",
        action="append",
        default=[],
        help="Feature description. Repeat for multiple features.",
    )
    parser.add_argument(
        "--features-file",
        default=None,
        help="Path to a newline-delimited features file. Lines starting with # are ignored.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=9,
        help="Limit the number of features to simulate.",
    )
    parser.add_argument(
        "--simulation-weeks",
        type=int,
        default=None,
        help="Total simulation period in weeks. Defaults to 2 weeks per iteration.",
    )
    parser.add_argument(
        "--weeks-per-iteration",
        type=int,
        default=2,
        help="How many weeks each iteration represents. Default: 2.",
    )
    parser.add_argument(
        "--agent-context",
        default=DEFAULT_AGENT_CONTEXT_FILE,
        help=(
            "Markdown file path describing multi-agent roles and focus. "
            f"Defaults to {DEFAULT_AGENT_CONTEXT_FILE}."
        ),
    )
    parser.add_argument(
        "--deps-command",
        default=None,
        help="Optional shell command to bootstrap project dependencies before iteration commands.",
    )
    parser.add_argument(
        "--iteration-command",
        default=None,
        help=(
            "Optional shell command run each iteration inside the copied codebase. "
            "Supports {feature}, {index}, and {slug} placeholders."
        ),
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Continue remaining iterations even if one iteration command fails.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Additional copy exclude patterns. Repeat flag for multiple values.",
    )
    return parser.parse_args(argv)


def _build_default_deps_command(codebase: Path) -> Optional[str]:
    # Python
    requirements = codebase / "requirements.txt"
    pyproject = codebase / "pyproject.toml"
    setup_cfg = codebase / "setup.cfg"
    setup_py = codebase / "setup.py"
    if requirements.exists():
        return "python -m pip install -r requirements.txt --disable-pip-version-check --no-input"
    if pyproject.exists() or setup_cfg.exists() or setup_py.exists():
        return "python -m pip install -e . --disable-pip-version-check --no-input"

    # Node / TS / JS
    package_json = codebase / "package.json"
    if package_json.exists():
        if (codebase / "package-lock.json").exists():
            return "npm ci --no-audit --no-fund"
        if (codebase / "pnpm-lock.yaml").exists():
            return "pnpm install --frozen-lockfile"
        if (codebase / "yarn.lock").exists():
            return "yarn install --frozen-lockfile"
        return "npm install --no-audit --no-fund"

    # Go
    if (codebase / "go.mod").exists():
        return "go mod download"

    # Rust
    if (codebase / "Cargo.toml").exists():
        return "cargo fetch"

    # Java / JVM
    if (codebase / "pom.xml").exists():
        return "mvn -q -DskipTests package -DskipITs"
    if (codebase / "build.gradle").exists() or (codebase / "build.gradle.kts").exists():
        return "gradle --no-daemon build -x test"

    # .NET
    if any(codebase.glob("*.csproj")):
        return "dotnet restore"

    # Ruby
    if (codebase / "Gemfile").exists():
        return "bundle install"

    # PHP
    if (codebase / "composer.json").exists():
        return "composer install --no-interaction --no-progress --prefer-dist"

    return None


def configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    configure_console_encoding()
    args = parse_args(argv)

    workspace = Path(args.workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    run_name = _derive_run_name(args.run_name, args.source_url, args.source)
    run_dir = workspace / run_name
    if run_dir.exists():
        print(f"Error: run directory already exists: {run_dir}", file=sys.stderr)
        return 2

    try:
        if args.source_url:
            source = prepare_remote_source(
                repo_url=args.source_url,
                workspace=workspace,
                ref=args.source_ref,
                subdir=args.source_subdir,
                run_name=run_name,
            )
        else:
            source = Path(cast(str, args.source)).expanduser().resolve()
            if not source.exists() or not source.is_dir():
                print(f"Error: source path is not a directory: {source}", file=sys.stderr)
                return 2
    except (RuntimeError, ValueError) as error:
        print(f"Error: failed to resolve source: {error}", file=sys.stderr)
        return 2

    features_file: Optional[Path] = None
    generated_features: Optional[List[str]] = None
    requested_features = list(args.features)
    if args.features_file:
        requested = Path(args.features_file).expanduser()
        if requested.exists():
            features_file = requested
        else:
            candidates = [source / requested, source / requested.name, source / "features.example.txt"]
            for candidate in candidates:
                if candidate.exists():
                    features_file = candidate
                    break
            if features_file is None and not requested_features:
                generated_features = infer_features_from_codebase(source)

    if features_file is None and not requested_features and generated_features is None:
        generated_features = infer_features_from_codebase(source)

    try:
        features = load_features(requested_features, features_file)
    except ValueError as error:
        if generated_features is not None and not requested_features:
            features = generated_features
        else:
            print(f"Error: {error}", file=sys.stderr)
            return 2

    if not features:
        generated_features = generated_features or infer_features_from_codebase(source)
        features = generated_features or []

    if not features:
        print("Error: no features provided. Use --feature, or --features-file, or allow auto-generation.", file=sys.stderr)
        return 2

    if args.simulation_weeks is not None and args.simulation_weeks < 1:
        print("Error: --simulation-weeks must be >= 1.", file=sys.stderr)
        return 2
    if args.weeks_per_iteration < 1:
        print("Error: --weeks-per-iteration must be >= 1.", file=sys.stderr)
        return 2
    if args.max_iterations < 1:
        print("Error: --max-iterations must be >= 1.", file=sys.stderr)
        return 2

    # Keep cadence fixed for this simulation profile.
    args.weeks_per_iteration = 2

    if args.simulation_weeks is not None:
        args.max_iterations = (args.simulation_weeks + args.weeks_per_iteration - 1) // args.weeks_per_iteration
    args.max_iterations = min(args.max_iterations, 9)
    features = features[: args.max_iterations]

    if args.agent_context:
        agent_context_path = Path(args.agent_context).expanduser().resolve()
        if not agent_context_path.exists():
            print(f"Error: agent context file does not exist: {agent_context_path}", file=sys.stderr)
            return 2
    else:
        agent_context_path = None

    codebase_copy = run_dir / "codebase"
    checkpoints_dir = run_dir / "checkpoints"

    run_dir.mkdir(parents=True, exist_ok=False)

    excludes = list(dict.fromkeys(DEFAULT_EXCLUDES + list(args.exclude)))
    if is_subpath(run_dir, source):
        excludes.append(workspace.name)
        excludes.append(run_dir.name)
        excludes = list(dict.fromkeys(excludes))

    try:
        run_command(["git", "--version"], cwd=source)
    except RuntimeError as error:
        print(f"Error: git is required but unavailable: {error}", file=sys.stderr)
        return 2

    try:
        copy_source(source, codebase_copy, excludes)
    except Exception as error:
        print(f"Error: failed to copy source into simulation workspace: {error}", file=sys.stderr)
        return 1

    if features_file is None and generated_features:
        generated_features_path = codebase_copy / "features.example.txt"
        try:
            generated_features_path.write_text(
                "\n".join(generated_features) + "\n",
                encoding="utf-8",
            )
        except Exception as error:
            print(f"Error: failed to write generated features list: {error}", file=sys.stderr)
            return 1

    context_snapshot = run_dir / "agent_context_snapshot.md"
    context_snapshot_value = ""
    if args.agent_context:
        context_snapshot.write_text(
            cast(Path, agent_context_path).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        context_snapshot_value = str(context_snapshot)

    try:
        init_git_repo(codebase_copy)
    except RuntimeError as error:
        print(f"Error: failed to initialize git checkpoint repo: {error}", file=sys.stderr)
        return 1

    checkpoints: List[CheckpointRecord] = []

    try:
        baseline_sha, baseline_files = create_checkpoint(
            codebase_copy,
            "checkpoint 000: baseline copy",
            "checkpoint-000",
            allow_empty=True,
        )
    except RuntimeError as error:
        print(f"Error: failed to create baseline checkpoint: {error}", file=sys.stderr)
        return 1

    baseline_record = CheckpointRecord(
        iteration=0,
        tag="checkpoint-000",
        feature="Baseline copy",
        commit=baseline_sha,
        timestamp_utc=utc_now_iso(),
        status="ok",
        files_changed=baseline_files,
        notes="Initial isolated snapshot of source codebase.",
    )
    checkpoints.append(baseline_record)
    write_json(checkpoints_dir / "000.json", asdict(baseline_record))

    preferred_extension = detect_preferred_extension(codebase_copy)
    run_failed = False

    simulation_start = datetime.now(timezone.utc)

    deps_command = args.deps_command
    if deps_command is None:
        deps_command = _build_default_deps_command(source)

    if deps_command:
        try:
            run_shell_command(deps_command, cwd=codebase_copy)
        except Exception as error:
            print(f"Error: failed to bootstrap dependencies: {error}", file=sys.stderr)
            return 1

    for index, feature in enumerate(features, start=1):
        slug = compact_slug(sanitize_slug(feature), index=index, max_len=28)
        status = "ok"
        notes = "Simulated feature artifact generated."
        agent_reports: Dict[str, str] = {
            "red_team_report": "",
            "blue_team_report": "",
            "refactorer_report": "",
            "historian_report": "",
        }
        agent_paths: Dict[str, str] = {}

        try:
            write_iteration_artifacts(
                codebase_copy,
                index,
                feature,
                slug,
                preferred_extension,
                "planned",
                notes,
            )

            if args.iteration_command:
                prepared_iteration_command = normalize_iteration_command(
                    args.iteration_command.format(feature=feature, index=index, slug=slug),
                    codebase_copy,
                )
                stdout, stderr = run_shell_command(
                    prepared_iteration_command,
                    cwd=codebase_copy,
                )
                log_path = codebase_copy / ".simulation" / "iterations" / f"{index:03d}-{slug}.command.log"
                log_path.write_text(
                    "\n".join(
                        [
                            f"Command: {prepared_iteration_command}",
                            "",
                            "--- STDOUT ---",
                            stdout.strip(),
                            "",
                            "--- STDERR ---",
                            stderr.strip(),
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
                notes = "Simulated feature artifact generated; iteration command executed."

            refactor_note = apply_iterative_refactors(codebase_copy, index, feature)
            if refactor_note:
                notes = f"Simulated feature artifact generated; agent cycle completed. {refactor_note}"
            agent_reports, agent_paths = run_agent_cycle(codebase_copy, index, feature, slug)
            notes = "Simulated feature artifact generated; agent cycle completed."
            if refactor_note:
                notes = f"{notes} {refactor_note}"

        except Exception as error:
            status = "failed"
            notes = str(error)
            failure_log = codebase_copy / ".simulation" / "iterations" / f"{index:03d}-{slug}.failure.log"
            failure_log.parent.mkdir(parents=True, exist_ok=True)
            failure_log.write_text(f"{error}\n", encoding="utf-8")
            if not args.keep_going:
                run_failed = True

        try:
            checkpoint_sha, changed_files = create_checkpoint(
                codebase_copy,
                f"checkpoint {index:03d}: {feature}",
                f"checkpoint-{index:03d}",
                allow_empty=True,
            )
        except RuntimeError as error:
            print(f"Error: failed to create checkpoint for iteration {index}: {error}", file=sys.stderr)
            return 1

        record = CheckpointRecord(
            iteration=index,
            tag=f"checkpoint-{index:03d}",
            feature=feature,
            commit=checkpoint_sha,
            timestamp_utc=utc_now_iso(),
            status=status,
            files_changed=changed_files,
            notes=notes,
            red_team_report=agent_reports["red_team_report"],
            blue_team_report=agent_reports["blue_team_report"],
            refactorer_report=agent_reports["refactorer_report"],
            historian_report=agent_reports["historian_report"],
        )
        checkpoints.append(record)
        write_json(checkpoints_dir / f"{index:03d}.json", asdict(record))

        if run_failed:
            break

    manifest = {
        "source": str(source),
        "source_type": "git" if args.source_url else "local",
        "source_url": args.source_url or "",
        "source_ref": args.source_ref or "",
        "source_subdir": args.source_subdir or "",
        "workspace": str(workspace),
        "run_dir": str(run_dir),
        "codebase_copy": str(codebase_copy),
        "created_at_utc": utc_now_iso(),
        "simulation_start_iso": simulation_start.isoformat(),
        "simulation_weeks": args.simulation_weeks,
        "weeks_per_iteration": args.weeks_per_iteration,
        "features_requested": features,
        "features_simulated": len(checkpoints) - 1,
        "status": "failed" if run_failed else "completed",
        "agent_context": context_snapshot_value,
        "agent_context_source": str(args.agent_context) if args.agent_context else "",
        "copy_excludes": excludes,
        "checkpoints": [asdict(item) for item in checkpoints],
    }
    summary_payload = build_simulation_insights(manifest, checkpoints)
    pre_work_pointers = build_reader_pointers(manifest, checkpoints, pre_work=True, insights=summary_payload)
    post_work_pointers = build_reader_pointers(manifest, checkpoints, pre_work=False, insights=summary_payload)
    risk_counts = cast(List[tuple[str, int]], summary_payload["risk_counts"])
    hotspot_lines = cast(List[str], summary_payload["hotspot_lines"])
    successful_iterations = cast(List[CheckpointRecord], summary_payload["successful_iterations"])
    status = str(summary_payload["status"])
    simulated = cast(int, summary_payload["simulated"])
    requested = cast(List[str], summary_payload["requested"])
    iteration_success_rate = cast(float, summary_payload["iteration_success_rate"])
    manifest["simulation_summary"] = {
        "status": status,
        "requested_count": len(requested),
        "features_completed": simulated,
        "iteration_success_rate": iteration_success_rate,
        "last_stable_checkpoint": successful_iterations[-1].tag if successful_iterations else "",
        "risk_counts": [[label, count] for label, count in risk_counts],
        "hotspot_lines": hotspot_lines,
        "pre_work_pointers": pre_work_pointers,
        "post_work_pointers": post_work_pointers,
        "feature_snapshot": [
            f"{item.iteration:03d} — {item.feature} ({item.status})" for item in cast(List[CheckpointRecord], summary_payload["iterations"])
        ],
    }

    manifest_path = run_dir / "run_manifest.json"
    write_json(manifest_path, manifest)
    report_path = write_markdown_report(run_dir, manifest, checkpoints)

    print(f"Run directory: {run_dir}")
    print(f"Copied codebase: {codebase_copy}")
    print(f"Manifest: {manifest_path}")
    print(f"Report: {report_path}")
    print("Checkpoints:")
    for item in checkpoints:
        print(
            f"  {item.tag} | {item.commit[:8]} | {item.status} | {item.feature}"
        )

    if run_failed:
        print("Simulation ended early due to iteration failure. Use --keep-going to continue on errors.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())



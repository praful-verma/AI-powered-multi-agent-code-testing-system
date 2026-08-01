from __future__ import annotations

import hashlib
from pathlib import Path

from multiagent_testing.adapters.registry import DEFAULT_REGISTRY
from multiagent_testing.analyzer.call_graph import extract_calls_for_unit
from multiagent_testing.analyzer.dependency_analyzer import analyze_dependencies
from multiagent_testing.analyzer.export_analyzer import extract_exports
from multiagent_testing.analyzer.import_analyzer import extract_imports
from multiagent_testing.analyzer.mock_planner import build_mock_plan
from multiagent_testing.analyzer.models import DependencyNode, RepositoryGraph, SourceFileNode, UnitNode


JS_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
IGNORED_DIRS = {"node_modules", ".git", "dist", "build", "coverage", "generated_tests", "__pycache__"}


def analyze_repository(repo_path: str, stack: str | None = "auto") -> RepositoryGraph:
    root = Path(repo_path).resolve()
    adapter = DEFAULT_REGISTRY.detect(str(root), stack)
    units_by_path = _units_by_path(adapter.discover_units(str(root)))
    graph = RepositoryGraph(root_path=str(root), stack=adapter.name, test_framework=adapter.get_test_framework())

    dependency_index: dict[tuple[str, str], DependencyNode] = {}
    for file_path in _iter_source_files(root):
        rel = file_path.relative_to(root).as_posix()
        text = _read_text(file_path)
        if not text.strip():
            continue

        imports = extract_imports(text, file_path, root)
        exports = extract_exports(text)
        dependencies = analyze_dependencies(text, imports)
        file_units = [_unit_node_from_code_unit(unit) for unit in units_by_path.get(rel, [])]

        for unit in file_units:
            edges = extract_calls_for_unit(unit)
            unit.calls = [edge.callee for edge in edges]
            unit.dependencies = _dependencies_for_unit(unit, dependencies)
            unit.mock_plan = build_mock_plan(unit, dependencies, graph.test_framework)
            graph.call_edges.extend(edges)

        source_file = SourceFileNode(
            path=str(file_path),
            relative_path=rel,
            language=file_path.suffix.lstrip("."),
            stack_area=_classify_stack_area(rel),
            file_role=_classify_file_role(rel, text),
            imports=imports,
            exports=exports,
            dependencies=dependencies,
            units=file_units,
            source_hash=hashlib.sha1(text.encode("utf-8")).hexdigest(),
        )
        graph.files.append(source_file)
        graph.units.extend(file_units)
        for dependency in dependencies:
            key = (dependency.name, dependency.import_path)
            if key not in dependency_index:
                dependency_index[key] = dependency

    graph.dependencies = list(dependency_index.values())
    if not graph.units:
        graph.warnings.append("No testable units were discovered by the selected adapter.")
    return graph


def _iter_source_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in JS_EXTENSIONS:
            continue
        try:
            rel_parts = path.relative_to(root).parts
        except ValueError:
            rel_parts = path.parts
        lower_parts = {part.lower() for part in rel_parts}
        if lower_parts & IGNORED_DIRS:
            continue
        lower_name = path.name.lower()
        if ".generated." in lower_name or ".test." in lower_name or ".spec." in lower_name:
            continue
        yield path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _units_by_path(units) -> dict[str, list]:
    by_path: dict[str, list] = {}
    for unit in units:
        by_path.setdefault(unit.relative_path.replace("\\", "/"), []).append(unit)
    return by_path


def _unit_node_from_code_unit(unit) -> UnitNode:
    return UnitNode(
        id=unit.id,
        file_path=unit.file_path,
        relative_path=unit.relative_path.replace("\\", "/"),
        unit_type=unit.unit_type,
        name=unit.name,
        start_line=unit.start_line,
        end_line=unit.end_line,
        source=unit.source,
        template_kind=_template_kind(unit.unit_type),
        risk_level=_risk_level(unit.unit_type),
    )


def _dependencies_for_unit(unit: UnitNode, dependencies) -> list[str]:
    source = unit.source
    used = []
    for dependency in dependencies:
        if dependency.name in source or dependency.import_path in source:
            used.append(dependency.name)
    return used


def _classify_stack_area(relative_path: str):
    lowered = relative_path.lower()
    if lowered.startswith(("backend/", "server/")) or "/backend/" in lowered or "/server/" in lowered:
        return "backend"
    if lowered.startswith(("frontend/", "client/")) or "/frontend/" in lowered or "/client/" in lowered:
        return "frontend"
    if "/src/" in lowered and any(token in lowered for token in ("component", "hook", "context", "pages")):
        return "frontend"
    return "unknown"


def _classify_file_role(relative_path: str, text: str):
    lowered = relative_path.lower()
    if "controller" in lowered:
        return "controller"
    if "/routes/" in lowered or "routes" in Path(relative_path).stem.lower():
        return "route"
    if "/models/" in lowered or "mongoose.model" in text or "new mongoose.schema" in text.lower():
        return "model"
    if "/middleware/" in lowered:
        return "middleware"
    if "/services/" in lowered:
        return "service"
    if "/context/" in lowered:
        return "context"
    if "/hooks/" in lowered or Path(relative_path).stem.startswith("use"):
        return "hook"
    if "/api" in lowered or Path(relative_path).stem.lower() in {"api", "client", "http"}:
        return "api_helper"
    if relative_path.endswith((".jsx", ".tsx")) or "return (" in text and "<" in text:
        return "component"
    if "/config/" in lowered:
        return "config"
    return "utility"


def _template_kind(unit_type: str) -> str:
    if unit_type in {"route", "component", "model"}:
        return unit_type
    if unit_type in {"function", "controller"}:
        return "controller" if unit_type == "controller" else "function"
    return "function"


def _risk_level(unit_type: str) -> str:
    if unit_type in {"route", "controller", "model"}:
        return "high"
    if unit_type in {"component", "function"}:
        return "medium"
    return "low"

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from multiagent_testing.adapters.registry import DEFAULT_REGISTRY
from multiagent_testing.excel_store import ExcelStore
from multiagent_testing.models import AgentState, TestSpecification
from multiagent_testing.templates import build_test_code



def test_builder_node(state: AgentState) -> AgentState:
    repo_path = state["repo_path"]
    graph = _load_graph(state)
    specifications = _load_specifications(state)
    assertion_blocks = _load_assertion_blocks(state)
    units = _units_by_id(graph)
    output_dir = Path(state.get("output_dir") or "runs").resolve()
    excel_path = Path(state.get("excel_path") or output_dir / "test_cases.xlsx")
    adapter = DEFAULT_REGISTRY.detect(repo_path, state.get("adapter_name") or state.get("stack"))
    store = ExcelStore(excel_path)
    store.ensure_workbook()

    test_number = store.next_test_number()
    rows: list[dict[str, Any]] = []
    for specification in specifications:
        unit = units.get(specification.target_unit_id)
        if not unit:
            continue
        row, test_number = _row_from_specification(
            specification=specification,
            unit=unit,
            repo_path=repo_path,
            test_number=test_number,
            framework=adapter.get_test_framework(),
            assertion_body=(assertion_blocks.get(specification.target_unit_id) or {}).get("body"),
        )
        rows.append(row)

    if state.get("reuse_existing_tests"):
        store.upsert_rows(rows, ["unit_id", "scenario_name"])
    else:
        store.append_rows(rows)
    state["excel_path"] = str(excel_path)
    state["generated_test_count"] = len(rows)
    return state


def _row_from_specification(
    specification: TestSpecification,
    unit: dict[str, Any],
    repo_path: str,
    test_number: int,
    framework: str,
    assertion_body: str | None = None,
) -> tuple[dict[str, Any], int]:
    test_id = f"TC-{test_number:04d}"
    target_file = str(unit.get("relative_path") or "")
    target_path = Path(repo_path) / target_file
    suffix = ".test.jsx" if target_path.suffix.lower() in {".jsx", ".tsx"} else ".test.js"
    test_file = target_path.parent / f"{target_path.stem}.generated.{test_id}_{_safe_filename(specification.scenario_name)}{suffix}"
    test_code = build_test_code(specification, unit, repo_path, str(test_file), framework, assertion_body)
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(test_code, encoding="utf-8")
    row = {
        "test_id": test_id,
        "unit_type": unit.get("unit_type", ""),
        "target_file": target_file,
        "target_function_or_route": unit.get("name", ""),
        "test_description": specification.purpose,
        "test_code": test_code,
        "test_file_path": str(test_file),
        "priority": specification.priority,
        "unit_id": specification.target_unit_id,
        "scenario_name": specification.scenario_name,
        "mock_plan": json.dumps(unit.get("mock_plan") or {}, ensure_ascii=True),
        "validation_status": "Not Run",
        "validation_errors": "",
        "repairs_applied": "",
        "failure_category": "",
        "coverage_percent": "",
        "confidence_score": "",
    }
    return row, test_number + 1


def _load_specifications(state: AgentState) -> list[TestSpecification]:
    plan_path = state.get("test_plan_path")
    if not plan_path:
        return []
    data = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    return [TestSpecification.model_validate(item) for item in data.get("specifications", [])]


def _load_assertion_blocks(state: AgentState) -> dict[str, dict[str, Any]]:
    blocks = state.get("assertion_blocks")
    if isinstance(blocks, dict):
        return {str(key): value for key, value in blocks.items() if isinstance(value, dict)}
    path = state.get("assertion_blocks_path")
    if path and Path(path).exists():
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return {
            str(item.get("target_unit_id") or ""): item
            for item in data.get("assertions", [])
            if isinstance(item, dict)
        }
    return {}


def _load_graph(state: AgentState) -> dict[str, Any]:
    graph = state.get("repository_graph")
    if isinstance(graph, dict):
        return graph
    graph_path = state.get("repository_graph_path")
    if graph_path and Path(graph_path).exists():
        return json.loads(Path(graph_path).read_text(encoding="utf-8"))
    return {}


def _units_by_id(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    units = {}
    for unit in graph.get("units", []) if isinstance(graph, dict) else []:
        if isinstance(unit, dict):
            units[str(unit.get("id") or "")] = unit
    return units


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "scenario").strip("._")
    return cleaned[:80] or "scenario"

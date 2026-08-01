from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from multiagent_testing.models import AgentState, TestSpecification




def test_planner_node(state: AgentState) -> AgentState:
    graph = _load_graph(state)
    specifications = build_deterministic_test_plan(graph)
    output_dir = Path(state.get("output_dir") or "runs").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = output_dir / "test_plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "repository_graph_path": state.get("repository_graph_path", ""),
                "specifications": [spec.model_dump() for spec in specifications],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    state["test_plan_path"] = str(plan_path)
    state["generation_chunk_count"] = 0
    state["generated_test_count"] = len(specifications)
    return state


def build_deterministic_test_plan(repository_graph: dict[str, Any]) -> list[TestSpecification]:
    specifications: list[TestSpecification] = []
    for unit in repository_graph.get("units", []) if isinstance(repository_graph, dict) else []:
        if not isinstance(unit, dict):
            continue
        specifications.append(_specification_for_unit(unit))
    return specifications


def _specification_for_unit(unit: dict[str, Any]) -> TestSpecification:
    unit_type = str(unit.get("unit_type") or "function")
    name = str(unit.get("name") or "unit")
    dependencies = [str(item) for item in unit.get("dependencies") or []]
    mock_plan = unit.get("mock_plan") or {}
    required_mocks = dependencies or _mock_bindings(mock_plan)

    return TestSpecification(
        target_unit_id=str(unit.get("id") or ""),
        scenario_name=_scenario_name(unit_type, name),
        purpose=_purpose(unit_type, name),
        arrange_steps=_arrange_steps(unit_type, required_mocks),
        act_steps=_act_steps(unit_type, name),
        expected_behavior=_expected_behavior(unit_type),
        required_mocks=required_mocks,
        priority=_priority(unit),
    )


def _mock_bindings(mock_plan: dict[str, Any]) -> list[str]:
    bindings = []
    for item in mock_plan.get("module_mocks") or []:
        binding = item.get("binding")
        if binding:
            bindings.append(str(binding))
    bindings.extend(str(item) for item in mock_plan.get("inline_stubs") or [])
    return bindings


def _scenario_name(unit_type: str, name: str) -> str:
    if unit_type == "route":
        return f"{name} routes requests through isolated handlers"
    if unit_type == "component":
        return f"{name} renders its primary state"
    if unit_type == "middleware":
        return f"{name} handles request flow"
    return f"{name} performs its expected behavior"


def _purpose(unit_type: str, name: str) -> str:
    if unit_type in {"controller", "route", "middleware"}:
        return f"Verify {name} without live network, database, or auth side effects."
    if unit_type == "component":
        return f"Verify {name} through rendered user-visible behavior."
    if unit_type == "model":
        return f"Verify {name} schema behavior without connecting to a live database."
    return f"Verify {name} with deterministic inputs and isolated dependencies."


def _arrange_steps(unit_type: str, required_mocks: list[str]) -> list[str]:
    steps = [f"Mock {name}" for name in required_mocks]
    if unit_type in {"controller", "middleware"}:
        steps.extend(["Create req/res stubs", "Create next stub when applicable"])
    if unit_type == "route":
        steps.append("Mount the router on an isolated Express app")
    if unit_type == "component":
        steps.append("Render the component with required providers mocked")
    return steps or ["Prepare deterministic input fixtures"]


def _act_steps(unit_type: str, name: str) -> list[str]:
    if unit_type == "route":
        return ["Send a request through Supertest"]
    if unit_type == "component":
        return ["Render the component", "Trigger the relevant user interaction if needed"]
    return [f"Invoke {name}"]


def _expected_behavior(unit_type: str) -> str:
    if unit_type in {"controller", "route"}:
        return "The unit sends the expected status and JSON response while using mocked dependencies."
    if unit_type == "component":
        return "The user-visible output matches the source-defined behavior."
    if unit_type == "middleware":
        return "The middleware calls next or returns the expected response for the scenario."
    return "The observable result matches the source-defined behavior."


def _priority(unit: dict[str, Any]) -> str:
    risk = str(unit.get("risk_level") or "").lower()
    if risk == "high":
        return "High"
    if risk == "low":
        return "Low"
    return "Medium"


def _load_graph(state: AgentState) -> dict[str, Any]:
    graph = state.get("repository_graph")
    if isinstance(graph, dict):
        return graph
    path = state.get("repository_graph_path")
    if path and Path(path).exists():
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return {}

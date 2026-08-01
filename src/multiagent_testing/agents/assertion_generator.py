from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from multiagent_testing.models import AgentState, AssertionBlock, TestSpecification





FORBIDDEN_FRAGMENT_PATTERNS = [
    re.compile(r"^\s*import\s+", re.MULTILINE),
    re.compile(r"\brequire\s*\("),
    re.compile(r"\b(?:jest|vi)\.mock\s*\("),
    re.compile(r"\bdescribe\s*\("),
    re.compile(r"\b(?:it|test)(?:\.\w+)?\s*\("),
    re.compile(r"\b(?:beforeEach|afterEach|beforeAll|afterAll)\s*\("),
]


def assertion_generator_node(state: AgentState) -> AgentState:
    graph = _load_graph(state)
    specs = _load_specifications(state)
    units = _units_by_id(graph)
    assertions = []
    errors = list(state.get("errors", []))

    for spec in specs:
        unit = units.get(spec.target_unit_id, {})
        block = generate_deterministic_assertion_block(spec, unit)
        validation_errors = validate_assertion_fragment(block.body)
        if validation_errors:
            errors.append(
                f"Assertion fragment rejected for {spec.target_unit_id}: {'; '.join(validation_errors)}"
            )
            block = AssertionBlock(
                target_unit_id=spec.target_unit_id,
                scenario_name=spec.scenario_name,
                body="",
                notes=["No executable assertion emitted after validation; builder will create an explicit todo."],
            )
        assertions.append(block)

    output_dir = Path(state.get("output_dir") or "runs").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "assertion_blocks.json"
    path.write_text(
        json.dumps({"assertions": [block.model_dump() for block in assertions]}, indent=2),
        encoding="utf-8",
    )
    state["assertion_blocks_path"] = str(path)
    state["assertion_blocks"] = {block.target_unit_id: block.model_dump() for block in assertions}
    state["errors"] = errors
    return state


def generate_deterministic_assertion_block(specification: TestSpecification, unit: dict[str, Any]) -> AssertionBlock:
    unit_type = str(unit.get("unit_type") or unit.get("template_kind") or "function")
    unit_name = str(unit.get("name") or "target")
    mock_plan = unit.get("mock_plan") or {}
    api = _mock_api(mock_plan)

    source = str(unit.get("source") or "")

    if unit_type == "route":
        method, route_path = _route_request(unit_name)
        body = "\n".join(
            [
                f"const response = await request(app).{method}('{route_path}');",
                "expect(response.status).toBeGreaterThanOrEqual(200);",
                "expect(response.status).toBeLessThan(400);",
            ]
        )
    elif unit_type == "component":
        body = _component_assertion(source, api)
    elif unit_type in {"controller", "middleware"} or "res.status(" in source or "res.json(" in source:
        status_code = _first_status_code(source) or 200
        body = "\n".join(
            [
                "const req = { body: {}, params: {}, query: {} };",
                f"const res = {{ status: {api}.fn().mockReturnThis(), json: {api}.fn() }};",
                f"const next = {api}.fn();",
                f"const handler = targetModule.{unit_name} || targetModule.default || targetModule;",
                "await handler(req, res, next);",
                f"expect(res.status).toHaveBeenCalledWith({status_code});",
                "expect(res.json).toHaveBeenCalled();",
            ]
        )
    elif "axios." in source:
        method = _axios_method(source)
        body = "\n".join(
            [
                f"const subject = targetModule.{unit_name} || targetModule.default || targetModule;",
                "const result = await subject('test-value');",
                f"expect(axios.{method}).toHaveBeenCalledTimes(1);",
                "expect(result).toEqual({ data: [] });",
            ]
        )
    else:
        body = ""

    return AssertionBlock(
        target_unit_id=specification.target_unit_id,
        scenario_name=specification.scenario_name,
        body=body,
        notes=["Generated source-aware assertion fragment." if body else "No safe source-grounded assertion could be inferred; emitted as todo."],
    )


def validate_assertion_fragment(body: str) -> list[str]:
    errors = []
    if not body.strip():
        errors.append("fragment is empty")
    for pattern in FORBIDDEN_FRAGMENT_PATTERNS:
        if pattern.search(body):
            errors.append(f"fragment contains forbidden construct matching {pattern.pattern}")
    if "expect(" not in body:
        errors.append("fragment does not contain an assertion")
    if re.search(r"expect\(document\.body\)\.toBeTruthy\(\)|expect\(subject\)\.toBeDefined\(\)", body):
        errors.append("fragment contains a vacuous assertion")
    return errors


def _mock_api(mock_plan: dict[str, Any]) -> str:
    framework = str(mock_plan.get("framework") or "").lower()
    return "vi" if "vitest" in framework else "jest"


def _route_request(unit_name: str) -> tuple[str, str]:
    parts = unit_name.split(maxsplit=1)
    method = parts[0].lower() if parts and parts[0].lower() in {"get", "post", "put", "patch", "delete"} else "get"
    path = parts[1] if len(parts) > 1 else "/"
    path = re.sub(r":([A-Za-z_$][\w$]*)", r"test-\1", path)
    return method, path or "/"


def _first_status_code(source: str) -> int | None:
    match = re.search(r"\.status\(\s*([1-5]\d\d)\s*\)", source)
    return int(match.group(1)) if match else None


def _axios_method(source: str) -> str:
    match = re.search(r"\baxios\.(get|post|put|patch|delete)\s*\(", source)
    return match.group(1) if match else "get"


def _component_assertion(source: str, api: str) -> str:
    # Prefer real user-facing contracts over CSS class strings or body existence.
    props = f"const props = {{ todo: {{ _id: 'todo-1', text: 'Test item', completed: false }}, todos: [], onToggle: {api}.fn(), onDelete: {api}.fn(), onAdd: {api}.fn() }};"
    placeholder = re.search(r"\bplaceholder\s*=\s*['\"]([^'\"]+)['\"]", source)
    if placeholder:
        value = re.escape(placeholder.group(1))
        assertion = f"expect(screen.getByPlaceholderText(/{value}/i)).toBeInTheDocument();"
    else:
        visible = re.search(r">\s*([A-Za-z][^<>{}]{0,80})\s*</(?:h[1-6]|p|button)>", source)
        if visible:
            value = re.escape(visible.group(1).strip())
            assertion = f"expect(screen.getByText(/{value}/i)).toBeInTheDocument();"
        elif re.search(r"\btodo\.text\b", source):
            assertion = "expect(screen.getByText('Test item')).toBeInTheDocument();"
        else:
            return ""
    return "\n".join([props, "render(<ComponentUnderTest {...props} />);", assertion])


def _load_specifications(state: AgentState) -> list[TestSpecification]:
    path = state.get("test_plan_path")
    if not path:
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [TestSpecification.model_validate(item) for item in data.get("specifications", [])]


def _load_graph(state: AgentState) -> dict[str, Any]:
    graph = state.get("repository_graph")
    if isinstance(graph, dict):
        return graph
    path = state.get("repository_graph_path")
    if path and Path(path).exists():
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return {}


def _units_by_id(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    units = {}
    for unit in graph.get("units", []) if isinstance(graph, dict) else []:
        if isinstance(unit, dict):
            units[str(unit.get("id") or "")] = unit
    return units

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from multiagent_testing.models import TestSpecification


def build_test_code(
    specification: TestSpecification,
    unit: dict[str, Any],
    repo_path: str,
    test_file_path: str,
    framework: str,
    assertion_body: str | None = None,
) -> str:
    target_path = Path(repo_path) / str(unit.get("relative_path") or unit.get("file_path") or "")
    import_path = _relative_import(test_file_path, target_path)
    api = "vi" if "vitest" in framework.lower() else "jest"
    unit_name = str(unit.get("name") or "target")
    unit_type = str(unit.get("unit_type") or unit.get("template_kind") or "function")
    mock_plan = unit.get("mock_plan") or {}
    lines: list[str] = []

    if api == "vi":
        lines.append("import { describe, expect, it, beforeEach, vi } from 'vitest';")

    lines.extend(_module_mock_lines(mock_plan, api))

    if unit_type in {"route"}:
        lines.extend(_route_import_lines(import_path))
    elif unit_type in {"component"}:
        lines.extend(_component_import_lines(import_path, unit_name))
    else:
        lines.append(f"const targetModule = require('{import_path}');")
        if "axios." in str(unit.get("source") or ""):
            lines.append("const axios = require('axios');")

    if _has_mocks(mock_plan):
        lines.extend(["", "beforeEach(() => {", f"  {api}.clearAllMocks();", "});"])

    lines.extend(["", f"describe('{_escape(unit_name)}', () => {{"])
    lines.extend(_scenario_lines(specification, unit_type, api, assertion_body))
    lines.append("});")
    return "\n".join(lines).rstrip() + "\n"


def _module_mock_lines(mock_plan: dict[str, Any], api: str) -> list[str]:
    lines: list[str] = []
    for module_mock in mock_plan.get("module_mocks") or []:
        import_path = str(module_mock.get("import_path") or "")
        if not import_path:
            continue
        dependency_type = str(module_mock.get("dependency_type") or "")
        if dependency_type == "axios_client":
            lines.append(
                f"{api}.mock('axios', () => {{ const client = {{ get: {api}.fn().mockResolvedValue({{ data: [] }}), post: {api}.fn().mockResolvedValue({{ data: [] }}), put: {api}.fn().mockResolvedValue({{ data: [] }}), patch: {api}.fn().mockResolvedValue({{ data: [] }}), delete: {api}.fn().mockResolvedValue({{ data: [] }}) }}; return {{ default: client, ...client }}; }});"
            )
            continue
        methods = module_mock.get("methods") or ["default"]
        body = ", ".join(
            f"{method}: {_mock_value_for_method(str(method), dependency_type, import_path, api)}"
            for method in methods
            if _is_identifier(str(method))
        )
        if dependency_type == "local_module" and _looks_like_component_mock(methods, import_path) and "default:" not in body:
            component_default = f"default: {api}.fn(() => null)"
            body = f"{component_default}, {body}" if body else component_default
        if not body:
            body = "default: " + api + ".fn()"
        lines.append(f"{api}.mock('{import_path}', () => ({{ {body} }}));")
    if lines:
        lines.append("")
    return lines


def _mock_value_for_method(method: str, dependency_type: str, import_path: str, api: str) -> str:
    lowered_path = import_path.lower()
    if dependency_type == "local_module" and "controller" in lowered_path:
        status = 201 if method.lower().startswith(("add", "create")) else 200
        payload = "[]" if method.lower().startswith(("get", "list", "find")) and "byid" not in method.lower() else "{}"
        return f"{api}.fn((req, res) => res.status({status}).json({payload}))"
    if dependency_type == "local_module" and ("api" in lowered_path or "client" in lowered_path):
        if method.lower().startswith(("get", "list", "fetch")):
            return f"{api}.fn().mockResolvedValue([])"
        return f"{api}.fn().mockResolvedValue({{}})"
    if dependency_type == "local_module" and ("util" in lowered_path or method.lower().startswith("format")):
        return f"{api}.fn((value) => String(value))"
    if dependency_type == "local_module" and method[:1].isupper():
        return f"{api}.fn(() => null)"
    if dependency_type == "axios_client":
        return f"{api}.fn().mockResolvedValue({{ data: [] }})"
    return f"{api}.fn()"


def _looks_like_component_mock(methods: list[Any], import_path: str) -> bool:
    lowered_path = import_path.lower()
    if "controller" in lowered_path or "api" in lowered_path or "util" in lowered_path:
        return False
    return any(str(method)[:1].isupper() for method in methods)


def _route_import_lines(import_path: str) -> list[str]:
    return [
        "const request = require('supertest');",
        "const express = require('express');",
        f"const routeUnderTest = require('{import_path}');",
        "const app = express();",
        "app.use(express.json());",
        "app.use('/', routeUnderTest);",
    ]


def _component_import_lines(import_path: str, unit_name: str) -> list[str]:
    return [
        "import { render, screen } from '@testing-library/react';",
        f"import ComponentUnderTest from '{import_path}';",
        f"const componentName = '{_escape(unit_name)}';",
    ]


def _scenario_lines(
    specification: TestSpecification,
    unit_type: str,
    api: str,
    assertion_body: str | None = None,
) -> list[str]:
    title = _escape(specification.scenario_name or specification.purpose or "planned behavior")
    if assertion_body and assertion_body.strip():
        lines = [f"  it('{title}', async () => {{"]
        lines.extend(f"    {line}" if line.strip() else "" for line in assertion_body.strip().splitlines())
        lines.append("  });")
    else:
        lines = [f"  it.todo('{title}');"]
    details = {
        "purpose": specification.purpose,
        "arrange": specification.arrange_steps,
        "act": specification.act_steps,
        "expected": specification.expected_behavior,
        "required_mocks": specification.required_mocks,
        "template_status": "planned_skeleton",
        "unit_type": unit_type,
        "mock_api": api,
    }
    lines.append(f"  // Planned scenario: {json.dumps(details, ensure_ascii=True)}")
    return lines


def _relative_import(test_file_path: str, target_path: Path) -> str:
    test_dir = Path(test_file_path).resolve().parent
    target = target_path.resolve()
    try:
        value = target.relative_to(test_dir).as_posix()
    except ValueError:
        value = Path(os.path.relpath(target, test_dir)).as_posix()
    if target.suffix:
        value = value[: -len(target.suffix)]
    if not value.startswith("."):
        value = "./" + value
    return value


def _has_mocks(mock_plan: dict[str, Any]) -> bool:
    return bool((mock_plan.get("module_mocks") or []) or (mock_plan.get("inline_stubs") or []))


def _is_identifier(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z_$][\w$]*$", value))


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")

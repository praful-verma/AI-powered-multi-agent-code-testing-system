from __future__ import annotations

from multiagent_testing.analyzer.models import DependencyNode, MockPlan, UnitNode


def build_mock_plan(unit: UnitNode, dependencies: list[DependencyNode], framework: str) -> MockPlan:
    plan = MockPlan(target_unit_id=unit.id, framework=framework)
    for dependency in dependencies:
        if dependency.mock_strategy == "module_mock":
            methods = dependency.methods
            if dependency.dependency_type == "local_module" and not methods:
                methods = [dependency.name]
            plan.module_mocks.append(
                {
                    "import_path": dependency.import_path,
                    "binding": dependency.name,
                    "dependency_type": dependency.dependency_type,
                    "methods": methods,
                    "resolved_path": dependency.resolved_path,
                }
            )
        elif dependency.mock_strategy in {"global_mock", "fake_timers", "inline_stub"}:
            plan.inline_stubs.append(dependency.name)

    if unit.unit_type in {"controller", "route", "middleware"}:
        for stub in ("req", "res"):
            if stub not in plan.inline_stubs:
                plan.inline_stubs.append(stub)
        if unit.unit_type == "middleware" and "next" not in plan.inline_stubs:
            plan.inline_stubs.append("next")

    if any(item.get("dependency_type") == "mongoose_model" for item in plan.module_mocks):
        plan.notes.append("Declare Mongoose model mocks before requiring controllers, routes, or apps.")
    if any(item.get("dependency_type") == "axios_client" for item in plan.module_mocks):
        plan.notes.append("Mock axios in every API-helper test to avoid live network calls.")
    plan.module_mocks = _merge_module_mocks(plan.module_mocks)
    return plan


def _merge_module_mocks(module_mocks: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for module_mock in module_mocks:
        import_path = str(module_mock.get("import_path") or "")
        if not import_path:
            continue
        existing = merged.setdefault(import_path, dict(module_mock, methods=[]))
        methods = list(existing.get("methods") or [])
        for method in module_mock.get("methods") or []:
            if method not in methods:
                methods.append(method)
        existing["methods"] = methods
        if existing.get("dependency_type") == "unknown" and module_mock.get("dependency_type"):
            existing["dependency_type"] = module_mock.get("dependency_type")
    return list(merged.values())

from __future__ import annotations

import re

from multiagent_testing.analyzer.models import DependencyNode, ImportNode


MONGOOSE_METHODS = {
    "find",
    "findOne",
    "findById",
    "create",
    "save",
    "findByIdAndUpdate",
    "findByIdAndDelete",
    "deleteOne",
    "deleteMany",
    "remove",
}
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "request"}


def analyze_dependencies(text: str, imports: list[ImportNode]) -> list[DependencyNode]:
    dependencies: list[DependencyNode] = []
    for import_node in imports:
        names = import_node.bindings or [_name_from_source(import_node.source)]
        for name in names:
            dependencies.append(
                DependencyNode(
                    name=name,
                    import_path=import_node.source,
                    dependency_type=_classify_dependency(name, import_node, text),
                    methods=_methods_for_binding(name, text),
                    resolved_path=import_node.resolved_path,
                    side_effect_level=_side_effect_level(import_node.source, name),
                    mock_strategy=_mock_strategy(import_node.source, name, import_node, text),
                )
            )

    if re.search(r"\bfetch\s*\(", text):
        dependencies.append(
            DependencyNode(
                name="fetch",
                import_path="global:fetch",
                dependency_type="fetch_client",
                methods=["fetch"],
                side_effect_level="external",
                mock_strategy="global_mock",
            )
        )
    if re.search(r"\b(?:setTimeout|setInterval|Date\.now)\s*\(", text):
        dependencies.append(
            DependencyNode(
                name="timer",
                import_path="global:timer",
                dependency_type="timer",
                methods=[],
                side_effect_level="time",
                mock_strategy="fake_timers",
            )
        )
    if "process.env" in text:
        dependencies.append(
            DependencyNode(
                name="process.env",
                import_path="global:process.env",
                dependency_type="env",
                methods=[],
                side_effect_level="environment",
                mock_strategy="inline_stub",
            )
        )
    return _dedupe_dependencies(dependencies)


def _classify_dependency(name: str, import_node: ImportNode, text: str):
    source = import_node.source.lower()
    lowered_name = name.lower()
    resolved = (import_node.resolved_path or "").lower()

    if source in {"axios"}:
        return "axios_client"
    if source in {"fs", "node:fs", "fs/promises", "node:fs/promises"}:
        return "filesystem"
    if source in {"jsonwebtoken", "jwt-decode"} or lowered_name in {"jwt", "jsonwebtoken"}:
        return "jwt"
    if source in {"express", "react", "react-dom", "react-router-dom"}:
        return "framework"
    if any(token in source for token in ("stripe", "razorpay", "paypal")):
        return "payment_sdk"
    if "auth" in lowered_name or "auth" in source:
        return "auth_middleware"
    if any(token in source for token in ("logger", "winston", "pino")) or "logger" in lowered_name:
        return "logger"
    if import_node.resolved_path:
        mongoose_methods = "|".join(re.escape(method) for method in sorted(MONGOOSE_METHODS))
        if "/models/" in f"/{resolved}" or re.search(rf"\b{re.escape(name)}\.(?:{mongoose_methods})\b", text):
            return "mongoose_model"
        return "local_module"
    return "unknown"


def _methods_for_binding(name: str, text: str) -> list[str]:
    if not name:
        return []
    method_pattern = re.compile(rf"\b{re.escape(name)}\.([A-Za-z_$][\w$]*)\b")
    methods = sorted({match.group(1) for match in method_pattern.finditer(text)})
    if name.lower() == "axios":
        methods = sorted(set(methods) | (HTTP_METHODS & set(methods)))
    return methods


def _mock_strategy(source: str, name: str, import_node: ImportNode, text: str) -> str:
    dependency_type = _classify_dependency(name, import_node, text)
    if dependency_type in {"mongoose_model", "axios_client", "filesystem", "jwt", "payment_sdk", "local_module"}:
        return "module_mock"
    if dependency_type == "fetch_client":
        return "global_mock"
    if dependency_type == "timer":
        return "fake_timers"
    if dependency_type == "env":
        return "inline_stub"
    return "manual"


def _side_effect_level(source: str, name: str) -> str:
    lowered = f"{source} {name}".lower()
    if any(token in lowered for token in ("axios", "fetch", "stripe", "paypal", "razorpay")):
        return "external"
    if any(token in lowered for token in ("mongoose", "model", "database", "db")):
        return "database"
    if "fs" in lowered:
        return "filesystem"
    if "jwt" in lowered or "auth" in lowered:
        return "auth"
    return "local"


def _name_from_source(source: str) -> str:
    return source.rstrip("/").rsplit("/", 1)[-1].replace("-", "_") or source


def _dedupe_dependencies(dependencies: list[DependencyNode]) -> list[DependencyNode]:
    merged: dict[tuple[str, str], DependencyNode] = {}
    for dependency in dependencies:
        key = (dependency.name, dependency.import_path)
        if key not in merged:
            merged[key] = dependency
            continue
        existing = merged[key]
        existing.methods = sorted(set(existing.methods) | set(dependency.methods))
    return list(merged.values())

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


StackArea = Literal["backend", "frontend", "shared", "unknown"]
FileRole = Literal[
    "controller",
    "route",
    "model",
    "service",
    "utility",
    "component",
    "hook",
    "context",
    "api_helper",
    "middleware",
    "config",
    "unknown",
]
DependencyType = Literal[
    "mongoose_model",
    "axios_client",
    "fetch_client",
    "filesystem",
    "jwt",
    "auth_middleware",
    "payment_sdk",
    "logger",
    "timer",
    "env",
    "local_module",
    "framework",
    "unknown",
]


@dataclass(slots=True)
class ImportNode:
    source: str
    bindings: list[str] = field(default_factory=list)
    line: int = 0
    import_kind: str = "unknown"
    resolved_path: str | None = None
    is_external: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExportNode:
    name: str
    line: int = 0
    export_kind: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CallEdge:
    caller_id: str
    callee: str
    line: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DependencyNode:
    name: str
    import_path: str
    dependency_type: DependencyType = "unknown"
    methods: list[str] = field(default_factory=list)
    resolved_path: str | None = None
    side_effect_level: str = "unknown"
    mock_strategy: str = "manual"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MockPlan:
    target_unit_id: str
    framework: str
    module_mocks: list[dict[str, Any]] = field(default_factory=list)
    inline_stubs: list[str] = field(default_factory=list)
    reset_strategy: str = "clear_all_mocks"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class UnitNode:
    id: str
    file_path: str
    relative_path: str
    unit_type: str
    name: str
    start_line: int
    end_line: int
    source: str
    calls: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    template_kind: str = "function"
    risk_level: str = "medium"
    mock_plan: MockPlan | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.mock_plan is not None:
            data["mock_plan"] = self.mock_plan.to_dict()
        return data


@dataclass(slots=True)
class SourceFileNode:
    path: str
    relative_path: str
    language: str
    stack_area: StackArea
    file_role: FileRole
    imports: list[ImportNode] = field(default_factory=list)
    exports: list[ExportNode] = field(default_factory=list)
    dependencies: list[DependencyNode] = field(default_factory=list)
    units: list[UnitNode] = field(default_factory=list)
    source_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "relative_path": self.relative_path,
            "language": self.language,
            "stack_area": self.stack_area,
            "file_role": self.file_role,
            "imports": [item.to_dict() for item in self.imports],
            "exports": [item.to_dict() for item in self.exports],
            "dependencies": [item.to_dict() for item in self.dependencies],
            "units": [item.to_dict() for item in self.units],
            "source_hash": self.source_hash,
        }


@dataclass(slots=True)
class RepositoryGraph:
    root_path: str
    stack: str
    test_framework: str
    files: list[SourceFileNode] = field(default_factory=list)
    units: list[UnitNode] = field(default_factory=list)
    dependencies: list[DependencyNode] = field(default_factory=list)
    call_edges: list[CallEdge] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_path": self.root_path,
            "stack": self.stack,
            "test_framework": self.test_framework,
            "files": [item.to_dict() for item in self.files],
            "units": [item.to_dict() for item in self.units],
            "dependencies": [item.to_dict() for item in self.dependencies],
            "call_edges": [item.to_dict() for item in self.call_edges],
            "warnings": self.warnings,
        }

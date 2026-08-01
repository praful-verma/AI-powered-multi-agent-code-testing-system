from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field, field_validator, model_validator


Priority = Literal["High", "Medium", "Low"]
Status = Literal["Pass", "Fail", "Error", "Skipped"]
Confidence = Literal["Low", "Med", "High"]


@dataclass(slots=True)
class CodeUnit:
    id: str
    file_path: str
    relative_path: str
    unit_type: str
    name: str
    start_line: int
    end_line: int
    source: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class TestResult:
    passed: bool
    status: Status
    score: float
    error_message: str | None = None
    duration_ms: int = 0
    raw_output: str = ""


@dataclass(slots=True)
class TestCaseResult:
    test_title: str
    status: Status
    duration_ms: int = 0
    error_message: str | None = None


class GeneratedTestCase(BaseModel):
    unit_type: str = Field(default="", description="route, component, model, or function")
    target_file: str = ""
    target_function_or_route: str = ""
    test_description: str = ""
    test_code: str = Field(description="Full runnable Jest test code")
    priority: Priority = "Medium"

    @field_validator("unit_type", "target_file", "target_function_or_route", "test_description", "test_code", mode="before")
    @classmethod
    def _coerce_optional_text(cls, value) -> str:
        if value is None:
            return ""
        return str(value)


class GeneratedTestBatch(BaseModel):
    tests: list[GeneratedTestCase]

    @model_validator(mode="before")
    @classmethod
    def _drop_empty_generated_tests(cls, value):
        if not isinstance(value, dict):
            return value
        tests = value.get("tests")
        if not isinstance(tests, list):
            return value
        value = dict(value)
        value["tests"] = [
            test
            for test in tests
            if isinstance(test, dict) and isinstance(test.get("test_code"), str) and test.get("test_code", "").strip()
        ]
        return value


class TestSpecification(BaseModel):
    target_unit_id: str = ""
    scenario_name: str = ""
    purpose: str = ""
    arrange_steps: list[str] = Field(default_factory=list)
    act_steps: list[str] = Field(default_factory=list)
    expected_behavior: str = ""
    required_mocks: list[str] = Field(default_factory=list)
    priority: Priority = "Medium"

    @field_validator("target_unit_id", "scenario_name", "purpose", "expected_behavior", mode="before")
    @classmethod
    def _coerce_text(cls, value) -> str:
        if value is None:
            return ""
        return str(value)

    @field_validator("arrange_steps", "act_steps", "required_mocks", mode="before")
    @classmethod
    def _coerce_text_list(cls, value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        return [str(value)] if str(value).strip() else []


class TestSpecificationBatch(BaseModel):
    specifications: list[TestSpecification] = Field(default_factory=list)


class AssertionBlock(BaseModel):
    target_unit_id: str = ""
    scenario_name: str = ""
    body: str = Field(description="Only the inside of one it/test callback body")
    notes: list[str] = Field(default_factory=list)

    @field_validator("target_unit_id", "scenario_name", "body", mode="before")
    @classmethod
    def _coerce_assertion_text(cls, value) -> str:
        if value is None:
            return ""
        return str(value)

    @field_validator("notes", mode="before")
    @classmethod
    def _coerce_notes(cls, value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        return [str(value)] if str(value).strip() else []


class AssertionBlockBatch(BaseModel):
    assertions: list[AssertionBlock] = Field(default_factory=list)


class FixSuggestion(BaseModel):
    root_cause_analysis: str
    suggested_fix: str = Field(description="Prefer unified diff format")
    fix_location: str
    confidence: Confidence


class AgentState(TypedDict, total=False):
    repo_path: str
    original_repo: str
    stack: str | None
    output_dir: str
    excel_path: str
    code_units: list[CodeUnit]
    adapter_name: str
    errors: list[str]
    failing_count: int
    skip_runner: bool
    skip_fixes: bool
    rerun_all_tests: bool
    reuse_existing_tests: bool
    max_input_tokens: int
    temp_dir: str
    keep_generated_tests: bool
    discovered_unit_count: int
    generation_chunk_count: int
    generated_test_count: int
    empty_generation_batch_count: int
    repository_graph_path: str
    repository_graph: dict[str, Any]
    test_plan_path: str
    assertion_blocks_path: str
    assertion_blocks: dict[str, Any]
    legacy_generator: bool
    coverage: bool

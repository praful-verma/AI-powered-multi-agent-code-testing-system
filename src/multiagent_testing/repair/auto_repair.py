from __future__ import annotations

import re
from dataclasses import dataclass, field

from multiagent_testing.validators.static_validator import ValidationIssue


@dataclass(slots=True)
class RepairResult:
    test_code: str
    repairs: list[str] = field(default_factory=list)


def repair_test_code(test_code: str, issues: list[ValidationIssue], framework: str = "jest") -> RepairResult:
    repaired = test_code
    repairs: list[str] = []
    issue_codes = {issue.code for issue in issues}

    if "duplicate_require" in issue_codes or "duplicate_express_require" in issue_codes:
        repaired, changed = _remove_duplicate_requires(repaired)
        if changed:
            repairs.append("removed duplicate require statements")

    if "duplicate_import" in issue_codes:
        repaired, changed = _remove_duplicate_imports(repaired)
        if changed:
            repairs.append("removed duplicate import statements")

    if "missing_supertest" in issue_codes and "supertest" not in repaired:
        repaired = "const request = require('supertest');\n" + repaired
        repairs.append("inserted missing supertest import")

    if "missing_axios_mock" in issue_codes:
        repaired, changed = _insert_axios_mock(repaired, framework)
        if changed:
            repairs.append("inserted missing axios mock")

    if "wrong_framework_api" in issue_codes:
        if "vitest" in framework.lower():
            repaired = repaired.replace("jest.", "vi.")
            if "from 'vitest'" not in repaired and 'from "vitest"' not in repaired:
                repaired = "import { vi } from 'vitest';\n" + repaired
            repairs.append("rewrote jest APIs to vi APIs")
        elif "jest" in framework.lower() and "vitest" not in repaired:
            repaired = repaired.replace("vi.", "jest.")
            repairs.append("rewrote vi APIs to jest APIs")

    if "missing_clear_all_mocks" in issue_codes:
        repaired, changed = _insert_clear_all_mocks(repaired, framework)
        if changed:
            repairs.append("inserted clearAllMocks reset")

    if "mongoose_mock_order" in issue_codes:
        repaired, changed = _move_model_mocks_before_requires(repaired)
        if changed:
            repairs.append("moved model mocks before controller or route imports")

    return RepairResult(repaired, repairs)


def _remove_duplicate_requires(test_code: str) -> tuple[str, bool]:
    seen: set[tuple[str, str]] = set()
    changed = False
    lines = []
    pattern = re.compile(r"^\s*const\s+([A-Za-z_$][\w$]*)\s*=\s*require\((['\"])([^'\"]+)\2\)\s*;?\s*$")
    for line in test_code.splitlines():
        match = pattern.match(line)
        if match:
            key = (match.group(1), match.group(3))
            if key in seen:
                changed = True
                continue
            seen.add(key)
        lines.append(line)
    return "\n".join(lines) + ("\n" if test_code.endswith("\n") else ""), changed


def _remove_duplicate_imports(test_code: str) -> tuple[str, bool]:
    seen: set[tuple[str, str]] = set()
    changed = False
    lines = []
    pattern = re.compile(r"^\s*import\s+(.+?)\s+from\s+(['\"])([^'\"]+)\2\s*;?\s*$")
    for line in test_code.splitlines():
        match = pattern.match(line)
        if match:
            key = (_normalize_import_body(match.group(1)), match.group(3))
            if key in seen:
                changed = True
                continue
            seen.add(key)
        lines.append(line)
    return "\n".join(lines) + ("\n" if test_code.endswith("\n") else ""), changed


def _insert_axios_mock(test_code: str, framework: str) -> tuple[str, bool]:
    if re.search(r"\b(?:jest|vi)\.mock\((['\"])axios\1", test_code):
        return test_code, False
    api = "vi" if "vitest" in framework.lower() or re.search(r"\bvi\.", test_code) else "jest"
    mock_line = f"{api}.mock('axios');\n"
    lines = test_code.splitlines()
    insert_at = 0
    for index, line in enumerate(lines):
        if re.match(r"^\s*(?:const\s+.+?=\s*require\(['\"]axios['\"]\)|import\s+.+?\s+from\s+['\"]axios['\"])", line):
            insert_at = index + 1
            break
    lines.insert(insert_at, mock_line.rstrip("\n"))
    return "\n".join(lines) + ("\n" if test_code.endswith("\n") else ""), True


def _move_model_mocks_before_requires(test_code: str) -> tuple[str, bool]:
    lines = test_code.splitlines()
    mock_indices = [
        index
        for index, line in enumerate(lines)
        if re.search(r"\b(?:jest|vi)\.mock\((['\"])[^'\"]*/models/[^'\"]+\1", line.replace("\\", "/"))
    ]
    if not mock_indices:
        return test_code, False
    require_indices = [
        index
        for index, line in enumerate(lines)
        if re.search(r"\brequire\((['\"])[^'\"]*(?:controllers?|routes?|app)[^'\"]*\1\)", line.replace("\\", "/"))
    ]
    if not require_indices or min(require_indices) > min(mock_indices):
        return test_code, False

    mock_lines = [lines[index] for index in mock_indices]
    remaining = [line for index, line in enumerate(lines) if index not in set(mock_indices)]
    first_require = min(
        index
        for index, line in enumerate(remaining)
        if re.search(r"\brequire\((['\"])[^'\"]*(?:controllers?|routes?|app)[^'\"]*\1\)", line.replace("\\", "/"))
    )
    repaired_lines = remaining[:first_require] + mock_lines + remaining[first_require:]
    return "\n".join(repaired_lines) + ("\n" if test_code.endswith("\n") else ""), True


def _insert_clear_all_mocks(test_code: str, framework: str) -> tuple[str, bool]:
    if re.search(r"\b(?:jest|vi)\.clearAllMocks\(\)", test_code):
        return test_code, False
    api = "vi" if "vitest" in framework.lower() or re.search(r"\bvi\.", test_code) else "jest"
    block = f"\nbeforeEach(() => {{\n  {api}.clearAllMocks();\n}});\n"
    describe_match = re.search(r"\bdescribe\s*\(", test_code)
    if describe_match:
        return test_code[: describe_match.start()] + block + "\n" + test_code[describe_match.start() :], True
    return test_code + block, True


def _normalize_import_body(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())

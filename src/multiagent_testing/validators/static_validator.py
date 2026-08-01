from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ValidationIssue:
    code: str
    message: str
    severity: str = "warning"


def validate_test_code(test_code: str, test_file_path: str, framework: str = "jest") -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    issues.extend(_duplicate_require_issues(test_code))
    issues.extend(_duplicate_import_issues(test_code))
    issues.extend(_duplicate_express_issue(test_code))
    issues.extend(_missing_supertest_issue(test_code))
    issues.extend(_missing_axios_mock_issue(test_code, test_file_path))
    issues.extend(_framework_api_issues(test_code, framework))
    issues.extend(_mongoose_mock_order_issues(test_code))
    issues.extend(_missing_clear_mocks_issue(test_code, framework))
    issues.extend(_ignored_test_path_issues(test_file_path))
    issues.extend(_private_import_issues(test_code))
    issues.extend(_vacuous_assertion_issues(test_code))
    return issues


def _duplicate_require_issues(test_code: str) -> list[ValidationIssue]:
    seen: set[tuple[str, str]] = set()
    issues = []
    pattern = re.compile(r"^\s*const\s+([A-Za-z_$][\w$]*)\s*=\s*require\((['\"])([^'\"]+)\2\)\s*;?\s*$", re.MULTILINE)
    for match in pattern.finditer(test_code):
        key = (match.group(1), match.group(3))
        if key in seen:
            issues.append(ValidationIssue("duplicate_require", f"Duplicate require for {match.group(1)} from {match.group(3)}"))
        seen.add(key)
    return issues


def _duplicate_import_issues(test_code: str) -> list[ValidationIssue]:
    seen: set[tuple[str, str]] = set()
    issues = []
    pattern = re.compile(r"^\s*import\s+(.+?)\s+from\s+(['\"])([^'\"]+)\2\s*;?\s*$", re.MULTILINE)
    for match in pattern.finditer(test_code):
        key = (_normalize_import_body(match.group(1)), match.group(3))
        if key in seen:
            issues.append(ValidationIssue("duplicate_import", f"Duplicate import from {match.group(3)}"))
        seen.add(key)
    return issues


def _duplicate_express_issue(test_code: str) -> list[ValidationIssue]:
    count = len(re.findall(r"^\s*const\s+express\s*=\s*require\((['\"])express\1\)\s*;?\s*$", test_code, flags=re.MULTILINE))
    if count > 1:
        return [ValidationIssue("duplicate_express_require", "Duplicate const express = require('express') statements")]
    return []


def _missing_supertest_issue(test_code: str) -> list[ValidationIssue]:
    if re.search(r"\brequest\s*\(", test_code) and "supertest" not in test_code:
        return [ValidationIssue("missing_supertest", "request() is used without importing supertest", "error")]
    return []


def _missing_axios_mock_issue(test_code: str, test_file_path: str) -> list[ValidationIssue]:
    path = Path(test_file_path)
    name = path.name.lower()
    looks_like_api_test = "api" in name or "/api" in path.as_posix().lower()
    if looks_like_api_test and "axios" in test_code and not re.search(r"\b(?:jest|vi)\.mock\((['\"])axios\1", test_code):
        return [ValidationIssue("missing_axios_mock", "API-helper test imports axios without an explicit module mock", "error")]
    return []


def _framework_api_issues(test_code: str, framework: str) -> list[ValidationIssue]:
    lowered = framework.lower()
    if "vitest" in lowered and re.search(r"\bjest\.", test_code):
        return [ValidationIssue("wrong_framework_api", "Vitest test contains jest.* APIs")]
    if "jest" in lowered and re.search(r"\bvi\.", test_code) and "vitest" not in test_code:
        return [ValidationIssue("wrong_framework_api", "Jest test contains vi.* APIs")]
    return []


def _mongoose_mock_order_issues(test_code: str) -> list[ValidationIssue]:
    if "/models/" not in test_code.replace("\\", "/"):
        return []
    mock_match = re.search(r"\b(?:jest|vi)\.mock\((['\"])[^'\"]*/models/[^'\"]+\1", test_code.replace("\\", "/"))
    require_match = re.search(r"\brequire\((['\"])[^'\"]*(?:controllers?|routes?|app)[^'\"]*\1\)", test_code.replace("\\", "/"))
    if mock_match and require_match and require_match.start() < mock_match.start():
        return [ValidationIssue("mongoose_mock_order", "Mongoose model mock appears after controller/route import", "error")]
    return []


def _ignored_test_path_issues(test_file_path: str) -> list[ValidationIssue]:
    path = Path(test_file_path)
    ignored = {"node_modules", ".git", "dist", "build", "coverage"}
    lower_parts = {part.lower() for part in path.parts}
    if lower_parts & ignored:
        return [ValidationIssue("ignored_test_path", "Generated test file path points into an ignored directory", "error")]
    return []


def _private_import_issues(test_code: str) -> list[ValidationIssue]:
    issues = []
    named_import_pattern = re.compile(r"^\s*import\s+\{([^}]+)\}\s+from\s+['\"][^'\"]+['\"]", re.MULTILINE)
    destructured_require_pattern = re.compile(r"^\s*const\s+\{([^}]+)\}\s*=\s*require\(['\"][^'\"]+['\"]\)", re.MULTILINE)
    for pattern in (named_import_pattern, destructured_require_pattern):
        for match in pattern.finditer(test_code):
            names = [item.strip().split(" as ")[-1].strip() for item in match.group(1).split(",")]
            private_names = [name for name in names if name.startswith("_") or name.startswith("handle")]
            if private_names:
                issues.append(
                    ValidationIssue(
                        "private_import",
                        f"Test imports likely private/non-exported helper(s): {', '.join(private_names)}",
                        "error",
                    )
                )
    return issues


def _missing_clear_mocks_issue(test_code: str, framework: str) -> list[ValidationIssue]:
    has_mocks = re.search(r"\b(?:jest|vi)\.(?:fn|mock|spyOn)\b", test_code)
    clears = re.search(r"\b(?:jest|vi)\.clearAllMocks\(\)", test_code)
    if has_mocks and not clears:
        return [ValidationIssue("missing_clear_all_mocks", "Mocks are used without clearAllMocks reset")]
    return []


def _normalize_import_body(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _vacuous_assertion_issues(test_code: str) -> list[ValidationIssue]:
    patterns = {
        r"expect\(document\.body\)\.toBeTruthy\(\)": "body truthiness does not verify component behaviour",
        r"expect\(subject\)\.toBeDefined\(\)": "export existence does not verify function behaviour",
        r"expect\(true\)\.toBe\(true\)": "constant truth assertion is vacuous",
        r"\.toBeLessThan\(500\)": "non-5xx route assertion is too broad",
    }
    return [ValidationIssue("vacuous_assertion", message, "error") for pattern, message in patterns.items() if re.search(pattern, test_code)]

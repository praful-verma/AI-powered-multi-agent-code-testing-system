from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConfidenceBreakdown:
    score: int
    details: str


def confidence_score(row: dict) -> int:
    return confidence_breakdown(row).score


def confidence_details(row: dict) -> str:
    return confidence_breakdown(row).details


def confidence_breakdown(row: dict) -> ConfidenceBreakdown:
    status = str(row.get("status") or "")
    try:
        runner_score = float(row.get("score") or 0)
    except (TypeError, ValueError):
        runner_score = 0

    if status == "Pass":
        score = 85 + runner_score * 0.15
        reasons = [f"execution passed with runner score {runner_score:g}"]
    elif status == "Skipped":
        score = 35
        reasons = ["runner skipped matching assertions"]
    elif status in {"Fail", "Error"}:
        score = min(45, runner_score * 0.5)
        category = str(row.get("failure_category") or "Unknown")
        reasons = [f"{status.lower()} result categorized as {category}"]
    else:
        score = 50
        reasons = ["execution has not produced a final status"]

    repairs = str(row.get("repairs_applied") or "").strip()
    validation_errors = str(row.get("validation_errors") or "").strip()
    if repairs:
        repair_count = len([item for item in repairs.split(";") if item.strip()])
        penalty = min(20, repair_count * 5)
        score -= penalty
        reasons.append(f"{repair_count} deterministic repair(s) applied (-{penalty})")
    if validation_errors:
        validation_count = len([item for item in validation_errors.split(";") if item.strip()])
        penalty = min(25, validation_count * 7)
        score -= penalty
        reasons.append(f"{validation_count} validation issue(s) remain (-{penalty})")
    elif str(row.get("validation_status") or "") == "Pass":
        reasons.append("static validation passed")

    coverage = row.get("coverage_percent")
    if coverage not in (None, ""):
        try:
            coverage_value = float(coverage)
            if coverage_value >= 80:
                score += 3
                reasons.append(f"coverage is high at {coverage_value:g}% (+3)")
            elif coverage_value < 40:
                score -= 8
                reasons.append(f"coverage is low at {coverage_value:g}% (-8)")
            else:
                reasons.append(f"coverage recorded at {coverage_value:g}%")
        except (TypeError, ValueError):
            score -= 3
            reasons.append("coverage value was not parseable (-3)")
    else:
        reasons.append("coverage was not collected")

    if _has_unresolved_dependency(row):
        score -= 8
        reasons.append("mock plan has unresolved dependency hints (-8)")

    if _has_vacuous_assertion(row):
        score = min(score, 25)
        reasons.append("test contains a vacuous assertion; confidence capped at 25")

    final_score = max(0, min(100, round(score)))
    return ConfidenceBreakdown(final_score, "; ".join(reasons))


def _has_unresolved_dependency(row: dict) -> bool:
    mock_plan = str(row.get("mock_plan") or "").lower()
    validation_errors = str(row.get("validation_errors") or "").lower()
    return "unresolved" in mock_plan or "unknown" in mock_plan or "unresolved" in validation_errors


def _has_vacuous_assertion(row: dict) -> bool:
    code = str(row.get("test_code") or "")
    patterns = (
        "expect(document.body).toBeTruthy()",
        "expect(subject).toBeDefined()",
        "expect(true).toBe(true)",
        "toBeLessThan(500)",
    )
    return any(pattern in code for pattern in patterns)


def confidence_label(score: int) -> str:
    if score >= 80:
        return "High"
    if score >= 50:
        return "Med"
    return "Low"

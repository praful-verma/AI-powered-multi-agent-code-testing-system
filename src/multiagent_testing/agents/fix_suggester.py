from __future__ import annotations



import json
from collections import defaultdict
from pathlib import Path

from multiagent_testing.chunking import relevant_source_context
from multiagent_testing.excel_store import ExcelStore
from multiagent_testing.groq_client import GroqStructuredClient
from multiagent_testing.models import AgentState, FixSuggestion


SYSTEM_PROMPT = """You diagnose failed code tests and propose concrete source fixes.
Return only structured output. Prefer unified diff format for suggested_fix.
Use the smallest relevant source context. Do not suggest unrelated rewrites.
Before concluding that the source code is buggy, check whether the test's own input data, fixture setup, mocks, or assertion timing could fully explain the failure. If the test appears to be missing required fields in its fixture, asserts against an intermediate/loading state without properly waiting for it (for example, missing waitFor/findBy in React Testing Library), or otherwise seems incomplete, say so explicitly in root_cause_analysis instead of attributing the failure to the source function. Only attribute a bug to source code when the test's inputs and setup are correct and complete."""


def fix_suggester_node(state: AgentState) -> AgentState:
    if state.get("skip_fixes") or int(state.get("failing_count") or 0) == 0:
        return state

    repo_path = state["repo_path"]
    repository_graph = _load_repository_graph(state)
    store = ExcelStore(state["excel_path"])
    failing_rows = [
        row
        for row in store.rows()
        if row.get("status") in {"Fail", "Error"} or _score(row) < float(state.get("fix_threshold") or 70)
    ]
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in failing_rows:
        grouped[str(row.get("target_file"))].append(row)

    llm = GroqStructuredClient(model=state.get("agent3_model", "llama-3.1-8b-instant"), temperature=0.05)
    updates: dict[str, dict] = {}

    for target_file, rows in grouped.items():
        for row in rows:
            source = relevant_source_context(repo_path, target_file, str(row.get("target_function_or_route") or ""))
            graph_context = _graph_context_for_row(row, repository_graph)
            try:
                suggestion = llm.invoke(FixSuggestion, SYSTEM_PROMPT, _build_user_prompt(row, source, graph_context))
                updates[str(row["test_id"])] = {
                    "root_cause_analysis": suggestion.root_cause_analysis,
                    "suggested_fix": suggestion.suggested_fix,
                    "fix_location": suggestion.fix_location,
                    "confidence": suggestion.confidence,
                }
            except RuntimeError as exc:
                if _is_rate_limit_error(exc):
                    updates[str(row["test_id"])] = {
                        "root_cause_analysis": "Fix suggestion skipped because the Groq token/rate limit was reached.",
                        "suggested_fix": str(exc)[:2000],
                        "fix_location": str(row.get("target_file") or ""),
                        "confidence": "Low",
                    }
                    store.bulk_update_by_test_id(updates)
                    _write_report(Path(state.get("output_dir") or Path(state["excel_path"]).parent), store.rows())
                    state.setdefault("errors", []).append("Groq rate limit reached during fix suggestions.")
                    return state
                raise

    store.bulk_update_by_test_id(updates)
    _write_report(Path(state.get("output_dir") or Path(state["excel_path"]).parent), store.rows())
    return state


def _score(row: dict) -> float:
    try:
        return float(row.get("score") or 0)
    except (TypeError, ValueError):
        return 0


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "rate limit" in text or "rate_limit" in text or "tokens per day" in text or "429" in text


def _build_user_prompt(row: dict, source_context: str, graph_context: str = "") -> str:
    return f"""A generated test failed or scored poorly.

Test ID: {row.get("test_id")}
Target: {row.get("target_file")} / {row.get("target_function_or_route")}
Status: {row.get("status")}
Score: {row.get("score")}
Failure category: {row.get("failure_category")}
Validation status: {row.get("validation_status")}
Validation errors: {row.get("validation_errors")}
Repairs applied: {row.get("repairs_applied")}

Test code:
```javascript
{row.get("test_code") or ""}
```

Actual output:
```text
{row.get("actual_output") or ""}
```

Relevant source context with line numbers:
```javascript
{source_context}
```

Repository graph and mock-plan context:
```json
{graph_context}
```

Return a concise root cause, a concrete unified diff if possible, a precise fix location, and confidence."""


def _load_repository_graph(state: AgentState) -> dict:
    graph = state.get("repository_graph")
    if isinstance(graph, dict):
        return graph
    graph_path = state.get("repository_graph_path")
    if graph_path and Path(str(graph_path)).exists():
        try:
            return json.loads(Path(str(graph_path)).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _graph_context_for_row(row: dict, repository_graph: dict) -> str:
    target_file = str(row.get("target_file") or "").replace("\\", "/")
    target_name = str(row.get("target_function_or_route") or "")
    unit_id = str(row.get("unit_id") or "")
    candidates = []
    for unit in repository_graph.get("units", []) if isinstance(repository_graph, dict) else []:
        if not isinstance(unit, dict):
            continue
        if unit_id and unit.get("id") == unit_id:
            candidates.append(unit)
            break
        if unit.get("relative_path") == target_file and (unit.get("name") == target_name or target_name in str(unit.get("name") or "")):
            candidates.append(unit)
    payload = {
        "unit": candidates[0] if candidates else {},
        "excel_mock_plan": _safe_json(row.get("mock_plan")),
    }
    return json.dumps(payload, indent=2, ensure_ascii=True)


def _safe_json(value) -> object:
    if not value:
        return {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return str(value)


def _write_report(output_dir: Path, rows: list[dict]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    failing = [row for row in rows if row.get("suggested_fix")]
    by_file: dict[str, list[dict]] = defaultdict(list)
    for row in failing:
        by_file[str(row.get("target_file"))].append(row)

    lines = ["# Fix Report", ""]
    if not failing:
        lines.append("No fix suggestions were generated.")
    for target_file, file_rows in sorted(by_file.items()):
        lines.extend([f"## {target_file}", ""])
        for row in file_rows:
            lines.extend(
                [
                    f"### {row.get('test_id')} - {row.get('target_function_or_route')}",
                    "",
                    f"- Status: {row.get('status')}",
                    f"- Score: {row.get('score')}",
                    f"- Location: {row.get('fix_location')}",
                    f"- Confidence: {row.get('confidence')}",
                    "",
                    "Root cause:",
                    "",
                    str(row.get("root_cause_analysis") or ""),
                    "",
                    "Suggested fix:",
                    "",
                    "```diff",
                    str(row.get("suggested_fix") or ""),
                    "```",
                    "",
                ]
            )
    (output_dir / "fix_report.md").write_text("\n".join(lines), encoding="utf-8")

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from multiagent_testing.adapters.registry import DEFAULT_REGISTRY
from multiagent_testing.cleanup import cleanup_generated_test_files, cleanup_temp_dir
from multiagent_testing.agents.assertion_generator import assertion_generator_node
from multiagent_testing.agents.fix_suggester import fix_suggester_node
from multiagent_testing.agents.repository_analyzer import repository_analyzer_node
from multiagent_testing.agents.test_planner import test_planner_node
from multiagent_testing.agents.test_runner import test_runner_node
from multiagent_testing.excel_store import ExcelStore
from multiagent_testing.graph import build_graph
from multiagent_testing.models import AgentState
from multiagent_testing.repo_loader import materialize_repo


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run the multi-agent code testing system.")
    parser.add_argument("--repo", required=True, help="Local repo path or GitHub URL.")
    parser.add_argument("--stack", default="auto", help="Stack adapter name, or auto.")
    parser.add_argument("--output-dir", default="runs", help="Directory for Excel, tests, reports, and checkpoints.")
    parser.add_argument("--excel-path", default=None, help="Optional explicit workbook path.")
    parser.add_argument("--max-input-tokens", type=int, default=2200, help="Max input tokens per logical LLM chunk.")
    parser.add_argument("--agent1-model", default="llama-3.1-8b-instant", help="Groq model for test generation.")
    parser.add_argument("--agent3-model", default="llama-3.1-8b-instant", help="Groq model for fix suggestions.")
    parser.add_argument("--skip-runner", action="store_true", help="Generate tests only; do not execute them.")
    parser.add_argument("--skip-fixes", action="store_true", help="Do not generate fix suggestions.")
    parser.add_argument("--rerun-all-tests", action="store_true", help="Run every Excel row, including rows with status.")
    parser.add_argument("--reuse-existing-tests", action="store_true", help="Update existing unit_id + scenario_name rows instead of appending duplicates.")
    parser.add_argument("--runner-only", action="store_true", help="Run Agent 2 against an existing Excel workbook.")
    parser.add_argument("--analyze-only", action="store_true", help="Build runs/repository_graph.json and exit.")
    parser.add_argument("--plan-only", action="store_true", help="Build runs/repository_graph.json and runs/test_plan.json, then exit.")
    parser.add_argument("--validate-only", action="store_true", help="Validate and repair generated tests from the workbook without executing them.")
    parser.add_argument("--legacy-generator", action="store_true", help="Use the current full-file LLM generator path.")
    parser.add_argument("--coverage", action="store_true", help="Run generated tests with coverage after normal execution and record coverage_percent.")
    parser.add_argument("--thread-id", default=None, help="Optional LangGraph checkpoint thread id for resuming a run.")
    parser.add_argument("--keep-generated-tests", action="store_true", help="Leave generated test files in the repo for debugging.")
    parser.add_argument("--verbose", action="store_true", help="Enable informational logs.")
    parser.add_argument("--debug", action="store_true", help="Enable debug logs, including target path resolution.")
    args = parser.parse_args(argv)
    _configure_logging(args.verbose, args.debug)

    output_dir = Path(args.output_dir).resolve()
    excel_path = Path(args.excel_path).resolve() if args.excel_path else output_dir / "test_cases.xlsx"
    state: AgentState = {
        "repo_path": args.repo,
        "stack": args.stack,
        "output_dir": str(output_dir),
        "excel_path": str(excel_path),
        "errors": [],
        "skip_runner": args.skip_runner,
        "skip_fixes": args.skip_fixes,
        "rerun_all_tests": args.rerun_all_tests,
        "reuse_existing_tests": args.reuse_existing_tests,
        "max_input_tokens": args.max_input_tokens,
        "agent1_model": args.agent1_model,
        "agent3_model": args.agent3_model,
        "keep_generated_tests": args.keep_generated_tests,
        "legacy_generator": args.legacy_generator,
        "coverage": args.coverage,
    }

    final_state = state
    exit_code = 0
    if args.analyze_only:
        try:
            final_state = _run_analysis_only(state)
            return exit_code
        finally:
            _cleanup_after_run(final_state, keep_generated_tests=True)
            _print_final_state(final_state)

    if args.plan_only:
        try:
            final_state = _run_plan_only(state)
            return exit_code
        finally:
            _cleanup_after_run(final_state, keep_generated_tests=True)
            _print_final_state(final_state)

    if args.validate_only:
        try:
            final_state = _run_validation_only(state)
            return exit_code
        finally:
            _cleanup_after_run(final_state, keep_generated_tests=True)
            _print_final_state(final_state)

    if args.runner_only:
        try:
            final_state = test_runner_node(state)
            if not args.skip_fixes:
                final_state = fix_suggester_node(final_state)
            return exit_code
        finally:
            _cleanup_after_run(final_state, args.keep_generated_tests)
            _print_final_state(final_state)

    try:
        graph = build_graph(str(output_dir))
        thread_id = args.thread_id or f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        final_state = graph.invoke(state, config={"configurable": {"thread_id": thread_id}})
        return exit_code
    finally:
        _cleanup_after_run(final_state, args.keep_generated_tests)
        _print_final_state(final_state)


def _configure_logging(verbose: bool, debug: bool) -> None:
    if debug:
        level = logging.DEBUG
    elif verbose:
        level = logging.INFO
    else:
        level = logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s:%(name)s:%(message)s")


def _run_analysis_only(state: AgentState) -> AgentState:
    final_state = repository_analyzer_node(state)
    final_state["generation_chunk_count"] = 0
    final_state["generated_test_count"] = 0
    return final_state


def _run_plan_only(state: AgentState) -> AgentState:
    final_state = repository_analyzer_node(state)
    final_state = test_planner_node(final_state)
    return assertion_generator_node(final_state)


def _run_validation_only(state: AgentState) -> AgentState:
    repo_path, temp_dir = materialize_repo(state["repo_path"])
    if temp_dir:
        state["temp_dir"] = temp_dir
    state["repo_path"] = repo_path
    adapter = DEFAULT_REGISTRY.detect(repo_path, state.get("stack"))
    state["adapter_name"] = adapter.name
    store = ExcelStore(state["excel_path"])
    updates = {}
    for row in store.rows():
        try:
            from multiagent_testing.agents.test_runner import _materialize_row_test_file

            path = _materialize_row_test_file(adapter, repo_path, row)
            updates[str(row["test_id"])] = {
                "test_file_path": str(path),
                "test_code": row.get("test_code"),
                "validation_status": row.get("validation_status"),
                "validation_errors": row.get("validation_errors"),
                "repairs_applied": row.get("repairs_applied"),
            }
        except Exception as exc:
            updates[str(row.get("test_id") or "")] = {
                "validation_status": "Error",
                "validation_errors": str(exc),
            }
    store.bulk_update_by_test_id({key: value for key, value in updates.items() if key})
    from multiagent_testing.agents.test_runner import _write_execution_reports

    _write_execution_reports(Path(state.get("output_dir") or Path(state["excel_path"]).parent), store.rows())
    state["failing_count"] = 0
    state["generated_test_count"] = len(updates)
    return state


def _cleanup_after_run(final_state: AgentState, keep_generated_tests: bool) -> None:
    repo_path = final_state.get("repo_path")
    logger = logging.getLogger(__name__)
    if repo_path and not keep_generated_tests:
        try:
            deleted = cleanup_generated_test_files(repo_path)
            logger.info("Deleted %s generated test file(s).", deleted)
        except OSError as exc:
            logger.warning("Failed to clean generated test files in %s: %s", repo_path, exc)
    try:
        cleanup_temp_dir(final_state.get("temp_dir"))
    except OSError as exc:
        logger.warning("Failed to clean temp dir %s: %s", final_state.get("temp_dir"), exc)


def _print_final_state(final_state: AgentState) -> None:
    print(f"Excel: {final_state.get('excel_path')}")
    print(f"Output dir: {final_state.get('output_dir')}")
    print(f"Adapter: {final_state.get('adapter_name')}")
    print(f"Discovered units: {final_state.get('discovered_unit_count', 0)}")
    print(f"Generation chunks: {final_state.get('generation_chunk_count', 0)}")
    print(f"Generated tests: {final_state.get('generated_test_count', 0)}")
    if final_state.get("repository_graph_path"):
        print(f"Repository graph: {final_state.get('repository_graph_path')}")
    if final_state.get("test_plan_path"):
        print(f"Test plan: {final_state.get('test_plan_path')}")
    if final_state.get("assertion_blocks_path"):
        print(f"Assertion blocks: {final_state.get('assertion_blocks_path')}")
    if final_state.get("coverage"):
        print("Coverage: enabled")
    if final_state.get("empty_generation_batch_count"):
        print(f"Empty generation batches: {final_state.get('empty_generation_batch_count')}")
    confidence_summary = _confidence_summary(final_state.get("excel_path"))
    if confidence_summary:
        print(f"Confidence: avg {confidence_summary['average']} across {confidence_summary['count']} scored test(s)")
    print(f"Failing tests: {final_state.get('failing_count', 0)}")
    errors = final_state.get("errors") or []
    if errors:
        print("Warnings:")
        for error in errors[-5:]:
            print(f"- {error}")


def _confidence_summary(excel_path: str | None) -> dict[str, float | int] | None:
    if not excel_path or not Path(excel_path).exists():
        return None
    try:
        rows = ExcelStore(excel_path).rows()
    except Exception:
        return None
    scores = []
    for row in rows:
        try:
            scores.append(float(row.get("confidence_score")))
        except (TypeError, ValueError):
            continue
    if not scores:
        return None
    return {"average": round(sum(scores) / len(scores), 2), "count": len(scores)}


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

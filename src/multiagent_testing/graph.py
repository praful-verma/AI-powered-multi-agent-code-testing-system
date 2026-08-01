from __future__ import annotations

from pathlib import Path

from multiagent_testing.agents import (
    assertion_generator_node,
    fix_suggester_node,
    repository_analyzer_node,
    test_builder_node,
    test_generator_node,
    test_planner_node,
    test_runner_node,
)
from multiagent_testing.models import AgentState


def build_graph(output_dir: str | None = None):
    from langgraph.graph import END, StateGraph

    graph = StateGraph(AgentState)
    graph.add_node("repository_analyzer", repository_analyzer_node)
    graph.add_node("test_generator", test_generator_node)
    graph.add_node("test_planner", test_planner_node)
    graph.add_node("assertion_generator", assertion_generator_node)
    graph.add_node("test_builder", test_builder_node)
    graph.add_node("test_runner", test_runner_node)
    graph.add_node("fix_suggester", fix_suggester_node)

    graph.set_entry_point("repository_analyzer")
    graph.add_conditional_edges(
        "repository_analyzer",
        _route_after_analysis,
        {
            "test_generator": "test_generator",
            "test_planner": "test_planner",
        },
    )
    graph.add_edge("test_planner", "assertion_generator")
    graph.add_edge("assertion_generator", "test_builder")
    graph.add_edge("test_builder", "test_runner")
    graph.add_edge("test_generator", "test_runner")
    graph.add_conditional_edges(
        "test_runner",
        _route_after_runner,
        {
            "fix_suggester": "fix_suggester",
            "end": END,
        },
    )
    graph.add_edge("fix_suggester", END)
    return graph.compile(checkpointer=_checkpoint(output_dir))


def _route_after_analysis(state: AgentState) -> str:
    if state.get("legacy_generator"):
        return "test_generator"
    return "test_planner"


def _route_after_runner(state: AgentState) -> str:
    if state.get("skip_fixes") or int(state.get("failing_count") or 0) == 0:
        return "end"
    return "fix_suggester"


def _checkpoint(output_dir: str | None):
    if not output_dir:
        return None
    checkpoint_dir = Path(output_dir) / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    try:
        import sqlite3

        from langgraph.checkpoint.sqlite import SqliteSaver

        connection = sqlite3.connect(str(checkpoint_dir / "state.sqlite"), check_same_thread=False)
        return SqliteSaver(connection)
    except Exception:
        try:
            from langgraph.checkpoint.memory import MemorySaver

            return MemorySaver()
        except Exception:
            return None

from __future__ import annotations

import json
from pathlib import Path

from multiagent_testing.analyzer import analyze_repository
from multiagent_testing.models import AgentState
from multiagent_testing.repo_loader import materialize_repo




def repository_analyzer_node(state: AgentState) -> AgentState:
    original_repo = state.get("original_repo") or state.get("repo_path")
    repo_path, temp_dir = materialize_repo(state["repo_path"])
    state["repo_path"] = repo_path
    state["original_repo"] = original_repo or repo_path
    if temp_dir:
        state["temp_dir"] = temp_dir

    output_dir = Path(state.get("output_dir") or "runs").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    graph = analyze_repository(repo_path, state.get("stack"))
    graph_path = output_dir / "repository_graph.json"
    graph_path.write_text(json.dumps(graph.to_dict(), indent=2), encoding="utf-8")

    errors = list(state.get("errors", []))
    errors.extend(graph.warnings)
    state.update(
        {
            "repo_path": repo_path,
            "original_repo": state.get("original_repo", repo_path),
            "output_dir": str(output_dir),
            "adapter_name": graph.stack,
            "repository_graph_path": str(graph_path),
            "repository_graph": graph.to_dict(),
            "discovered_unit_count": len(graph.units),
            "errors": errors,
        }
    )
    return state

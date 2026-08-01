from __future__ import annotations

import re

from multiagent_testing.analyzer.models import CallEdge, UnitNode


CALL_RE = re.compile(r"\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)\s*\(")
IGNORED_CALLEES = {"if", "for", "while", "switch", "catch", "function", "describe", "it", "test", "expect"}


def extract_calls_for_unit(unit: UnitNode) -> list[CallEdge]:
    edges: list[CallEdge] = []
    for offset, line in enumerate(unit.source.splitlines(), start=unit.start_line):
        for match in CALL_RE.finditer(line):
            callee = match.group(1)
            if callee.split(".", 1)[0] in IGNORED_CALLEES:
                continue
            edges.append(CallEdge(caller_id=unit.id, callee=callee, line=offset))
    return _dedupe_edges(edges)


def _dedupe_edges(edges: list[CallEdge]) -> list[CallEdge]:
    seen: set[tuple[str, str, int]] = set()
    unique: list[CallEdge] = []
    for edge in edges:
        key = (edge.caller_id, edge.callee, edge.line)
        if key in seen:
            continue
        seen.add(key)
        unique.append(edge)
    return unique

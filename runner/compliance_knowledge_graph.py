"""In-memory directed graph for explainable regulatory impact analysis."""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    relation: str
    metadata: dict[str, Any]


class ComplianceKnowledgeGraph:
    def __init__(self) -> None:
        self._out: dict[str, list[GraphEdge]] = {}
        self._in: dict[str, list[GraphEdge]] = {}

    def link(self, source: str, target: str, relation: str, **metadata: Any) -> GraphEdge:
        edge = GraphEdge(source, target, relation, metadata)
        self._out.setdefault(source, []).append(edge)
        self._in.setdefault(target, []).append(edge)
        return edge

    def affected(self, node: str, relation: str | None = None) -> list[GraphEdge]:
        seen, result, queue = {node}, [], deque([node])
        while queue:
            current = queue.popleft()
            for edge in self._out.get(current, ()):
                if relation is None or edge.relation == relation:
                    result.append(edge)
                if edge.target not in seen:
                    seen.add(edge.target); queue.append(edge.target)
        return result

    def shortest_path(self, source: str, target: str) -> list[GraphEdge]:
        queue, parent = deque([source]), {source: None}
        while queue:
            current = queue.popleft()
            if current == target: break
            for edge in self._out.get(current, ()):
                if edge.target not in parent:
                    parent[edge.target] = edge; queue.append(edge.target)
        if target not in parent: return []
        path: list[GraphEdge] = []
        while parent[target] is not None:
            edge = parent[target]; path.append(edge); target = edge.source
        return list(reversed(path))

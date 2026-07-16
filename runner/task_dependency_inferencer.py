"""Task dependency inference via historical sequence analysis.

Analyzes past task execution sequences to build a dependency graph.
Uses co-occurrence and temporal ordering to predict prerequisites.
"""

import logging
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Optional

log = logging.getLogger(__name__)


class DependencyGraph:
    """Directed graph of task type dependencies with confidence scores."""

    def __init__(self):
        self._edges: Dict[str, Dict[str, float]] = defaultdict(dict)
        self._nodes: Set[str] = set()

    def add_edge(self, prerequisite: str, dependent: str, weight: float = 1.0):
        self._nodes.add(prerequisite)
        self._nodes.add(dependent)
        self._edges[dependent][prerequisite] = weight

    def get_prerequisites(self, task_type: str) -> Dict[str, float]:
        return dict(self._edges.get(task_type, {}))

    def has_cycle(self) -> Optional[List[str]]:
        visited, rec_stack, path = set(), set(), []
        def dfs(node):
            visited.add(node); rec_stack.add(node); path.append(node)
            for prereq in self._edges.get(node, {}):
                if prereq not in visited:
                    cycle = dfs(prereq)
                    if cycle is not None: return cycle
                elif prereq in rec_stack:
                    return path[path.index(prereq):] + [prereq]
            path.pop(); rec_stack.discard(node)
            return None
        for node in self._nodes:
            if node not in visited:
                cycle = dfs(node)
                if cycle is not None: return cycle
        return None

    @property
    def nodes(self) -> Set[str]: return set(self._nodes)
    @property
    def edge_count(self) -> int: return sum(len(d) for d in self._edges.values())


class TaskDependencyInferencer:
    """Infers task dependencies from historical execution sequences."""

    def __init__(self, min_confidence: float = 0.5, min_observations: int = 2):
        self._pair_counts: Dict[Tuple[str, str], int] = defaultdict(int)
        self._type_counts: Dict[str, int] = defaultdict(int)
        self._sequence_count = 0
        self._min_confidence = min_confidence
        self._min_observations = min_observations
        self._graph: Optional[DependencyGraph] = None

    def observe_sequence(self, task_types: List[str]):
        self._sequence_count += 1
        self._graph = None
        for t in task_types: self._type_counts[t] += 1
        for i in range(len(task_types)):
            for j in range(i + 1, len(task_types)):
                self._pair_counts[(task_types[i], task_types[j])] += 1

    def build_graph(self) -> DependencyGraph:
        if self._graph is not None: return self._graph
        graph = DependencyGraph()
        seen = set()
        for (a, b) in self._pair_counts:
            key = tuple(sorted([a, b]))
            if key in seen: continue
            seen.add(key)
            fwd = self._pair_counts.get((a, b), 0)
            bwd = self._pair_counts.get((b, a), 0)
            total = fwd + bwd
            if total < self._min_observations: continue
            conf = fwd / total
            if conf >= self._min_confidence: graph.add_edge(a, b, conf)
            elif (1 - conf) >= self._min_confidence: graph.add_edge(b, a, 1 - conf)
        cycle = graph.has_cycle()
        if cycle: log.warning("Cycle: %s", " -> ".join(cycle))
        self._graph = graph
        return graph

    def predict_dependencies(self, task_type: str) -> Set[str]:
        return set(self.build_graph().get_prerequisites(task_type).keys())

    def predict_dependencies_with_confidence(self, task_type: str) -> Dict[str, float]:
        return self.build_graph().get_prerequisites(task_type)

    @property
    def known_types(self) -> Set[str]: return set(self._type_counts.keys())
    @property
    def sequence_count(self) -> int: return self._sequence_count

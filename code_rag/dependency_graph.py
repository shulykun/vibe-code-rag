from __future__ import annotations

"""
Простейший граф зависимостей между сущностями кода.

MVP:
- храним связи "from -> to" без глубокого анализа;
- API для запросов входящих/исходящих зависимостей.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Set


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    kind: str  # e.g. "calls", "uses", "implements"


class DependencyGraph:
    def __init__(self) -> None:
        self._outgoing: Dict[str, List[Edge]] = {}
        self._incoming: Dict[str, List[Edge]] = {}

    def add_edge(self, source: str, target: str, kind: str = "uses") -> None:
        edge = Edge(source=source, target=target, kind=kind)
        self._outgoing.setdefault(source, []).append(edge)
        self._incoming.setdefault(target, []).append(edge)

    def outgoing(self, node: str) -> List[Edge]:
        return list(self._outgoing.get(node, ()))

    def incoming(self, node: str) -> List[Edge]:
        return list(self._incoming.get(node, ()))

    def impacted_by_change(self, node: str, max_depth: int = 3) -> Set[str]:
        """
        Простейшая эвристика "что сломается, если изменить node".
        Возвращает множество узлов, зависящих от node (по входящим рёбрам).
        """
        impacted: Set[str] = set()
        frontier: Set[str] = {node}

        for _ in range(max_depth):
            new_frontier: Set[str] = set()
            for n in frontier:
                for edge in self.incoming(n):
                    if edge.source not in impacted:
                        impacted.add(edge.source)
                        new_frontier.add(edge.source)
            if not new_frontier:
                break
            frontier = new_frontier

        return impacted


__all__ = ["Edge", "DependencyGraph"]


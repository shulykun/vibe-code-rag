from __future__ import annotations

"""Тесты для DependencyGraph."""

import pytest

from code_rag.dependency_graph import DependencyGraph, Edge


def test_add_and_query_edges() -> None:
    g = DependencyGraph()
    g.add_edge("A", "B", kind="uses")
    g.add_edge("A", "C", kind="calls")
    g.add_edge("D", "B", kind="uses")

    assert len(g.outgoing("A")) == 2
    assert len(g.incoming("B")) == 2
    assert len(g.incoming("C")) == 1
    assert g.incoming("Z") == []
    assert g.outgoing("Z") == []


def test_impacted_by_change_direct() -> None:
    g = DependencyGraph()
    g.add_edge("B", "A", kind="uses")  # B зависит от A
    g.add_edge("C", "A", kind="uses")  # C зависит от A

    impacted = g.impacted_by_change("A", max_depth=1)
    assert "B" in impacted
    assert "C" in impacted
    assert "A" not in impacted


def test_impacted_by_change_transitive() -> None:
    g = DependencyGraph()
    # цепочка: D -> C -> B -> A
    g.add_edge("B", "A", kind="uses")
    g.add_edge("C", "B", kind="uses")
    g.add_edge("D", "C", kind="uses")

    impacted_d1 = g.impacted_by_change("A", max_depth=1)
    assert "B" in impacted_d1
    assert "C" not in impacted_d1

    impacted_d3 = g.impacted_by_change("A", max_depth=3)
    assert "B" in impacted_d3
    assert "C" in impacted_d3
    assert "D" in impacted_d3


def test_impacted_by_change_with_cycle() -> None:
    """Граф с циклом не должен зависать."""
    g = DependencyGraph()
    g.add_edge("A", "B", kind="uses")
    g.add_edge("B", "A", kind="uses")  # цикл

    impacted = g.impacted_by_change("A", max_depth=5)
    # Не зависает, возвращает конечное множество
    assert isinstance(impacted, set)


def test_empty_graph_impacted() -> None:
    g = DependencyGraph()
    assert g.impacted_by_change("nonexistent", max_depth=3) == set()


def test_edge_kinds_preserved() -> None:
    g = DependencyGraph()
    g.add_edge("X", "Y", kind="calls")
    g.add_edge("X", "Y", kind="uses")

    out = g.outgoing("X")
    kinds = {e.kind for e in out}
    assert "calls" in kinds
    assert "uses" in kinds

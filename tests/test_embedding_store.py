from __future__ import annotations

"""Тесты для InMemoryEmbeddingStore."""

import numpy as np
import pytest

from code_rag.embedding_store import InMemoryEmbeddingStore, ScoredItem


def _vec(values: list[float]) -> np.ndarray:
    v = np.array(values, dtype=np.float32)
    return v / (np.linalg.norm(v) + 1e-8)


def test_search_returns_closest_vector() -> None:
    store = InMemoryEmbeddingStore()
    v_a = _vec([1.0, 0.0, 0.0])
    v_b = _vec([0.0, 1.0, 0.0])
    v_c = _vec([0.0, 0.0, 1.0])

    store.add([
        ("a", v_a, {"label": "A"}),
        ("b", v_b, {"label": "B"}),
        ("c", v_c, {"label": "C"}),
    ])

    results = store.search(v_a, top_k=1)
    assert len(results) == 1
    assert results[0].id == "a"
    assert results[0].score > 0.99


def test_search_top_k_limit() -> None:
    store = InMemoryEmbeddingStore()
    for i in range(10):
        store.add([(f"id_{i}", _vec([float(i), 1.0]), {"i": i})])

    results = store.search(_vec([1.0, 0.0]), top_k=3)
    assert len(results) == 3


def test_search_empty_store_returns_empty() -> None:
    store = InMemoryEmbeddingStore()
    results = store.search(_vec([1.0, 0.0, 0.0]), top_k=5)
    assert results == []


def test_payload_preserved() -> None:
    store = InMemoryEmbeddingStore()
    v = _vec([1.0, 2.0, 3.0])
    store.add([("x", v, {"location": "Foo.java:10-20", "module": "core"})])

    results = store.search(v, top_k=1)
    assert results[0].payload["location"] == "Foo.java:10-20"
    assert results[0].payload["module"] == "core"


def test_scores_ordered_descending() -> None:
    store = InMemoryEmbeddingStore()
    query = _vec([1.0, 0.0])
    store.add([
        ("close", _vec([1.0, 0.01]), {}),
        ("far", _vec([0.0, 1.0]), {}),
        ("medium", _vec([1.0, 0.5]), {}),
    ])

    results = store.search(query, top_k=3)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)

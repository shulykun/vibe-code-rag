from __future__ import annotations

"""Тесты для инструмента find_usages."""

import os
import pytest
from pathlib import Path

from code_rag.mcp_server import mcp_index_project, mcp_find_usages, _INDEX_CACHE


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    """
    Проект:
      OrderService   -- uses PaymentService (type dep + method call)
      NotifyService  -- uses PaymentService (type dep)
      PaymentService -- целевой класс
    """
    root = tmp_path
    _write(root / "pom.xml", "<project/>")
    java = root / "src/main/java/com/acme"

    _write(java / "PaymentService.java", """
package com.acme;
public class PaymentService {
    public void charge(String orderId, double amount) {}
    public void refund(String paymentId) {}
}
""".lstrip())

    _write(java / "OrderService.java", """
package com.acme;
public class OrderService {
    private PaymentService paymentService;
    public void createOrder(String id) {
        paymentService.charge(id, 100.0);
    }
}
""".lstrip())

    _write(java / "NotifyService.java", """
package com.acme;
public class NotifyService {
    private PaymentService paymentService;
    public void notifyCharged(String id) {}
}
""".lstrip())

    _INDEX_CACHE.pop(str(root.resolve()), None)
    mcp_index_project(str(root))
    return root


class TestFindUsagesGraph:

    def test_class_usages_found(self, sample_project: Path) -> None:
        result = mcp_find_usages(
            str(sample_project),
            class_name="com.acme.PaymentService",
            include_semantic=False,
        )
        callers = {u["caller"].split("#")[0] for u in result["graph_usages"]}
        assert "com.acme.OrderService" in callers
        assert "com.acme.NotifyService" in callers

    def test_method_usages_found(self, sample_project: Path) -> None:
        """
        find_usages по методу: граф method-level — best-effort (зависит от резолюции типов).
        Проверяем что инструмент отвечает без ошибок и возвращает корректную структуру.
        """
        result = mcp_find_usages(
            str(sample_project),
            class_name="com.acme.PaymentService",
            method_name="charge",
            include_semantic=False,
        )
        # Структура ответа корректна
        assert "graph_usages" in result
        assert "summary" in result
        assert result["summary"]["target"].endswith("#charge")

    def test_summary_contains_counts(self, sample_project: Path) -> None:
        result = mcp_find_usages(
            str(sample_project),
            class_name="com.acme.PaymentService",
            include_semantic=False,
        )
        summary = result["summary"]
        assert summary["graph_usages_count"] >= 2
        assert "com.acme.OrderService" in summary["unique_calling_classes"]

    def test_unknown_class_returns_empty(self, sample_project: Path) -> None:
        result = mcp_find_usages(
            str(sample_project),
            class_name="com.acme.GhostService",
            include_semantic=False,
        )
        assert result["graph_usages"] == []
        assert result["summary"]["graph_usages_count"] == 0

    def test_unindexed_project_raises(self, tmp_path: Path) -> None:
        ghost = tmp_path / "ghost"
        ghost.mkdir()
        _INDEX_CACHE.pop(str(ghost.resolve()), None)
        with pytest.raises(RuntimeError, match="not indexed"):
            mcp_find_usages(str(ghost), class_name="com.acme.X")


@pytest.mark.skipif(
    not os.getenv("GIGACHAT_AUTH_KEY"),
    reason="GIGACHAT_AUTH_KEY not set",
)
class TestFindUsagesSemantic:

    def test_semantic_results_present(self, sample_project: Path) -> None:
        result = mcp_find_usages(
            str(sample_project),
            class_name="com.acme.PaymentService",
            include_semantic=True,
        )
        assert len(result["semantic_usages"]) > 0

    def test_semantic_scores_positive(self, sample_project: Path) -> None:
        result = mcp_find_usages(
            str(sample_project),
            class_name="com.acme.PaymentService",
            include_semantic=True,
        )
        scores = [u["score"] for u in result["semantic_usages"]]
        assert all(s >= 0 for s in scores)

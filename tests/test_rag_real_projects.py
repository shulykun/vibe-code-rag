from __future__ import annotations

"""
Интеграционные RAG-тесты на реальных Java-проектах.

Требуют:
  - GIGACHAT_AUTH_KEY (иначе скипаются)
  - Клонированные репозитории в ../

Проекты:
  - Train-Ticket-Reservation-System (сервлеты, без Spring)
  - jasome (Gradle, доменная модель, калькуляторы метрик)
  - BankingPortal-API (Spring Boot, JWT, полный стек)
"""

import os
import pytest
from pathlib import Path

from code_rag.mcp_server import (
    mcp_index_project,
    mcp_project_query,
    mcp_find_usages,
    mcp_explain_architecture,
    _INDEX_CACHE,
)

PROJECTS_DIR = Path(__file__).resolve().parents[2]

requires_gigachat = pytest.mark.skipif(
    not os.getenv("GIGACHAT_AUTH_KEY"),
    reason="GIGACHAT_AUTH_KEY not set",
)


def _project(name: str) -> Path:
    return PROJECTS_DIR / name


def _skip_if_missing(name: str):
    return pytest.mark.skipif(
        not _project(name).exists(),
        reason=f"{name} not cloned locally",
    )


def _index(name: str) -> str:
    root = str(_project(name))
    _INDEX_CACHE.pop(str(_project(name).resolve()), None)
    mcp_index_project(root)
    return root


# ── Train-Ticket-Reservation-System ──────────────────────────────────────────

@requires_gigachat
@_skip_if_missing("Train-Ticket-Reservation-System")
class TestTrainTicketRAG:

    @pytest.fixture(scope="class")
    def root(self):
        return _index("Train-Ticket-Reservation-System")

    def test_semantic_search_finds_booking(self, root):
        res = mcp_project_query(root, "бронирование билета", top_k=5)
        classes = [r.get("location", "") for r in res["results"]]
        assert any("Book" in c or "booking" in c.lower() for c in classes), \
            f"Expected booking-related chunk, got: {classes}"

    def test_semantic_search_finds_user_auth(self, root):
        res = mcp_project_query(root, "user login authentication", top_k=5)
        results = res["results"]
        assert len(results) > 0
        scores = [r["score"] for r in results]
        assert scores[0] > 0.5, f"Low relevance score: {scores[0]:.3f}"

    def test_find_usages_train_service(self, root):
        result = mcp_find_usages(
            root,
            class_name="com.shashi.service.TrainService",
            include_semantic=True,
        )
        assert result["summary"]["graph_usages_count"] > 0 or \
               len(result["semantic_usages"]) > 0, \
            "TrainService should be referenced somewhere"

    def test_explain_architecture_booking_flow(self, root):
        result = mcp_explain_architecture(root, "train booking and ticket reservation")
        assert "flow_text" in result
        assert len(result["chunks"]) > 0
        # Должен найти что-то связанное с бронированием
        text = result["flow_text"]
        assert any(word in text for word in ["Book", "Train", "Service", "Ticket"])


# ── jasome ───────────────────────────────────────────────────────────────────

@requires_gigachat
@_skip_if_missing("jasome")
class TestJasomeRAG:

    @pytest.fixture(scope="class")
    def root(self):
        return _index("jasome")

    def test_semantic_search_finds_calculator(self, root):
        res = mcp_project_query(root, "calculate cyclomatic complexity", top_k=5)
        classes = [r.get("location", "") for r in res["results"]]
        assert any("Calculator" in c or "Cyclomatic" in c for c in classes), \
            f"Expected Calculator chunk, got: {classes}"

    def test_semantic_search_finds_metric(self, root):
        res = mcp_project_query(root, "metric value numeric", top_k=5)
        results = res["results"]
        assert len(results) > 0
        scores = [r["score"] for r in results]
        assert scores[0] > 0.6

    def test_find_usages_calculator_interface(self, root):
        result = mcp_find_usages(
            root,
            class_name="org.jasome.metrics.Calculator",
            include_semantic=False,
        )
        # Calculator — центральный интерфейс, должен иметь много зависимостей
        assert result["summary"]["graph_usages_count"] >= 5, \
            f"Calculator should have many usages, got: {result['summary']['graph_usages_count']}"

    def test_explain_architecture_metrics_calculation(self, root):
        result = mcp_explain_architecture(root, "how metrics are calculated for Java code")
        assert len(result["chunks"]) > 0
        # В топе должны быть Calculator или Metric
        top_classes = {c["class"] for c in result["chunks"][:5]}
        assert any("Calculator" in cls or "Metric" in cls for cls in top_classes), \
            f"Expected Calculator/Metric in top chunks, got: {top_classes}"

    def test_explain_architecture_returns_layers(self, root):
        result = mcp_explain_architecture(root, "project scanning and file parsing")
        assert "layers" in result
        assert len(result["layers"]) > 0


# ── BankingPortal-API ─────────────────────────────────────────────────────────

@requires_gigachat
@_skip_if_missing("BankingPortal-API")
class TestBankingPortalRAG:

    @pytest.fixture(scope="class")
    def root(self):
        return _index("BankingPortal-API")

    def test_semantic_search_finds_transfer(self, root):
        res = mcp_project_query(root, "fund transfer between accounts", top_k=5)
        classes = [r.get("location", "") for r in res["results"]]
        assert any("Account" in c or "Transfer" in c for c in classes), \
            f"Expected Account/Transfer chunk, got: {classes}"

    def test_semantic_search_finds_otp(self, root):
        res = mcp_project_query(root, "OTP verification one time password", top_k=5)
        results = res["results"]
        assert len(results) > 0
        scores = [r["score"] for r in results]
        assert scores[0] > 0.6, f"Low relevance: {scores[0]:.3f}"

    def test_find_usages_account_service(self, root):
        result = mcp_find_usages(
            root,
            class_name="com.webapp.bankingportal.service.AccountService",
            include_semantic=True,
        )
        summary = result["summary"]
        assert summary["graph_usages_count"] > 0 or len(result["semantic_usages"]) > 0

    def test_find_usages_account_service_has_controller(self, root):
        result = mcp_find_usages(
            root,
            class_name="com.webapp.bankingportal.service.AccountService",
            include_semantic=False,
        )
        callers = result["summary"]["unique_calling_classes"]
        assert any("Controller" in c or "Impl" in c for c in callers), \
            f"AccountService should be used by Controller or Impl: {callers}"

    def test_explain_architecture_authentication(self, root):
        result = mcp_explain_architecture(root, "JWT authentication and token validation")
        text = result["flow_text"]
        assert any(word in text for word in ["Token", "Auth", "Jwt", "Security"])
        assert len(result["chunks"]) > 0

    def test_explain_architecture_returns_service_layer(self, root):
        result = mcp_explain_architecture(root, "account balance and transactions")
        layers = result["layers"]
        assert "service" in layers or "Service" in str(layers), \
            f"Service layer expected, got: {list(layers.keys())}"

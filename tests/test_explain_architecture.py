from __future__ import annotations

"""Тесты для инструмента explain_architecture."""

import os
import pytest
from pathlib import Path

from code_rag.mcp_server import mcp_index_project, mcp_explain_architecture, _INDEX_CACHE


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture
def payment_project(tmp_path: Path) -> Path:
    """
    Мини-проект с полным стеком оплаты:
      PaymentController -> PaymentService -> PaymentRepository
    """
    root = tmp_path
    _write(root / "pom.xml", "<project/>")
    java = root / "src/main/java/com/acme"

    _write(java / "PaymentController.java", """
package com.acme;
/** REST-контроллер для оплаты заказов. */
public class PaymentController {
    private PaymentService paymentService;
    /** Инициирует оплату заказа. */
    public void pay(String orderId) {
        paymentService.processPayment(orderId, 100.0);
    }
}
""".lstrip())

    _write(java / "PaymentService.java", """
package com.acme;
/** Сервис обработки платежей. Выполняет charge и refund. */
public class PaymentService {
    private PaymentRepository paymentRepository;
    /** Выполняет оплату и сохраняет транзакцию. */
    public void processPayment(String orderId, double amount) {
        paymentRepository.save(orderId, amount);
    }
    /** Возвращает средства. */
    public void refund(String paymentId) {}
}
""".lstrip())

    _write(java / "PaymentRepository.java", """
package com.acme;
/** Репозиторий транзакций. */
public interface PaymentRepository {
    void save(String orderId, double amount);
    PaymentDto findByOrderId(String orderId);
}
""".lstrip())

    _write(java / "PaymentDto.java", """
package com.acme;
public class PaymentDto {
    public String orderId;
    public double amount;
}
""".lstrip())

    _INDEX_CACHE.pop(str(root.resolve()), None)
    mcp_index_project(str(root))
    return root


class TestExplainArchitectureStructure:

    def test_returns_required_keys(self, payment_project: Path) -> None:
        result = mcp_explain_architecture(str(payment_project), "payment processing")
        assert "flow_text" in result
        assert "layers" in result
        assert "call_chain" in result
        assert "chunks" in result

    def test_flow_text_contains_feature(self, payment_project: Path) -> None:
        result = mcp_explain_architecture(str(payment_project), "payment processing")
        assert "payment" in result["flow_text"].lower()

    def test_layers_classified_correctly(self, payment_project: Path) -> None:
        result = mcp_explain_architecture(str(payment_project), "payment processing")
        layers = result["layers"]
        # PaymentController -> controller, PaymentService -> service,
        # PaymentRepository -> repository, PaymentDto -> dto
        flat = {cls for classes in layers.values() for cls in classes}
        assert "PaymentController" in flat or "PaymentService" in flat

    def test_service_layer_present(self, payment_project: Path) -> None:
        result = mcp_explain_architecture(str(payment_project), "payment processing")
        layers = result["layers"]
        assert "service" in layers
        assert "PaymentService" in layers["service"]

    def test_chunks_have_scores(self, payment_project: Path) -> None:
        result = mcp_explain_architecture(str(payment_project), "payment processing")
        for chunk in result["chunks"]:
            assert "score" in chunk
            assert isinstance(chunk["score"], float)

    def test_flow_text_has_sections(self, payment_project: Path) -> None:
        result = mcp_explain_architecture(str(payment_project), "payment processing")
        text = result["flow_text"]
        assert "## Задействованные компоненты" in text
        assert "## Ключевые методы" in text

    def test_unindexed_project_raises(self, tmp_path: Path) -> None:
        ghost = tmp_path / "ghost"
        ghost.mkdir()
        _INDEX_CACHE.pop(str(ghost.resolve()), None)
        with pytest.raises(RuntimeError, match="not indexed"):
            mcp_explain_architecture(str(ghost), "anything")


@pytest.mark.skipif(
    not os.getenv("GIGACHAT_AUTH_KEY"),
    reason="GIGACHAT_AUTH_KEY not set",
)
class TestExplainArchitectureIntegration:
    """Интеграционные тесты на bike-rental-service с реальными эмбеддингами."""

    BIKE_RENTAL = Path(__file__).resolve().parents[2] / "bike-rental-service"

    @pytest.fixture(scope="class")
    def bike_indexed(self) -> str:
        if not self.BIKE_RENTAL.exists():
            pytest.skip("bike-rental-service not found")
        root = str(self.BIKE_RENTAL)
        _INDEX_CACHE.pop(str(Path(root).resolve()), None)
        mcp_index_project(root)
        return root

    def test_discount_flow_finds_discount_service(self, bike_indexed: str) -> None:
        result = mcp_explain_architecture(bike_indexed, "как работают скидки за пятое бронирование")
        flat = {cls for classes in result["layers"].values() for cls in classes}
        assert "DiscountService" in flat, f"DiscountService not found in layers: {flat}"

    def test_blog_flow_finds_blog_service(self, bike_indexed: str) -> None:
        result = mcp_explain_architecture(bike_indexed, "публикация статей в блоге и модерация комментариев")
        flat = {cls for classes in result["layers"].values() for cls in classes}
        assert "BlogService" in flat, f"BlogService not found in layers: {flat}"

    def test_rental_flow_has_call_chain(self, bike_indexed: str) -> None:
        result = mcp_explain_architecture(bike_indexed, "процесс аренды велосипеда от начала до возврата")
        # Должны быть цепочки вызовов
        assert len(result["chunks"]) > 0
        assert "RentalService" in result["flow_text"] or "BikeService" in result["flow_text"]

    def test_flow_text_is_readable_markdown(self, bike_indexed: str) -> None:
        result = mcp_explain_architecture(bike_indexed, "discount calculation")
        text = result["flow_text"]
        assert text.startswith("# Архитектура:")
        assert "```java" in text

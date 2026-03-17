from __future__ import annotations

"""
Интеграционные тесты GigaChat Embeddings API.

Запускаются только если задан GIGACHAT_AUTH_KEY.
Требуют GIGACHAT_VERIFY_SSL=false для самоподписанного сертификата Sber.

Запуск:
  GIGACHAT_AUTH_KEY=... GIGACHAT_VERIFY_SSL=false pytest tests/test_embeddings_integration.py -v
"""

import os
import pytest
import numpy as np

from code_rag.embeddings_client import GigaChatEmbeddingsClient

# Скипаем весь модуль если ключа нет
pytestmark = pytest.mark.skipif(
    not os.getenv("GIGACHAT_AUTH_KEY"),
    reason="GIGACHAT_AUTH_KEY not set — skipping GigaChat integration tests",
)


@pytest.fixture(scope="module")
def client() -> GigaChatEmbeddingsClient:
    return GigaChatEmbeddingsClient.from_env()


def test_single_text_returns_1024_dim(client: GigaChatEmbeddingsClient) -> None:
    vecs = client.embed_texts(["Hello, Java world!"])
    assert len(vecs) == 1
    assert len(vecs[0]) == 1024


def test_multiple_texts_returns_correct_count(client: GigaChatEmbeddingsClient) -> None:
    texts = [
        "public class OrderService {}",
        "public void createOrder(OrderDto dto) {}",
        "@Transactional annotation in Spring",
    ]
    vecs = client.embed_texts(texts)
    assert len(vecs) == len(texts)
    for v in vecs:
        assert len(v) == 1024


def test_vectors_are_normalized_ish(client: GigaChatEmbeddingsClient) -> None:
    """GigaChat возвращает не нормализованные векторы, но они должны быть конечными."""
    vecs = client.embed_texts(["test normalization"])
    v = vecs[0]
    assert np.all(np.isfinite(v)), "Vector contains NaN or Inf"
    norm = np.linalg.norm(v)
    assert norm > 0, "Zero vector returned"


def test_similar_texts_closer_than_dissimilar(client: GigaChatEmbeddingsClient) -> None:
    """Семантически похожие тексты должны быть ближе друг к другу."""
    texts = [
        "UserService creates a new user",
        "UserService registers a user account",   # похоже на первый
        "SELECT * FROM orders WHERE status = 'PAID'",  # сильно отличается
    ]
    vecs = client.embed_texts(texts)

    def cosine(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))

    sim_close = cosine(vecs[0], vecs[1])
    sim_far = cosine(vecs[0], vecs[2])
    assert sim_close > sim_far, (
        f"Expected similar texts to be closer: sim_close={sim_close:.3f}, sim_far={sim_far:.3f}"
    )


def test_token_refresh_on_second_call(client: GigaChatEmbeddingsClient) -> None:
    """Два последовательных вызова работают без ошибок (токен переиспользуется)."""
    vecs1 = client.embed_texts(["first call"])
    vecs2 = client.embed_texts(["second call"])
    assert len(vecs1) == 1
    assert len(vecs2) == 1


def test_empty_input_returns_empty(client: GigaChatEmbeddingsClient) -> None:
    vecs = client.embed_texts([])
    assert vecs == []


def test_indexer_uses_real_embeddings(tmp_path) -> None:
    """
    Полный пайплайн: индексация Java-проекта с реальными эмбеддингами от GigaChat.
    Проверяем что поиск возвращает семантически релевантные результаты.
    """
    from pathlib import Path
    from code_rag.mcp_server import mcp_index_project, mcp_project_query, _INDEX_CACHE

    root = tmp_path
    (root / "pom.xml").write_text("<project/>")

    java_dir = root / "src/main/java/com/demo"
    java_dir.mkdir(parents=True)

    (java_dir / "PaymentService.java").write_text("""
package com.demo;
public class PaymentService {
    public void processPayment(String orderId, double amount) {
        // charge the card
    }
    public void refund(String paymentId) {
        // refund transaction
    }
}
""")
    (java_dir / "UserRepository.java").write_text("""
package com.demo;
public class UserRepository {
    public User findByEmail(String email) {
        return null;
    }
    public void save(User user) {}
}
""")

    # Индексируем с реальными эмбеддингами
    _INDEX_CACHE.pop(str(root.resolve()), None)
    info = mcp_index_project(str(root))
    assert info["chunks_count"] > 0

    # Ищем по семантически близкому запросу
    result = mcp_project_query(str(root), query="payment processing and charging", top_k=3)
    hits = result["results"]
    assert len(hits) > 0

    # PaymentService должен быть в топе
    locations = [h.get("location", "") for h in hits]
    assert any("PaymentService" in loc for loc in locations), (
        f"Expected PaymentService in top results, got: {locations}"
    )

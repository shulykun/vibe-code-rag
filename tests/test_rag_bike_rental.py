from __future__ import annotations

"""
Интеграционные RAG-тесты на проекте bike-rental-service.

Проверяют что семантический поиск находит правильные классы/методы
для бизнес-запросов. Требуют GIGACHAT_AUTH_KEY.
"""

import os
import pytest
from pathlib import Path

from code_rag.indexer import index_project, project_query

BIKE_RENTAL_PATH = Path(__file__).resolve().parents[2] / "bike-rental-service"

pytestmark = pytest.mark.skipif(
    not os.getenv("GIGACHAT_AUTH_KEY"),
    reason="GIGACHAT_AUTH_KEY not set",
)

pytestmark = [
    pytest.mark.skipif(
        not os.getenv("GIGACHAT_AUTH_KEY"),
        reason="GIGACHAT_AUTH_KEY not set",
    ),
    pytest.mark.skipif(
        not BIKE_RENTAL_PATH.exists(),
        reason="bike-rental-service project not found",
    ),
]


@pytest.fixture(scope="module")
def indexed():
    return index_project(BIKE_RENTAL_PATH)


def top_classes(indexed, query: str, top_k: int = 5) -> list[str]:
    results = project_query(indexed, query, top_k=top_k)
    return [indexed.chunks[r.chunk_id].metadata.get("class", "") for r in results]


def top_methods(indexed, query: str, top_k: int = 5) -> list[str]:
    results = project_query(indexed, query, top_k=top_k)
    return [indexed.chunks[r.chunk_id].metadata.get("name", "") for r in results]


def top_scores(indexed, query: str, top_k: int = 3) -> list[float]:
    results = project_query(indexed, query, top_k=top_k)
    return [r.score for r in results]


class TestDiscountRAG:
    """RAG должен находить DiscountService при запросах о скидках."""

    def test_discount_every_fifth_rental(self, indexed):
        classes = top_classes(indexed, "скидка за каждое пятое бронирование")
        assert "DiscountService" in classes, f"Expected DiscountService, got: {classes}"

    def test_discount_applicable_method(self, indexed):
        methods = top_methods(indexed, "проверить положена ли скидка клиенту")
        assert "isDiscountApplicable" in methods or "applyDiscount" in methods, \
            f"Expected discount method, got: {methods}"

    def test_discount_scores_above_threshold(self, indexed):
        scores = top_scores(indexed, "discount 20 percent every fifth rental")
        assert scores[0] > 0.70, f"Expected score > 0.70, got: {scores[0]:.3f}"


class TestBlogRAG:
    """RAG должен находить BlogService при запросах о блоге."""

    def test_publish_post_found(self, indexed):
        classes = top_classes(indexed, "публикация статьи в блоге")
        assert "BlogService" in classes or "BlogController" in classes, \
            f"Expected BlogService/Controller, got: {classes}"

    def test_comment_moderation_found(self, indexed):
        classes = top_classes(indexed, "одобрение и отклонение комментариев модерация")
        assert "BlogService" in classes, f"Expected BlogService, got: {classes}"

    def test_slug_generation_found(self, indexed):
        methods = top_methods(indexed, "генерация slug из заголовка статьи")
        assert "generateSlug" in methods, f"Expected generateSlug, got: {methods}"

    def test_blog_scores_above_threshold(self, indexed):
        scores = top_scores(indexed, "blog post publish article")
        assert scores[0] > 0.75, f"Expected score > 0.75, got: {scores[0]:.3f}"


class TestRentalWithDiscountRAG:
    """RAG находит связь аренды со скидкой."""

    def test_rental_applies_discount_on_return(self, indexed):
        classes = top_classes(indexed, "применение скидки при возврате велосипеда")
        # RentalService.returnBike теперь вызывает discountService
        assert "RentalService" in classes or "DiscountService" in classes, \
            f"Expected RentalService or DiscountService, got: {classes}"

    def test_overall_chunk_count(self, indexed):
        """После добавления блога и скидок проект должен содержать >150 чанков."""
        assert len(indexed.chunks) > 150, \
            f"Expected >150 chunks, got: {len(indexed.chunks)}"

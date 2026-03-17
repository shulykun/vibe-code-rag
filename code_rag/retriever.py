from __future__ import annotations

"""
Комбинированный ретривер:
- поиск по ключевым словам/символам (пока заглушка);
- семантический поиск по EmbeddingStore;
- объединение и ранжирование результатов.
"""

from dataclasses import dataclass
from typing import List

from .embedding_store import EmbeddingStore, ScoredItem, Vector


@dataclass
class RetrievalResult:
    chunk_id: str
    score: float
    metadata: dict


class Retriever:
    def __init__(self, store: EmbeddingStore) -> None:
        self.store = store

    def search_by_vector(self, vector: Vector, top_k: int = 10) -> List[RetrievalResult]:
        items: List[ScoredItem] = self.store.search(vector, top_k=top_k)
        return [
            RetrievalResult(
                chunk_id=item.id,
                score=item.score,
                metadata=item.payload,
            )
            for item in items
        ]


__all__ = ["Retriever", "RetrievalResult"]


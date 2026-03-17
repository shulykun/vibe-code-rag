from __future__ import annotations

"""
Базовый RAG-пайплайн.

MVP:
- принимает текстовый запрос и уже посчитанный эмбеддинг;
- вытаскивает top-K чанков через Retriever;
- готовит структуру для промпта LLM (без реального вызова модели).
"""

from dataclasses import dataclass
from typing import List

from .retriever import Retriever, RetrievalResult
from .embedding_store import Vector


@dataclass
class RagContext:
    query: str
    results: List[RetrievalResult]

    def to_prompt_text(self) -> str:
        """
        Готовит текстовый контекст для LLM.
        Пока делаем очень простой формат.
        """
        lines = [f"User query: {self.query}", "", "Relevant code chunks:"]
        for r in self.results:
            meta = r.metadata
            location = meta.get("location", r.chunk_id)
            lines.append(f"- [{r.score:.3f}] {location}")
        return "\n".join(lines)


class RagOrchestrator:
    def __init__(self, retriever: Retriever) -> None:
        self.retriever = retriever

    def build_context(self, query: str, query_embedding: Vector, top_k: int = 10) -> RagContext:
        results = self.retriever.search_by_vector(query_embedding, top_k=top_k)
        return RagContext(query=query, results=results)


__all__ = ["RagOrchestrator", "RagContext"]


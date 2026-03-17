from __future__ import annotations

"""
Интерфейс к векторному стору (Qdrant и др.).

MVP:
- определяем абстракцию EmbeddingStore;
- делаем простую in-memory реализацию, чтобы можно было тестировать без Qdrant.
"""

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

import numpy as np

try:
    import chromadb
    from chromadb import PersistentClient as ChromaClient
except Exception:  # pragma: no cover - опциональная зависимость
    chromadb = None
    ChromaClient = None  # type: ignore


Vector = np.ndarray


@dataclass
class ScoredItem:
    id: str
    score: float
    payload: dict


class EmbeddingStore:
    def add(self, items: Sequence[Tuple[str, Vector, dict]]) -> None:
        raise NotImplementedError

    def search(self, vector: Vector, top_k: int = 10) -> List[ScoredItem]:
        raise NotImplementedError


class InMemoryEmbeddingStore(EmbeddingStore):
    def __init__(self) -> None:
        self._vectors: Dict[str, Vector] = {}
        self._payloads: Dict[str, dict] = {}

    def add(self, items: Sequence[Tuple[str, Vector, dict]]) -> None:
        for item_id, vec, payload in items:
            self._vectors[item_id] = vec
            self._payloads[item_id] = payload

    def search(self, vector: Vector, top_k: int = 10) -> List[ScoredItem]:
        if not self._vectors:
            return []

        ids = list(self._vectors.keys())
        matrix = np.stack([self._vectors[i] for i in ids], axis=0)

        # косинусная близость
        vec_norm = vector / (np.linalg.norm(vector) + 1e-8)
        mat_norm = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-8)
        scores = mat_norm @ vec_norm

        top_idx = np.argsort(-scores)[:top_k]
        return [
            ScoredItem(
                id=ids[int(i)],
                score=float(scores[int(i)]),
                payload=self._payloads[ids[int(i)]],
            )
            for i in top_idx
        ]


class ChromaEmbeddingStore(EmbeddingStore):
    """
    Простая обертка над ChromaDB.

    Храним:
    - ids — идентификаторы чанков;
    - embeddings — numpy-векторы;
    - metadatas — payload (dict).
    """

    def __init__(self, path: str, collection_name: str = "code_rag") -> None:
        if ChromaClient is None:  # pragma: no cover
            raise RuntimeError(
                "chromadb is not available. Install 'chromadb' to use ChromaEmbeddingStore."
            )

        self._client = ChromaClient(path=path)
        self._collection = self._client.get_or_create_collection(
            name=collection_name, metadata={"hnsw:space": "cosine"}
        )

    def add(self, items: Sequence[Tuple[str, Vector, dict]]) -> None:
        if not items:
            return
        ids = [item_id for item_id, _vec, _payload in items]
        embeddings = [vec.tolist() for _id, vec, _payload in items]
        metadatas = [payload for _id, _vec, payload in items]
        self._collection.add(ids=ids, embeddings=embeddings, metadatas=metadatas)

    def search(self, vector: Vector, top_k: int = 10) -> List[ScoredItem]:
        if self._collection.count() == 0:
            return []
        res = self._collection.query(
            query_embeddings=[vector.tolist()],
            n_results=top_k,
            include=["metadatas", "distances"],
        )
        ids = res.get("ids", [[]])[0]
        metadatas = res.get("metadatas", [[]])[0]
        distances = res.get("distances", [[]])[0]

        results: List[ScoredItem] = []
        for _id, meta, dist in zip(ids, metadatas, distances):
            score = float(1.0 - dist)  # cosine distance -> similarity
            results.append(ScoredItem(id=_id, score=score, payload=meta or {}))
        return results


__all__ = [
    "EmbeddingStore",
    "InMemoryEmbeddingStore",
    "ChromaEmbeddingStore",
    "ScoredItem",
    "Vector",
]


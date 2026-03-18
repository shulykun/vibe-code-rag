from __future__ import annotations

"""
Локальные эмбеддинги через sentence-transformers.

Не требует API-ключей и интернет-соединения после первой загрузки модели.
Модель скачивается автоматически при первом использовании (~330MB).

Рекомендуемые модели:
  jina-embeddings-v2-base-code  — специализирована на коде, 768-dim, 8192 токенов
  nomic-embed-text              — общий текст, 768-dim, быстрая
  all-MiniLM-L6-v2              — маленькая 384-dim, самая быстрая

Переменные окружения:
  CODE_RAG_LOCAL_MODEL  — имя модели (по умолчанию jinaai/jina-embeddings-v2-base-code)
  CODE_RAG_LOCAL_DEVICE — устройство: cpu / cuda / mps (по умолчанию cpu)

Использование:
  export CODE_RAG_LOCAL_MODEL="jinaai/jina-embeddings-v2-base-code"
  python -m code_rag index /path/to/project
"""

import logging
import os
from typing import List, Optional, Sequence

import numpy as np

from .embedding_store import Vector

log = logging.getLogger(__name__)

DEFAULT_MODEL = "jinaai/jina-embeddings-v2-base-code"
DEFAULT_DEVICE = "cpu"
# Размерности популярных моделей
_MODEL_DIMS = {
    "jinaai/jina-embeddings-v2-base-code": 768,
    "nomic-ai/nomic-embed-text-v1": 768,
    "sentence-transformers/all-MiniLM-L6-v2": 384,
    "sentence-transformers/all-mpnet-base-v2": 768,
}


class LocalEmbeddingsClient:
    """
    Клиент локальных эмбеддингов через sentence-transformers.

    Ленивая инициализация — модель загружается при первом вызове embed_texts().
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str = DEFAULT_DEVICE,
        batch_size: int = 32,
        normalize: bool = True,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self.normalize = normalize
        self._model = None  # ленивая загрузка

    @classmethod
    def from_env(cls) -> "LocalEmbeddingsClient":
        model = os.getenv("CODE_RAG_LOCAL_MODEL", DEFAULT_MODEL)
        device = os.getenv("CODE_RAG_LOCAL_DEVICE", DEFAULT_DEVICE)
        return cls(model_name=model, device=device)

    def _load_model(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise RuntimeError(
                "sentence-transformers не установлен. "
                "Установите: pip install sentence-transformers"
            )
        log.info("Загрузка модели %s на %s...", self.model_name, self.device)
        trust_remote = "jina" in self.model_name  # jina требует trust_remote_code
        self._model = SentenceTransformer(
            self.model_name,
            device=self.device,
            trust_remote_code=trust_remote,
        )
        log.info("Модель загружена: dim=%d", self.embedding_dim)

    @property
    def embedding_dim(self) -> int:
        if self._model is not None:
            return self._model.get_sentence_embedding_dimension()
        return _MODEL_DIMS.get(self.model_name, 768)

    def embed_texts(self, texts: Sequence[str]) -> List[Vector]:
        """
        Вычисляет эмбеддинги локально.

        Первый вызов загружает модель (~330MB для jina, ~90MB для MiniLM).
        Последующие вызовы быстрые — модель в памяти.
        """
        if not texts:
            return []

        self._load_model()
        texts_list = list(texts)

        log.debug("Embedding %d texts locally with %s", len(texts_list), self.model_name)

        embeddings = self._model.encode(
            texts_list,
            batch_size=self.batch_size,
            normalize_embeddings=self.normalize,
            show_progress_bar=len(texts_list) > 50,
        )

        return [np.array(e, dtype=np.float32) for e in embeddings]


def is_local_mode() -> bool:
    """True если задан CODE_RAG_LOCAL_MODEL или явно выбран локальный режим."""
    return bool(os.getenv("CODE_RAG_LOCAL_MODEL"))


__all__ = ["LocalEmbeddingsClient", "is_local_mode", "DEFAULT_MODEL"]

from __future__ import annotations

"""
Клиент для получения эмбеддингов через внешний API.

Сейчас ориентирован на формат из embeddings_api.md (Gigachat-like):

POST https://gigachat.devices.sberbank.ru/api/v1/embeddings
Headers:
  Content-Type: application/json
  Authorization: Bearer <токен доступа>
Body:
{
  "model": "Embeddings",
  "input": ["text1", "text2", ...]
}

Фактический URL/модель/токен берутся из окружения, чтобы не хардкодить секреты.
"""

import os
from dataclasses import dataclass
from typing import List, Sequence

import httpx
import numpy as np

from .embedding_store import Vector


DEFAULT_EMBEDDINGS_URL = "https://gigachat.devices.sberbank.ru/api/v1/embeddings"


@dataclass
class EmbeddingsConfig:
    api_url: str
    api_token: str
    model: str = "Embeddings"

    @classmethod
    def from_env(cls) -> "EmbeddingsConfig":
        return cls(
            api_url=os.getenv("CODE_RAG_EMBEDDINGS_URL", DEFAULT_EMBEDDINGS_URL),
            api_token=os.getenv("CODE_RAG_EMBEDDINGS_TOKEN", ""),
            model=os.getenv("CODE_RAG_EMBEDDINGS_MODEL", "Embeddings"),
        )


class EmbeddingsClient:
    def __init__(self, config: EmbeddingsConfig | None = None) -> None:
        self.config = config or EmbeddingsConfig.from_env()
        if not self.config.api_token:
            raise RuntimeError(
                "Embeddings API token is not set. "
                "Set CODE_RAG_EMBEDDINGS_TOKEN in environment."
            )

    def embed_texts(self, texts: Sequence[str]) -> List[Vector]:
        """
        Вызывает внешний API и возвращает список numpy-векторов.
        """
        if not texts:
            return []

        payload = {
            "model": self.config.model,
            "input": list(texts),
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_token}",
        }

        with httpx.Client(timeout=30.0) as client:
            resp = client.post(self.config.api_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        # Ожидаем, что API вернет список векторов в data["data"][i]["embedding"]
        vectors: List[Vector] = []
        items = data.get("data") or []
        for item in items:
            emb = item.get("embedding")
            if emb is None:
                continue
            vectors.append(np.array(emb, dtype=np.float32))

        return vectors


__all__ = ["EmbeddingsClient", "EmbeddingsConfig"]


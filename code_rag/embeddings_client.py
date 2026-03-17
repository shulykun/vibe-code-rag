from __future__ import annotations

"""
Клиент для получения эмбеддингов через GigaChat API.

Авторизация: OAuth2 (client credentials).

Переменные окружения:
  GIGACHAT_AUTH_KEY   — Authorization key (Basic, base64-строка из личного кабинета)
  GIGACHAT_SCOPE      — scope (по умолчанию GIGACHAT_API_PERS)
  GIGACHAT_VERIFY_SSL — "false" чтобы отключить проверку сертификата (самоподписанный)

Пример:
  export GIGACHAT_AUTH_KEY="OGZiNmQw..."
  python -m code_rag index /path/to/project
"""

import os
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

import httpx
import numpy as np

from .embedding_store import Vector

log = logging.getLogger(__name__)

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
EMBEDDINGS_URL = "https://gigachat.devices.sberbank.ru/api/v1/embeddings"
EMBEDDINGS_MODEL = "Embeddings"


@dataclass
class _TokenCache:
    access_token: str = ""
    expires_at: float = 0.0  # unix timestamp

    def is_valid(self, margin_sec: float = 60.0) -> bool:
        return bool(self.access_token) and time.time() < self.expires_at - margin_sec


@dataclass
class GigaChatEmbeddingsClient:
    """
    Клиент для GigaChat Embeddings с автоматическим обновлением OAuth-токена.
    """

    auth_key: str  # Basic key из личного кабинета Sber
    scope: str = "GIGACHAT_API_PERS"
    verify_ssl: bool = True
    _token: _TokenCache = field(default_factory=_TokenCache, init=False, repr=False)

    # ── OAuth ────────────────────────────────────────────────────────────────

    def _fetch_token(self) -> None:
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
            "Authorization": f"Basic {self.auth_key}",
        }
        data = {"scope": self.scope}

        with httpx.Client(verify=self.verify_ssl, timeout=15.0) as client:
            resp = client.post(OAUTH_URL, headers=headers, data=data)
            resp.raise_for_status()
            body = resp.json()

        self._token.access_token = body["access_token"]
        # expires_at приходит в миллисекундах
        expires_at_ms = body.get("expires_at", 0)
        self._token.expires_at = expires_at_ms / 1000.0 if expires_at_ms > 1e10 else expires_at_ms
        log.debug("GigaChat token refreshed, expires_at=%s", self._token.expires_at)

    def _ensure_token(self) -> str:
        if not self._token.is_valid():
            self._fetch_token()
        return self._token.access_token

    # ── Embeddings ───────────────────────────────────────────────────────────

    def embed_texts(self, texts: Sequence[str], batch_size: int = 5,
                    max_chars_per_batch: int = 10_000) -> List[Vector]:
        """
        Получает эмбеддинги батчами с ограничением по числу символов.

        GigaChat ограничивает размер запроса — при длинных чанках даже батч из 5 текстов
        может превысить лимит. Батч разбивается так чтобы суммарный размер
        не превышал max_chars_per_batch символов.
        """
        if not texts:
            return []

        all_vectors: List[Vector] = []
        texts_list = list(texts)
        i = 0

        while i < len(texts_list):
            batch: List[str] = []
            chars = 0
            while i < len(texts_list) and len(batch) < batch_size:
                t = texts_list[i]
                if batch and chars + len(t) > max_chars_per_batch:
                    break
                batch.append(t)
                chars += len(t)
                i += 1

            vectors = self._embed_batch(batch)
            all_vectors.extend(vectors)
            log.debug("Embedded batch of %d texts (%d chars)", len(batch), chars)

        return all_vectors

    def _embed_batch(self, texts: List[str]) -> List[Vector]:
        token = self._ensure_token()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        payload = {"model": EMBEDDINGS_MODEL, "input": texts}

        with httpx.Client(verify=self.verify_ssl, timeout=30.0) as client:
            resp = client.post(EMBEDDINGS_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        vectors: List[Vector] = []
        for item in data.get("data") or []:
            emb = item.get("embedding")
            if emb is not None:
                v = np.array(emb, dtype=np.float32)
                v = v / (np.linalg.norm(v) + 1e-8)  # L2-нормализация
                vectors.append(v)

        if len(vectors) != len(texts):
            raise RuntimeError(
                f"GigaChat returned {len(vectors)} embeddings for {len(texts)} texts"
            )
        return vectors

    # ── Factory ──────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "GigaChatEmbeddingsClient":
        auth_key = os.getenv("GIGACHAT_AUTH_KEY", "")
        if not auth_key:
            raise RuntimeError(
                "GIGACHAT_AUTH_KEY is not set. "
                "Get it from https://developers.sber.ru/portal/products/gigachat"
            )
        scope = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
        verify_ssl = os.getenv("GIGACHAT_VERIFY_SSL", "true").lower() != "false"
        return cls(auth_key=auth_key, scope=scope, verify_ssl=verify_ssl)


# ── Backward-compat alias (старый код импортировал EmbeddingsClient) ─────────

class EmbeddingsClient(GigaChatEmbeddingsClient):
    """Alias для обратной совместимости."""

    def __init__(self, config=None) -> None:  # type: ignore[override]
        if config is not None:
            # старый путь через EmbeddingsConfig — игнорируем, берём из env
            pass
        client = GigaChatEmbeddingsClient.from_env()
        super().__init__(
            auth_key=client.auth_key,
            scope=client.scope,
            verify_ssl=client.verify_ssl,
        )


__all__ = ["GigaChatEmbeddingsClient", "EmbeddingsClient"]

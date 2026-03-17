from __future__ import annotations

"""
Персистентный векторный стор на основе numpy + JSON.

Структура кэша (~/.code-rag/<project-hash>/):
  vectors.npy   — матрица эмбеддингов [N x dim], float32
  index.json    — метаданные: chunk_ids, payloads, file_hashes, timestamp

Инвалидация кэша:
  При индексации сохраняются SHA-256 хэши всех проиндексированных Java-файлов.
  При загрузке проверяем что хэши не изменились — если файл добавлен,
  удалён или изменён, кэш считается устаревшим и пересчитывается.
"""

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .embedding_store import EmbeddingStore, InMemoryEmbeddingStore, ScoredItem, Vector

log = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".code-rag"


def _project_hash(root: Path) -> str:
    """Стабильный идентификатор проекта по абсолютному пути."""
    return hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]


def _file_hash(path: Path) -> str:
    """SHA-256 первых 64кб файла (быстро, достаточно для детектирования изменений)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(65536))
    return h.hexdigest()[:16]


class PersistentEmbeddingStore(EmbeddingStore):
    """
    Обёртка над InMemoryEmbeddingStore с сохранением на диск.

    При создании пытается загрузить кэш. Если кэш устарел или отсутствует —
    работает как обычный InMemoryEmbeddingStore, а после заполнения его можно
    сохранить вызовом save().
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._cache_dir = CACHE_DIR / _project_hash(self._root)
        self._inner = InMemoryEmbeddingStore()
        self._loaded = False

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    # ── EmbeddingStore API ────────────────────────────────────────────

    def add(self, items: Sequence[Tuple[str, Vector, dict]]) -> None:
        self._inner.add(items)

    def search(self, vector: Vector, top_k: int = 10) -> List[ScoredItem]:
        return self._inner.search(vector, top_k=top_k)

    # ── Persistence ───────────────────────────────────────────────────

    def save(self, java_files: List[Path]) -> None:
        """
        Сохраняет эмбеддинги и метаданные на диск.

        :param java_files: список всех проиндексированных файлов
                           (используются для расчёта хэшей инвалидации)
        """
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        ids = list(self._inner._vectors.keys())
        if not ids:
            log.warning("Nothing to save — store is empty")
            return

        # Матрица векторов
        matrix = np.stack([self._inner._vectors[i] for i in ids], axis=0)
        np.save(str(self._cache_dir / "vectors.npy"), matrix)

        # Метаданные
        file_hashes = {str(p): _file_hash(p) for p in java_files if p.exists()}
        index = {
            "version": 1,
            "root": str(self._root),
            "saved_at": time.time(),
            "chunk_count": len(ids),
            "chunk_ids": ids,
            "payloads": [self._inner._payloads.get(i, {}) for i in ids],
            "file_hashes": file_hashes,
        }
        with open(self._cache_dir / "index.json", "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

        log.info(
            "Saved %d embeddings to %s (files: %d)",
            len(ids), self._cache_dir, len(file_hashes),
        )

    def load(self, java_files: List[Path]) -> bool:
        """
        Загружает кэш с диска.

        Возвращает True если кэш актуален и успешно загружен, False — иначе.
        При возврате False нужно переиндексировать и вызвать save().

        :param java_files: текущий список файлов проекта (для проверки хэшей)
        """
        vectors_path = self._cache_dir / "vectors.npy"
        index_path = self._cache_dir / "index.json"

        if not vectors_path.exists() or not index_path.exists():
            log.debug("Cache miss: files not found at %s", self._cache_dir)
            return False

        try:
            with open(index_path, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception as e:
            log.warning("Cache corrupted (index.json): %s", e)
            return False

        # Проверяем хэши файлов
        cached_hashes: Dict[str, str] = meta.get("file_hashes", {})
        current_files = {str(p) for p in java_files if p.exists()}
        cached_files = set(cached_hashes.keys())

        if current_files != cached_files:
            log.info(
                "Cache invalidated: file set changed "
                "(added: %d, removed: %d)",
                len(current_files - cached_files),
                len(cached_files - current_files),
            )
            return False

        for path_str, cached_hash in cached_hashes.items():
            actual = _file_hash(Path(path_str))
            if actual != cached_hash:
                log.info("Cache invalidated: %s changed", path_str)
                return False

        # Загружаем матрицу
        try:
            matrix = np.load(str(vectors_path))
        except Exception as e:
            log.warning("Cache corrupted (vectors.npy): %s", e)
            return False

        ids: List[str] = meta["chunk_ids"]
        payloads: List[dict] = meta.get("payloads", [{} for _ in ids])

        if len(ids) != matrix.shape[0]:
            log.warning("Cache corrupted: ids/matrix length mismatch")
            return False

        items = [(ids[i], matrix[i], payloads[i]) for i in range(len(ids))]
        self._inner.add(items)
        self._loaded = True

        log.info(
            "Cache loaded: %d embeddings from %s (saved %.0fs ago)",
            len(ids), self._cache_dir,
            time.time() - meta.get("saved_at", 0),
        )
        return True

    @property
    def is_loaded_from_cache(self) -> bool:
        return self._loaded

    def invalidate(self) -> None:
        """Удаляет кэш на диске."""
        for f in (self._cache_dir / "vectors.npy", self._cache_dir / "index.json"):
            if f.exists():
                f.unlink()
        log.info("Cache invalidated: %s", self._cache_dir)


__all__ = ["PersistentEmbeddingStore", "CACHE_DIR"]

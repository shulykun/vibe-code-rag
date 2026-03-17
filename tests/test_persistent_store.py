from __future__ import annotations

"""Тесты для PersistentEmbeddingStore."""

import numpy as np
import pytest
from pathlib import Path

from code_rag.persistent_store import PersistentEmbeddingStore


def _vec(dim: int = 4) -> np.ndarray:
    v = np.random.default_rng(42).standard_normal(dim).astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-8)


def _make_files(tmp_path: Path) -> list[Path]:
    """Создаёт несколько фиктивных java-файлов."""
    files = []
    for i in range(3):
        p = tmp_path / f"Foo{i}.java"
        p.write_text(f"public class Foo{i} {{}}")
        files.append(p)
    return files


class TestSaveLoad:

    def test_save_creates_files(self, tmp_path: Path) -> None:
        store = PersistentEmbeddingStore(tmp_path)
        store.add([("id1", _vec(), {"loc": "A.java:1"})])
        java_files = _make_files(tmp_path)
        store.save(java_files)

        assert (store.cache_dir / "vectors.npy").exists()
        assert (store.cache_dir / "index.json").exists()

    def test_load_restores_vectors(self, tmp_path: Path) -> None:
        java_files = _make_files(tmp_path)
        v = _vec()

        store1 = PersistentEmbeddingStore(tmp_path)
        store1.add([("id1", v, {"loc": "A.java:1"})])
        store1.save(java_files)

        store2 = PersistentEmbeddingStore(tmp_path)
        loaded = store2.load(java_files)

        assert loaded is True
        assert store2.is_loaded_from_cache is True

        results = store2.search(v, top_k=1)
        assert len(results) == 1
        assert results[0].id == "id1"
        assert results[0].score > 0.99

    def test_load_returns_false_if_no_cache(self, tmp_path: Path) -> None:
        java_files = _make_files(tmp_path)
        store = PersistentEmbeddingStore(tmp_path)
        assert store.load(java_files) is False

    def test_cache_invalidated_when_file_changed(self, tmp_path: Path) -> None:
        java_files = _make_files(tmp_path)

        store1 = PersistentEmbeddingStore(tmp_path)
        store1.add([("id1", _vec(), {})])
        store1.save(java_files)

        # Изменяем один файл
        java_files[0].write_text("public class Modified {}")

        store2 = PersistentEmbeddingStore(tmp_path)
        assert store2.load(java_files) is False

    def test_cache_invalidated_when_file_added(self, tmp_path: Path) -> None:
        java_files = _make_files(tmp_path)

        store1 = PersistentEmbeddingStore(tmp_path)
        store1.add([("id1", _vec(), {})])
        store1.save(java_files)

        # Добавляем новый файл
        new_file = tmp_path / "NewClass.java"
        new_file.write_text("public class NewClass {}")
        java_files.append(new_file)

        store2 = PersistentEmbeddingStore(tmp_path)
        assert store2.load(java_files) is False

    def test_invalidate_removes_files(self, tmp_path: Path) -> None:
        java_files = _make_files(tmp_path)
        store = PersistentEmbeddingStore(tmp_path)
        store.add([("id1", _vec(), {})])
        store.save(java_files)

        store.invalidate()

        assert not (store.cache_dir / "vectors.npy").exists()
        assert not (store.cache_dir / "index.json").exists()

    def test_payload_preserved_after_load(self, tmp_path: Path) -> None:
        java_files = _make_files(tmp_path)
        payload = {"location": "Foo.java:10-20", "module": "core", "kind": "method"}

        store1 = PersistentEmbeddingStore(tmp_path)
        store1.add([("id1", _vec(), payload)])
        store1.save(java_files)

        store2 = PersistentEmbeddingStore(tmp_path)
        store2.load(java_files)
        results = store2.search(_vec(), top_k=1)

        assert results[0].payload["location"] == "Foo.java:10-20"
        assert results[0].payload["kind"] == "method"


class TestIndexerCache:
    """Проверяем что index_project использует кэш."""

    def test_second_call_uses_cache(self, tmp_path: Path) -> None:
        from code_rag.indexer import index_project

        root = tmp_path
        (root / "pom.xml").write_text("<project/>")
        java = root / "src/main/java/com/acme"
        java.mkdir(parents=True)
        (java / "Foo.java").write_text("package com.acme; public class Foo { void bar() {} }")

        # Первый вызов — индексируем и сохраняем кэш
        idx1 = index_project(root, use_cache=True)
        assert len(idx1.chunks) > 0

        # Второй вызов — должен загрузить из кэша (нет обращений к GigaChat)
        idx2 = index_project(root, use_cache=True)
        assert len(idx2.chunks) == len(idx1.chunks)

    def test_force_no_cache(self, tmp_path: Path) -> None:
        from code_rag.indexer import index_project

        root = tmp_path
        (root / "pom.xml").write_text("<project/>")
        java = root / "src/main/java/com/acme"
        java.mkdir(parents=True)
        (java / "Bar.java").write_text("package com.acme; public class Bar {}")

        idx = index_project(root, use_cache=False)
        assert len(idx.chunks) > 0

from __future__ import annotations

"""
Тесты для LocalEmbeddingsClient.

Интеграционные тесты (с реальной загрузкой модели) скипаются
если sentence-transformers не установлен.
"""

import os
import pytest
import numpy as np

# Проверяем наличие sentence-transformers
try:
    import sentence_transformers
    HAS_ST = True
except ImportError:
    HAS_ST = False

requires_st = pytest.mark.skipif(
    not HAS_ST,
    reason="sentence-transformers not installed (pip install sentence-transformers)",
)


class TestLocalEmbeddingsClientUnit:
    """Unit-тесты без загрузки модели."""

    def test_from_env_default_model(self, monkeypatch):
        monkeypatch.delenv("CODE_RAG_LOCAL_MODEL", raising=False)
        monkeypatch.delenv("CODE_RAG_LOCAL_DEVICE", raising=False)
        from code_rag.local_embeddings import LocalEmbeddingsClient, DEFAULT_MODEL
        client = LocalEmbeddingsClient.from_env()
        assert client.model_name == DEFAULT_MODEL
        assert client.device == "cpu"

    def test_from_env_custom_model(self, monkeypatch):
        monkeypatch.setenv("CODE_RAG_LOCAL_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        monkeypatch.setenv("CODE_RAG_LOCAL_DEVICE", "cpu")
        from code_rag.local_embeddings import LocalEmbeddingsClient
        client = LocalEmbeddingsClient.from_env()
        assert client.model_name == "sentence-transformers/all-MiniLM-L6-v2"

    def test_is_local_mode_false_by_default(self, monkeypatch):
        monkeypatch.delenv("CODE_RAG_LOCAL_MODEL", raising=False)
        from code_rag.local_embeddings import is_local_mode
        assert is_local_mode() is False

    def test_is_local_mode_true_when_set(self, monkeypatch):
        monkeypatch.setenv("CODE_RAG_LOCAL_MODEL", "some-model")
        from code_rag.local_embeddings import is_local_mode
        assert is_local_mode() is True

    def test_embed_empty_returns_empty(self):
        from code_rag.local_embeddings import LocalEmbeddingsClient
        client = LocalEmbeddingsClient()
        assert client.embed_texts([]) == []

    def test_known_model_dims(self):
        from code_rag.local_embeddings import _MODEL_DIMS
        assert _MODEL_DIMS["jinaai/jina-embeddings-v2-base-code"] == 768
        assert _MODEL_DIMS["sentence-transformers/all-MiniLM-L6-v2"] == 384


@requires_st
class TestLocalEmbeddingsIntegration:
    """Интеграционные тесты — загружают MiniLM (~90MB, быстро)."""

    MODEL = "sentence-transformers/all-MiniLM-L6-v2"  # маленькая, для CI

    @pytest.fixture(scope="class")
    def client(self):
        from code_rag.local_embeddings import LocalEmbeddingsClient
        return LocalEmbeddingsClient(model_name=self.MODEL, device="cpu")

    def test_single_text(self, client):
        vecs = client.embed_texts(["Hello Java world"])
        assert len(vecs) == 1
        assert len(vecs[0]) == 384
        assert np.linalg.norm(vecs[0]) == pytest.approx(1.0, abs=0.01)

    def test_multiple_texts(self, client):
        texts = ["public class Service {}", "void method() {}", "@Transactional"]
        vecs = client.embed_texts(texts)
        assert len(vecs) == 3
        for v in vecs:
            assert len(v) == 384

    def test_semantic_similarity(self, client):
        """Похожие тексты должны быть ближе чем несвязанные."""
        vecs = client.embed_texts([
            "public class UserService { void createUser() {} }",
            "public class UserManager { void addUser() {} }",    # похоже
            "CREATE TABLE orders (id INT PRIMARY KEY)",           # другое
        ])
        sim_close = float(np.dot(vecs[0], vecs[1]))
        sim_far = float(np.dot(vecs[0], vecs[2]))
        assert sim_close > sim_far, \
            f"Expected similar texts closer: close={sim_close:.3f}, far={sim_far:.3f}"

    def test_normalized_output(self, client):
        vecs = client.embed_texts(["test normalization"])
        norm = np.linalg.norm(vecs[0])
        assert norm == pytest.approx(1.0, abs=0.01)

    def test_embedding_dim_property(self, client):
        client._load_model()
        assert client.embedding_dim == 384


@requires_st
class TestIndexerWithLocalModel:
    """Проверяем что indexer корректно использует локальную модель."""

    def test_indexer_uses_local_when_env_set(self, tmp_path, monkeypatch):
        monkeypatch.setenv(
            "CODE_RAG_LOCAL_MODEL",
            "sentence-transformers/all-MiniLM-L6-v2",
        )
        monkeypatch.delenv("GIGACHAT_AUTH_KEY", raising=False)

        (tmp_path / "pom.xml").write_text("<project/>")
        java = tmp_path / "src/main/java/com/test"
        java.mkdir(parents=True)
        (java / "Service.java").write_text(
            "package com.test; public class Service { void run() {} }"
        )

        from code_rag.indexer import index_project, project_query
        indexed = index_project(tmp_path, use_cache=False)

        assert len(indexed.chunks) > 0

        # Проверяем что поиск работает
        results = project_query(indexed, "service run method", top_k=3)
        assert len(results) > 0
        # Скоры должны быть реальными (не детерминированный шум)
        assert results[0].score > 0.3, \
            f"Expected real semantic score, got: {results[0].score:.3f}"

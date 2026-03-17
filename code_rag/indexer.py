from __future__ import annotations

"""
Локальный индексатор Java-проекта.

Использует:
- ProjectScanner — для структуры модулей и файлов;
- CodeParser + Chunker — для получения чанков;
- PersistentEmbeddingStore — хранит эмбеддинги на диск (~/.code-rag/),
  InMemoryEmbeddingStore — fallback для тестов.

Эмбеддинги: GigaChat API (если задан GIGACHAT_AUTH_KEY),
иначе — локальный детерминированный fallback.
"""

from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

from .project_scanner import ProjectScanner, ProjectLayout
from .code_parser import CodeParser
from .chunker import Chunk, Chunker
from .embedding_store import InMemoryEmbeddingStore, Vector, EmbeddingStore
from .persistent_store import PersistentEmbeddingStore
from .retriever import Retriever, RetrievalResult
from .rag_orchestrator import RagOrchestrator, RagContext
from .embeddings_client import GigaChatEmbeddingsClient
from .dependency_graph import DependencyGraph
from .dependency_extractor import (
    extract_java_symbols,
    extract_type_dependencies,
    extract_method_calls,
    primary_declared_type,
)


EMBEDDING_DIM = 1024  # GigaChat Embeddings dimension


log = logging.getLogger(__name__)


@dataclass
class IndexedProject:
    root: Path
    layout: ProjectLayout
    store: EmbeddingStore
    chunks: Dict[str, Chunk]
    graph: DependencyGraph

    def retriever(self) -> Retriever:
        return Retriever(self.store)


def _local_embed(text: str) -> Vector:
    """Детерминированный локальный эмбеддинг (fallback без API)."""
    import hashlib
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:4], "big", signed=False)
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(EMBEDDING_DIM)
    return vec / (np.linalg.norm(vec) + 1e-8)


def _embed_texts(texts: Sequence[str], client: GigaChatEmbeddingsClient | None = None) -> List[Vector]:
    """
    Получает эмбеддинги через GigaChat API батчами.
    Каждый батч, на который API вернул ошибку, переходит на локальный fallback.
    """
    if client is None:
        try:
            client = GigaChatEmbeddingsClient.from_env()
        except Exception:
            client = None

    if client is None:
        return [_local_embed(t) for t in texts]

    # Батчинг: для каждого батча пробуем API, при ошибке — fallback только для него
    texts_list = list(texts)
    all_vectors: List[Vector] = []
    i = 0
    batch_size = 3
    max_chars = 5_000

    while i < len(texts_list):
        batch: List[str] = []
        chars = 0
        while i < len(texts_list) and len(batch) < batch_size:
            t = texts_list[i]
            if batch and chars + len(t) > max_chars:
                break
            batch.append(t)
            chars += len(t)
            i += 1

        try:
            vecs = client._embed_batch(batch)
            all_vectors.extend(vecs)
        except Exception:
            # fallback только для этого батча
            all_vectors.extend(_local_embed(t) for t in batch)

    return all_vectors


def index_project(
    root: Path,
    store: EmbeddingStore | None = None,
    use_cache: bool = True,
) -> IndexedProject:
    """
    Полный локальный индекс Java-проекта.

    При use_cache=True (по умолчанию) сохраняет эмбеддинги в ~/.code-rag/<hash>/
    и переиспользует их если исходники не изменились.
    При use_cache=False или явно переданном store — работает как раньше (in-memory).

    Возвращает IndexedProject, с которым можно делать семантические запросы.
    """
    root = root.resolve()

    scanner = ProjectScanner(root)
    layout = scanner.scan()

    # Список всех java-файлов для хэширования
    all_java_files: List[Path] = [
        f for module in layout.modules for f in module.java_sources
    ]

    parser = CodeParser()
    chunker = Chunker()
    graph = DependencyGraph()

    # Выбираем стор
    persistent: Optional[PersistentEmbeddingStore] = None
    if store is not None:
        # Явно передан стор — используем его (тесты)
        pass
    elif use_cache:
        persistent = PersistentEmbeddingStore(root)
        store = persistent
    else:
        store = InMemoryEmbeddingStore()

    chunks: Dict[str, Chunk] = {}
    texts_for_embedding: List[str] = []
    chunk_ids: List[str] = []
    payloads: List[dict] = []

    for module in layout.modules:
        for java_file in module.java_sources:
            parsed = parser.parse_file(java_file)
            file_chunks: List[Chunk] = chunker.build_chunks_for_file(parsed)

            # dependency graph: class -> used types
            try:
                symbols = extract_java_symbols(parsed.tree, parsed.source)
                current_type = primary_declared_type(symbols)
                if current_type:
                    current_fqcn = (
                        f"{symbols.package}.{current_type}" if symbols.package else current_type
                    )
                    deps = extract_type_dependencies(parsed.tree, parsed.source, symbols)
                    for dep in deps:
                        graph.add_edge(current_fqcn, dep, kind="uses")

                    calls = extract_method_calls(parsed.tree, parsed.source, symbols)
                    for caller_node, targets in calls.items():
                        for target_node in targets:
                            graph.add_edge(caller_node, target_node, kind="calls")
            except Exception:
                pass

            for ch in file_chunks:
                chunks[ch.id] = ch
                texts_for_embedding.append(ch.embed_text or ch.text)
                chunk_ids.append(ch.id)
                payloads.append({
                    "location": f"{ch.file}:{ch.start_line}-{ch.end_line}",
                    "module": module.module_name,
                    "kind": ch.kind,
                })

    # Пробуем загрузить эмбеддинги из кэша
    cache_hit = False
    if persistent is not None:
        cache_hit = persistent.load(all_java_files)
        if cache_hit:
            log.info("Using cached embeddings (%d chunks)", len(chunks))

    # Если кэш не попал — считаем эмбеддинги и сохраняем
    if not cache_hit:
        if texts_for_embedding:
            vectors = _embed_texts(texts_for_embedding)
            items_to_add = [
                (cid, vec, payload)
                for cid, vec, payload in zip(chunk_ids, vectors, payloads)
            ]
            store.add(items_to_add)

        if persistent is not None:
            persistent.save(all_java_files)

    return IndexedProject(root=root, layout=layout, store=store, chunks=chunks, graph=graph)


def project_query(index: IndexedProject, query_text: str, top_k: int = 10) -> List[RetrievalResult]:
    """
    Семантический запрос по уже проиндексированному проекту.

    Эмбеддинг запроса такой же фейковый, как и для чанков.
    """
    query_vec = _embed_texts([query_text])[0]
    retriever = index.retriever()
    return retriever.search_by_vector(query_vec, top_k=top_k)


def project_rag_context(
    index: IndexedProject, query_text: str, top_k: int = 10
) -> RagContext:
    """
    Строит полный RAG-контекст (без вызова LLM) для заданного запроса.
    """
    query_vec = _embed_texts([query_text])[0]
    retriever = index.retriever()
    orchestrator = RagOrchestrator(retriever)
    return orchestrator.build_context(query=query_text, query_embedding=query_vec, top_k=top_k)


__all__ = ["IndexedProject", "index_project", "project_query", "project_rag_context", "EMBEDDING_DIM"]


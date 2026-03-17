from __future__ import annotations

"""
Локальный индексатор Java-проекта (MVP, in-memory).

Использует:
- ProjectScanner — для структуры модулей и файлов;
- CodeParser + Chunker — для получения чанков;
- InMemoryEmbeddingStore — для хранения эмбеддингов чанков.

Эмбеддинги: GigaChat API (если задан GIGACHAT_AUTH_KEY),
иначе — локальный детерминированный fallback.
"""

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Dict, List, Sequence

import numpy as np

from .project_scanner import ProjectScanner, ProjectLayout
from .code_parser import CodeParser
from .chunker import Chunk, Chunker
from .embedding_store import InMemoryEmbeddingStore, Vector, EmbeddingStore
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


EMBEDDING_DIM = 128


@dataclass
class IndexedProject:
    root: Path
    layout: ProjectLayout
    store: InMemoryEmbeddingStore
    chunks: Dict[str, Chunk]
    graph: DependencyGraph

    def retriever(self) -> Retriever:
        return Retriever(self.store)


def _embed_texts(texts: Sequence[str], client: GigaChatEmbeddingsClient | None = None) -> List[Vector]:
    """
    Пытается получить эмбеддинги через GigaChat API (если задан GIGACHAT_AUTH_KEY).
    При отсутствии ключа/ошибке — fallback на локальный детерминированный эмбеддер.
    """
    if client is None:
        try:
            client = GigaChatEmbeddingsClient.from_env()
        except Exception:
            client = None

    if client is not None:
        try:
            vectors = client.embed_texts(texts)
            if len(vectors) == len(texts):
                return vectors
        except Exception:
            # fallback на локальный режим
            pass

    # локальный fallback: детерминированный эмбеддер
    vectors: List[Vector] = []
    for t in texts:
        # Python hash() не стабилен между запусками процесса.
        # Для воспроизводимости (и тестов) используем стабильный sha256 -> 32-bit seed.
        digest = hashlib.sha256(t.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:4], "big", signed=False)
        rng = np.random.default_rng(seed)
        vec = rng.standard_normal(EMBEDDING_DIM)
        vec = vec / (np.linalg.norm(vec) + 1e-8)
        vectors.append(vec)
    return vectors


def index_project(root: Path, store: EmbeddingStore | None = None) -> IndexedProject:
    """
    Полный локальный индекс Java-проекта.

    Возвращает IndexedProject, с которым можно делать семантические запросы.
    """
    root = root.resolve()

    scanner = ProjectScanner(root)
    layout = scanner.scan()

    parser = CodeParser()
    chunker = Chunker()
    store = store or InMemoryEmbeddingStore()
    graph = DependencyGraph()

    chunks: Dict[str, Chunk] = {}
    items_to_add = []

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

                    # method call edges (best-effort)
                    calls = extract_method_calls(parsed.tree, parsed.source, symbols)
                    for caller_node, targets in calls.items():
                        for target_node in targets:
                            graph.add_edge(caller_node, target_node, kind="calls")
            except Exception:
                # граф не должен ломать индексатор
                pass

            for ch in file_chunks:
                chunks[ch.id] = ch
                texts_for_embedding.append(ch.text)
                chunk_ids.append(ch.id)
                payloads.append(
                    {
                        "location": f"{ch.file}:{ch.start_line}-{ch.end_line}",
                        "module": module.module_name,
                        "kind": ch.kind,
                    }
                )

    if texts_for_embedding:
        vectors = _embed_texts(texts_for_embedding)
        items_to_add = [
            (cid, vec, payload)
            for cid, vec, payload in zip(chunk_ids, vectors, payloads)
        ]

    if items_to_add:
        store.add(items_to_add)

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


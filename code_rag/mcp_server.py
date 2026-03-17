from __future__ import annotations

"""
Скелет MCP-сервера для code-rag.

Задача этого модуля — адаптировать внутренний API:
- indexer.index_project / project_query / project_rag_context
под формат MCP-инструментов:
- index_project
- project_query

Здесь пока нет реальной JSON-RPC/transport-обвязки — только чистые
Python-функции, которые потом можно будет обернуть в MCP-фреймворк.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import fnmatch

from .indexer import index_project, project_query, project_rag_context, IndexedProject


_INDEX_CACHE: Dict[str, IndexedProject] = {}


def _cache_key(root: Path) -> str:
    return str(root.resolve())


def mcp_index_project(
    root_path: str,
    force_reindex: bool = False,
) -> Dict[str, Any]:
    """
    MCP-инструмент: index_project

    Аргументы:
    - root_path: путь к корню Java-проекта;
    - force_reindex: если True — переиндексация даже при наличии кэша.

    Возвращает краткую информацию о проиндексированном проекте.
    """
    root = Path(root_path)
    key = _cache_key(root)

    if not force_reindex and key in _INDEX_CACHE:
        indexed = _INDEX_CACHE[key]
    else:
        indexed = index_project(root)
        _INDEX_CACHE[key] = indexed

    return {
        "root": str(indexed.root),
        "build_system": indexed.layout.build_system,
        "modules": [
            {
                "name": m.module_name,
                "root": str(m.root),
                "java_files": [str(p) for p in m.java_sources],
                "test_files": [str(p) for p in m.tests],
            }
            for m in indexed.layout.modules
        ],
        "chunks_count": len(indexed.chunks),
    }


def _get_index_or_raise(root_path: str) -> IndexedProject:
    root = Path(root_path)
    key = _cache_key(root)
    if key not in _INDEX_CACHE:
        raise RuntimeError(
            f"Project at {root} is not indexed yet. Call mcp_index_project first."
        )
    return _INDEX_CACHE[key]


def _find_module_name(index: IndexedProject, file_path: Path) -> Optional[str]:
    """
    Находит имя модуля по пути файла.
    """
    for m in index.layout.modules:
        try:
            file_path.relative_to(m.root)
        except ValueError:
            continue
        return m.module_name
    return None


def mcp_project_query(
    root_path: str,
    query: str,
    top_k: int = 10,
    with_rag_context: bool = False,
) -> Dict[str, Any]:
    """
    MCP-инструмент: project_query

    Делает семантический поиск по уже проиндексированному проекту.
    Опционально возвращает текстовый RAG-контекст.
    """
    index = _get_index_or_raise(root_path)

    results = project_query(index, query_text=query, top_k=top_k)

    payload_results: List[Dict[str, Any]] = []
    for r in results:
        payload = dict(r.metadata)
        payload.update({"chunk_id": r.chunk_id, "score": r.score})
        payload_results.append(payload)

    response: Dict[str, Any] = {
        "results": payload_results,
    }

    if with_rag_context:
        ctx = project_rag_context(index, query_text=query, top_k=top_k)
        response["rag_context"] = {
            "query": ctx.query,
            "results": [
                {
                    "chunk_id": r.chunk_id,
                    "score": r.score,
                    "metadata": r.metadata,
                }
                for r in ctx.results
            ],
            "prompt_text": ctx.to_prompt_text(),
        }

    return response


def mcp_search_code(
    root_path: str,
    query: str,
    class_filter: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    MCP-инструмент: search_code

    Простое text-based API поверх уже построенных чанков.

    - query: строка для поиска (case-insensitive substring);
    - class_filter: glob-шаблон по имени класса (например, "*Service");
    - limit: максимальное число результатов.
    """
    index = _get_index_or_raise(root_path)
    q = query.lower()

    results: List[Dict[str, Any]] = []

    for ch in index.chunks.values():
        if q not in ch.text.lower():
            continue

        meta = ch.metadata or {}
        name = meta.get("name") or ch.file.stem

        # Определяем имя класса и метода для ответа
        class_name: Optional[str] = None
        method_name: Optional[str] = None
        if ch.kind == "class":
            class_name = name
        elif ch.kind == "method":
            method_name = name
            # для метода привязываем класс по имени файла (приблизительно)
            class_name = ch.file.stem
        else:
            class_name = ch.file.stem

        if class_filter and class_name:
            if not fnmatch.fnmatch(class_name, class_filter):
                continue

        module_name = _find_module_name(index, ch.file)

        # небольшой сниппет вокруг начала чанка
        lines = ch.text.splitlines()
        snippet_lines = lines[: min(8, len(lines))]
        code_snippet = "\n".join(snippet_lines)

        results.append(
            {
                "class": class_name,
                "method": method_name,
                "code_snippet": code_snippet,
                "location": f"{ch.file}:{ch.start_line}-{ch.end_line}",
                "module": module_name,
            }
        )

        if len(results) >= limit:
            break

    return results


def mcp_analyze_impact(
    root_path: str,
    class_name: str,
    method_name: Optional[str] = None,
    max_depth: int = 2,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    MCP-инструмент: analyze_impact

    MVP-версия:
    - class_name: ожидаем FQCN (например, com.company.OrderService).
    - method_name: если задан — анализ на уровне узла "Class#method".
    - возвращает входящие зависимости (кто использует) и
      транзитивно "impacted_by_change".
    """
    index = _get_index_or_raise(root_path)
    g = index.graph

    node = f"{class_name}#{method_name}" if method_name else class_name
    incoming = g.incoming(node)
    impacted = sorted(g.impacted_by_change(node, max_depth=max_depth))

    return {
        "target": node,
        "incoming": [
            {"source": e.source, "target": e.target, "kind": e.kind} for e in incoming[:limit]
        ],
        "impacted": impacted[:limit],
        "max_depth": max_depth,
    }


__all__ = [
    "mcp_index_project",
    "mcp_project_query",
    "mcp_search_code",
    "mcp_analyze_impact",
]


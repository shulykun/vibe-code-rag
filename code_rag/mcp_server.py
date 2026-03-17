from __future__ import annotations

"""
MCP-сервер для code-rag.

Запуск:
  python -m code_rag.mcp_server

Или через __main__.py:
  python -m code_rag

Транспорт: stdio (стандарт для Claude Desktop / Cursor / Continue).
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import fnmatch

from mcp.server.fastmcp import FastMCP

from .indexer import index_project, project_query, project_rag_context, IndexedProject


mcp = FastMCP("code-rag")

_INDEX_CACHE: Dict[str, IndexedProject] = {}


def _cache_key(root: Path) -> str:
    return str(root.resolve())


def _get_index_or_raise(root_path: str) -> IndexedProject:
    root = Path(root_path)
    key = _cache_key(root)
    if key not in _INDEX_CACHE:
        raise RuntimeError(
            f"Project at {root} is not indexed yet. Call index_project first."
        )
    return _INDEX_CACHE[key]


def _find_module_name(index: IndexedProject, file_path: Path) -> Optional[str]:
    for m in index.layout.modules:
        try:
            file_path.relative_to(m.root)
        except ValueError:
            continue
        return m.module_name
    return None


# ─── Tools ────────────────────────────────────────────────────────────────────


@mcp.tool()
def index_project_tool(root_path: str, force_reindex: bool = False) -> Dict[str, Any]:
    """
    Индексирует Java-проект по указанному пути.

    Аргументы:
    - root_path: путь к корню проекта (с pom.xml или build.gradle);
    - force_reindex: принудительная переиндексация даже при наличии кэша.

    Возвращает краткую сводку: build-систему, список модулей, число чанков.
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


@mcp.tool()
def project_query_tool(
    root_path: str,
    query: str,
    top_k: int = 10,
    with_rag_context: bool = False,
) -> Dict[str, Any]:
    """
    Семантический поиск по проиндексированному проекту.

    Аргументы:
    - root_path: путь к корню проекта (должен быть проиндексирован);
    - query: текстовый запрос на естественном языке или код;
    - top_k: максимальное число результатов;
    - with_rag_context: вернуть также готовый RAG-промпт.
    """
    index = _get_index_or_raise(root_path)

    results = project_query(index, query_text=query, top_k=top_k)

    payload_results: List[Dict[str, Any]] = []
    for r in results:
        payload = dict(r.metadata)
        payload.update({"chunk_id": r.chunk_id, "score": r.score})
        payload_results.append(payload)

    response: Dict[str, Any] = {"results": payload_results}

    if with_rag_context:
        ctx = project_rag_context(index, query_text=query, top_k=top_k)
        response["rag_context"] = {
            "query": ctx.query,
            "results": [
                {"chunk_id": r.chunk_id, "score": r.score, "metadata": r.metadata}
                for r in ctx.results
            ],
            "prompt_text": ctx.to_prompt_text(),
        }

    return response


@mcp.tool()
def search_code(
    root_path: str,
    query: str,
    class_filter: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    Текстовый поиск по чанкам кода (substring, case-insensitive).

    Аргументы:
    - root_path: путь к корню проекта;
    - query: подстрока для поиска в тексте чанка;
    - class_filter: glob по имени класса (например, "*Service");
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

        class_name: Optional[str] = None
        method_name: Optional[str] = None
        if ch.kind == "class":
            class_name = name
        elif ch.kind == "method":
            method_name = name
            class_name = ch.file.stem
        else:
            class_name = ch.file.stem

        if class_filter and class_name:
            if not fnmatch.fnmatch(class_name, class_filter):
                continue

        module_name = _find_module_name(index, ch.file)
        lines = ch.text.splitlines()
        code_snippet = "\n".join(lines[: min(8, len(lines))])

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


@mcp.tool()
def analyze_impact(
    root_path: str,
    class_name: str,
    method_name: Optional[str] = None,
    max_depth: int = 2,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    Анализ влияния изменения класса или метода.

    Аргументы:
    - root_path: путь к корню проекта;
    - class_name: полное имя класса (FQCN), например com.company.OrderService;
    - method_name: имя метода (опционально) — анализ на уровне Class#method;
    - max_depth: глубина транзитивного обхода;
    - limit: максимальное число узлов в ответе.

    Возвращает прямые входящие зависимости и список всех затронутых узлов.
    """
    index = _get_index_or_raise(root_path)
    g = index.graph

    node = f"{class_name}#{method_name}" if method_name else class_name
    incoming = g.incoming(node)
    impacted = sorted(g.impacted_by_change(node, max_depth=max_depth))

    return {
        "target": node,
        "incoming": [
            {"source": e.source, "target": e.target, "kind": e.kind}
            for e in incoming[:limit]
        ],
        "impacted": impacted[:limit],
        "max_depth": max_depth,
    }


# ─── Internal helpers (не-MCP, для тестов) ────────────────────────────────────


def mcp_index_project(root_path: str, force_reindex: bool = False) -> Dict[str, Any]:
    """Совместимость с тестами — делегирует в index_project_tool."""
    return index_project_tool(root_path, force_reindex)


def mcp_project_query(root_path: str, query: str, top_k: int = 10, with_rag_context: bool = False) -> Dict[str, Any]:
    return project_query_tool(root_path, query, top_k, with_rag_context)


def mcp_search_code(root_path: str, query: str, class_filter: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    return search_code(root_path, query, class_filter, limit)


def mcp_analyze_impact(root_path: str, class_name: str, method_name: Optional[str] = None, max_depth: int = 2, limit: int = 50) -> Dict[str, Any]:
    return analyze_impact(root_path, class_name, method_name, max_depth, limit)


# ─── Entrypoint ───────────────────────────────────────────────────────────────


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()


__all__ = [
    "mcp",
    "mcp_index_project",
    "mcp_project_query",
    "mcp_search_code",
    "mcp_analyze_impact",
]

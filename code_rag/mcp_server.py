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
def dependency_tree(
    root_path: str,
    format: str = "layered",
) -> Dict[str, Any]:
    """
    Строит граф зависимостей Java-проекта без эмбеддингов.

    Работает мгновенно — только статический анализ AST.
    Фильтрует внешние зависимости (JDK, Spring, Lombok и т.д.).

    Аргументы:
    - root_path: путь к корню проекта
    - format: формат вывода:
        "layered"  — таблица по слоям + потоки (по умолчанию)
        "full"     — каждый класс со списком зависимостей
        "mermaid"  — граф в формате Mermaid для GitHub/Obsidian
        "all"      — все три формата

    Возвращает:
    - markdown: готовый Markdown текст
    - stats: статистика (классов, связей, слоёв)
    """
    from .dep_graph_renderer import build_project_deps, render_full_tree, render_layered_view, render_mermaid

    root = Path(root_path)
    deps = build_project_deps(root)

    stats = {
        "classes": len(deps.classes),
        "edges": sum(len(v) for v in deps.edges_by_class.values()),
        "package_prefix": deps.package_prefix,
        "layers": {k: len(v) for k, v in deps.layers.items()},
    }

    if format == "full":
        md = render_full_tree(deps)
    elif format == "mermaid":
        md = render_mermaid(deps)
    elif format == "all":
        md = "\n\n---\n\n".join([
            render_layered_view(deps),
            render_full_tree(deps),
            render_mermaid(deps),
        ])
    else:
        md = render_layered_view(deps)

    return {"markdown": md, "stats": stats}


def mcp_dependency_tree(root_path: str, format: str = "layered") -> Dict[str, Any]:
    return dependency_tree(root_path, format)


@mcp.tool()
def explain_architecture(
    root_path: str,
    feature: str,
    top_k: int = 10,
    max_depth: int = 2,
) -> Dict[str, Any]:
    """
    Объясняет архитектуру фичи или потока данных в проекте.

    Алгоритм:
    1. Семантический поиск: находит top_k чанков, релевантных запросу
    2. Граф зависимостей: для каждого найденного класса собирает
       входящие и исходящие связи (кто вызывает и кого использует)
    3. Формирует текстовое описание потока: слои Controller → Service → Repository

    Аргументы:
    - root_path: путь к корню проекта
    - feature: описание фичи на естественном языке (например, "как работают скидки")
    - top_k: число чанков для начального поиска
    - max_depth: глубина обхода графа зависимостей

    Возвращает:
    - flow_text: готовый текст с описанием архитектуры (для вставки в LLM-промпт)
    - layers: классы сгруппированные по архитектурным слоям
    - call_chain: цепочки вызовов между найденными классами
    - chunks: сырые чанки для контекста
    """
    index = _get_index_or_raise(root_path)
    g = index.graph

    # 1. Семантический поиск
    results = project_query(index, query_text=feature, top_k=top_k)

    # Собираем уникальные классы из результатов
    found_classes: Dict[str, Dict] = {}  # simple_name -> info
    found_chunks: List[Dict] = []

    for r in results:
        ch = index.chunks.get(r.chunk_id)
        if not ch:
            continue
        cls = ch.metadata.get("class", "")
        method = ch.metadata.get("name", "")
        if not cls:
            continue

        if cls not in found_classes:
            found_classes[cls] = {
                "class": cls,
                "file": str(ch.file),
                "methods": [],
                "score": r.score,
            }
        if method and method not in found_classes[cls]["methods"]:
            found_classes[cls]["methods"].append(method)

        found_chunks.append({
            "score": round(r.score, 3),
            "class": cls,
            "method": method,
            "location": f"{ch.file}:{ch.start_line}-{ch.end_line}",
            "snippet": ch.text[:150].strip(),
        })

    # 2. Граф: для каждого найденного класса — связи
    call_chain: List[Dict] = []
    for fqcn, _ in _resolve_fqcns(index, list(found_classes.keys())):
        for edge in g.outgoing(fqcn)[:max_depth * 5]:
            target_simple = edge.target.split(".")[-1].split("#")[0]
            if target_simple in found_classes or target_simple in _ALL_SIMPLE(index):
                call_chain.append({
                    "from": fqcn.split(".")[-1],
                    "to": edge.target.split(".")[-1],
                    "kind": edge.kind,
                })

    # 3. Разбивка по слоям
    layers = _classify_layers(found_classes)

    # 4. Текстовое описание потока
    flow_text = _build_flow_text(feature, layers, call_chain, found_chunks)

    return {
        "flow_text": flow_text,
        "layers": layers,
        "call_chain": call_chain[:30],
        "chunks": found_chunks,
    }


def _resolve_fqcns(index: IndexedProject, simple_names: List[str]):
    """Возвращает (fqcn, simple) для классов из графа по простому имени."""
    result = []
    all_nodes = set(index.graph._outgoing.keys()) | set(index.graph._incoming.keys())
    for simple in simple_names:
        for node in all_nodes:
            node_simple = node.split(".")[-1].split("#")[0]
            if node_simple == simple and "#" not in node:
                result.append((node, simple))
                break
    return result


def _ALL_SIMPLE(index: IndexedProject):
    """Простые имена всех классов в индексе."""
    return {ch.metadata.get("class", "") for ch in index.chunks.values()}


# Слои по суффиксу имени класса
_LAYER_PATTERNS = [
    ("controller", ["Controller"]),
    ("service", ["Service"]),
    ("repository", ["Repository"]),
    ("model", ["Entity", "Model"]),
    ("dto", ["Dto", "Request", "Response"]),
    ("exception", ["Exception"]),
    ("config", ["Config", "Configuration", "Handler"]),
]


def _classify_layers(classes: Dict[str, Dict]) -> Dict[str, List[str]]:
    layers: Dict[str, List[str]] = {layer: [] for layer, _ in _LAYER_PATTERNS}
    layers["other"] = []
    for cls_name in classes:
        matched = False
        for layer, suffixes in _LAYER_PATTERNS:
            if any(cls_name.endswith(s) for s in suffixes):
                layers[layer].append(cls_name)
                matched = True
                break
        if not matched:
            layers["other"].append(cls_name)
    return {k: v for k, v in layers.items() if v}  # убираем пустые


def _build_flow_text(
    feature: str,
    layers: Dict[str, List],
    call_chain: List[Dict],
    chunks: List[Dict],
) -> str:
    lines = [
        f"# Архитектура: {feature}",
        "",
        "## Задействованные компоненты",
    ]

    layer_labels = {
        "controller": "Контроллеры (HTTP)",
        "service": "Сервисы (бизнес-логика)",
        "repository": "Репозитории (доступ к данным)",
        "model": "Модели/Сущности",
        "dto": "DTO (запросы/ответы)",
        "exception": "Исключения",
        "config": "Конфигурация",
        "other": "Прочее",
    }
    for layer, classes in layers.items():
        label = layer_labels.get(layer, layer)
        lines.append(f"\n### {label}")
        for cls in classes:
            lines.append(f"- {cls}")

    if call_chain:
        lines.append("\n## Цепочки вызовов")
        seen = set()
        for edge in call_chain:
            key = f"{edge['from']} → {edge['to']}"
            if key not in seen:
                seen.add(key)
                lines.append(f"- {key}  [{edge['kind']}]")

    lines.append("\n## Ключевые методы")
    top_chunks = sorted(chunks, key=lambda x: -x["score"])[:6]
    for ch in top_chunks:
        lines.append(f"\n### {ch['class']}.{ch['method']}  (score: {ch['score']})")
        lines.append(f"```java\n{ch['snippet']}\n```")

    return "\n".join(lines)


@mcp.tool()
def find_usages(
    root_path: str,
    class_name: str,
    method_name: Optional[str] = None,
    include_semantic: bool = True,
    limit: int = 30,
) -> Dict[str, Any]:
    """
    Находит все места в проекте, где используется указанный класс или метод.

    Комбинирует два источника:
    1. Граф зависимостей (статический анализ вызовов и импортов)
    2. Семантический поиск по чанкам (находит упоминания даже без явного импорта)

    Аргументы:
    - root_path: путь к корню проекта
    - class_name: FQCN класса, например com.bikerental.service.DiscountService
    - method_name: имя метода (опционально), например isDiscountApplicable
    - include_semantic: добавить семантический поиск поверх графа (по умолчанию true)
    - limit: максимальное число результатов в каждом источнике

    Возвращает:
    - graph_usages: прямые вхождения из графа зависимостей
    - semantic_usages: результаты семантического поиска
    - summary: краткая сводка
    """
    index = _get_index_or_raise(root_path)
    g = index.graph

    target = f"{class_name}#{method_name}" if method_name else class_name
    simple_name = class_name.split(".")[-1]

    # -- 1. Граф: прямые входящие рёбра --
    incoming = g.incoming(target)

    # Если метод не найден напрямую — ищем по короткому имени
    if not incoming and method_name:
        # Перебираем все узлы графа с совпадающим суффиксом
        for node in list(index.graph._incoming.keys()):
            if node.endswith(f"#{method_name}") and simple_name in node:
                incoming = g.incoming(node)
                target = node
                break

    graph_results: List[Dict[str, Any]] = []
    seen_sources: set = set()
    for edge in incoming[:limit]:
        if edge.source in seen_sources:
            continue
        seen_sources.add(edge.source)

        # Находим чанк для этого источника
        chunk_info = _find_chunk_by_fqcn(index, edge.source)
        graph_results.append({
            "caller": edge.source,
            "kind": edge.kind,
            "location": chunk_info.get("location"),
            "snippet": chunk_info.get("snippet"),
        })

    # -- 2. Семантический поиск --
    semantic_results: List[Dict[str, Any]] = []
    if include_semantic:
        query = f"{simple_name} {method_name or ''} usage call".strip()
        from .indexer import project_query
        sem_hits = project_query(index, query_text=query, top_k=limit)
        for hit in sem_hits:
            ch = index.chunks.get(hit.chunk_id)
            if ch is None:
                continue
            # Исключаем сам класс из результатов
            if simple_name in str(ch.file) and not method_name:
                continue
            semantic_results.append({
                "score": round(hit.score, 4),
                "class": ch.metadata.get("class", ""),
                "method": ch.metadata.get("name", ""),
                "location": f"{ch.file}:{ch.start_line}-{ch.end_line}",
                "snippet": ch.text[:120].strip(),
            })

    # -- 3. Сводка --
    unique_callers = {r["caller"].split("#")[0] for r in graph_results}
    summary = {
        "target": target,
        "graph_usages_count": len(graph_results),
        "semantic_usages_count": len(semantic_results),
        "unique_calling_classes": sorted(unique_callers),
    }

    return {
        "summary": summary,
        "graph_usages": graph_results,
        "semantic_usages": semantic_results[:limit],
    }


def _find_chunk_by_fqcn(index, fqcn: str) -> Dict[str, Any]:
    """Ищет чанк по FQCN вида com.example.Class или com.example.Class#method."""
    parts = fqcn.split("#")
    class_fqcn = parts[0]
    method = parts[1] if len(parts) > 1 else None
    simple = class_fqcn.split(".")[-1]

    for ch in index.chunks.values():
        meta = ch.metadata or {}
        if meta.get("class") == simple:
            if method is None or meta.get("name") == method:
                return {
                    "location": f"{ch.file}:{ch.start_line}-{ch.end_line}",
                    "snippet": ch.text[:120].strip(),
                }
    return {}


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


def mcp_find_usages(root_path: str, class_name: str, method_name: Optional[str] = None, include_semantic: bool = True, limit: int = 30) -> Dict[str, Any]:
    return find_usages(root_path, class_name, method_name, include_semantic, limit)


def mcp_explain_architecture(root_path: str, feature: str, top_k: int = 10, max_depth: int = 2) -> Dict[str, Any]:
    return explain_architecture(root_path, feature, top_k, max_depth)


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
    "mcp_find_usages",
    "mcp_explain_architecture",
]

from __future__ import annotations

"""
Облегчённый MCP-сервер: только dependency_tree.

Не требует эмбеддингов, GigaChat API, Qdrant/ChromaDB.
Работает мгновенно — чистый статический анализ Java AST.

Запуск:
  python -m code_rag mcp
  python -m code_rag deps /path/to/project [--format layered|full|mermaid|all]
"""

from pathlib import Path
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP

from .dep_graph_renderer import build_project_deps, render_full_tree, render_layered_view, render_mermaid

mcp = FastMCP("code-rag-lite")


@mcp.tool()
def dependency_tree(
    root_path: str,
    format: str = "layered",
) -> Dict[str, Any]:
    """
    Строит граф зависимостей Java-проекта без эмбеддингов.

    Работает мгновенно — только статический анализ AST.
    Фильтрует внешние зависимости (JDK, Spring, Lombok и т.д.).
    Группирует классы по архитектурным слоям.

    Аргументы:
    - root_path: путь к корню проекта (с pom.xml или build.gradle)
    - format: формат вывода:
        "layered"  — таблица по слоям + потоки (по умолчанию)
        "full"     — каждый класс со списком зависимостей
        "mermaid"  — граф в формате Mermaid для GitHub/Obsidian
        "all"      — все три формата

    Возвращает:
    - markdown: готовый Markdown текст
    - stats: статистика (классов, связей, слоёв, пакет)
    """
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
    """Алиас для тестов."""
    return dependency_tree(root_path, format)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()


__all__ = ["mcp", "dependency_tree", "mcp_dependency_tree"]

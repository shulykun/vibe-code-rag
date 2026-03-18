from __future__ import annotations

"""
CLI для облегчённого code-rag (только dependency_tree).

Команды:
  deps   — вывести граф зависимостей Java-проекта
  mcp    — запустить MCP-сервер (stdio транспорт)

Примеры:
  python -m code_rag deps /path/to/java-project
  python -m code_rag deps /path/to/java-project --format mermaid
  python -m code_rag mcp
"""

import argparse

from .mcp_server import mcp_dependency_tree, main as mcp_main


def cmd_deps(args: argparse.Namespace) -> None:
    result = mcp_dependency_tree(args.root, args.format)
    print(result["markdown"])
    stats = result["stats"]
    print(f"\n---\n_Классов: {stats['classes']} | Связей: {stats['edges']} | Пакет: {stats['package_prefix']}_")


def main() -> None:
    parser = argparse.ArgumentParser(prog="code_rag", description="Java dependency graph (no embeddings)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # deps
    p_deps = subparsers.add_parser("deps", help="Print dependency graph")
    p_deps.add_argument("root", type=str, help="Path to Java project root (with pom.xml/build.gradle)")
    p_deps.add_argument(
        "--format", choices=["layered", "full", "mermaid", "all"],
        default="layered", help="Output format (default: layered)"
    )
    p_deps.set_defaults(func=cmd_deps)

    # mcp
    p_mcp = subparsers.add_parser("mcp", help="Run MCP server (stdio transport)")
    p_mcp.set_defaults(func=lambda _: mcp_main())

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

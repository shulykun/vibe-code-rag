from __future__ import annotations

"""
Простой CLI-энтрипоинт для code_rag.

Позволяет запускать базовые операции без интеграции MCP:
- index        — проиндексировать Java-проект;
- project-query — сделать семантический запрос;
- search-code  — поиск по коду по подстроке.

Примеры:

python -m code_rag index /path/to/java-project
python -m code_rag project-query /path/to/java-project "user service"
python -m code_rag search-code /path/to/java-project "@Transactional" --class-filter "*Service"
"""

import argparse
import json
from pathlib import Path

from .mcp_server import mcp_index_project, mcp_project_query, mcp_search_code


def cmd_index(args: argparse.Namespace) -> None:
    info = mcp_index_project(args.root, force_reindex=args.force)
    print(json.dumps(info, indent=2, ensure_ascii=False))


def cmd_project_query(args: argparse.Namespace) -> None:
    res = mcp_project_query(
        root_path=args.root,
        query=args.query,
        top_k=args.top_k,
        with_rag_context=args.with_rag_context,
    )
    print(json.dumps(res, indent=2, ensure_ascii=False))


def cmd_search_code(args: argparse.Namespace) -> None:
    res = mcp_search_code(
        root_path=args.root,
        query=args.query,
        class_filter=args.class_filter,
        limit=args.limit,
    )
    print(json.dumps(res, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(prog="code_rag", description="Java code RAG helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # index
    p_index = subparsers.add_parser("index", help="Index Java project")
    p_index.add_argument("root", type=str, help="Path to project root")
    p_index.add_argument(
        "--force",
        action="store_true",
        help="Force reindex even if cache exists",
    )
    p_index.set_defaults(func=cmd_index)

    # project-query
    p_pq = subparsers.add_parser("project-query", help="Semantic query over project")
    p_pq.add_argument("root", type=str, help="Path to project root")
    p_pq.add_argument("query", type=str, help="Natural language query")
    p_pq.add_argument("--top-k", type=int, default=10, help="Number of results")
    p_pq.add_argument(
        "--with-rag-context",
        action="store_true",
        help="Include RAG context in response",
    )
    p_pq.set_defaults(func=cmd_project_query)

    # search-code
    p_sc = subparsers.add_parser("search-code", help="Text search over code chunks")
    p_sc.add_argument("root", type=str, help="Path to project root")
    p_sc.add_argument("query", type=str, help="Substring to search for")
    p_sc.add_argument(
        "--class-filter",
        type=str,
        default=None,
        help='Glob filter for class name, e.g. "*Service"',
    )
    p_sc.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max number of results",
    )
    p_sc.set_defaults(func=cmd_search_code)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()


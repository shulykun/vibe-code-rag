from __future__ import annotations

"""
Заготовка парсера Java-кода.

MVP:
- инициализация tree-sitter для Java;
- API для парсинга исходника и возврата AST-дерева;
- дальше поверх этого будут строиться чанки и граф зависимостей.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from tree_sitter import Parser
from tree_sitter_languages import get_language


@dataclass
class ParsedFile:
    path: Path
    tree: Any  # tree_sitter.Tree
    source: str


class CodeParser:
    def __init__(self) -> None:
        """
        Инициализация tree-sitter для Java.
        """
        language = get_language("java")
        parser = Parser()
        parser.set_language(language)
        self._parser: Parser = parser

    def parse_file(self, path: Path) -> ParsedFile:
        """
        Парсит Java-файл и возвращает объект ParsedFile.

        Реальный парсинг через tree-sitter.
        """
        source = path.read_text(encoding="utf-8")
        tree = self._parse_source(source)
        return ParsedFile(path=path, tree=tree, source=source)

    def _parse_source(self, source: str) -> Any:
        """
        Парсит исходник и возвращает дерево tree-sitter.
        """
        # tree-sitter ожидает bytes
        return self._parser.parse(source.encode("utf-8"))


__all__ = ["ParsedFile", "CodeParser"]


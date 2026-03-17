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
    tree: Any        # tree_sitter.Tree
    source: str      # decoded text (для отображения)
    source_bytes: bytes = b""  # raw bytes (для байтовых смещений tree-sitter)


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
        source_bytes = path.read_bytes()
        source = source_bytes.decode("utf-8", errors="replace")
        tree = self._parser.parse(source_bytes)
        return ParsedFile(path=path, tree=tree, source=source, source_bytes=source_bytes)

    def parse_source(self, source: str) -> Any:
        """Парсит строку и возвращает дерево tree-sitter."""
        return self._parser.parse(source.encode("utf-8"))


__all__ = ["ParsedFile", "CodeParser"]


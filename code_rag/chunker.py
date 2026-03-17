from __future__ import annotations

"""
Заготовка модуля для формирования семантических чанков.

Работает поверх ParsedFile/AST и будет выделять чанки уровня:
- методов и классов;
- конфигурационных блоков;
- документации.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Literal


ChunkKind = Literal["method", "class", "config", "doc"]


@dataclass
class Chunk:
    id: str
    kind: ChunkKind
    file: Path
    start_line: int
    end_line: int
    text: str
    metadata: dict


class Chunker:
    def build_chunks_for_file(self, parsed_file) -> List[Chunk]:
        """
        Формирует чанки на основе AST tree-sitter.

        MVP:
        - чанк на каждый класс/интерфейс/enum;
        - чанк на каждый метод/конструктор;
        - если парсинг не удался — один чанк на весь файл.
        """
        tree = getattr(parsed_file, "tree", None)
        source: str = getattr(parsed_file, "source", "")
        if tree is None or source is None:
            # fallback: один чанк на файл
            text = parsed_file.path.read_text(encoding="utf-8")
            lines = text.splitlines()
            return [
                Chunk(
                    id=f"{parsed_file.path}::whole",
                    kind="class",
                    file=parsed_file.path,
                    start_line=1,
                    end_line=len(lines),
                    text=text,
                    metadata={},
                )
            ]

        lines = source.splitlines()
        chunks: List[Chunk] = []

        root = tree.root_node

        def add_chunk(node: Any, kind: ChunkKind, name: str) -> None:
            (start_row, _start_col) = node.start_point
            (end_row, _end_col) = node.end_point
            start_line = start_row + 1
            end_line = end_row + 1
            text = "\n".join(lines[start_line - 1 : end_line])
            chunk_id = f"{parsed_file.path}::{kind}:{start_line}-{end_line}"
            chunks.append(
                Chunk(
                    id=chunk_id,
                    kind=kind,
                    file=parsed_file.path,
                    start_line=start_line,
                    end_line=end_line,
                    text=text,
                    metadata={"name": name},
                )
            )

        class_stack: List[str] = []

        def walk(node: Any) -> None:
            type_ = node.type
            if type_ in ("class_declaration", "interface_declaration", "enum_declaration"):
                name_node = _find_child_by_type(node, "identifier")
                name = source[name_node.start_byte : name_node.end_byte] if name_node else ""
                class_stack.append(name)
                add_chunk(node, "class", name)
            elif type_ in ("method_declaration", "constructor_declaration"):
                name_node = _find_child_by_type(node, "identifier")
                name = source[name_node.start_byte : name_node.end_byte] if name_node else ""
                add_chunk(node, "method", name)
                # дополняем метаданные последнего чанка контекстом класса
                if chunks and chunks[-1].kind == "method":
                    chunks[-1].metadata["class"] = class_stack[-1] if class_stack else ""

            for child in node.children:
                walk(child)

            if type_ in ("class_declaration", "interface_declaration", "enum_declaration"):
                if class_stack:
                    class_stack.pop()

        def _find_child_by_type(node: Any, t: str) -> Any:
            for ch in node.children:
                if ch.type == t:
                    return ch
            return None

        walk(root)

        if not chunks:
            # если ничего не нашли по AST — fallback
            text = "\n".join(lines)
            chunks.append(
                Chunk(
                    id=f"{parsed_file.path}::whole",
                    kind="class",
                    file=parsed_file.path,
                    start_line=1,
                    end_line=len(lines),
                    text=text,
                    metadata={},
                )
            )

        return chunks


__all__ = ["Chunk", "Chunker", "ChunkKind"]


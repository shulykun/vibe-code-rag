from __future__ import annotations

"""
Модуль для формирования семантических чанков из Java AST.

Каждый чанк хранит:
- text       — исходный код (для отображения)
- embed_text — обогащённый текст для эмбеддинга:
               включает имя класса, метода и Javadoc (если есть)

Обогащение сильно улучшает семантический поиск — модель понимает
"calculateBonusPoints in RentalService" лучше чем голое тело метода.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Literal, Optional


ChunkKind = Literal["method", "class", "config", "doc"]


@dataclass
class Chunk:
    id: str
    kind: ChunkKind
    file: Path
    start_line: int
    end_line: int
    text: str                    # исходный код (для отображения)
    metadata: dict
    embed_text: str = field(default="")  # обогащённый текст для эмбеддинга


class Chunker:
    def build_chunks_for_file(self, parsed_file) -> List[Chunk]:
        """
        Формирует чанки на основе AST tree-sitter.

        - чанк на каждый класс/интерфейс/enum;
        - чанк на каждый метод/конструктор;
        - если парсинг не удался — один чанк на весь файл.
        """
        tree = getattr(parsed_file, "tree", None)
        source: str = getattr(parsed_file, "source", "")
        if tree is None or source is None:
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
                    embed_text=text,
                )
            ]

        lines = source.splitlines()
        chunks: List[Chunk] = []

        # Для байтовых срезов (имена идентификаторов) используем source_bytes
        source_bytes: bytes = getattr(parsed_file, "source_bytes", source.encode("utf-8"))

        class_stack: List[str] = []  # стек имён классов

        def extract_javadoc(node: Any) -> Optional[str]:
            """Ищет block_comment /** перед узлом (пропускает whitespace)."""
            parent = node.parent
            if parent is None:
                return None
            siblings = list(parent.children)
            idx = next((i for i, c in enumerate(siblings) if c == node), None)
            if idx is None or idx == 0:
                return None
            # Ищем назад, пропуская пробельные узлы
            for i in range(idx - 1, -1, -1):
                sib = siblings[i]
                if sib.type in ("block_comment",):
                    comment = source_bytes[sib.start_byte:sib.end_byte].decode("utf-8", errors="replace")
                    if comment.startswith("/**"):
                        inner = comment[3:-2]  # strip /** and */
                        lines_c = [l.lstrip("* ").rstrip() for l in inner.splitlines()]
                        return " ".join(l for l in lines_c if l)
                    break
                elif sib.type not in ("line_comment", "\n", " ", "\t"):
                    break
            return None

        def make_embed_text(
            kind: ChunkKind,
            class_name: str,
            method_name: str,
            code: str,
            javadoc: Optional[str],
        ) -> str:
            """
            Строит текст для эмбеддинга: контекст + javadoc + код.

            Формат:
              // Class: RentalService
              // Method: returnBike
              // Doc: Возвращает велосипед и закрывает аренду...
              <код>
            """
            header_lines = []
            if class_name:
                header_lines.append(f"// Class: {class_name}")
            if method_name:
                header_lines.append(f"// Method: {method_name}")
            if javadoc:
                doc_short = javadoc[:300].rstrip()
                header_lines.append(f"// Doc: {doc_short}")
            header = "\n".join(header_lines)
            return f"{header}\n{code}" if header else code

        MAX_EMBED_CHARS = 2000  # ограничение для GigaChat API

        def add_chunk(
            node: Any,
            kind: ChunkKind,
            name: str,
            class_name: str = "",
        ) -> None:
            # Пропускаем чанки с неправильно распознанным именем
            # (tree-sitter иногда сбивается на unicode-комментариях)
            if name and (" " in name or "\n" in name or len(name) > 100):
                return

            (start_row, _) = node.start_point
            (end_row, _) = node.end_point
            start_line = start_row + 1
            end_line = end_row + 1
            code = "\n".join(lines[start_line - 1: end_line])
            chunk_id = f"{parsed_file.path}::{kind}:{start_line}-{end_line}"

            javadoc = extract_javadoc(node)

            if kind == "method":
                cls_name = class_name
                method_name = name
            else:
                cls_name = name
                method_name = ""

            embed = make_embed_text(kind, cls_name, method_name, code, javadoc)
            # Обрезаем до лимита, сохраняя заголовок
            embed = embed[:MAX_EMBED_CHARS]

            chunks.append(
                Chunk(
                    id=chunk_id,
                    kind=kind,
                    file=parsed_file.path,
                    start_line=start_line,
                    end_line=end_line,
                    text=code,
                    metadata={"name": name, "class": cls_name},
                    embed_text=embed,
                )
            )

        def walk(node: Any) -> None:
            type_ = node.type
            if type_ in ("class_declaration", "interface_declaration", "enum_declaration"):
                name_node = _find_child_by_type(node, "identifier")
                name = source_bytes[name_node.start_byte: name_node.end_byte].decode("utf-8", errors="replace") if name_node else ""
                class_stack.append(name)
                add_chunk(node, "class", name)

            elif type_ in ("method_declaration", "constructor_declaration"):
                name_node = _find_child_by_type(node, "identifier")
                name = source_bytes[name_node.start_byte: name_node.end_byte].decode("utf-8", errors="replace") if name_node else ""
                class_name = class_stack[-1] if class_stack else ""
                add_chunk(node, "method", name, class_name=class_name)

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

        walk(tree.root_node)

        if not chunks:
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
                    embed_text=text,
                )
            )

        return chunks


__all__ = ["Chunk", "Chunker", "ChunkKind"]

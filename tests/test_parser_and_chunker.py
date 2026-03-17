from __future__ import annotations

from pathlib import Path

from code_rag.code_parser import CodeParser
from code_rag.chunker import Chunker


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_parser_and_chunker_extract_class_and_method_chunks(tmp_path: Path) -> None:
    java = tmp_path / "src/main/java/com/acme/UserService.java"
    _write(
        java,
        """
package com.acme;

public class UserService {
    public void createUser() {
        helper();
    }

    private void helper() {}
}
""".lstrip(),
    )

    parsed = CodeParser().parse_file(java)
    chunks = Chunker().build_chunks_for_file(parsed)

    kinds = [c.kind for c in chunks]
    assert "class" in kinds
    assert "method" in kinds

    method_names = {c.metadata.get("name") for c in chunks if c.kind == "method"}
    assert "createUser" in method_names
    assert "helper" in method_names

    # методные чанки должны знать свой класс (best-effort)
    for c in chunks:
        if c.kind == "method":
            assert c.metadata.get("class") == "UserService"


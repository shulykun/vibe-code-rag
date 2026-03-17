from __future__ import annotations

"""Edge-case тесты для MCP-инструментов."""

import pytest
from pathlib import Path

from code_rag.mcp_server import (
    mcp_index_project,
    mcp_project_query,
    mcp_search_code,
    mcp_analyze_impact,
    _INDEX_CACHE,
)


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _make_project(root: Path) -> None:
    _write(root / "pom.xml", "<project/>")
    _write(
        root / "src/main/java/com/demo/GreetService.java",
        """
package com.demo;
public class GreetService {
    public String greet(String name) {
        return "Hello, " + name;
    }
}
""".lstrip(),
    )


def test_project_query_unindexed_raises(tmp_path: Path) -> None:
    """project_query на незаиндексированный проект должен кидать RuntimeError."""
    unindexed = tmp_path / "ghost"
    unindexed.mkdir()
    # убедимся что его нет в кэше
    _INDEX_CACHE.pop(str(unindexed.resolve()), None)

    with pytest.raises(RuntimeError, match="not indexed"):
        mcp_project_query(str(unindexed), query="anything")


def test_search_code_unindexed_raises(tmp_path: Path) -> None:
    unindexed = tmp_path / "ghost2"
    unindexed.mkdir()
    _INDEX_CACHE.pop(str(unindexed.resolve()), None)

    with pytest.raises(RuntimeError, match="not indexed"):
        mcp_search_code(str(unindexed), query="test")


def test_force_reindex(tmp_path: Path) -> None:
    """force_reindex=True должен пересчитать индекс, не брать из кэша."""
    root = tmp_path
    _make_project(root)

    info1 = mcp_index_project(str(root))
    chunks_before = info1["chunks_count"]

    # добавляем файл и переиндексируем
    _write(
        root / "src/main/java/com/demo/FooService.java",
        """
package com.demo;
public class FooService {
    public void foo() {}
}
""".lstrip(),
    )
    info2 = mcp_index_project(str(root), force_reindex=True)
    assert info2["chunks_count"] > chunks_before


def test_project_query_with_rag_context(tmp_path: Path) -> None:
    """with_rag_context=True должен вернуть prompt_text."""
    root = tmp_path
    _make_project(root)
    mcp_index_project(str(root))

    res = mcp_project_query(str(root), query="greet method", with_rag_context=True)
    assert "rag_context" in res
    assert "prompt_text" in res["rag_context"]
    assert "greet method" in res["rag_context"]["prompt_text"]


def test_search_code_no_results(tmp_path: Path) -> None:
    """Поиск несуществующей строки возвращает пустой список."""
    root = tmp_path
    _make_project(root)
    mcp_index_project(str(root))

    hits = mcp_search_code(str(root), query="xyzzyNonExistentToken123")
    assert hits == []


def test_analyze_impact_unknown_class(tmp_path: Path) -> None:
    """analyze_impact по несуществующему классу возвращает пустые списки, не падает."""
    root = tmp_path
    _make_project(root)
    mcp_index_project(str(root))

    result = mcp_analyze_impact(str(root), class_name="com.demo.Ghost")
    assert result["incoming"] == []
    assert result["impacted"] == []


def test_index_project_returns_correct_build_system(tmp_path: Path) -> None:
    """Gradle-проект определяется как gradle."""
    root = tmp_path
    _write(root / "build.gradle", "plugins { id 'java' }")
    _write(
        root / "src/main/java/com/demo/App.java",
        "package com.demo; public class App {}",
    )

    info = mcp_index_project(str(root))
    assert info["build_system"] == "gradle"

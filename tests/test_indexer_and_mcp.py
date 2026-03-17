from __future__ import annotations

from pathlib import Path

from code_rag.indexer import index_project
from code_rag.mcp_server import mcp_analyze_impact, mcp_index_project, mcp_search_code


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_indexer_builds_graph_and_mcp_tools_work(tmp_path: Path) -> None:
    root = tmp_path
    _write(root / "pom.xml", "<project/>")

    # B depends on A via type usage and calls A.create()
    _write(
        root / "src/main/java/com/acme/A.java",
        """
package com.acme;
public class A {
  public void create() {}
}
""".lstrip(),
    )
    _write(
        root / "src/main/java/com/acme/BService.java",
        """
package com.acme;
public class BService {
  private A a;
  public void run() {
    a.create();
  }
}
""".lstrip(),
    )

    # index via MCP cache
    info = mcp_index_project(str(root))
    assert info["build_system"] == "maven"
    assert info["chunks_count"] > 0

    # search_code должен найти "create()" в чанках
    hits = mcp_search_code(str(root), query="create()", class_filter="*Service", limit=10)
    assert any(h["class"] == "BService" for h in hits)

    # analyze impact for class A: BService should be in incoming/impacted
    impact = mcp_analyze_impact(str(root), class_name="com.acme.A", max_depth=2)
    incoming_sources = {e["source"] for e in impact["incoming"]}
    assert "com.acme.BService" in incoming_sources

    # analyze impact for method A#create: should be referenced by BService#run
    impact_m = mcp_analyze_impact(
        str(root), class_name="com.acme.A", method_name="create", max_depth=2
    )
    incoming_sources_m = {e["source"] for e in impact_m["incoming"]}
    assert "com.acme.BService#run" in incoming_sources_m


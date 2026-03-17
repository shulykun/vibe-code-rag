from __future__ import annotations

from pathlib import Path

from code_rag.project_scanner import ProjectScanner


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_scanner_detects_maven_and_sources(tmp_path: Path) -> None:
    root = tmp_path
    _write(root / "pom.xml", "<project/>")
    _write(
        root / "src/main/java/com/acme/App.java",
        "package com.acme; public class App {}",
    )
    _write(
        root / "src/test/java/com/acme/AppTest.java",
        "package com.acme; public class AppTest {}",
    )
    _write(root / "src/main/resources/application.yml", "k: v")

    layout = ProjectScanner(root).scan()

    assert layout.build_system == "maven"
    assert len(layout.modules) == 1
    mod = layout.modules[0]
    assert any(p.name == "App.java" for p in mod.java_sources)
    assert any(p.name == "AppTest.java" for p in mod.tests)
    assert any(p.name == "application.yml" for p in mod.resources)


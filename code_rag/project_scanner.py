from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class SourceSet:
    """Описание набора исходников в модуле Java-проекта."""

    module_name: str
    root: Path
    java_sources: List[Path]
    resources: List[Path]
    tests: List[Path]


@dataclass(frozen=True)
class ProjectLayout:
    """Высокоуровневое представление структуры проекта."""

    root: Path
    build_system: str  # "maven" | "gradle" | "unknown"
    modules: List[SourceSet]


class ProjectScanner:
    """
    Отвечает за обнаружение модулей и исходников Java-проекта.

    MVP-версия:
    - определяет тип сборки (Maven/Gradle/unknown);
    - ищет стандартные директории `src/main/java`, `src/test/java`, `src/main/resources`;
    - поддерживает монорепо и многомодульные проекты на основе наличия `pom.xml`/`build.gradle`.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def detect_build_system(self) -> str:
        if any(self.root.glob("**/pom.xml")):
            return "maven"
        if any(self.root.glob("**/build.gradle")) or any(
            self.root.glob("**/build.gradle.kts")
        ):
            return "gradle"
        return "unknown"

    def scan(self) -> ProjectLayout:
        build_system = self.detect_build_system()
        modules: List[SourceSet] = []

        for module_root in self._iter_module_roots():
            module_name = (
                module_root.relative_to(self.root).as_posix()
                if module_root != self.root
                else ""
            ) or module_root.name

            java_main = module_root / "src" / "main" / "java"
            java_test = module_root / "src" / "test" / "java"
            resources = module_root / "src" / "main" / "resources"

            # Fallback для нестандартных структур:
            # src/com/... (без main/java) — типично для старых Maven/Eclipse проектов
            if not java_main.exists():
                alt_src = module_root / "src"
                if alt_src.exists() and any(alt_src.rglob("*.java")):
                    java_main = alt_src

            modules.append(
                SourceSet(
                    module_name=module_name,
                    root=module_root,
                    java_sources=list(self._iter_java_files(java_main)),
                    resources=list(self._iter_files(resources)),
                    tests=list(self._iter_java_files(java_test)),
                )
            )

        return ProjectLayout(root=self.root, build_system=build_system, modules=modules)

    def _iter_module_roots(self) -> Iterable[Path]:
        """
        Находит корни модулей.

        Простая эвристика:
        - директории, где есть pom.xml или build.gradle(.kts);
        - если таких нет, считаем весь проект одним модулем.
        """
        candidates: List[Path] = []
        for path in self.root.rglob("pom.xml"):
            candidates.append(path.parent)
        for path in self.root.rglob("build.gradle"):
            candidates.append(path.parent)
        for path in self.root.rglob("build.gradle.kts"):
            candidates.append(path.parent)

        if not candidates:
            return [self.root]

        unique_candidates = sorted(set(candidates))

        # Если корневой pom.xml есть И модульные — убираем корень
        # (у него нет своих src/, он просто aggregator)
        # Оставляем все уровни которые реально содержат src/
        roots_with_src = [
            c for c in unique_candidates
            if (c / "src" / "main" / "java").exists()
            or (c / "src").exists() and any((c / "src").rglob("*.java"))
        ]

        if roots_with_src:
            return roots_with_src

        # fallback — верхнеуровневые
        unique_roots: List[Path] = []
        for c in unique_candidates:
            if not any(parent in unique_roots for parent in c.parents):
                unique_roots.append(c)
        return unique_roots

    @staticmethod
    def _iter_java_files(root: Path) -> Iterable[Path]:
        if not root.exists():
            return []
        return root.rglob("*.java")

    @staticmethod
    def _iter_files(root: Path) -> Iterable[Path]:
        if not root.exists():
            return []
        return (p for p in root.rglob("*") if p.is_file())


__all__ = ["SourceSet", "ProjectLayout", "ProjectScanner"]


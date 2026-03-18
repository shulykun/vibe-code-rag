from __future__ import annotations

"""
Рендеринг графа зависимостей Java-проекта в Markdown.

Работает без эмбеддингов — только статический анализ AST.
Строит граф мгновенно, фильтрует внешние зависимости (JDK, Spring и т.д.),
группирует по архитектурным слоям.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .project_scanner import ProjectScanner
from .code_parser import CodeParser
from .chunker import Chunker
from .dependency_graph import DependencyGraph, Edge
from .dependency_extractor import (
    extract_java_symbols,
    extract_type_dependencies,
    extract_method_calls,
    primary_declared_type,
)


# Пакеты которые фильтруем из графа (внешние зависимости)
_EXTERNAL_PREFIXES = (
    "java.", "javax.", "jakarta.",
    "org.springframework.", "org.hibernate.", "org.slf4j.",
    "com.fasterxml.", "io.swagger.", "lombok.",
    "org.junit.", "org.mockito.", "org.assertj.",
)

# Имена которые не являются реальными классами (Lombok/Spring аннотации,
# tree-sitter артефакты при парсинге файлов с кириллицей)
_ANNOTATION_NOISE = frozenset({
    "Data", "Slf4j", "Builder", "Getter", "Setter", "ToString",
    "EqualsAndHashCode", "NoArgsConstructor", "AllArgsConstructor",
    "RequiredArgsConstructor", "Value",
    "Repository", "Service", "Component", "Controller",
    "RestController", "SpringBootApplication",
    "Configuration", "Bean",
    "Override", "SuppressWarnings", "FunctionalInterface",
})

# Слои: (название, суффиксы имён классов)
_LAYERS: List[Tuple[str, Tuple[str, ...]]] = [
    ("Controller",  ("Controller",)),
    ("Servlet",     ("Servlet", "Fwd", "Filter")),
    ("Service",     ("Service", "ServiceImpl")),
    ("Repository",  ("Repository", "Dao", "DAO")),
    ("Model",       ("Entity", "Model", "Bean")),
    ("DTO",         ("Dto", "Request", "Response")),
    ("Exception",   ("Exception",)),
    ("Config",      ("Config", "Configuration", "Handler", "Advice", "Util")),
]


def _is_external(fqcn: str) -> bool:
    return any(fqcn.startswith(p) for p in _EXTERNAL_PREFIXES)


def _layer_of(simple_name: str) -> str:
    for layer, suffixes in _LAYERS:
        if any(simple_name.endswith(s) for s in suffixes):
            return layer
    return "Other"


def _simple(fqcn: str) -> str:
    """com.example.foo.MyClass#method -> MyClass#method"""
    parts = fqcn.split(".")
    return parts[-1]


@dataclass
class ProjectDeps:
    """Результат статического анализа зависимостей."""
    root: Path
    package_prefix: str                          # общий пакет проекта
    classes: Dict[str, str]                      # fqcn -> simple_name
    edges_by_class: Dict[str, List[Edge]]        # fqcn -> исходящие рёбра (только internal)
    method_calls: Dict[str, List[str]]           # caller_fqcn -> [target_fqcn]
    layers: Dict[str, List[str]]                 # layer -> [fqcn]


def build_project_deps(root: Path) -> ProjectDeps:
    """
    Строит граф зависимостей без эмбеддингов.
    Парсит AST всех Java-файлов и извлекает:
    - class-level uses (через import-анализ)
    - method-level calls (best-effort через tree-sitter)
    """
    root = root.resolve()
    scanner = ProjectScanner(root)
    layout = scanner.scan()
    parser = CodeParser()
    graph = DependencyGraph()

    classes: Dict[str, str] = {}       # fqcn -> simple
    method_calls: Dict[str, List[str]] = {}

    for module in layout.modules:
        for java_file in module.java_sources:
            try:
                parsed = parser.parse_file(java_file)
                # Передаём bytes чтобы _node_text использовал байтовые срезы
                # (кириллица в Javadoc не сбивает смещения)
                src = parsed.source_bytes if parsed.source_bytes else parsed.source
                symbols = extract_java_symbols(parsed.tree, src)
                current_type = primary_declared_type(symbols)
                if not current_type:
                    continue

                fqcn = f"{symbols.package}.{current_type}" if symbols.package else current_type

                # Пропускаем "классы" с мусорными именами (артефакты парсера)
                if not current_type or len(current_type) > 80:
                    continue
                if not current_type[0].isupper():
                    continue
                if not current_type.replace("_", "").isalnum():
                    continue
                # Должно быть ASCII-идентификатором Java
                if not current_type.isascii():
                    continue
                # Исключаем аннотации и известный шум
                if current_type in _ANNOTATION_NOISE:
                    continue

                classes[fqcn] = current_type

                # Class-level uses
                deps = extract_type_dependencies(parsed.tree, src, symbols)
                for dep in deps:
                    if not _is_external(dep):
                        graph.add_edge(fqcn, dep, kind="uses")

                # Method-level calls
                calls = extract_method_calls(parsed.tree, src, symbols)
                for caller, targets in calls.items():
                    internal = [t for t in targets if not _is_external(t)]
                    if internal:
                        method_calls[caller] = internal
                        for t in internal:
                            graph.add_edge(caller, t, kind="calls")

            except Exception:
                continue

    # Определяем общий пакет проекта
    package_prefix = _common_prefix(list(classes.keys()))

    # Фильтруем edges — только внутренние классы
    internal_fqcns = set(classes.keys())
    edges_by_class: Dict[str, List[Edge]] = {}
    for fqcn in classes:
        outgoing = [
            e for e in graph.outgoing(fqcn)
            if e.target in internal_fqcns and e.kind == "uses"
        ]
        if outgoing:
            edges_by_class[fqcn] = outgoing

    # Группировка по слоям
    layers: Dict[str, List[str]] = {layer: [] for layer, _ in _LAYERS}
    layers["Other"] = []
    for fqcn, simple in classes.items():
        layers[_layer_of(simple)].append(fqcn)

    return ProjectDeps(
        root=root,
        package_prefix=package_prefix,
        classes=classes,
        edges_by_class=edges_by_class,
        method_calls=method_calls,
        layers={k: sorted(v) for k, v in layers.items() if v},
    )


def _common_prefix(fqcns: List[str]) -> str:
    if not fqcns:
        return ""
    parts = [f.split(".") for f in fqcns]
    prefix = []
    for segment in zip(*parts):
        if len(set(segment)) == 1:
            prefix.append(segment[0])
        else:
            break
    return ".".join(prefix)


# ── Renderers ────────────────────────────────────────────────────────────────


def render_full_tree(deps: ProjectDeps) -> str:
    """
    Полное дерево зависимостей — каждый класс со списком зависимостей.
    """
    lines = [
        f"# Граф зависимостей: `{deps.root.name}`",
        f"\nПакет: `{deps.package_prefix}`  |  "
        f"Классов: {len(deps.classes)}  |  "
        f"Связей: {sum(len(v) for v in deps.edges_by_class.values())}",
    ]

    for layer_name, fqcns in deps.layers.items():
        if not fqcns:
            continue
        lines.append(f"\n## {layer_name}")
        for fqcn in fqcns:
            simple = deps.classes[fqcn]
            edges = deps.edges_by_class.get(fqcn, [])
            lines.append(f"\n### `{simple}`")
            lines.append(f"```\n{fqcn}\n```")

            if edges:
                lines.append("\n**Зависит от:**")
                # Убираем дубли
                seen: Set[str] = set()
                for e in edges:
                    if e.target in seen:
                        continue
                    seen.add(e.target)
                    target_simple = deps.classes.get(e.target, _simple(e.target))
                    target_layer = _layer_of(target_simple)
                    lines.append(f"- `{target_simple}` _{target_layer}_")
            else:
                lines.append("_Нет внутренних зависимостей_")

    return "\n".join(lines)


def render_layered_view(deps: ProjectDeps) -> str:
    """
    Слоёный вид: таблица Controller → Service → Repository.
    Показывает архитектурные потоки.
    """
    lines = [
        f"# Архитектурные слои: `{deps.root.name}`",
        "",
    ]

    layer_order = ["Controller", "Service", "Repository", "Model", "DTO", "Exception", "Config", "Other"]

    present_layers = [l for l in layer_order if l in deps.layers and deps.layers[l]]

    # Заголовок таблицы
    header = " | ".join(present_layers)
    separator = " | ".join(["---"] * len(present_layers))
    lines.append(f"| {header} |")
    lines.append(f"| {separator} |")

    # Собираем классы по слоям
    layer_classes = {
        l: [deps.classes[fqcn] for fqcn in deps.layers.get(l, [])]
        for l in present_layers
    }
    max_len = max((len(v) for v in layer_classes.values()), default=0)

    for i in range(max_len):
        row = []
        for layer in present_layers:
            items = layer_classes[layer]
            row.append(f"`{items[i]}`" if i < len(items) else "")
        lines.append("| " + " | ".join(row) + " |")

    # Потоки вызовов между слоями
    lines.append("\n## Потоки между слоями\n")
    flow_seen: Set[str] = set()

    for fqcn, edges in deps.edges_by_class.items():
        src_simple = deps.classes.get(fqcn, _simple(fqcn))
        src_layer = _layer_of(src_simple)
        for e in edges:
            tgt_simple = deps.classes.get(e.target, _simple(e.target))
            tgt_layer = _layer_of(tgt_simple)
            if src_layer == tgt_layer:
                continue
            flow = f"{src_simple} → {tgt_simple}"
            if flow in flow_seen:
                continue
            flow_seen.add(flow)
            lines.append(f"- `{src_simple}` [{src_layer}] **→** `{tgt_simple}` [{tgt_layer}]")

    return "\n".join(lines)


def render_mermaid(deps: ProjectDeps) -> str:
    """
    Граф в формате Mermaid (graph TD).
    Можно вставить в GitHub README или Obsidian.
    """
    lines = ["```mermaid", "graph TD"]

    layer_styles = {
        "Controller": "fill:#dae8fc,stroke:#6c8ebf",
        "Servlet":    "fill:#dae8fc,stroke:#336699",
        "Service":    "fill:#d5e8d4,stroke:#82b366",
        "Repository": "fill:#fff2cc,stroke:#d6b656",
        "Model":      "fill:#f8cecc,stroke:#b85450",
        "DTO":        "fill:#e1d5e7,stroke:#9673a6",
        "Config":     "fill:#f0f0f0,stroke:#999999",
    }

    node_ids: Dict[str, str] = {}
    for i, (fqcn, simple) in enumerate(deps.classes.items()):
        node_id = f"N{i}"
        node_ids[fqcn] = node_id
        layer = _layer_of(simple)
        lines.append(f'    {node_id}["{simple}"]')
        if layer in layer_styles:
            lines.append(f'    style {node_id} {layer_styles[layer]}')

    seen_edges: Set[str] = set()
    for fqcn, edges in deps.edges_by_class.items():
        src_id = node_ids.get(fqcn)
        if not src_id:
            continue
        for e in edges:
            tgt_id = node_ids.get(e.target)
            if not tgt_id:
                continue
            key = f"{src_id}->{tgt_id}"
            if key in seen_edges:
                continue
            seen_edges.add(key)
            lines.append(f"    {src_id} --> {tgt_id}")

    lines.append("```")
    return "\n".join(lines)


__all__ = [
    "ProjectDeps",
    "build_project_deps",
    "render_full_tree",
    "render_layered_view",
    "render_mermaid",
]

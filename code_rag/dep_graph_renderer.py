from __future__ import annotations

"""
Рендеринг графа зависимостей Java-проекта в Markdown.

Улучшения v2:
1. Entity / Enum разделены из Other
2. Impl-классы свёрнуты под интерфейс в таблице
3. Потоки сгруппированы: главные (cross-layer) отдельно, мелкие — свёрнуты
4. Архитектурные нарушения слоёв выделены отдельной секцией
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .project_scanner import ProjectScanner
from .code_parser import CodeParser
from .dependency_graph import DependencyGraph, Edge
from .dependency_extractor import (
    extract_java_symbols,
    extract_type_dependencies,
    extract_method_calls,
    primary_declared_type,
)


# ── Фильтры ──────────────────────────────────────────────────────────────────

_EXTERNAL_PREFIXES = (
    "java.", "javax.", "jakarta.",
    "org.springframework.", "org.hibernate.", "org.slf4j.",
    "com.fasterxml.", "io.swagger.", "lombok.",
    "org.junit.", "org.mockito.", "org.assertj.",
)

_ANNOTATION_NOISE = frozenset({
    "Data", "Slf4j", "Builder", "Getter", "Setter", "ToString",
    "EqualsAndHashCode", "NoArgsConstructor", "AllArgsConstructor",
    "RequiredArgsConstructor", "Value",
    "Repository", "Service", "Component", "Controller",
    "RestController", "SpringBootApplication",
    "Configuration", "Bean",
    "Override", "SuppressWarnings", "FunctionalInterface",
})

# ── Слои ─────────────────────────────────────────────────────────────────────

_LAYERS: List[Tuple[str, Tuple[str, ...]]] = [
    ("Controller",  ("Controller",)),
    ("Servlet",     ("Servlet", "Fwd", "Filter")),
    ("Service",     ("Service", "ServiceImpl")),
    ("Repository",  ("Repository", "Dao", "DAO")),
    ("Entity",      ("Entity",)),       # явный суффикс Entity
    ("Model",       ("Model", "Bean")),
    ("DTO",         ("Dto", "DTO", "Request", "Response", "Mapper")),
    ("Exception",   ("Exception",)),
    ("Config",      ("Config", "Configuration", "Handler", "Advice", "Util")),
]

# Порядок слоёв в архитектурном потоке (от верхнего к нижнему)
_LAYER_ORDER = [
    "Controller", "Servlet", "Service", "Repository",
    "Entity", "Model", "DTO", "Exception", "Config", "Enum", "Other",
]

# Нарушения: какой слой не должен зависеть от какого
_LAYER_VIOLATIONS = [
    ("Config",      "Repository",  "утилита/конфиг не должна напрямую обращаться в БД"),
    ("Config",      "Service",     "утилита/конфиг не должна вызывать сервисы"),
    ("DTO",         "Repository",  "DTO не должен зависеть от репозитория"),
    ("DTO",         "Service",     "DTO не должен зависеть от сервиса"),
    ("Exception",   "Service",     "исключение не должно зависеть от сервиса"),
    ("Exception",   "Repository",  "исключение не должно зависеть от репозитория"),
    ("Repository",  "Service",     "репозиторий не должен зависеть от сервиса"),
]


def _is_external(fqcn: str) -> bool:
    return any(fqcn.startswith(p) for p in _EXTERNAL_PREFIXES)


def _layer_of(simple_name: str, is_enum: bool = False) -> str:
    if is_enum:
        return "Enum"
    for layer, suffixes in _LAYERS:
        if any(simple_name.endswith(s) for s in suffixes):
            return layer
    return "Other"


def _simple(fqcn: str) -> str:
    return fqcn.split(".")[-1]


def _is_impl(simple: str) -> bool:
    return simple.endswith("Impl")


def _interface_of(simple: str) -> Optional[str]:
    """AccountServiceImpl -> AccountService"""
    if simple.endswith("Impl"):
        return simple[:-4]
    return None


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class ProjectDeps:
    root: Path
    package_prefix: str
    classes: Dict[str, str]           # fqcn -> simple_name
    enums: Set[str]                   # fqcn of enum classes
    edges_by_class: Dict[str, List[Edge]]
    method_calls: Dict[str, List[str]]
    layers: Dict[str, List[str]]      # layer -> [fqcn]


# ── Построение графа ──────────────────────────────────────────────────────────

def build_project_deps(root: Path) -> ProjectDeps:
    root = root.resolve()
    scanner = ProjectScanner(root)
    layout = scanner.scan()
    parser = CodeParser()
    graph = DependencyGraph()

    classes: Dict[str, str] = {}
    enums: Set[str] = set()
    method_calls: Dict[str, List[str]] = {}

    for module in layout.modules:
        for java_file in module.java_sources:
            try:
                parsed = parser.parse_file(java_file)
                src = parsed.source_bytes if parsed.source_bytes else parsed.source
                symbols = extract_java_symbols(parsed.tree, src)
                current_type = primary_declared_type(symbols)
                if not current_type:
                    continue

                fqcn = f"{symbols.package}.{current_type}" if symbols.package else current_type

                # Валидация имени
                if not current_type or len(current_type) > 80:
                    continue
                if not current_type[0].isupper():
                    continue
                if not current_type.replace("_", "").isalnum():
                    continue
                if not current_type.isascii():
                    continue
                if current_type in _ANNOTATION_NOISE:
                    continue

                classes[fqcn] = current_type

                # Определяем enum по source
                source_text = parsed.source_bytes.decode("utf-8", errors="replace") \
                    if parsed.source_bytes else parsed.source
                if re.search(r'\benum\s+' + re.escape(current_type) + r'\b', source_text):
                    enums.add(fqcn)

                # Зависимости
                deps = extract_type_dependencies(parsed.tree, src, symbols)
                for dep in deps:
                    if not _is_external(dep):
                        graph.add_edge(fqcn, dep, kind="uses")

                calls = extract_method_calls(parsed.tree, src, symbols)
                for caller, targets in calls.items():
                    internal = [t for t in targets if not _is_external(t)]
                    if internal:
                        method_calls[caller] = internal
                        for t in internal:
                            graph.add_edge(caller, t, kind="calls")

            except Exception:
                continue

    package_prefix = _common_prefix(list(classes.keys()))
    internal_fqcns = set(classes.keys())

    edges_by_class: Dict[str, List[Edge]] = {}
    for fqcn in classes:
        outgoing = [
            e for e in graph.outgoing(fqcn)
            if e.target in internal_fqcns and e.kind == "uses"
        ]
        if outgoing:
            edges_by_class[fqcn] = outgoing

    # Группировка по слоям (с учётом Enum)
    layers: Dict[str, List[str]] = {layer: [] for layer, _ in _LAYERS}
    layers["Enum"] = []
    layers["Other"] = []
    for fqcn, simple in classes.items():
        layer = _layer_of(simple, is_enum=(fqcn in enums))
        layers[layer].append(fqcn)

    return ProjectDeps(
        root=root,
        package_prefix=package_prefix,
        classes=classes,
        enums=enums,
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


# ── Renderers ─────────────────────────────────────────────────────────────────

def render_layered_view(deps: ProjectDeps) -> str:
    """
    Слоёный вид с улучшениями:
    - Impl свёрнуты под интерфейс
    - Главные потоки (cross-layer) выделены
    - Архитектурные нарушения в отдельной секции
    """
    lines = [f"# Архитектурные слои: `{deps.root.name}`", ""]

    present_layers = [l for l in _LAYER_ORDER if l in deps.layers and deps.layers[l]]

    # Таблица с Impl под интерфейсом
    header = " | ".join(present_layers)
    separator = " | ".join(["---"] * len(present_layers))
    lines.append(f"| {header} |")
    lines.append(f"| {separator} |")

    # Для Service-слоя: строим пары интерфейс/Impl
    layer_display: Dict[str, List[str]] = {}
    for layer in present_layers:
        fqcns = deps.layers.get(layer, [])
        simples = [deps.classes[f] for f in fqcns]
        if layer == "Service":
            # Интерфейсы первыми, Impl — показываем как "(+ impl)"
            interfaces = [s for s in simples if not _is_impl(s)]
            impls = {s for s in simples if _is_impl(s)}
            display = []
            for iface in interfaces:
                impl_name = iface + "Impl"
                if impl_name in impls:
                    display.append(f"{iface} _(+ impl)_")
                    impls.discard(impl_name)
                else:
                    display.append(iface)
            display.extend(sorted(impls))  # orphan Impl без интерфейса
            layer_display[layer] = display
        else:
            layer_display[layer] = [deps.classes[f] for f in fqcns]

    max_len = max((len(v) for v in layer_display.values()), default=0)
    for i in range(max_len):
        row = []
        for layer in present_layers:
            items = layer_display[layer]
            row.append(f"`{items[i]}`" if i < len(items) else "")
        lines.append("| " + " | ".join(row) + " |")

    # Главные потоки (cross-layer, только значимые направления)
    lines.append("\n## Ключевые потоки\n")
    key_flows: List[str] = []
    minor_flows: List[str] = []
    flow_seen: Set[str] = set()

    # Определяем "главные" слои для потоков
    main_layers = {"Controller", "Servlet", "Service", "Repository"}

    for fqcn, edges in deps.edges_by_class.items():
        src_simple = deps.classes.get(fqcn, _simple(fqcn))
        src_layer = _layer_of(src_simple, fqcn in deps.enums)
        if _is_impl(src_simple):
            continue  # Impl не показываем отдельно
        for e in edges:
            tgt_simple = deps.classes.get(e.target, _simple(e.target))
            tgt_layer = _layer_of(tgt_simple, e.target in deps.enums)
            if src_layer == tgt_layer:
                continue
            flow = f"{src_simple} → {tgt_simple}"
            if flow in flow_seen:
                continue
            flow_seen.add(flow)
            line = f"- `{src_simple}` [{src_layer}] **→** `{tgt_simple}` [{tgt_layer}]"
            if src_layer in main_layers and tgt_layer in main_layers:
                key_flows.append(line)
            else:
                minor_flows.append(line)

    if key_flows:
        lines.extend(key_flows)
    else:
        lines.append("_Нет прямых потоков между основными слоями_")

    if minor_flows:
        lines.append(f"\n<details><summary>Прочие зависимости ({len(minor_flows)})</summary>\n")
        lines.extend(minor_flows)
        lines.append("\n</details>")

    # Архитектурные нарушения
    violations = _detect_violations(deps)
    if violations:
        lines.append("\n## ⚠️ Нарушения архитектуры\n")
        for v in violations:
            lines.append(f"- `{v['source']}` [{v['source_layer']}] → `{v['target']}` [{v['target_layer']}]  \n"
                         f"  _{v['reason']}_")

    return "\n".join(lines)


def _detect_violations(deps: ProjectDeps) -> List[Dict]:
    """Находит зависимости нарушающие слоёвую архитектуру."""
    violations = []
    for fqcn, edges in deps.edges_by_class.items():
        src_simple = deps.classes.get(fqcn, _simple(fqcn))
        src_layer = _layer_of(src_simple, fqcn in deps.enums)
        for e in edges:
            tgt_simple = deps.classes.get(e.target, _simple(e.target))
            tgt_layer = _layer_of(tgt_simple, e.target in deps.enums)
            for from_layer, to_layer, reason in _LAYER_VIOLATIONS:
                if src_layer == from_layer and tgt_layer == to_layer:
                    violations.append({
                        "source": src_simple,
                        "target": tgt_simple,
                        "source_layer": src_layer,
                        "target_layer": tgt_layer,
                        "reason": reason,
                    })
    return violations


def render_full_tree(deps: ProjectDeps) -> str:
    """Полное дерево: каждый класс со списком зависимостей."""
    lines = [
        f"# Граф зависимостей: `{deps.root.name}`",
        f"\nПакет: `{deps.package_prefix}`  |  "
        f"Классов: {len(deps.classes)}  |  "
        f"Связей: {sum(len(v) for v in deps.edges_by_class.values())}",
    ]

    for layer_name in _LAYER_ORDER:
        fqcns = deps.layers.get(layer_name, [])
        if not fqcns:
            continue
        lines.append(f"\n## {layer_name}")
        for fqcn in fqcns:
            simple = deps.classes[fqcn]
            edges = deps.edges_by_class.get(fqcn, [])
            tag = " _(enum)_" if fqcn in deps.enums else ""
            lines.append(f"\n### `{simple}`{tag}")
            lines.append(f"```\n{fqcn}\n```")
            if edges:
                lines.append("\n**Зависит от:**")
                seen: Set[str] = set()
                for e in edges:
                    if e.target in seen:
                        continue
                    seen.add(e.target)
                    tgt_simple = deps.classes.get(e.target, _simple(e.target))
                    tgt_layer = _layer_of(tgt_simple, e.target in deps.enums)
                    lines.append(f"- `{tgt_simple}` _{tgt_layer}_")
            else:
                lines.append("_Нет внутренних зависимостей_")

    return "\n".join(lines)


def render_mermaid(deps: ProjectDeps) -> str:
    """Граф в формате Mermaid, сгруппированный по пакетам (subgraph)."""
    lines = ["```mermaid", "graph TD"]

    layer_styles = {
        "Controller": "fill:#dae8fc,stroke:#6c8ebf",
        "Servlet":    "fill:#dae8fc,stroke:#336699",
        "Service":    "fill:#d5e8d4,stroke:#82b366",
        "Repository": "fill:#fff2cc,stroke:#d6b656",
        "Entity":     "fill:#f8cecc,stroke:#b85450",
        "Model":      "fill:#f8cecc,stroke:#b85450",
        "DTO":        "fill:#e1d5e7,stroke:#9673a6",
        "Config":     "fill:#f0f0f0,stroke:#999999",
        "Enum":       "fill:#ffe6cc,stroke:#d79b00",
    }

    node_ids: Dict[str, str] = {}

    # Группируем по слоям через subgraph
    for layer_name in _LAYER_ORDER:
        fqcns = deps.layers.get(layer_name, [])
        if not fqcns:
            continue
        lines.append(f"    subgraph {layer_name}")
        for i, fqcn in enumerate(fqcns):
            simple = deps.classes[fqcn]
            node_id = f"N{len(node_ids)}"
            node_ids[fqcn] = node_id
            if _is_impl(simple):
                iface = _interface_of(simple)
                label = f"{simple}\\n(impl)"
            else:
                label = simple
            lines.append(f'        {node_id}["{label}"]')
            style = layer_styles.get(layer_name, "")
            if style:
                lines.append(f"        style {node_id} {style}")
        lines.append("    end")

    # Рёбра — только cross-layer для читаемости
    seen_edges: Set[str] = set()
    for fqcn, edges in deps.edges_by_class.items():
        src_id = node_ids.get(fqcn)
        if not src_id:
            continue
        src_layer = _layer_of(deps.classes.get(fqcn, ""), fqcn in deps.enums)
        for e in edges:
            tgt_id = node_ids.get(e.target)
            if not tgt_id:
                continue
            tgt_layer = _layer_of(deps.classes.get(e.target, ""), e.target in deps.enums)
            if src_layer == tgt_layer:
                continue  # внутрислойные убираем — слишком много шума
            key = f"{src_id}->{tgt_id}"
            if key in seen_edges:
                continue
            seen_edges.add(key)
            lines.append(f"    {src_id} --> {tgt_id}")

    lines.append("```")
    return "\n".join(lines)


def render_edges_csv(deps: ProjectDeps) -> str:
    lines = ["source,target,source_layer,target_layer,kind"]
    seen: Set[str] = set()
    for fqcn, edges in deps.edges_by_class.items():
        src_simple = deps.classes.get(fqcn, _simple(fqcn))
        src_layer = _layer_of(src_simple, fqcn in deps.enums)
        for e in edges:
            tgt_simple = deps.classes.get(e.target, _simple(e.target))
            tgt_layer = _layer_of(tgt_simple, e.target in deps.enums)
            key = f"{src_simple}->{tgt_simple}"
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"{src_simple},{tgt_simple},{src_layer},{tgt_layer},{e.kind}")
    return "\n".join(lines)


def render_edges_json(deps: ProjectDeps) -> str:
    classes_list = [
        {
            "name": simple,
            "fqcn": fqcn,
            "layer": _layer_of(simple, fqcn in deps.enums),
            "is_enum": fqcn in deps.enums,
        }
        for fqcn, simple in sorted(deps.classes.items())
    ]

    edges_list = []
    seen: Set[str] = set()
    for fqcn, edges in deps.edges_by_class.items():
        src_simple = deps.classes.get(fqcn, _simple(fqcn))
        src_layer = _layer_of(src_simple, fqcn in deps.enums)
        for e in edges:
            tgt_simple = deps.classes.get(e.target, _simple(e.target))
            tgt_layer = _layer_of(tgt_simple, e.target in deps.enums)
            key = f"{src_simple}->{tgt_simple}"
            if key in seen:
                continue
            seen.add(key)
            edges_list.append({
                "source": src_simple,
                "target": tgt_simple,
                "source_layer": src_layer,
                "target_layer": tgt_layer,
                "kind": e.kind,
            })

    violations = _detect_violations(deps)

    return json.dumps({
        "package": deps.package_prefix,
        "stats": {"classes": len(deps.classes), "edges": len(edges_list)},
        "classes": classes_list,
        "edges": edges_list,
        "violations": violations,
    }, ensure_ascii=False, indent=2)


__all__ = [
    "ProjectDeps",
    "build_project_deps",
    "render_layered_view",
    "render_full_tree",
    "render_mermaid",
    "render_edges_csv",
    "render_edges_json",
]

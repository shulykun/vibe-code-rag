from __future__ import annotations

"""
Извлечение зависимостей из Java AST (tree-sitter).

MVP-цель:
- строить зависимости на уровне классов: A -> B (uses)
  на основе:
  - import-ов;
  - используемых type_identifier / scoped_type_identifier.

Это не полноценный call-graph, но уже позволяет делать impact analysis:
"кто зависит от этого класса".
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


@dataclass(frozen=True)
class JavaFileSymbols:
    package: str
    imports: Dict[str, str]  # SimpleName -> FQCN
    declared_types: Set[str]  # simple names


def _node_text(source: str, node: Any) -> str:
    return source[node.start_byte : node.end_byte]


def _walk(node: Any) -> Iterable[Any]:
    yield node
    for ch in node.children:
        yield from _walk(ch)


def extract_java_symbols(tree: Any, source: str) -> JavaFileSymbols:
    root = tree.root_node

    package = ""
    imports: Dict[str, str] = {}
    declared: Set[str] = set()

    for node in _walk(root):
        if node.type == "package_declaration":
            # package_declaration: (scoped_identifier) child usually present
            pkg = _first_descendant_of_type(node, ("scoped_identifier", "identifier"))
            if pkg is not None:
                package = _node_text(source, pkg)

        elif node.type == "import_declaration":
            # import_declaration содержит scoped_identifier / identifier / scoped_identifier + asterisk
            scoped = _first_descendant_of_type(node, ("scoped_identifier",))
            if scoped is not None:
                fqcn = _node_text(source, scoped)
                simple = fqcn.split(".")[-1]
                imports[simple] = fqcn

        elif node.type in ("class_declaration", "interface_declaration", "enum_declaration"):
            ident = _first_descendant_of_type(node, ("identifier",))
            if ident is not None:
                declared.add(_node_text(source, ident))

    return JavaFileSymbols(package=package, imports=imports, declared_types=declared)


def _first_descendant_of_type(node: Any, types: Tuple[str, ...]) -> Optional[Any]:
    for n in _walk(node):
        if n.type in types:
            return n
    return None


def extract_type_dependencies(tree: Any, source: str, symbols: JavaFileSymbols) -> Set[str]:
    """
    Возвращает множество "зависимостей" (FQCN или best-effort) используемых типов.
    """
    root = tree.root_node
    deps: Set[str] = set()

    for node in _walk(root):
        if node.type == "type_identifier":
            name = _node_text(source, node)
            deps.add(_resolve_type(name, symbols))
        elif node.type == "scoped_type_identifier":
            # например: Map.Entry
            deps.add(_node_text(source, node))

    # Не считаем зависимостью типы, объявленные в этом же файле
    for declared in symbols.declared_types:
        deps.discard(_resolve_type(declared, symbols))
        deps.discard(declared)

    return {d for d in deps if d}


def _resolve_type(simple_or_scoped: str, symbols: JavaFileSymbols) -> str:
    # если это импортированный простой тип — вернем fqcn
    if "." not in simple_or_scoped:
        fqcn = symbols.imports.get(simple_or_scoped)
        if fqcn:
            return fqcn
        # best-effort: считаем, что тип из того же package
        if symbols.package:
            return f"{symbols.package}.{simple_or_scoped}"
        return simple_or_scoped
    return simple_or_scoped


def primary_declared_type(symbols: JavaFileSymbols) -> Optional[str]:
    """
    Best-effort: "главный" тип файла — первый из declared_types (set не упорядочен),
    поэтому выбираем лексикографически для стабильности.
    """
    if not symbols.declared_types:
        return None
    return sorted(symbols.declared_types)[0]


def extract_method_calls(tree: Any, source: str, symbols: JavaFileSymbols) -> Dict[str, Set[str]]:
    """
    Best-effort извлечение вызовов методов.

    Возвращает map: caller_method_name -> set(target_nodes)
    где target_nodes это строки вида:
    - "<CurrentFQCN>#method" для неявных вызовов (method()) — считаем, что это вызов внутри класса
    - "<ResolvedType>#method" для вызовов вида Type.method()

    Ограничения:
    - без типизации объектов (obj.method()) мы не можем резолвить тип receiver-а.
      Поэтому обрабатываем только:
      - неявные вызовы method()
      - статические/квалифицированные вызовы Type.method()
    """
    root = tree.root_node
    current_type = primary_declared_type(symbols)
    current_fqcn = f"{symbols.package}.{current_type}" if symbols.package and current_type else (current_type or "")
    if not current_fqcn:
        return {}

    calls: Dict[str, Set[str]] = {}

    # В tree-sitter java: method_declaration содержит identifier как имя метода.
    for node in _walk(root):
        if node.type not in ("method_declaration", "constructor_declaration"):
            continue

        name_node = _first_descendant_of_type(node, ("identifier",))
        caller = _node_text(source, name_node) if name_node is not None else ""
        if not caller:
            continue

        caller_node = f"{current_fqcn}#{caller}"
        calls.setdefault(caller_node, set())

        for inner in _walk(node):
            if inner.type != "method_invocation":
                continue

            method_name = _method_invocation_name(inner, source)
            if not method_name:
                continue

            qualifier = _method_invocation_qualifier(inner, source)
            if qualifier and qualifier[:1].isupper():
                # likely Type.method() — резолвим Type
                target_type = _resolve_type(qualifier, symbols)
                calls[caller_node].add(f"{target_type}#{method_name}")
            else:
                # method() — best-effort: вызов внутри класса
                calls[caller_node].add(f"{current_fqcn}#{method_name}")

    return calls


def _method_invocation_name(node: Any, source: str) -> str:
    # метод — последний identifier внутри method_invocation
    ids: List[Any] = [n for n in _walk(node) if n.type == "identifier"]
    if not ids:
        return ""
    return _node_text(source, ids[-1])


def _method_invocation_qualifier(node: Any, source: str) -> str:
    """
    Возвращает qualifier для вызовов вида Qualifier.method()
    Best-effort: берем первый identifier внутри method_invocation.
    """
    ids: List[Any] = [n for n in _walk(node) if n.type == "identifier"]
    if len(ids) < 2:
        return ""
    return _node_text(source, ids[0])


__all__ = [
    "JavaFileSymbols",
    "extract_java_symbols",
    "extract_type_dependencies",
    "extract_method_calls",
    "primary_declared_type",
]


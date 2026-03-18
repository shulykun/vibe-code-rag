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


def _node_text(source, node: Any) -> str:
    """Извлекает текст узла. source может быть str или bytes."""
    if isinstance(source, (bytes, bytearray)):
        return source[node.start_byte: node.end_byte].decode("utf-8", errors="replace")
    return source[node.start_byte: node.end_byte]


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
            # Ищем identifier прямо среди children (не рекурсивно)
            # чтобы не захватить имена из аннотаций (@Slf4j, @Service и т.д.)
            ident = next((c for c in node.children if c.type == "identifier"), None)
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

    Поддерживаем:
    - неявные вызовы method() — считаем вызовом внутри текущего класса;
    - Type.method() — резолвим Type через imports/package;
    - obj.method() — best-effort резолвим тип obj по:
      - полям класса;
      - параметрам метода;
      - локальным переменным (простые объявления).
    """
    root = tree.root_node
    current_type = primary_declared_type(symbols)
    current_fqcn = f"{symbols.package}.{current_type}" if symbols.package and current_type else (current_type or "")
    if not current_fqcn:
        return {}

    calls: Dict[str, Set[str]] = {}

    class_fields = _extract_field_types(root, source, symbols)

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

        scope_types = dict(class_fields)
        scope_types.update(_extract_parameter_types(node, source, symbols))
        scope_types.update(_extract_local_var_types(node, source, symbols))

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
            elif qualifier:
                # obj.method() — пробуем резолвить obj -> Type
                t = scope_types.get(qualifier)
                if t:
                    calls[caller_node].add(f"{t}#{method_name}")
                else:
                    # не смогли резолвить — пусть будет внутри класса (лучше чем пропустить)
                    calls[caller_node].add(f"{current_fqcn}#{method_name}")
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


def _type_text_for_decl(node: Any, source: str) -> str:
    t = _first_descendant_of_type(node, ("scoped_type_identifier", "type_identifier"))
    if t is None:
        return ""
    return _node_text(source, t)


def _extract_field_types(root: Any, source: str, symbols: JavaFileSymbols) -> Dict[str, str]:
    """
    Map fieldName -> ResolvedType(FQCN best-effort).
    """
    out: Dict[str, str] = {}
    for n in _walk(root):
        if n.type != "field_declaration":
            continue
        t = _type_text_for_decl(n, source)
        if not t:
            continue
        resolved = _resolve_type(t, symbols)

        # поле(я) — variable_declarator -> identifier
        for inner in _walk(n):
            if inner.type == "variable_declarator":
                ident = _first_descendant_of_type(inner, ("identifier",))
                if ident is not None:
                    out[_node_text(source, ident)] = resolved
    return out


def _extract_parameter_types(method_node: Any, source: str, symbols: JavaFileSymbols) -> Dict[str, str]:
    """
    Map paramName -> ResolvedType.
    """
    out: Dict[str, str] = {}
    for n in _walk(method_node):
        if n.type != "formal_parameter":
            continue
        t = _type_text_for_decl(n, source)
        if not t:
            continue
        resolved = _resolve_type(t, symbols)
        ident = _first_descendant_of_type(n, ("identifier",))
        if ident is not None:
            out[_node_text(source, ident)] = resolved
    return out


def _extract_local_var_types(method_node: Any, source: str, symbols: JavaFileSymbols) -> Dict[str, str]:
    """
    Map localVarName -> ResolvedType.
    Best-effort только для простых `Type x = ...;`
    """
    out: Dict[str, str] = {}
    for n in _walk(method_node):
        if n.type != "local_variable_declaration":
            continue
        t = _type_text_for_decl(n, source)
        if not t:
            continue
        resolved = _resolve_type(t, symbols)
        for inner in _walk(n):
            if inner.type == "variable_declarator":
                ident = _first_descendant_of_type(inner, ("identifier",))
                if ident is not None:
                    out[_node_text(source, ident)] = resolved
    return out


__all__ = [
    "JavaFileSymbols",
    "extract_java_symbols",
    "extract_type_dependencies",
    "extract_method_calls",
    "primary_declared_type",
]


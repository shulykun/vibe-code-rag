from __future__ import annotations

from pathlib import Path

from code_rag.code_parser import CodeParser
from code_rag.dependency_extractor import (
    extract_java_symbols,
    extract_method_calls,
    extract_type_dependencies,
    primary_declared_type,
)


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_extract_type_deps_and_method_calls_with_obj_receiver(tmp_path: Path) -> None:
    java = tmp_path / "A.java"
    _write(
        java,
        """
package com.acme;

import com.other.PaymentService;

public class A {
    private PaymentService paymentService;

    public void run(PaymentService ps) {
        paymentService.charge();
        ps.refund();
        helper();
        PaymentService.staticLike();
    }

    private void helper() {}
}
""".lstrip(),
    )

    parsed = CodeParser().parse_file(java)
    symbols = extract_java_symbols(parsed.tree, parsed.source)
    assert symbols.package == "com.acme"
    assert primary_declared_type(symbols) == "A"

    deps = extract_type_dependencies(parsed.tree, parsed.source, symbols)
    # PaymentService должен зарезолвиться через import
    assert "com.other.PaymentService" in deps

    calls = extract_method_calls(parsed.tree, parsed.source, symbols)
    caller = "com.acme.A#run"
    assert caller in calls
    targets = calls[caller]

    # obj.method() по полю/параметру
    assert "com.other.PaymentService#charge" in targets
    assert "com.other.PaymentService#refund" in targets

    # method() внутри класса
    assert "com.acme.A#helper" in targets

    # Type.method()
    assert "com.other.PaymentService#staticLike" in targets


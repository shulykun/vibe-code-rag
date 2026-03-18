from __future__ import annotations

"""Тесты для dep_graph_renderer — без эмбеддингов."""

from pathlib import Path
import pytest

from code_rag.dep_graph_renderer import (
    build_project_deps,
    render_full_tree,
    render_layered_view,
    render_mermaid,
)
from code_rag.mcp_server import mcp_dependency_tree


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture
def layered_project(tmp_path: Path) -> Path:
    root = tmp_path
    _write(root / "pom.xml", "<project/>")
    java = root / "src/main/java/com/acme"

    _write(java / "OrderController.java", """
package com.acme;
import com.acme.OrderService;
public class OrderController {
    private OrderService orderService;
    public void create() { orderService.createOrder(); }
}
""".lstrip())

    _write(java / "OrderService.java", """
package com.acme;
import com.acme.OrderRepository;
import com.acme.PaymentService;
public class OrderService {
    private OrderRepository orderRepository;
    private PaymentService paymentService;
    public void createOrder() {}
}
""".lstrip())

    _write(java / "PaymentService.java", """
package com.acme;
import com.acme.PaymentRepository;
public class PaymentService {
    private PaymentRepository paymentRepository;
    public void charge() {}
}
""".lstrip())

    _write(java / "OrderRepository.java", """
package com.acme;
public interface OrderRepository { void save(); }
""".lstrip())

    _write(java / "PaymentRepository.java", """
package com.acme;
public interface PaymentRepository { void save(); }
""".lstrip())

    _write(java / "OrderDto.java", """
package com.acme;
public class OrderDto { public String id; }
""".lstrip())

    return root


class TestBuildProjectDeps:

    def test_all_classes_found(self, layered_project: Path) -> None:
        deps = build_project_deps(layered_project)
        names = set(deps.classes.values())
        assert "OrderController" in names
        assert "OrderService" in names
        assert "PaymentService" in names
        assert "OrderRepository" in names

    def test_internal_edges_only(self, layered_project: Path) -> None:
        deps = build_project_deps(layered_project)
        for fqcn, edges in deps.edges_by_class.items():
            for e in edges:
                assert e.target in deps.classes, \
                    f"External target leaked: {e.target}"

    def test_layers_classified(self, layered_project: Path) -> None:
        deps = build_project_deps(layered_project)
        assert "Controller" in deps.layers
        assert "Service" in deps.layers
        assert "Repository" in deps.layers
        assert "DTO" in deps.layers
        assert "OrderController" in [deps.classes[f] for f in deps.layers["Controller"]]
        assert "OrderService" in [deps.classes[f] for f in deps.layers["Service"]]

    def test_package_prefix_detected(self, layered_project: Path) -> None:
        deps = build_project_deps(layered_project)
        assert deps.package_prefix == "com.acme"

    def test_edges_service_uses_repository(self, layered_project: Path) -> None:
        deps = build_project_deps(layered_project)
        service_fqcn = next(f for f, s in deps.classes.items() if s == "OrderService")
        targets = {e.target.split(".")[-1] for e in deps.edges_by_class.get(service_fqcn, [])}
        assert "OrderRepository" in targets or "PaymentService" in targets


class TestRenderers:

    def test_full_tree_contains_class_names(self, layered_project: Path) -> None:
        deps = build_project_deps(layered_project)
        md = render_full_tree(deps)
        assert "OrderService" in md
        assert "PaymentService" in md
        assert "## Service" in md

    def test_layered_view_has_table(self, layered_project: Path) -> None:
        deps = build_project_deps(layered_project)
        md = render_layered_view(deps)
        assert "Controller" in md
        assert "Service" in md
        assert "Repository" in md
        assert "→" in md  # потоки

    def test_mermaid_has_graph_syntax(self, layered_project: Path) -> None:
        deps = build_project_deps(layered_project)
        md = render_mermaid(deps)
        assert "```mermaid" in md
        assert "graph TD" in md
        assert "-->" in md


class TestExport:

    def test_export_creates_file(self, layered_project: Path) -> None:
        result = mcp_dependency_tree(str(layered_project), export=True)
        assert result["exported_to"] is not None
        out = Path(result["exported_to"])
        assert out.exists()
        assert out.name == "DEPENDENCY_TREE.md"
        assert out.parent == layered_project

    def test_exported_file_contains_markdown(self, layered_project: Path) -> None:
        mcp_dependency_tree(str(layered_project), export=True)
        content = (layered_project / "DEPENDENCY_TREE.md").read_text()
        assert "OrderService" in content
        assert "Сгенерировано" in content  # footer

    def test_custom_output_filename(self, layered_project: Path) -> None:
        result = mcp_dependency_tree(str(layered_project), export=True, output_file="ARCH.md")
        assert Path(result["exported_to"]).name == "ARCH.md"
        assert (layered_project / "ARCH.md").exists()

    def test_no_export_by_default(self, layered_project: Path) -> None:
        result = mcp_dependency_tree(str(layered_project))
        assert result["exported_to"] is None
        assert not (layered_project / "DEPENDENCY_TREE.md").exists()

    def test_export_overwrites_existing(self, layered_project: Path) -> None:
        out = layered_project / "DEPENDENCY_TREE.md"
        out.write_text("old content")
        mcp_dependency_tree(str(layered_project), export=True)
        assert "old content" not in out.read_text()
        assert "OrderService" in out.read_text()


class TestMcpDependencyTree:

    def test_returns_markdown_and_stats(self, layered_project: Path) -> None:
        result = mcp_dependency_tree(str(layered_project))
        assert "markdown" in result
        assert "stats" in result
        assert result["stats"]["classes"] >= 5
        assert result["stats"]["package_prefix"] == "com.acme"

    def test_format_full(self, layered_project: Path) -> None:
        result = mcp_dependency_tree(str(layered_project), format="full")
        assert "# Граф зависимостей" in result["markdown"]

    def test_format_mermaid(self, layered_project: Path) -> None:
        result = mcp_dependency_tree(str(layered_project), format="mermaid")
        assert "mermaid" in result["markdown"]

    def test_format_all_contains_all_sections(self, layered_project: Path) -> None:
        result = mcp_dependency_tree(str(layered_project), format="all")
        md = result["markdown"]
        assert "graph TD" in md
        assert "# Граф зависимостей" in md
        assert "# Архитектурные слои" in md

    def test_works_on_bike_rental(self) -> None:
        """Тест на реальном проекте — без эмбеддингов, быстро."""
        bike = Path(__file__).resolve().parents[2] / "bike-rental-service"
        if not bike.exists():
            pytest.skip("bike-rental-service not found")
        result = mcp_dependency_tree(str(bike))
        assert result["stats"]["classes"] > 20
        assert "RentalService" in result["markdown"]
        assert "DiscountService" in result["markdown"]
        assert "BlogService" in result["markdown"]

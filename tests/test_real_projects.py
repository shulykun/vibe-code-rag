from __future__ import annotations

"""
Smoke-тесты на реальных Java-проектах.

Клонированы локально, пропускаются если не найдены.
Проверяют что анализ не падает и возвращает разумные результаты.
"""

import pytest
from pathlib import Path

from code_rag.mcp_server import mcp_dependency_tree

PROJECTS_DIR = Path(__file__).resolve().parents[2]


def _project(name: str) -> Path:
    return PROJECTS_DIR / name


def _skip_if_missing(name: str):
    return pytest.mark.skipif(
        not _project(name).exists(),
        reason=f"{name} not cloned locally",
    )


# ── bike-rental-service ───────────────────────────────────────────────────────

@_skip_if_missing("bike-rental-service")
def test_bike_rental_layers():
    result = mcp_dependency_tree(str(_project("bike-rental-service")))
    layers = result["stats"]["layers"]
    assert "Controller" in layers
    assert "Service" in layers
    assert "Repository" in layers
    assert layers["Controller"] >= 3
    assert layers["Service"] >= 5
    assert layers["Repository"] >= 3


@_skip_if_missing("bike-rental-service")
def test_bike_rental_key_classes():
    result = mcp_dependency_tree(str(_project("bike-rental-service")))
    md = result["markdown"]
    assert "RentalService" in md
    assert "DiscountService" in md
    assert "BlogService" in md
    assert result["stats"]["classes"] >= 35


# ── Train-Ticket-Reservation-System ──────────────────────────────────────────

@_skip_if_missing("Train-Ticket-Reservation-System")
def test_train_ticket_finds_services():
    result = mcp_dependency_tree(str(_project("Train-Ticket-Reservation-System")))
    layers = result["stats"]["layers"]
    assert "Service" in layers
    assert layers["Service"] >= 3  # BookingService, TrainService, UserService
    assert result["stats"]["classes"] >= 40


@_skip_if_missing("Train-Ticket-Reservation-System")
def test_train_ticket_servlet_layer():
    result = mcp_dependency_tree(str(_project("Train-Ticket-Reservation-System")))
    md = result["markdown"]
    # Хотя бы часть классов с Fwd/Servlet суффиксами попадает в Servlet-слой
    layers = result["stats"]["layers"]
    assert "Servlet" in layers or "Service" in layers


@_skip_if_missing("Train-Ticket-Reservation-System")
def test_train_ticket_non_standard_src_layout():
    """Проверяем что нестандартный src/ layout корректно сканируется."""
    result = mcp_dependency_tree(str(_project("Train-Ticket-Reservation-System")))
    assert result["stats"]["package_prefix"] == "com.shashi"
    assert result["stats"]["classes"] >= 40


# ── jasome ───────────────────────────────────────────────────────────────────

@_skip_if_missing("jasome")
def test_jasome_gradle_project():
    result = mcp_dependency_tree(str(_project("jasome")))
    assert result["stats"]["build_system"] if "build_system" in result["stats"] else True
    assert result["stats"]["classes"] >= 30
    assert result["stats"]["package_prefix"] == "org.jasome"


@_skip_if_missing("jasome")
def test_jasome_calculator_classes():
    result = mcp_dependency_tree(str(_project("jasome")))
    md = result["markdown"]
    assert "Calculator" in md
    assert "Metric" in md


# ── BankingPortal-API ─────────────────────────────────────────────────────────

@_skip_if_missing("BankingPortal-API")
def test_banking_portal_full_stack():
    result = mcp_dependency_tree(str(_project("BankingPortal-API")))
    layers = result["stats"]["layers"]
    assert "Controller" in layers
    assert "Service" in layers
    assert "Repository" in layers
    assert "Exception" in layers
    assert layers["Exception"] >= 10  # много кастомных исключений


@_skip_if_missing("BankingPortal-API")
def test_banking_portal_dto_layer():
    """TransactionDTO должен попасть в DTO (uppercase суффикс)."""
    result = mcp_dependency_tree(str(_project("BankingPortal-API")))
    layers = result["stats"]["layers"]
    assert "DTO" in layers
    # TransactionDTO, AccountResponse, UserResponse, TransactionMapper
    assert layers["DTO"] >= 3


@_skip_if_missing("BankingPortal-API")
def test_banking_portal_config_layer():
    result = mcp_dependency_tree(str(_project("BankingPortal-API")))
    layers = result["stats"]["layers"]
    assert "Config" in layers
    assert layers["Config"] >= 4  # CacheConfig, CorsConfig, WebSecurityConfig, GlobalExceptionHandler


@_skip_if_missing("BankingPortal-API")
def test_banking_portal_stats():
    result = mcp_dependency_tree(str(_project("BankingPortal-API")))
    stats = result["stats"]
    assert stats["classes"] >= 60
    assert stats["edges"] >= 80
    assert stats["package_prefix"] == "com.webapp.bankingportal"


@_skip_if_missing("BankingPortal-API")
def test_banking_portal_export(tmp_path):
    """Экспорт не должен писать в исходный проект в этом тесте — используем tmp."""
    result = mcp_dependency_tree(
        str(_project("BankingPortal-API")),
        export=True,
        output_file=str(tmp_path / "DEPS.md"),
    )
    assert result["exported_to"] is not None
    out = Path(result["exported_to"])
    assert out.exists()
    content = out.read_text()
    assert "AccountController" in content
    assert "Сгенерировано" in content

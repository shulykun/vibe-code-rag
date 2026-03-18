from __future__ import annotations

"""Тесты для keyword_extractor."""

from code_rag.keyword_extractor import extract_keywords, format_keywords_for_embed


def test_extracts_enum_values():
    code = """
    rental.setStatus(RentalStatus.COMPLETED);
    bike.setStatus(BikeStatus.AVAILABLE);
    """
    kws = extract_keywords(code)
    assert any("completed" in k for k in kws)
    assert any("available" in k for k in kws)


def test_extracts_meaningful_annotations():
    code = """
    @Transactional
    @Cacheable("users")
    public User findById(Long id) { return repo.findById(id).orElseThrow(); }
    """
    kws = extract_keywords(code)
    assert "transactional" in kws
    assert "cacheable" in kws


def test_extracts_thrown_exceptions():
    code = """
    if (!bike.isAvailable()) throw new BikeNotAvailableException(bike.getId());
    if (customer == null) throw new ResourceNotFoundException("Customer", id);
    """
    kws = extract_keywords(code)
    assert any("bike not available" in k for k in kws)
    assert any("resource not found" in k for k in kws)


def test_extracts_string_constants():
    code = """
    log.info("Rental started successfully");
    throw new IllegalStateException("Cancellation window expired");
    """
    kws = extract_keywords(code)
    assert any("cancellation window expired" in k for k in kws)


def test_limit_check_keywords():
    code = """
    if (elapsed.toMinutes() > 5) {
        throw new IllegalStateException("too late");
    }
    """
    kws = extract_keywords(code)
    assert any("5" in k for k in kws)


def test_no_stop_words_alone():
    code = "if (this.get() != null) { return new Object(); }"
    kws = extract_keywords(code)
    # Стоп-слова не должны быть ключевыми словами
    assert "get" not in kws
    assert "null" not in kws
    assert "this" not in kws


def test_deduplication():
    code = """
    bike.setStatus(BikeStatus.AVAILABLE);
    if (!bike.isAvailable()) bike.setStatus(BikeStatus.AVAILABLE);
    """
    kws = extract_keywords(code)
    available_count = sum(1 for k in kws if "available" in k and "bikestatus" in k)
    assert available_count == 1  # дедупликация работает


def test_empty_code():
    assert extract_keywords("") == []
    assert extract_keywords("{}") == []


def test_format_keywords_for_embed():
    kws = ["transactional", "bike status available", "bonus points"]
    result = format_keywords_for_embed(kws)
    assert result.startswith("// Keywords:")
    assert "transactional" in result
    assert "bonus points" in result


def test_format_empty_keywords():
    assert format_keywords_for_embed([]) == ""


def test_embed_text_contains_keywords():
    """Chunker должен включать keywords в embed_text для методов."""
    from code_rag.code_parser import CodeParser
    from code_rag.chunker import Chunker
    from pathlib import Path
    import tempfile

    java_code = """
package com.test;
public class PaymentService {
    /**
     * Processes payment and charges the card.
     */
    @Transactional
    public void processPayment(String orderId, double amount) {
        if (amount <= 0) throw new IllegalArgumentException("Invalid amount");
        payment.setStatus(PaymentStatus.COMPLETED);
    }
}
""".lstrip()

    with tempfile.NamedTemporaryFile(suffix=".java", mode="w", delete=False) as f:
        f.write(java_code)
        tmp = Path(f.name)

    try:
        parsed = CodeParser().parse_file(tmp)
        chunks = Chunker().build_chunks_for_file(parsed)
        method_chunks = [c for c in chunks if c.kind == "method"]
        assert len(method_chunks) > 0
        embed = method_chunks[0].embed_text
        assert "// Keywords:" in embed
        assert "transactional" in embed.lower()
    finally:
        tmp.unlink()

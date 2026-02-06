"""Tests for the Devanagari terminal font renderer."""

from hindi_srs.devanagari_renderer import (
    _bitmap_to_blocks,
    _fallback_render,
    is_devanagari,
    render_card_display,
    render_devanagari,
    render_if_devanagari,
)


class TestIsDevanagari:
    def test_hindi_text(self) -> None:
        assert is_devanagari("नमस्ते") is True

    def test_mixed_text(self) -> None:
        assert is_devanagari("hello नमस्ते world") is True

    def test_english_only(self) -> None:
        assert is_devanagari("hello world") is False

    def test_empty_string(self) -> None:
        assert is_devanagari("") is False

    def test_devanagari_digits(self) -> None:
        # Devanagari digits are in U+0966-U+096F range
        assert is_devanagari("१२३") is True

    def test_other_scripts(self) -> None:
        assert is_devanagari("こんにちは") is False
        assert is_devanagari("مرحبا") is False


class TestFallbackRender:
    def test_basic_fallback(self) -> None:
        result = _fallback_render("hello")
        assert "hello" in result
        assert "┌" in result
        assert "┘" in result

    def test_fallback_with_indent(self) -> None:
        result = _fallback_render("test", indent="    ")
        lines = result.split("\n")
        for line in lines:
            assert line.startswith("    ")


class TestBitmapToBlocks:
    def test_empty_grid(self) -> None:
        result = _bitmap_to_blocks([])
        assert result == ""

    def test_simple_2x2_all_on(self) -> None:
        grid = [[True, True], [True, True]]
        result = _bitmap_to_blocks(grid, indent="")
        assert "█" in result

    def test_simple_2x2_top_only(self) -> None:
        grid = [[True, True], [False, False]]
        result = _bitmap_to_blocks(grid, indent="")
        assert "▀" in result

    def test_simple_2x2_bottom_only(self) -> None:
        grid = [[False, False], [True, True]]
        result = _bitmap_to_blocks(grid, indent="")
        assert "▄" in result

    def test_odd_rows(self) -> None:
        # Odd number of rows — last row treated as top-only
        grid = [[True, True], [True, True], [True, True]]
        result = _bitmap_to_blocks(grid, indent="")
        lines = result.strip().split("\n")
        assert len(lines) == 2  # 3 rows -> 2 block lines


class TestRenderDevanagari:
    def test_renders_multiline_output(self) -> None:
        result = render_devanagari("नमस्ते")
        lines = result.split("\n")
        assert len(lines) > 1  # Should produce multiple lines of block art

    def test_uses_block_characters(self) -> None:
        result = render_devanagari("क")
        # Should contain at least one of the block characters
        block_chars = {"█", "▀", "▄"}
        found = any(ch in result for ch in block_chars)
        assert found, f"Expected block characters in output, got: {result!r}"

    def test_custom_font_size(self) -> None:
        small = render_devanagari("क", font_size=14)
        large = render_devanagari("क", font_size=30)
        # Larger font should produce more lines
        assert len(large.split("\n")) >= len(small.split("\n"))

    def test_indent(self) -> None:
        result = render_devanagari("क", indent=">>>")
        for line in result.split("\n"):
            assert line.startswith(">>>")


class TestRenderIfDevanagari:
    def test_renders_devanagari(self) -> None:
        result = render_if_devanagari("नमस्ते")
        lines = result.split("\n")
        assert len(lines) > 1  # Block art, not plain text

    def test_passes_through_english(self) -> None:
        result = render_if_devanagari("hello")
        assert result.strip() == "hello"


class TestRenderCardDisplay:
    def test_produces_bordered_output(self) -> None:
        result = render_card_display("नमस्ते", romanization="namaste", definition="hello")
        assert "┌" in result
        assert "┘" in result
        assert "namaste" in result
        assert "hello" in result

    def test_without_metadata(self) -> None:
        result = render_card_display("क")
        assert "┌" in result
        assert "┘" in result

    def test_contains_block_art(self) -> None:
        result = render_card_display("नमस्ते")
        block_chars = {"█", "▀", "▄"}
        found = any(ch in result for ch in block_chars)
        assert found

"""Tests for the Devanagari terminal font renderer."""

import io
from unittest.mock import patch

from hindi_srs.devanagari_renderer import (
    _fallback_render,
    _find_font,
    _is_iterm2_terminal,
    _is_kitty_terminal,
    _supports_inline_images,
    display_card,
    display_mixed_text,
    extract_devanagari_segments,
    is_devanagari,
    is_pure_devanagari,
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
        assert is_devanagari("१२३") is True

    def test_other_scripts(self) -> None:
        assert is_devanagari("こんにちは") is False
        assert is_devanagari("مرحبا") is False


class TestExtractDevanagariSegments:
    def test_pure_english(self) -> None:
        result = extract_devanagari_segments("hello world")
        assert len(result) == 1
        assert result[0][1] is False

    def test_pure_devanagari(self) -> None:
        result = extract_devanagari_segments("नमस्ते")
        assert len(result) == 1
        assert result[0][1] is True

    def test_mixed_text(self) -> None:
        result = extract_devanagari_segments("What is: नमस्ते?")
        assert len(result) >= 2
        has_english = any(not is_dev for _, is_dev in result)
        has_devanagari = any(is_dev for _, is_dev in result)
        assert has_english and has_devanagari

    def test_empty_string(self) -> None:
        assert extract_devanagari_segments("") == []

    def test_meaning_prompt_format(self) -> None:
        result = extract_devanagari_segments("What is the meaning of: सबसे अच्छा खिलाड़ी कौन है?")
        devanagari_segments = [seg for seg, is_dev in result if is_dev]
        assert len(devanagari_segments) >= 1
        assert "सबसे" in devanagari_segments[0] or "खिलाड़ी" in devanagari_segments[0]


class TestIsPureDevanagari:
    def test_pure_hindi(self) -> None:
        assert is_pure_devanagari("नमस्ते") is True

    def test_hindi_with_punctuation(self) -> None:
        assert is_pure_devanagari("नमस्ते!") is True
        assert is_pure_devanagari("क्या हाल है?") is True

    def test_hindi_with_numbers(self) -> None:
        assert is_pure_devanagari("१२३") is True
        assert is_pure_devanagari("नमस्ते 123") is True

    def test_mixed_with_latin(self) -> None:
        assert is_pure_devanagari("hello नमस्ते") is False
        assert is_pure_devanagari("What is: नमस्ते") is False

    def test_pure_english(self) -> None:
        assert is_pure_devanagari("hello") is False

    def test_empty(self) -> None:
        assert is_pure_devanagari("") is False


class TestFallbackRender:
    def test_basic_fallback(self) -> None:
        result = _fallback_render("hello")
        assert "hello" in result
        assert "╭" in result
        assert "╯" in result

    def test_fallback_with_indent(self) -> None:
        result = _fallback_render("test", indent="    ")
        for line in result.split("\n"):
            assert line.startswith("    ")


class TestFindFont:
    def test_returns_path_or_none(self) -> None:
        result = _find_font()
        assert result is None or result.endswith((".ttf", ".ttc"))

    def test_respects_env_override(self) -> None:
        with patch.dict("os.environ", {"HINDI_SRS_FONT": "/nonexistent/font.ttf"}):
            result = _find_font()
            assert result != "/nonexistent/font.ttf"


class TestTerminalDetection:
    def test_kitty_detection_via_term(self) -> None:
        with patch.dict("os.environ", {"TERM": "xterm-kitty", "TERM_PROGRAM": ""}):
            assert _is_kitty_terminal() is True

    def test_kitty_detection_via_term_program(self) -> None:
        with patch.dict("os.environ", {"TERM": "", "TERM_PROGRAM": "kitty"}):
            assert _is_kitty_terminal() is True

    def test_not_kitty(self) -> None:
        with patch.dict("os.environ", {"TERM": "xterm-256color", "TERM_PROGRAM": ""}, clear=True):
            assert _is_kitty_terminal() is False

    def test_iterm2_detection_via_session(self) -> None:
        with patch.dict("os.environ", {"ITERM_SESSION_ID": "w0t0p0:12345", "TERM_PROGRAM": ""}):
            assert _is_iterm2_terminal() is True

    def test_iterm2_detection_via_term_program(self) -> None:
        with patch.dict("os.environ", {"ITERM_SESSION_ID": "", "TERM_PROGRAM": "iTerm.app"}):
            assert _is_iterm2_terminal() is True

    def test_not_iterm2(self) -> None:
        with patch.dict("os.environ", {"ITERM_SESSION_ID": "", "TERM_PROGRAM": ""}, clear=True):
            assert _is_iterm2_terminal() is False


class TestSupportsInlineImages:
    def test_kitty_supports(self) -> None:
        with patch.dict(
            "os.environ", {"TERM": "xterm-kitty", "TERM_PROGRAM": "", "ITERM_SESSION_ID": ""}
        ):
            assert _supports_inline_images() is True

    def test_iterm2_supports(self) -> None:
        with patch.dict(
            "os.environ", {"TERM": "", "TERM_PROGRAM": "iTerm.app", "ITERM_SESSION_ID": ""}
        ):
            assert _supports_inline_images() is True

    def test_plain_terminal_no_support(self) -> None:
        with patch.dict(
            "os.environ", {"TERM": "xterm", "TERM_PROGRAM": "", "ITERM_SESSION_ID": ""}, clear=True
        ):
            assert _supports_inline_images() is False


class TestRenderDevanagari:
    def test_returns_text_with_indent(self) -> None:
        result = render_devanagari("नमस्ते")
        assert "नमस्ते" in result
        assert result.startswith("  ")

    def test_custom_indent(self) -> None:
        result = render_devanagari("क", indent=">>>")
        assert result == ">>>क"


class TestRenderIfDevanagari:
    def test_returns_text_without_image_support(self) -> None:
        with patch.dict(
            "os.environ", {"TERM": "xterm", "TERM_PROGRAM": "", "ITERM_SESSION_ID": ""}, clear=True
        ):
            result = render_if_devanagari("नमस्ते")
            assert result.strip() == "नमस्ते"

    def test_passes_through_english(self) -> None:
        result = render_if_devanagari("hello")
        assert result.strip() == "hello"


class TestDisplayMixedText:
    def test_prints_text_when_no_image_support(self) -> None:
        with patch.dict(
            "os.environ", {"TERM": "xterm", "TERM_PROGRAM": "", "ITERM_SESSION_ID": ""}, clear=True
        ):
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                display_mixed_text("What is: नमस्ते?")
            output = captured.getvalue()
            assert "नमस्ते" in output
            assert "What is:" in output


class TestDisplayCard:
    def test_prints_bordered_output(self) -> None:
        with patch.dict(
            "os.environ", {"TERM": "xterm", "TERM_PROGRAM": "", "ITERM_SESSION_ID": ""}, clear=True
        ):
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                display_card("नमस्ते", romanization="namaste", definition="hello")
            output = captured.getvalue()
            assert "╭" in output
            assert "╯" in output
            assert "namaste" in output
            assert "hello" in output
            assert "नमस्ते" in output

    def test_without_metadata(self) -> None:
        with patch.dict(
            "os.environ", {"TERM": "xterm", "TERM_PROGRAM": "", "ITERM_SESSION_ID": ""}, clear=True
        ):
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                display_card("क")
            output = captured.getvalue()
            assert "╭" in output
            assert "╯" in output
            assert "क" in output

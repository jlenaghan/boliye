"""Render Devanagari text beautifully in the terminal.

Supports inline image rendering in Kitty and iTerm2 terminals using the
ITF Devanagari font. For mixed English/Hindi text, extracts and renders
only the Devanagari portions as images while keeping English as plain text.

Falls back to plain Unicode for unsupported terminals.

Usage:
    from hindi_srs.devanagari_renderer import render_if_devanagari, display_card

    # Mixed text - Hindi rendered as inline images
    print(render_if_devanagari("What is: नमस्ते?"))

    # Card display with term, romanization, and definition
    display_card("नमस्ते", romanization="namaste", definition="hello")
"""

from __future__ import annotations

import base64
import io
import os
import shutil
import sys

_PILLOW_AVAILABLE = False
try:
    from PIL import Image, ImageDraw, ImageFont

    _PILLOW_AVAILABLE = True
except ImportError:
    pass


# =============================================================================
# Configuration
# =============================================================================

# Font search paths, ordered by preference (ITF Devanagari first for best rendering)
_FONT_SEARCH_PATHS: list[str] = [
    # macOS fonts
    "/System/Library/Fonts/Supplemental/ITFDevanagari.ttc",
    "/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc",
    "/System/Library/Fonts/Supplemental/DevanagariMT.ttc",
    # Linux fonts (Noto)
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
    "/usr/share/fonts/google-noto/NotoSansDevanagari-Regular.ttf",
    "/usr/share/fonts/truetype/noto-sans-devanagari/NotoSansDevanagari-Regular.ttf",
    # User-installed on macOS
    "/Library/Fonts/NotoSansDevanagari-Regular.ttf",
]

_DEFAULT_FONT_SIZE = 36
_BG_COLOR = (30, 30, 30)  # Dark background
_TEXT_COLOR = (220, 220, 220)  # Light text


# =============================================================================
# Terminal Detection
# =============================================================================


def _is_kitty_terminal() -> bool:
    """Check if running in Kitty terminal."""
    term = os.environ.get("TERM", "")
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    return term.startswith("xterm-kitty") or "kitty" in term_program


def _is_iterm2_terminal() -> bool:
    """Check if running in iTerm2."""
    return bool(os.environ.get("ITERM_SESSION_ID")) or os.environ.get("TERM_PROGRAM") == "iTerm.app"


def _supports_inline_images() -> bool:
    """Check if terminal supports inline images."""
    return _is_kitty_terminal() or _is_iterm2_terminal()


def _find_font() -> str | None:
    """Return the first available Devanagari font path, or None."""
    env_font = os.environ.get("HINDI_SRS_FONT")
    if env_font and os.path.isfile(env_font):
        return env_font

    for path in _FONT_SEARCH_PATHS:
        if os.path.isfile(path):
            return path
    return None


# =============================================================================
# Character Classification
# =============================================================================


def _is_devanagari_char(ch: str) -> bool:
    """Check if a character is in the Devanagari Unicode range."""
    cp = ord(ch)
    return 0x0900 <= cp <= 0x097F or 0xA8E0 <= cp <= 0xA8FF


def is_devanagari(text: str) -> bool:
    """Return True if text contains any Devanagari characters."""
    return any(_is_devanagari_char(ch) for ch in text)


def is_pure_devanagari(text: str) -> bool:
    """Return True if text contains Devanagari and no Latin letters.

    Allows punctuation, digits, and whitespace alongside Devanagari.
    """
    has_devanagari = False
    for ch in text:
        cp = ord(ch)
        if (0x0041 <= cp <= 0x005A) or (0x0061 <= cp <= 0x007A):  # A-Z, a-z
            return False
        if _is_devanagari_char(ch):
            has_devanagari = True
    return has_devanagari


def extract_devanagari_segments(text: str) -> list[tuple[str, bool]]:
    """Split text into (segment, is_devanagari) tuples.

    Groups contiguous Devanagari and non-Devanagari text separately.
    Punctuation and whitespace stay with their adjacent segment.
    """
    if not text:
        return []

    segments: list[tuple[str, bool]] = []
    current_segment = ""
    current_is_devanagari: bool | None = None
    neutral_chars = " \t.,!?;:।॥'\"()-"

    for ch in text:
        ch_is_dev = _is_devanagari_char(ch)
        is_neutral = ch in neutral_chars

        if current_is_devanagari is None:
            current_is_devanagari = ch_is_dev
            current_segment = ch
        elif is_neutral or ch_is_dev == current_is_devanagari:
            current_segment += ch
        else:
            if current_segment.strip():
                segments.append((current_segment, current_is_devanagari))
            current_segment = ch
            current_is_devanagari = ch_is_dev

    if current_segment.strip():
        segments.append((current_segment, current_is_devanagari))

    return segments


# =============================================================================
# Image Rendering
# =============================================================================


def _render_text_to_image(
    text: str,
    font_path: str,
    font_size: int = _DEFAULT_FONT_SIZE,
    padding: int = 15,
) -> Image.Image:
    """Render text to a PIL Image with the specified font."""
    font = ImageFont.truetype(font_path, font_size)

    # Measure text bounds
    dummy = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0] + padding * 2
    height = bbox[3] - bbox[1] + padding * 2

    # Render
    img = Image.new("RGB", (width, height), color=_BG_COLOR)
    draw = ImageDraw.Draw(img)
    draw.text((padding, -bbox[1] + padding), text, font=font, fill=_TEXT_COLOR)

    return img


def _image_to_base64_png(img: Image.Image) -> str:
    """Convert PIL Image to base64-encoded PNG string."""
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.standard_b64encode(buffer.getvalue()).decode("ascii")


def _display_kitty_image(img: Image.Image) -> None:
    """Display image using Kitty graphics protocol."""
    b64_data = _image_to_base64_png(img)
    chunk_size = 4096
    first = True

    while b64_data:
        chunk = b64_data[:chunk_size]
        b64_data = b64_data[chunk_size:]
        m = 1 if b64_data else 0

        if first:
            sys.stdout.write(f"\033_Ga=T,f=100,m={m};{chunk}\033\\")
            first = False
        else:
            sys.stdout.write(f"\033_Gm={m};{chunk}\033\\")

    sys.stdout.flush()


def _display_iterm2_image(img: Image.Image) -> None:
    """Display image using iTerm2 inline image protocol."""
    b64_data = _image_to_base64_png(img)
    sys.stdout.write(f"\033]1337;File=inline=1;width=auto;preserveAspectRatio=1:{b64_data}\a")
    sys.stdout.flush()


def _display_inline_image(img: Image.Image) -> None:
    """Display image using the appropriate terminal protocol."""
    if _is_kitty_terminal():
        _display_kitty_image(img)
    elif _is_iterm2_terminal():
        _display_iterm2_image(img)


# =============================================================================
# Public API
# =============================================================================


def display_mixed_text(
    text: str,
    *,
    font_size: int = _DEFAULT_FONT_SIZE,
    indent: str = "  ",
) -> None:
    """Display mixed text with Devanagari segments as inline images.

    Prints directly to stdout. English text appears as plain terminal text,
    Devanagari text renders as inline images (in supported terminals).
    """
    print(indent, end="")

    if not _PILLOW_AVAILABLE or not _supports_inline_images():
        print(text)
        return

    font_path = _find_font()
    if not font_path:
        print(text)
        return

    segments = extract_devanagari_segments(text)
    for segment_text, is_dev in segments:
        if is_dev:
            img = _render_text_to_image(segment_text.strip(), font_path, font_size)
            _display_inline_image(img)
        else:
            print(segment_text, end="")

    print()


def render_if_devanagari(
    text: str,
    *,
    font_size: int = _DEFAULT_FONT_SIZE,
    indent: str = "  ",
) -> str:
    """Display text with Devanagari portions as inline images.

    For terminals supporting inline images (Kitty, iTerm2), renders
    Devanagari segments as images and returns empty string.
    For other terminals, returns the text with indent for printing.
    """
    if is_devanagari(text) and _PILLOW_AVAILABLE and _supports_inline_images():
        font_path = _find_font()
        if font_path:
            display_mixed_text(text, font_size=font_size, indent=indent)
            return ""

    return f"{indent}{text}"


def display_card(
    term: str,
    romanization: str = "",
    definition: str = "",
    *,
    font_size: int = _DEFAULT_FONT_SIZE,
) -> None:
    """Display a flashcard with Devanagari term and metadata.

    Renders the term as an inline image (if supported) within a
    decorative box, with romanization and definition below.
    """
    term_width = shutil.get_terminal_size((80, 24)).columns
    box_width = min(60, term_width - 4)

    def print_text_line(text: str) -> None:
        padded = f"  {text}"
        if len(padded) < box_width:
            padded += " " * (box_width - len(padded))
        elif len(padded) > box_width:
            padded = padded[: box_width - 3] + "..."
        print(f"  │{padded}│")

    # Top border
    print(f"  ╭{'─' * box_width}╮")
    print(f"  │{' ' * box_width}│")

    # Term (image or text)
    if is_pure_devanagari(term) and _PILLOW_AVAILABLE and _supports_inline_images():
        font_path = _find_font()
        if font_path:
            img = _render_text_to_image(term, font_path, font_size)
            print("  │  ", end="")
            _display_inline_image(img)
            print(f"{' ' * (box_width - 4)}│")
        else:
            print_text_line(term)
    else:
        print_text_line(term)

    print(f"  │{' ' * box_width}│")
    print(f"  ├{'─' * box_width}┤")

    # Metadata
    if romanization:
        print_text_line(romanization)
    if definition:
        print_text_line(definition)
    if romanization or definition:
        print(f"  │{' ' * box_width}│")

    # Bottom border
    print(f"  ╰{'─' * box_width}╯")


# =============================================================================
# Legacy API (for backward compatibility)
# =============================================================================


def render_devanagari(
    text: str,
    *,
    font_size: int = _DEFAULT_FONT_SIZE,
    indent: str = "  ",
    fallback: bool = True,
) -> str:
    """Return text with indent. Use render_if_devanagari() for image display."""
    return f"{indent}{text}"


def render_card_display(
    term: str,
    romanization: str = "",
    definition: str = "",
    *,
    font_size: int = _DEFAULT_FONT_SIZE,
) -> str:
    """Display card and return empty string. Use display_card() directly."""
    display_card(term, romanization, definition, font_size=font_size)
    return ""


def _fallback_render(text: str, indent: str = "  ") -> str:
    """Simple bordered text for testing."""
    inner = f" {text} "
    width = len(inner) + 2
    return "\n".join([
        f"{indent}╭{'─' * width}╮",
        f"{indent}│ {inner} │",
        f"{indent}╰{'─' * width}╯",
    ])

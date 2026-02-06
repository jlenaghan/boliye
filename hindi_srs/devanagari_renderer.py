"""Render Devanagari text as clean pixel art in the terminal.

Standard terminal fonts often render Devanagari poorly — broken ligatures,
misaligned matras, incorrect conjuncts. This module renders Devanagari text
using a proper TrueType font (via Pillow) and converts the result to Unicode
half-block characters for crisp display in any terminal.

Usage:
    from hindi_srs.devanagari_renderer import render_devanagari

    print(render_devanagari("नमस्ते"))
"""

from __future__ import annotations

import os
import shutil

_PILLOW_AVAILABLE = False
try:
    from PIL import Image, ImageDraw, ImageFont

    _PILLOW_AVAILABLE = True
except ImportError:
    pass

# Half-block characters for 2-row-per-cell rendering:
#   top pixel on, bottom pixel on  → █ (full block)
#   top pixel on, bottom pixel off → ▀ (upper half)
#   top pixel off, bottom pixel on → ▄ (lower half)
#   both off                       → ' ' (space)
_FULL = "█"
_UPPER = "▀"
_LOWER = "▄"
_EMPTY = " "

# Default font search paths, ordered by preference.
_FONT_SEARCH_PATHS: list[str] = [
    # Noto Sans Devanagari (best quality if installed)
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
    "/usr/share/fonts/google-noto/NotoSansDevanagari-Regular.ttf",
    "/usr/share/fonts/truetype/noto-sans-devanagari/NotoSansDevanagari-Regular.ttf",
    # FreeSerif has solid Devanagari glyphs
    "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    # macOS system fonts
    "/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc",
    "/Library/Fonts/NotoSansDevanagari-Regular.ttf",
]

# Brightness threshold (0–255). Pixels above this are considered "on".
_THRESHOLD = 80

# Default font size in points for rendering.
# 22pt gives a good balance between readability and terminal space usage.
_DEFAULT_FONT_SIZE = 22

# Horizontal padding in pixels around the rendered text.
_H_PAD = 4

# Vertical padding in pixels above and below the rendered text.
_V_PAD = 4


def _find_font() -> str | None:
    """Return the first available font path, or None."""
    # Allow override via environment variable.
    env_font = os.environ.get("HINDI_SRS_FONT")
    if env_font and os.path.isfile(env_font):
        return env_font

    for path in _FONT_SEARCH_PATHS:
        if os.path.isfile(path):
            return path
    return None


def _render_to_bitmap(
    text: str,
    font_path: str,
    font_size: int = _DEFAULT_FONT_SIZE,
) -> list[list[bool]]:
    """Render *text* into a 2-D boolean grid (True = ink pixel)."""
    font = ImageFont.truetype(font_path, font_size)

    # Measure text bounding box to size the image.
    dummy = Image.new("L", (1, 1), color=0)
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font)
    x0, y0, x1, y1 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
    w = x1 - x0 + _H_PAD * 2
    h = y1 - y0 + _V_PAD * 2

    # Render white text on black background in grayscale.
    img = Image.new("L", (w, h), color=0)
    draw = ImageDraw.Draw(img)
    draw.text((_H_PAD - x0, _V_PAD - y0), text, font=font, fill=255)

    # Convert to boolean grid by reading raw pixel bytes directly.
    raw = img.tobytes()
    grid: list[list[bool]] = []
    for y in range(h):
        row: list[bool] = []
        for x in range(w):
            row.append(raw[y * w + x] >= _THRESHOLD)
        grid.append(row)
    return grid


def _bitmap_to_blocks(grid: list[list[bool]], indent: str = "  ") -> str:
    """Convert a boolean bitmap into half-block character art.

    Each output character cell encodes two vertical pixels using Unicode
    half-block characters, giving twice the vertical resolution of plain
    block art.
    """
    rows = len(grid)
    cols = len(grid[0]) if rows > 0 else 0
    lines: list[str] = []

    for y in range(0, rows, 2):
        line_chars: list[str] = []
        for x in range(cols):
            top = grid[y][x]
            bot = grid[y + 1][x] if y + 1 < rows else False
            if top and bot:
                line_chars.append(_FULL)
            elif top:
                line_chars.append(_UPPER)
            elif bot:
                line_chars.append(_LOWER)
            else:
                line_chars.append(_EMPTY)
        # Strip trailing spaces per line but keep indent.
        lines.append(indent + "".join(line_chars).rstrip())

    # Remove blank leading/trailing lines.
    while lines and lines[0].strip() == "":
        lines.pop(0)
    while lines and lines[-1].strip() == "":
        lines.pop()

    return "\n".join(lines)


def render_devanagari(
    text: str,
    *,
    font_size: int = _DEFAULT_FONT_SIZE,
    indent: str = "  ",
    fallback: bool = True,
) -> str:
    """Render Devanagari *text* as Unicode block art for terminal display.

    Parameters
    ----------
    text:
        The text to render (typically Hindi in Devanagari script).
    font_size:
        Font size in points.  Larger sizes give more detail but use more
        terminal rows/columns.
    indent:
        String prepended to each output line.
    fallback:
        If True and rendering is not possible (missing Pillow or fonts),
        return the original text wrapped with a simple border.  If False,
        raise ``RuntimeError``.

    Returns
    -------
    str
        Multi-line string ready to be printed to the terminal.
    """
    if not _PILLOW_AVAILABLE:
        if fallback:
            return _fallback_render(text, indent=indent)
        raise RuntimeError("Pillow is required for Devanagari font rendering (pip install Pillow)")

    font_path = _find_font()
    if font_path is None:
        if fallback:
            return _fallback_render(text, indent=indent)
        raise RuntimeError(
            "No Devanagari-capable font found. Install noto-fonts-devanagari or set "
            "HINDI_SRS_FONT=/path/to/font.ttf"
        )

    grid = _render_to_bitmap(text, font_path, font_size)
    return _bitmap_to_blocks(grid, indent=indent)


def render_card_display(
    term: str,
    romanization: str = "",
    definition: str = "",
    *,
    font_size: int = _DEFAULT_FONT_SIZE,
) -> str:
    """Render a full card display with rendered Devanagari and plain-text metadata.

    Produces output like::

        ┌──────────────────────────────────────┐
        │                                      │
        │   ▄▄  ▀█▀▄▄▄  ▄▄▀▀ ▄▀▄▄            │
        │  ██▀  ██ ██▀  ██   ██▄▄▄            │
        │                                      │
        │  namaste                             │
        │  hello / greetings                   │
        │                                      │
        └──────────────────────────────────────┘
    """
    # Render Devanagari text without the outer indent — we'll handle spacing inside the box.
    rendered_text = render_devanagari(term, font_size=font_size, indent="")
    rendered_lines = rendered_text.split("\n")

    # Determine box width: fit the rendered content + metadata.
    term_width = shutil.get_terminal_size((80, 24)).columns
    content_max_width = max(
        (len(line) for line in rendered_lines),
        default=20,
    )
    # Also consider romanization and definition widths (with 4-char inner padding).
    if romanization:
        content_max_width = max(content_max_width, len(romanization) + 2)
    if definition:
        content_max_width = max(content_max_width, len(definition) + 2)
    # Inner width = content + left/right padding of 2 chars each.
    box_inner = content_max_width + 4
    box_inner = min(box_inner, term_width - 6)
    box_inner = max(box_inner, 20)

    def _pad_line(text: str) -> str:
        """Pad or trim *text* to exactly *box_inner* characters."""
        padded = f"  {text}"
        if len(padded) < box_inner:
            return padded + " " * (box_inner - len(padded))
        return padded[:box_inner]

    lines: list[str] = []
    lines.append(f"  ┌{'─' * box_inner}┐")
    lines.append(f"  │{' ' * box_inner}│")

    # Add rendered Devanagari lines (already have no indent — add 2-char left padding).
    for rline in rendered_lines:
        padded = f"  {rline}"
        if len(padded) < box_inner:
            padded = padded + " " * (box_inner - len(padded))
        elif len(padded) > box_inner:
            padded = padded[:box_inner]
        lines.append(f"  │{padded}│")

    lines.append(f"  │{' ' * box_inner}│")

    # Add romanization and definition as plain text.
    if romanization:
        lines.append(f"  │{_pad_line(romanization)}│")
    if definition:
        lines.append(f"  │{_pad_line(definition)}│")

    if romanization or definition:
        lines.append(f"  │{' ' * box_inner}│")

    lines.append(f"  └{'─' * box_inner}┘")

    return "\n".join(lines)


def _fallback_render(text: str, indent: str = "  ") -> str:
    """Simple bordered fallback when Pillow/fonts are unavailable."""
    inner = f" {text} "
    width = len(inner) + 2
    lines = [
        f"{indent}┌{'─' * width}┐",
        f"{indent}│ {inner} │",
        f"{indent}└{'─' * width}┘",
    ]
    return "\n".join(lines)


def is_devanagari(text: str) -> bool:
    """Return True if *text* contains Devanagari characters."""
    for ch in text:
        cp = ord(ch)
        # Devanagari: U+0900–U+097F, Devanagari Extended: U+A8E0–U+A8FF
        if 0x0900 <= cp <= 0x097F or 0xA8E0 <= cp <= 0xA8FF:
            return True
    return False


def render_if_devanagari(
    text: str,
    *,
    font_size: int = _DEFAULT_FONT_SIZE,
    indent: str = "  ",
) -> str:
    """Render *text* as block art only if it contains Devanagari; otherwise return as-is."""
    if is_devanagari(text):
        return render_devanagari(text, font_size=font_size, indent=indent)
    return f"{indent}{text}"

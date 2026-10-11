"""Renderer-neutral title-card design resolution and copy fitting.

The compiler uses a conservative average glyph width to reject copy that
cannot fit a locked layout, so a content model gets feedback before any media
work. The renderer then measures real glyphs and may only shrink further.
"""
from __future__ import annotations

import math
import textwrap

# Fontconfig weights and average advance (em) for mixed-case Latin sans copy:
# measured ~0.48-0.51 for Inter and DejaVu Sans, plus a ~10% margin. Capitals
# run wider; the renderer's glyph measurement catches that and shrinks.
WEIGHTS = {
    "regular": (80, 0.53), "medium": (100, 0.54), "semibold": (180, 0.55),
    "bold": (200, 0.56), "black": (210, 0.58),
}
CAP_HEIGHT = 0.75     # first baseline sits this far (em) below the block top
DESCENT = 0.25        # room below the last baseline (em)
KICKER_GAP = 0.45     # gap between kicker and headline (headline em)


def _contrast(background: str) -> str:
    red, green, blue = (int(background[i:i + 2], 16) for i in (1, 3, 5))
    return "#000000" if 0.2126 * red + 0.7152 * green + 0.0722 * blue > 155 else "#FFFFFF"


def resolve_title_card(blueprint: dict) -> dict:
    """Return the locked card design, synthesising the legacy v0.1/v0.2 look."""
    width, height = blueprint["output"]["width"], blueprint["output"]["height"]
    declared = blueprint["style"].get("title_card")
    if declared is None:
        background = blueprint["style"]["palette"][0]
        size = max(24, width // 18)
        declared = {
            "font_family": "Sans", "font_weight": "regular", "align": "center",
            "font_size": size, "min_font_size": max(16, round(size * 0.6)), "max_lines": 3,
            "background": background, "text_color": _contrast(background),
            "safe_margin_x": round(width * 0.08), "safe_margin_top": round(height * 0.1),
            "safe_margin_bottom": round(height * 0.1),
        }
    card = {
        "line_spacing": 1.15, "safe_margin_x": round(width * 0.08),
        "safe_margin_top": round(height * 0.1), "safe_margin_bottom": round(height * 0.1),
        "accent_bar": False, "entrance": "none", "entrance_frames": 0,
        **declared,
    }
    card.setdefault("kicker_font_size", max(12, round(card["font_size"] * 0.4)))
    card["fontconfig_weight"] = WEIGHTS[card["font_weight"]][0]
    return card


def bar_geometry(card: dict, size: int) -> tuple[int, int]:
    """Accent-bar thickness and the horizontal text indent it creates."""
    if not card["accent_bar"]:
        return 0, 0
    thickness = max(4, size // 12)
    return thickness, (thickness + round(size * 0.45) if card["align"] == "left" else 0)


def text_width_px(card: dict, size: int, output_width: int) -> int:
    _, indent = bar_geometry(card, size)
    return output_width - 2 * card["safe_margin_x"] - indent


def block_height(card: dict, size: int, lines: int, kicker: bool) -> float:
    height = CAP_HEIGHT * size + (lines - 1) * size * card["line_spacing"] + DESCENT * size
    if kicker:
        height += card["kicker_font_size"] * (CAP_HEIGHT + DESCENT) + KICKER_GAP * size
    if card["accent_bar"] and card["align"] == "center":
        height += size * 0.45 + bar_geometry(card, size)[0]
    return height


def balanced_wrap(text: str, width: int) -> list[str]:
    """Greedy line count, then the narrowest measure that keeps it: no orphans."""
    def wrap(measure: int) -> list[str]:
        return textwrap.wrap(text, width=measure, break_long_words=False, break_on_hyphens=False)

    lines = wrap(width)
    narrowest = max(len(word) for word in text.split())
    low, high = narrowest, width
    while low < high:
        middle = (low + high) // 2
        if len(wrap(middle)) <= len(lines):
            high = middle
        else:
            low = middle + 1
    return wrap(low)


def fit_copy(card: dict, text: str, kicker: str, output: dict) -> tuple[int, list[str]]:
    """Choose the largest locked size whose estimated wrap fits the safe area."""
    if not text:
        return card["font_size"], []
    advance = WEIGHTS[card["font_weight"]][1]
    available_height = output["height"] - card["safe_margin_top"] - card["safe_margin_bottom"]
    longest = max(len(word) for word in text.split())
    for size in [*range(card["font_size"], card["min_font_size"], -2), card["min_font_size"]]:
        per_line = math.floor(text_width_px(card, size, output["width"]) / (advance * size))
        if per_line < 1 or longest > per_line:
            continue
        lines = balanced_wrap(text, per_line)
        if len(lines) <= card["max_lines"] and block_height(card, size, len(lines), bool(kicker)) <= available_height:
            return size, lines
    raise ValueError(
        f"{len(text)} characters do not fit {card['max_lines']} line(s) even at the "
        f"minimum {card['min_font_size']}px size; shorten the copy"
    )

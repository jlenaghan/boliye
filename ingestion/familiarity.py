"""Infer familiarity level from signals found in learning materials."""

import logging

from ingestion.extractor import ExtractedItem

logger = logging.getLogger(__name__)

# Signals that indicate the learner knows a term well
KNOWN_SIGNALS = {
    "✓",
    "✔",
    "✅",
    "known",
    "easy",
    "mastered",
    "★★★",
    "***",
    "done",
    "confident",
}

# Signals that indicate the learner has seen but not mastered a term
SEEN_SIGNALS = {
    "~",
    "seen",
    "learning",
    "okay",
    "ok",
    "so-so",
    "★★",
    "**",
    "review",
    "practicing",
}

# Signals that indicate the learner doesn't know a term
UNKNOWN_SIGNALS = {
    "?",
    "??",
    "❓",
    "unknown",
    "new",
    "hard",
    "difficult",
    "★",
    "*",
    "todo",
    "learn",
    "confused",
}


def infer_familiarity(item: ExtractedItem) -> str:
    """Infer familiarity level from signals found in extracted items.

    Returns one of: "known", "seen", "unknown"
    """
    if not item.familiarity_signals:
        return "unknown"

    signals_lower = {s.lower().strip() for s in item.familiarity_signals}

    known_count = sum(1 for s in signals_lower if s in KNOWN_SIGNALS)
    seen_count = sum(1 for s in signals_lower if s in SEEN_SIGNALS)
    unknown_count = sum(1 for s in signals_lower if s in UNKNOWN_SIGNALS)

    # Prioritize: if any "known" signal, trust it
    if known_count > 0 and known_count >= unknown_count:
        return "known"
    if seen_count > 0 and seen_count >= unknown_count:
        return "seen"
    if unknown_count > 0:
        return "unknown"

    # If signals exist but don't match known patterns, default to "seen"
    # (having any annotation suggests some engagement)
    return "seen"


def assign_familiarity(items: list[ExtractedItem]) -> dict[str, list[ExtractedItem]]:
    """Assign familiarity levels to all items and return grouped results.

    Returns a dict mapping familiarity level to list of items.
    """
    grouped: dict[str, list[ExtractedItem]] = {"known": [], "seen": [], "unknown": []}
    for item in items:
        level = infer_familiarity(item)
        grouped[level].append(item)

    logger.info(
        "Familiarity breakdown: %d known, %d seen, %d unknown",
        len(grouped["known"]),
        len(grouped["seen"]),
        len(grouped["unknown"]),
    )
    return grouped

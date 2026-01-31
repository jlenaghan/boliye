"""Deduplication and normalization for extracted content items."""

import logging
import unicodedata

from ingestion.extractor import ExtractedItem

logger = logging.getLogger(__name__)


def normalize_hindi(text: str) -> str:
    """Normalize Hindi text for comparison.

    - Unicode NFC normalization (canonical decomposition + composition)
    - Strip whitespace
    - Remove zero-width joiners/non-joiners that don't affect meaning
    """
    text = unicodedata.normalize("NFC", text.strip())
    # Remove zero-width characters that can cause false mismatches
    text = text.replace("\u200b", "")  # zero-width space
    text = text.replace("\u200c", "")  # zero-width non-joiner
    text = text.replace("\u200d", "")  # zero-width joiner
    text = text.replace("\ufeff", "")  # BOM
    return text


def deduplicate(items: list[ExtractedItem]) -> list[ExtractedItem]:
    """Deduplicate extracted items, keeping the richest version of each term.

    Groups by normalized Hindi term and merges duplicates by preferring
    the entry with the most context and information.
    """
    groups: dict[str, list[ExtractedItem]] = {}
    for item in items:
        key = normalize_hindi(item.term)
        groups.setdefault(key, []).append(item)

    deduped = []
    duplicates_merged = 0

    for key, group in groups.items():
        if len(group) == 1:
            deduped.append(group[0])
        else:
            merged = _merge_duplicates(group)
            deduped.append(merged)
            duplicates_merged += len(group) - 1

    logger.info(
        "Deduplication: %d items -> %d unique (%d duplicates merged)",
        len(items),
        len(deduped),
        duplicates_merged,
    )
    return deduped


def _merge_duplicates(group: list[ExtractedItem]) -> ExtractedItem:
    """Merge multiple entries for the same term, preserving the richest data."""
    # Score each item by information richness
    scored = sorted(group, key=_richness_score, reverse=True)
    best = scored[0]

    # Collect all unique familiarity signals from all duplicates
    all_signals: list[str] = []
    seen_signals: set[str] = set()
    for item in group:
        for signal in item.familiarity_signals:
            if signal not in seen_signals:
                all_signals.append(signal)
                seen_signals.add(signal)

    # If the best item has no context but another does, take it
    if not best.context:
        for item in scored[1:]:
            if item.context:
                best.context = item.context
                break

    best.familiarity_signals = all_signals
    return best


def _richness_score(item: ExtractedItem) -> int:
    """Score an item by how much useful information it contains."""
    score = 0
    if item.definition:
        score += len(item.definition)
    if item.context:
        score += len(item.context) * 2  # Context is highly valuable
    if item.romanization:
        score += 10
    score += len(item.familiarity_signals) * 5
    return score

"""Deduplication and normalization for extracted content items."""

import logging

from ingestion.constants import CONTEXT_WEIGHT, FAMILIARITY_SIGNAL_WEIGHT, ROMANIZATION_BONUS
from ingestion.extractor import ExtractedItem
from ingestion.utils import normalize_hindi

logger = logging.getLogger(__name__)


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

    for _key, group in groups.items():
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
        score += len(item.context) * CONTEXT_WEIGHT
    if item.romanization:
        score += ROMANIZATION_BONUS
    score += len(item.familiarity_signals) * FAMILIARITY_SIGNAL_WEIGHT
    return score

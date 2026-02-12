"""Shared utilities for the ingestion pipeline."""

import json
import logging
import unicodedata
from collections.abc import Iterator
from typing import TypeVar

logger = logging.getLogger(__name__)

# Zero-width characters that can cause false mismatches in Hindi text
ZERO_WIDTH_CHARS = "\u200b\u200c\u200d\ufeff"

T = TypeVar("T")


def parse_llm_json_response(response: str, context: str = "LLM response") -> dict | list:
    """Extract and parse JSON from an LLM response.

    Handles common LLM output patterns:
    - Direct JSON output
    - JSON wrapped in markdown code blocks (```json ... ```)

    Args:
        response: Raw LLM response text.
        context: Description for error logging (e.g., "CEFR assignment").

    Returns:
        Parsed JSON as dict or list. Returns empty dict on parse failure.
    """
    text = response.strip()

    # Strip markdown code blocks if present
    if text.startswith("```"):
        # Remove opening fence and optional language identifier
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.error("Failed to parse %s as JSON", context)
        logger.debug("Response was: %s", text[:500] if len(text) > 500 else text)
        return {}


def normalize_hindi(text: str) -> str:
    """Normalize Hindi text for comparison.

    Applies:
    - Unicode NFC normalization (canonical decomposition + composition)
    - Strips leading/trailing whitespace
    - Removes zero-width characters that don't affect meaning

    Args:
        text: Hindi text to normalize.

    Returns:
        Normalized text suitable for comparison or deduplication.
    """
    text = unicodedata.normalize("NFC", text.strip())
    # Remove zero-width characters using translate (more efficient than multiple replace calls)
    text = text.translate(str.maketrans("", "", ZERO_WIDTH_CHARS))
    return text


def batch_items(
    items: list[T], batch_size: int, description: str = "items"
) -> Iterator[tuple[int, int, list[T]]]:
    """Yield batches of items with batch metadata.

    Args:
        items: List of items to batch.
        batch_size: Maximum items per batch.
        description: Description for logging (e.g., "CEFR assignments").

    Yields:
        Tuples of (batch_number, total_batches, batch_items).

    Example:
        for batch_num, total, batch in batch_items(items, 20, "exercises"):
            logger.info("Processing batch %d/%d", batch_num, total)
            process(batch)
    """
    total_batches = (len(items) + batch_size - 1) // batch_size

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        batch_num = i // batch_size + 1
        logger.info(
            "Processing %s: batch %d/%d (%d items)",
            description,
            batch_num,
            total_batches,
            len(batch),
        )
        yield batch_num, total_batches, batch

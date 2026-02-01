"""CEFR level assignment for content items via LLM."""

import json
import logging

from backend.llm_client import LLMClient
from ingestion.extractor import ExtractedItem

logger = logging.getLogger(__name__)

CEFR_SYSTEM_PROMPT = """\
You are an expert in Hindi language pedagogy and the Common European Framework of Reference \
for Languages (CEFR). Your task is to assign CEFR levels to Hindi vocabulary, phrases, and \
grammar patterns.

CEFR Levels for Hindi:
- A1: Basic greetings, numbers, colors, family members, very common verbs (होना, करना, जाना)
- A2: Common daily vocabulary, simple sentences, present/past tense, postpositions
- B1: Abstract concepts, compound verbs, subjunctive mood, relative clauses
- B2: Idiomatic expressions, formal/informal registers, complex grammar
- C1: Nuanced vocabulary, literary Hindi, advanced grammar patterns
- C2: Near-native proficiency, rare vocabulary, sophisticated expression

For each item, assign:
- level: The CEFR level (A1, A2, B1, B2, C1, or C2)
- confidence: Your confidence in the assignment (0.0 to 1.0)"""

CEFR_USER_PROMPT = """\
Assign CEFR levels to the following Hindi content items.

Items:
{items_json}

Return a JSON array where each element has:
- "term": the Hindi term (for matching)
- "level": CEFR level (A1/A2/B1/B2/C1/C2)
- "confidence": float 0.0-1.0

Return ONLY the JSON array."""


def assign_cefr_levels(
    items: list[ExtractedItem],
    llm: LLMClient,
    batch_size: int = 50,
) -> dict[str, tuple[str, float]]:
    """Assign CEFR levels to items in batches.

    Returns a dict mapping term -> (level, confidence).
    """
    results: dict[str, tuple[str, float]] = {}

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        logger.info(
            "Assigning CEFR levels: batch %d/%d (%d items)",
            i // batch_size + 1,
            (len(items) + batch_size - 1) // batch_size,
            len(batch),
        )
        batch_results = _process_batch(batch, llm)
        results.update(batch_results)

    level_counts: dict[str, int] = {}
    for level, _ in results.values():
        level_counts[level] = level_counts.get(level, 0) + 1
    logger.info("CEFR distribution: %s", level_counts)

    return results


def _process_batch(
    batch: list[ExtractedItem],
    llm: LLMClient,
) -> dict[str, tuple[str, float]]:
    """Process a single batch of items for CEFR assignment."""
    items_for_prompt = [
        {
            "term": item.term,
            "definition": item.definition,
            "content_type": item.content_type,
        }
        for item in batch
    ]

    prompt = CEFR_USER_PROMPT.format(
        items_json=json.dumps(items_for_prompt, ensure_ascii=False, indent=2)
    )
    response = llm.create_message(
        prompt=prompt,
        system=CEFR_SYSTEM_PROMPT,
        max_tokens=4096,
        temperature=0.2,
    )

    return _parse_cefr_response(response)


def _parse_cefr_response(response: str) -> dict[str, tuple[str, float]]:
    """Parse the LLM response into a term -> (level, confidence) mapping."""
    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.error("Failed to parse CEFR response as JSON")
        return {}

    results: dict[str, tuple[str, float]] = {}
    valid_levels = {"A1", "A2", "B1", "B2", "C1", "C2"}

    for entry in data:
        term = entry.get("term", "")
        level = entry.get("level", "").upper()
        confidence = float(entry.get("confidence", 0.5))

        if level not in valid_levels:
            logger.warning("Invalid CEFR level '%s' for term '%s', defaulting to A2", level, term)
            level = "A2"

        confidence = max(0.0, min(1.0, confidence))
        results[term] = (level, confidence)

    return results

"""Topic tagging for content items via LLM."""

import json
import logging

from backend.llm_client import LLMClient
from ingestion.extractor import ExtractedItem

logger = logging.getLogger(__name__)

# Standard topic taxonomy for Hindi learning
TOPIC_TAXONOMY = [
    "greetings",
    "introductions",
    "numbers",
    "colors",
    "family",
    "food_drink",
    "clothing",
    "body",
    "health",
    "home",
    "school",
    "work",
    "travel",
    "directions",
    "shopping",
    "weather",
    "time",
    "animals",
    "nature",
    "emotions",
    "daily_routine",
    "hobbies",
    "sports",
    "technology",
    "religion_culture",
    "grammar_pattern",
    "idiom",
    "formal_register",
    "informal_register",
]

TOPIC_SYSTEM_PROMPT = """\
You are a Hindi language curriculum designer. Your task is to assign topic tags to Hindi \
vocabulary, phrases, and grammar patterns.

Available topics: {topics}

Rules:
- Assign 1-3 topics per item (most relevant first)
- Use ONLY topics from the list above
- Every item must have at least one topic
- Grammar patterns should include "grammar_pattern" as one of their topics"""

TOPIC_USER_PROMPT = """\
Assign topic tags to the following Hindi content items.

Items:
{items_json}

Return a JSON array where each element has:
- "term": the Hindi term (for matching)
- "topics": array of topic strings from the allowed list

Return ONLY the JSON array."""


def assign_topics(
    items: list[ExtractedItem],
    llm: LLMClient,
    batch_size: int = 50,
) -> dict[str, list[str]]:
    """Assign topic tags to items in batches.

    Returns a dict mapping term -> list of topic tags.
    """
    results: dict[str, list[str]] = {}

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        logger.info(
            "Assigning topics: batch %d/%d (%d items)",
            i // batch_size + 1,
            (len(items) + batch_size - 1) // batch_size,
            len(batch),
        )
        batch_results = _process_batch(batch, llm)
        results.update(batch_results)

    # Log topic distribution
    topic_counts: dict[str, int] = {}
    for topics in results.values():
        for topic in topics:
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
    logger.info("Topic distribution: %s", dict(sorted(topic_counts.items(), key=lambda x: -x[1])))

    return results


def _process_batch(
    batch: list[ExtractedItem],
    llm: LLMClient,
) -> dict[str, list[str]]:
    """Process a single batch for topic assignment."""
    items_for_prompt = [
        {
            "term": item.term,
            "definition": item.definition,
            "content_type": item.content_type,
        }
        for item in batch
    ]

    system = TOPIC_SYSTEM_PROMPT.format(topics=", ".join(TOPIC_TAXONOMY))
    prompt = TOPIC_USER_PROMPT.format(
        items_json=json.dumps(items_for_prompt, ensure_ascii=False, indent=2)
    )
    response = llm.create_message(
        prompt=prompt,
        system=system,
        max_tokens=4096,
        temperature=0.2,
    )

    return _parse_topic_response(response)


def _parse_topic_response(response: str) -> dict[str, list[str]]:
    """Parse the LLM response into a term -> topics mapping."""
    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.error("Failed to parse topic response as JSON")
        return {}

    valid_topics = set(TOPIC_TAXONOMY)
    results: dict[str, list[str]] = {}

    for entry in data:
        term = entry.get("term", "")
        topics = entry.get("topics", [])
        # Filter to valid topics only
        filtered = [t for t in topics if t in valid_topics]
        if not filtered:
            filtered = ["daily_routine"]  # Safe default
        results[term] = filtered

    return results

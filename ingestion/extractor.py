"""LLM-based extraction of structured content items from raw documents."""

import json
import logging
from dataclasses import dataclass

from backend.llm_client import LLMClient

logger = logging.getLogger(__name__)

EXTRACTION_SYSTEM_PROMPT = """\
You are a Hindi language learning content extractor. Your job is to parse raw notes, \
vocabulary lists, and other learning materials into structured items.

For each item you find, extract:
- term: The Hindi text (Devanagari script)
- definition: English translation or explanation
- romanization: Transliteration in Latin script (IAST or common romanization)
- context: An example sentence or usage context if available
- content_type: One of "vocab", "phrase", or "grammar"
- familiarity_signals: Any signals about how well the learner knows this item \
  (e.g., checkmarks, stars, "known", question marks, repeated entries)

Rules:
- Extract EVERY distinct Hindi term, phrase, or grammar pattern you find
- If a term appears multiple times, include it once with the richest context
- Preserve the original Hindi text exactly as written
- If romanization is not provided, generate it
- If no English translation is given, provide one
- For grammar patterns, describe the pattern in the definition field
- Output valid JSON only, no markdown or explanation"""

EXTRACTION_USER_PROMPT = """\
Extract all Hindi learning items from the following document.

Source file: {source_path}
File type: {file_type}

---
{content}
---

Return a JSON array of objects with these fields:
["term", "definition", "romanization", "context", "content_type", "familiarity_signals"]

Return ONLY the JSON array, no other text."""


@dataclass
class ExtractedItem:
    """A single content item extracted from a raw document."""

    term: str
    definition: str
    romanization: str
    context: str | None
    content_type: str  # vocab, phrase, grammar
    familiarity_signals: list[str]
    source_file: str


def extract_items(
    content: str,
    source_path: str,
    file_type: str,
    llm: LLMClient,
) -> list[ExtractedItem]:
    """Use the LLM to extract structured items from raw content.

    For large documents, splits into chunks to stay within context limits.
    """
    chunks = _split_into_chunks(content, max_chars=12000)
    all_items: list[ExtractedItem] = []

    for i, chunk in enumerate(chunks):
        logger.info(
            "Extracting chunk %d/%d from %s (%d chars)",
            i + 1,
            len(chunks),
            source_path,
            len(chunk),
        )
        prompt = EXTRACTION_USER_PROMPT.format(
            source_path=source_path,
            file_type=file_type,
            content=chunk,
        )
        response = llm.create_message(
            prompt=prompt,
            system=EXTRACTION_SYSTEM_PROMPT,
            max_tokens=4096,
            temperature=0.3,
        )
        items = _parse_response(response, source_path)
        all_items.extend(items)

    logger.info("Extracted %d items from %s", len(all_items), source_path)
    return all_items


def _parse_response(response: str, source_path: str) -> list[ExtractedItem]:
    """Parse the LLM JSON response into ExtractedItem objects."""
    # Strip markdown code fences if present
    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.error("Failed to parse LLM response as JSON from %s", source_path)
        logger.debug("Response was: %s", text[:500])
        return []

    if not isinstance(data, list):
        logger.error("Expected JSON array, got %s", type(data).__name__)
        return []

    items = []
    for entry in data:
        try:
            items.append(
                ExtractedItem(
                    term=entry["term"],
                    definition=entry["definition"],
                    romanization=entry.get("romanization", ""),
                    context=entry.get("context"),
                    content_type=entry.get("content_type", "vocab"),
                    familiarity_signals=entry.get("familiarity_signals", []),
                    source_file=source_path,
                )
            )
        except KeyError as e:
            logger.warning("Skipping item missing required field %s: %s", e, entry)

    return items


def _split_into_chunks(text: str, max_chars: int = 12000) -> list[str]:
    """Split text into chunks, breaking at paragraph boundaries."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    paragraphs = text.split("\n\n")
    current_chunk = ""

    for para in paragraphs:
        if len(current_chunk) + len(para) + 2 > max_chars and current_chunk:
            chunks.append(current_chunk.strip())
            current_chunk = para
        else:
            current_chunk += "\n\n" + para if current_chunk else para

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks

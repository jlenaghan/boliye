"""Exercise generation pipeline: create MCQ and cloze exercises from content items."""

import json
import logging

from backend.llm_client import LLMClient
from ingestion.extractor import ExtractedItem

logger = logging.getLogger(__name__)

MCQ_SYSTEM_PROMPT = """\
You are a Hindi language exercise generator. Create multiple-choice questions that test \
recognition of Hindi vocabulary, phrases, and grammar patterns.

Rules:
- Each question has exactly 4 options (1 correct, 3 distractors)
- Distractors should be plausible but clearly wrong to someone who knows the answer
- Distractors should be the same type (all Hindi or all English) as the correct answer
- For vocab items: test Hindi→English or English→Hindi recognition
- For phrases: test understanding of the full phrase meaning
- For grammar: test application of the grammar pattern
- Questions should be clear and unambiguous"""

MCQ_USER_PROMPT = """\
Generate multiple-choice exercises for the following Hindi content items.

Items:
{items_json}

For each item, generate ONE MCQ exercise with this structure:
- "term": the Hindi term (for matching back)
- "prompt": the question text
- "answer": the correct answer
- "options": array of exactly 4 strings (including the correct answer, shuffled)
- "exercise_type": "mcq"

Return ONLY a JSON array of exercise objects."""

CLOZE_SYSTEM_PROMPT = """\
You are a Hindi language exercise generator. Create fill-in-the-blank (cloze) exercises \
that test active recall of Hindi vocabulary and phrases.

Rules:
- Create a natural Hindi sentence using the target term
- Replace the target term with a blank: ___
- Provide the English translation of the full sentence as a hint
- The blank should test the most important part of the item
- Sentences should be appropriate for the item's difficulty level
- Use Devanagari script for all Hindi text"""

CLOZE_USER_PROMPT = """\
Generate cloze (fill-in-the-blank) exercises for the following Hindi content items.

Items:
{items_json}

For each item, generate ONE cloze exercise with this structure:
- "term": the Hindi term (for matching back)
- "prompt": a Hindi sentence with ___ replacing the target term, plus English translation
- "answer": the word/phrase that fills the blank
- "exercise_type": "cloze"

Return ONLY a JSON array of exercise objects."""


def generate_exercises(
    items: list[ExtractedItem],
    llm: LLMClient,
    batch_size: int = 20,
    exercise_types: list[str] | None = None,
) -> list[dict]:
    """Generate exercises for content items.

    Args:
        items: Content items to generate exercises for.
        llm: LLM client for generation.
        batch_size: Number of items per LLM call.
        exercise_types: Which types to generate. Defaults to ["mcq", "cloze"].

    Returns:
        List of exercise dicts ready for database insertion.
    """
    if exercise_types is None:
        exercise_types = ["mcq", "cloze"]

    all_exercises: list[dict] = []

    for ex_type in exercise_types:
        logger.info("Generating %s exercises for %d items", ex_type, len(items))
        for i in range(0, len(items), batch_size):
            batch = items[i : i + batch_size]
            logger.info(
                "  %s batch %d/%d (%d items)",
                ex_type,
                i // batch_size + 1,
                (len(items) + batch_size - 1) // batch_size,
                len(batch),
            )

            if ex_type == "mcq":
                exercises = _generate_mcq_batch(batch, llm)
            elif ex_type == "cloze":
                exercises = _generate_cloze_batch(batch, llm)
            else:
                logger.warning("Unknown exercise type: %s", ex_type)
                continue

            all_exercises.extend(exercises)

    logger.info("Generated %d total exercises", len(all_exercises))
    return all_exercises


def _generate_mcq_batch(
    batch: list[ExtractedItem],
    llm: LLMClient,
) -> list[dict]:
    """Generate MCQ exercises for a batch of items."""
    items_for_prompt = [
        {
            "term": item.term,
            "definition": item.definition,
            "content_type": item.content_type,
            "context": item.context or "",
        }
        for item in batch
    ]

    prompt = MCQ_USER_PROMPT.format(
        items_json=json.dumps(items_for_prompt, ensure_ascii=False, indent=2)
    )
    response = llm.create_message(
        prompt=prompt,
        system=MCQ_SYSTEM_PROMPT,
        max_tokens=4096,
        temperature=0.7,
    )
    return _parse_exercise_response(response, "mcq")


def _generate_cloze_batch(
    batch: list[ExtractedItem],
    llm: LLMClient,
) -> list[dict]:
    """Generate cloze exercises for a batch of items."""
    items_for_prompt = [
        {
            "term": item.term,
            "definition": item.definition,
            "content_type": item.content_type,
            "context": item.context or "",
        }
        for item in batch
    ]

    prompt = CLOZE_USER_PROMPT.format(
        items_json=json.dumps(items_for_prompt, ensure_ascii=False, indent=2)
    )
    response = llm.create_message(
        prompt=prompt,
        system=CLOZE_SYSTEM_PROMPT,
        max_tokens=4096,
        temperature=0.7,
    )
    return _parse_exercise_response(response, "cloze")


def _parse_exercise_response(response: str, expected_type: str) -> list[dict]:
    """Parse the LLM response into exercise dicts."""
    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.error("Failed to parse exercise response as JSON")
        return []

    exercises = []
    for entry in data:
        exercise = {
            "term": entry.get("term", ""),
            "prompt": entry.get("prompt", ""),
            "answer": entry.get("answer", ""),
            "exercise_type": entry.get("exercise_type", expected_type),
            "options": json.dumps(entry.get("options", []), ensure_ascii=False)
            if entry.get("options")
            else None,
        }
        if exercise["prompt"] and exercise["answer"]:
            exercises.append(exercise)
        else:
            logger.warning("Skipping exercise with missing prompt or answer: %s", entry)

    return exercises

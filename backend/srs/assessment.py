"""Assessment engine for evaluating learner responses.

Provides exact match checking with Hindi-specific normalization,
and LLM-based fuzzy assessment for typed responses.
"""

import json
import logging
import unicodedata
from dataclasses import dataclass
from enum import Enum

from backend.llm_client import LLMClient

logger = logging.getLogger(__name__)

# Common Hindi variations that should be treated as equivalent
HINDI_EQUIVALENCES: list[tuple[str, str]] = [
    ("ये", "यह"),
    ("वो", "वह"),
    ("है", "हैं"),
    ("मैने", "मैंने"),
    ("नही", "नहीं"),
    ("कोन", "कौन"),
    ("मे", "में"),
    ("हे", "है"),
]


class AssessmentGrade(Enum):
    """How correct a response is."""

    CORRECT = "correct"           # Exact or near-exact match
    CLOSE = "close"               # Minor error (typo, small variation)
    PARTIAL = "partial"           # Shows understanding but significant errors
    INCORRECT = "incorrect"       # Fundamentally wrong


@dataclass
class Assessment:
    """The result of assessing a learner's response."""

    grade: AssessmentGrade
    suggested_rating: int        # 1=Again, 2=Hard, 3=Good, 4=Easy
    feedback: str                # Explanation for the learner
    expected: str                # What the correct answer was
    actual: str                  # What the learner answered
    is_exact_match: bool = False


# Grade to suggested rating mapping
GRADE_TO_RATING = {
    AssessmentGrade.CORRECT: 4,    # Easy if you got it right
    AssessmentGrade.CLOSE: 3,      # Good - minor issues
    AssessmentGrade.PARTIAL: 2,    # Hard - needs more work
    AssessmentGrade.INCORRECT: 1,  # Again
}


def normalize_for_comparison(text: str) -> str:
    """Normalize text for comparison.

    - Unicode NFC normalization
    - Strip whitespace
    - Lowercase (for English)
    - Remove common punctuation
    """
    text = unicodedata.normalize("NFC", text.strip())
    text = text.lower()
    # Remove zero-width characters
    for char in ["\u200b", "\u200c", "\u200d", "\ufeff"]:
        text = text.replace(char, "")
    # Remove common punctuation that doesn't affect meaning
    for char in [".", ",", "!", "?", "।", ";", ":", "'", '"', "(", ")"]:
        text = text.replace(char, "")
    return text.strip()


def check_hindi_equivalence(response: str, expected: str) -> bool:
    """Check if response matches expected considering common Hindi variations."""
    norm_response = normalize_for_comparison(response)
    norm_expected = normalize_for_comparison(expected)

    if norm_response == norm_expected:
        return True

    # Check known equivalences
    for a, b in HINDI_EQUIVALENCES:
        # Try replacing variations in both directions
        if norm_response.replace(a, b) == norm_expected:
            return True
        if norm_response.replace(b, a) == norm_expected:
            return True
        if norm_expected.replace(a, b) == norm_response:
            return True
        if norm_expected.replace(b, a) == norm_response:
            return True

    return False


def assess_exact(response: str, expected: str) -> Assessment:
    """Perform exact-match assessment with Hindi normalization.

    This is fast and free (no LLM calls).
    """
    if check_hindi_equivalence(response, expected):
        return Assessment(
            grade=AssessmentGrade.CORRECT,
            suggested_rating=GRADE_TO_RATING[AssessmentGrade.CORRECT],
            feedback="Correct!",
            expected=expected,
            actual=response,
            is_exact_match=True,
        )

    return Assessment(
        grade=AssessmentGrade.INCORRECT,
        suggested_rating=GRADE_TO_RATING[AssessmentGrade.INCORRECT],
        feedback=f"Expected: {expected}",
        expected=expected,
        actual=response,
    )


def assess_mcq(selected_option: str, correct_answer: str) -> Assessment:
    """Assess a multiple-choice question response."""
    if normalize_for_comparison(selected_option) == normalize_for_comparison(correct_answer):
        return Assessment(
            grade=AssessmentGrade.CORRECT,
            suggested_rating=3,  # MCQ correct = Good (not Easy, since it's recognition)
            feedback="Correct!",
            expected=correct_answer,
            actual=selected_option,
            is_exact_match=True,
        )
    return Assessment(
        grade=AssessmentGrade.INCORRECT,
        suggested_rating=1,
        feedback=f"The correct answer was: {correct_answer}",
        expected=correct_answer,
        actual=selected_option,
    )


FUZZY_SYSTEM_PROMPT = """\
You are a Hindi language tutor assessing a learner's response. \
Evaluate whether their answer is correct, close, partially correct, or incorrect.

Consider:
- Spelling variations in Devanagari (minor matras, halant differences)
- Common transliteration variations
- Whether the core meaning is preserved
- Typos vs fundamental misunderstandings

Respond with JSON only."""

FUZZY_USER_PROMPT = """\
Exercise prompt: {prompt}
Expected answer: {expected}
Learner's answer: {actual}

Assess the learner's response. Return JSON:
{{
  "grade": "correct" | "close" | "partial" | "incorrect",
  "feedback": "Brief, helpful feedback in 1-2 sentences",
  "is_typo": true/false
}}"""


def assess_fuzzy(
    response: str,
    expected: str,
    exercise_prompt: str,
    llm: LLMClient,
) -> Assessment:
    """Use the LLM to assess a typed response with fuzzy matching.

    More expensive but handles nuanced cases:
    - Typos vs real errors
    - Partial understanding
    - Alternative correct answers
    """
    # Try exact match first (free)
    exact = assess_exact(response, expected)
    if exact.grade == AssessmentGrade.CORRECT:
        return exact

    prompt = FUZZY_USER_PROMPT.format(
        prompt=exercise_prompt,
        expected=expected,
        actual=response,
    )

    try:
        result = llm.create_message(
            prompt=prompt,
            system=FUZZY_SYSTEM_PROMPT,
            max_tokens=256,
            temperature=0.1,
        )
        return _parse_fuzzy_response(result, expected, response)
    except Exception:
        logger.exception("LLM fuzzy assessment failed, falling back to exact match")
        return exact


def _parse_fuzzy_response(response: str, expected: str, actual: str) -> Assessment:
    """Parse the LLM fuzzy assessment response."""
    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.error("Failed to parse fuzzy assessment response")
        return Assessment(
            grade=AssessmentGrade.INCORRECT,
            suggested_rating=1,
            feedback=f"Expected: {expected}",
            expected=expected,
            actual=actual,
        )

    grade_str = data.get("grade", "incorrect")
    try:
        grade = AssessmentGrade(grade_str)
    except ValueError:
        grade = AssessmentGrade.INCORRECT

    feedback = data.get("feedback", f"Expected: {expected}")

    return Assessment(
        grade=grade,
        suggested_rating=GRADE_TO_RATING[grade],
        feedback=feedback,
        expected=expected,
        actual=actual,
    )

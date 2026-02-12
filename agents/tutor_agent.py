"""Tutor Agent: provides explanations, mnemonics, and adaptive teaching.

Responsibilities:
- Explain errors with context-appropriate depth
- Generate mnemonics for repeatedly failed items
- Adjust explanation depth based on learner history
- Provide cultural context and usage notes
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agents.base import BaseAgent, LearnerContext
from backend.models.content_item import ContentItem
from backend.models.exercise import Exercise
from backend.srs.assessment import Assessment

logger = logging.getLogger(__name__)

EXPLANATION_SYSTEM = """\
You are a patient, encouraging Hindi language tutor. The learner made an error \
and needs help understanding why. Provide a clear, concise explanation.

Guidelines:
- Use simple language appropriate for the learner's level
- Reference the Devanagari script directly
- If relevant, explain the grammar pattern
- Keep explanations under 3 sentences for basic errors
- Provide a memory aid or mnemonic when helpful
- Be encouraging but honest"""

MNEMONIC_SYSTEM = """\
You are a creative Hindi language tutor specializing in memory techniques. \
Create a memorable mnemonic or association to help the learner remember this item.

Guidelines:
- Use vivid imagery
- Connect to English sounds where possible (but note they are Hindi words)
- Keep it short and memorable (1-2 sentences)
- Be culturally respectful"""


@dataclass
class TutorResponse:
    """The tutor's explanation for a learner."""

    explanation: str
    mnemonic: str | None
    grammar_note: str | None
    usage_example: str | None
    depth: str  # "brief", "standard", "detailed"


class TutorAgent(BaseAgent):
    """Provides adaptive explanations and mnemonics."""

    @property
    def name(self) -> str:
        """Return the agent identifier."""
        return "tutor"

    @property
    def description(self) -> str:
        """Return what this agent does."""
        return "Explains errors, provides mnemonics, and adapts teaching depth"

    def explain(
        self,
        assessment: Assessment,
        exercise: Exercise,
        content_item: ContentItem,
        ctx: LearnerContext,
        error_type: str | None = None,
    ) -> TutorResponse:
        """Generate a tutoring response for an incorrect answer.

        Depth adapts based on:
        - Number of times this item has been failed
        - Learner's overall level
        - Type of error
        """
        depth = self._determine_depth(content_item, ctx, error_type)

        # Build explanation (LLM or template-based)
        if self.llm is not None and depth != "brief":
            explanation = self._llm_explanation(
                assessment, exercise, content_item, ctx, depth
            )
        else:
            explanation = self._template_explanation(
                assessment, exercise, content_item, error_type
            )

        # Generate mnemonic for repeatedly failed items
        mnemonic = None
        failure_count = self._count_failures(content_item.term, ctx)
        if failure_count >= 2 and self.llm is not None:
            mnemonic = self._generate_mnemonic(content_item)

        # Add grammar note if relevant
        grammar_note = None
        if content_item.content_type in ("grammar", "phrase") and error_type == "grammar":
            grammar_note = self._grammar_note(content_item)

        # Add usage example for vocabulary errors
        usage_example = None
        if error_type == "vocabulary" and depth in ("standard", "detailed"):
            usage_example = self._usage_example(content_item)

        return TutorResponse(
            explanation=explanation,
            mnemonic=mnemonic,
            grammar_note=grammar_note,
            usage_example=usage_example,
            depth=depth,
        )

    def _determine_depth(
        self,
        content_item: ContentItem,
        ctx: LearnerContext,
        error_type: str | None,
    ) -> str:
        """Determine how deep the explanation should go."""
        failure_count = self._count_failures(content_item.term, ctx)

        # Brief for first failure or typos
        if failure_count == 0 and error_type == "typo":
            return "brief"

        # Detailed after multiple failures
        if failure_count >= 3:
            return "detailed"

        # Detailed during failure streaks
        if ctx.failure_streak() >= 3:
            return "detailed"

        return "standard"

    def _count_failures(self, term: str, ctx: LearnerContext) -> int:
        """Count how many times this term has been failed in the session."""
        return sum(
            1 for e in ctx.session_reviews
            if e.term == term and e.grade != "correct"
        )

    def _llm_explanation(
        self,
        assessment: Assessment,
        exercise: Exercise,
        content_item: ContentItem,
        ctx: LearnerContext,
        depth: str,
    ) -> str:
        """Generate an LLM-powered explanation."""
        depth_instruction = {
            "brief": "Give a very brief explanation (1 sentence).",
            "standard": "Give a clear explanation (2-3 sentences).",
            "detailed": (
                "Give a thorough explanation (3-5 sentences) with a memory aid. "
                "The learner has struggled with this item multiple times."
            ),
        }

        prompt = (
            f"The learner answered '{assessment.actual}' but the correct answer is "
            f"'{assessment.expected}'.\n"
            f"Exercise: {exercise.prompt}\n"
            f"Hindi term: {content_item.term} ({content_item.romanization})\n"
            f"Meaning: {content_item.definition}\n"
            f"Learner level: {ctx.cefr_level}\n"
            f"\n{depth_instruction[depth]}"
        )

        try:
            return self.llm.create_message(  # type: ignore[union-attr]
                prompt=prompt,
                system=EXPLANATION_SYSTEM,
                max_tokens=300,
                temperature=0.5,
            )
        except Exception:
            logger.exception("LLM explanation generation failed")
            return self._template_explanation(assessment, exercise, content_item, None)

    def _template_explanation(
        self,
        assessment: Assessment,
        exercise: Exercise,
        content_item: ContentItem,
        error_type: str | None,
    ) -> str:
        """Generate a template-based explanation (no LLM needed)."""
        parts = []

        parts.append(
            f"The correct answer is **{content_item.term}** ({content_item.romanization}) "
            f"meaning \"{content_item.definition}\"."
        )

        if error_type == "typo":
            parts.append("Check the spelling carefully — the matra marks matter!")
        elif error_type == "vocabulary":
            parts.append("Try to create a mental image connecting this word to its meaning.")
        elif error_type == "grammar":
            if content_item.context:
                parts.append(f"Context: {content_item.context}")
        elif error_type == "meaning":
            parts.append("Break down the sentence word by word to understand the structure.")

        return " ".join(parts)

    def _generate_mnemonic(self, content_item: ContentItem) -> str | None:
        """Generate a mnemonic for a repeatedly failed item."""
        prompt = (
            f"Create a memorable mnemonic for the Hindi word:\n"
            f"Word: {content_item.term}\n"
            f"Romanization: {content_item.romanization}\n"
            f"Meaning: {content_item.definition}\n"
            f"Content type: {content_item.content_type}\n"
            f"\nCreate a short, vivid mnemonic (1-2 sentences)."
        )

        try:
            return self.llm.create_message(  # type: ignore[union-attr]
                prompt=prompt,
                system=MNEMONIC_SYSTEM,
                max_tokens=150,
                temperature=0.8,
            )
        except Exception:
            logger.exception("Mnemonic generation failed")
            return None

    def _grammar_note(self, content_item: ContentItem) -> str | None:
        """Provide a grammar note if the content item is a grammar pattern."""
        if content_item.context:
            return f"Grammar pattern: {content_item.context}"
        return None

    def _usage_example(self, content_item: ContentItem) -> str | None:
        """Provide a usage example for vocabulary items."""
        if content_item.context:
            return f"Example usage: {content_item.context}"
        return None

"""Content Agent: intelligent exercise selection and generation.

Responsibilities:
- Select the best exercise for a given card and learner state
- Manage exercise variety and difficulty progression
- Cache and reuse generated exercises
- Request new exercise generation when needed
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.base import BaseAgent, LearnerContext
from backend.llm_client import LLMClient
from backend.models.card import Card
from backend.models.content_item import ContentItem
from backend.models.exercise import Exercise
from backend.models.review_log import ReviewLog

logger = logging.getLogger(__name__)

# Exercise difficulty ranking (easiest first)
EXERCISE_DIFFICULTY = {
    "mcq": 1,
    "cloze": 2,
    "translation": 3,
}


@dataclass
class ExerciseSelection:
    """Result of the content agent selecting an exercise."""

    exercise: Exercise
    reasoning: str


class ContentAgent(BaseAgent):
    """Selects and manages exercises with intelligent variety."""

    @property
    def name(self) -> str:
        return "content"

    @property
    def description(self) -> str:
        return "Selects exercises, manages variety and difficulty progression"

    async def select_exercise(
        self,
        db: AsyncSession,
        card: Card,
        ctx: LearnerContext,
    ) -> ExerciseSelection | None:
        """Select the best exercise for a card given the learner's context.

        Strategy:
        - Struggling cards get easier exercise types (MCQ)
        - Mature cards get harder exercise types (cloze, translation)
        - Recent exercise types are tracked to avoid repetition
        - If accuracy is dropping, dial back difficulty
        """
        # Get available exercises for this card's content item
        stmt = (
            select(Exercise)
            .where(
                and_(
                    Exercise.content_item_id == card.content_item_id,
                    Exercise.status == "approved",
                )
            )
        )
        result = await db.execute(stmt)
        exercises = list(result.scalars().all())

        if not exercises:
            # Fall back to generated (unreviewed) exercises
            stmt_gen = (
                select(Exercise)
                .where(
                    and_(
                        Exercise.content_item_id == card.content_item_id,
                        Exercise.status == "generated",
                    )
                )
            )
            result_gen = await db.execute(stmt_gen)
            exercises = list(result_gen.scalars().all())

        if not exercises:
            return None

        # Determine target difficulty
        target_type, reasoning = self._pick_exercise_type(card, ctx)

        # Try to find an exercise of the target type
        matching = [e for e in exercises if e.exercise_type == target_type]
        if matching:
            # Avoid the most recently used exercise
            recent_types = self._recent_exercise_types(ctx, card.id)
            unused = [e for e in matching if e.id not in recent_types]
            exercise = random.choice(unused) if unused else random.choice(matching)
        else:
            # Fall back to any available exercise
            exercise = random.choice(exercises)
            reasoning = f"No {target_type} exercise available; using {exercise.exercise_type}."

        return ExerciseSelection(exercise=exercise, reasoning=reasoning)

    def _pick_exercise_type(
        self,
        card: Card,
        ctx: LearnerContext,
    ) -> tuple[str, str]:
        """Pick the ideal exercise type for this card and context."""
        # New card or high lapses -> MCQ (recognition)
        if card.reps == 0:
            return "mcq", "New card — starting with recognition (MCQ)."

        if card.lapses >= 3:
            return "mcq", f"Card has {card.lapses} lapses — using MCQ to rebuild confidence."

        # Session accuracy dropping -> easier exercises
        if ctx.session_count >= 5 and ctx.session_accuracy < 0.6:
            return "mcq", f"Session accuracy is {ctx.session_accuracy:.0%} — using easier MCQ."

        # Mature card (high reps, high stability) -> cloze or translation
        if card.reps >= 5 and card.stability > 10.0:
            return "cloze", "Mature card — testing active recall with cloze."

        if card.reps >= 8 and card.stability > 30.0:
            return "translation", "Well-known card — testing with translation."

        # Default progression: MCQ -> cloze
        if card.reps >= 2:
            return "cloze", "Card has some reviews — moving to cloze."

        return "mcq", "Default: starting with MCQ."

    def _recent_exercise_types(
        self,
        ctx: LearnerContext,
        card_id: int,
    ) -> set[int]:
        """Get exercise IDs recently used for this card (avoid repetition)."""
        recent = set()
        for event in ctx.session_reviews:
            if event.card_id == card_id:
                recent.add(event.card_id)
        return recent

    async def generate_on_demand(
        self,
        db: AsyncSession,
        card: Card,
        exercise_type: str,
    ) -> Exercise | None:
        """Generate a new exercise on-demand via LLM if none are available.

        Only used as a fallback when the pre-generated pool is exhausted.
        """
        if self.llm is None:
            return None

        # Get the content item
        stmt = select(ContentItem).where(ContentItem.id == card.content_item_id)
        result = await db.execute(stmt)
        content_item = result.scalar_one_or_none()
        if not content_item:
            return None

        prompt = self._build_generation_prompt(content_item, exercise_type)
        try:
            response = self.llm.create_message(
                prompt=prompt,
                system="You are a Hindi language exercise generator. Return JSON only.",
                max_tokens=512,
                temperature=0.7,
            )
            return self._parse_generated_exercise(response, content_item.id, exercise_type)
        except Exception:
            logger.exception("On-demand exercise generation failed")
            return None

    def _build_generation_prompt(self, item: ContentItem, exercise_type: str) -> str:
        """Build the LLM prompt for on-demand exercise generation."""
        if exercise_type == "mcq":
            return (
                f"Generate a multiple-choice question for the Hindi term '{item.term}' "
                f"(meaning: {item.definition}).\n"
                "Return JSON: {\"prompt\": \"...\", \"answer\": \"...\", "
                "\"options\": [\"opt1\", \"opt2\", \"opt3\", \"opt4\"]}"
            )
        elif exercise_type == "cloze":
            return (
                f"Generate a fill-in-the-blank exercise for '{item.term}' "
                f"(meaning: {item.definition}).\n"
                "Create a Hindi sentence using this term, replace it with ___.\n"
                "Return JSON: {\"prompt\": \"...\", \"answer\": \"...\"}"
            )
        else:
            return (
                f"Generate a translation exercise for '{item.term}' "
                f"(meaning: {item.definition}).\n"
                "Return JSON: {\"prompt\": \"...\", \"answer\": \"...\"}"
            )

    def _parse_generated_exercise(
        self, response: str, content_item_id: int, exercise_type: str
    ) -> Exercise | None:
        """Parse LLM response into an Exercise."""
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None

        if not data.get("prompt") or not data.get("answer"):
            return None

        return Exercise(
            content_item_id=content_item_id,
            exercise_type=exercise_type,
            prompt=data["prompt"],
            answer=data["answer"],
            options=json.dumps(data["options"], ensure_ascii=False)
            if data.get("options")
            else None,
            status="generated",
            generation_model="claude-sonnet-4-20250514",
            prompt_version="v1-ondemand",
        )

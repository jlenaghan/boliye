"""Exercise selection logic for review sessions.

Selects appropriate exercise types based on card state,
recent exercise history, and difficulty.
"""

import logging
import random
from collections import deque

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.card import Card
from backend.models.exercise import Exercise

logger = logging.getLogger(__name__)

# Exercise type difficulty ranking (easier first)
EXERCISE_DIFFICULTY = {
    "mcq": 1,       # Recognition - easiest
    "cloze": 2,     # Recall with context
    "translation": 3,  # Full production - hardest
}


class ExerciseSelector:
    """Selects exercises for cards during a review session.

    Strategy:
    - Vary exercise types to avoid monotony
    - Use easier types for struggling cards (high lapses)
    - Track recent types to prevent repetition
    """

    def __init__(self, history_size: int = 5) -> None:
        """Initialize the selector with a history of recent exercise types."""
        self._recent_types: deque[str] = deque(maxlen=history_size)

    async def select(
        self,
        session: AsyncSession,
        card: Card,
    ) -> Exercise | None:
        """Select the best exercise for a card.

        Args:
            session: Database session.
            card: The card to select an exercise for.

        Returns:
            An Exercise, or None if no exercises exist for this card's content.
        """
        # Fetch all approved/generated exercises for this card's content item
        stmt = (
            select(Exercise)
            .where(
                and_(
                    Exercise.content_item_id == card.content_item_id,
                    Exercise.status.in_(["generated", "approved"]),
                )
            )
        )
        result = await session.execute(stmt)
        exercises = list(result.scalars().all())

        if not exercises:
            logger.warning("No exercises found for content_item_id=%d", card.content_item_id)
            return None

        # Determine preferred exercise type based on card state
        preferred_type = self._preferred_type(card)

        # Try to find an exercise of the preferred type that wasn't recently used
        candidates = self._rank_candidates(exercises, preferred_type)
        if not candidates:
            return exercises[0]  # Fallback to any available

        chosen = candidates[0]
        self._recent_types.append(chosen.exercise_type)
        return chosen

    def _preferred_type(self, card: Card) -> str:
        """Determine the preferred exercise type based on card state."""
        # Struggling cards (many lapses) get easier exercises
        if card.lapses >= 3:
            return "mcq"

        # New cards start with recognition
        if card.reps <= 1:
            return "mcq"

        # Cards with some history get harder exercises
        if card.reps >= 5 and card.lapses == 0:
            return "cloze"

        # Default: try to vary
        if self._recent_types:
            last_type = self._recent_types[-1]
            # Pick something different from the last one
            if last_type == "mcq":
                return "cloze"
            return "mcq"

        return "mcq"

    def _rank_candidates(
        self,
        exercises: list[Exercise],
        preferred_type: str,
    ) -> list[Exercise]:
        """Rank exercises by preference.

        Priority:
        1. Preferred type, not recently used
        2. Preferred type, recently used
        3. Other types, not recently used
        4. Other types, recently used
        """
        recent_set = set(self._recent_types)

        preferred_fresh = []
        preferred_stale = []
        other_fresh = []
        other_stale = []

        for ex in exercises:
            is_preferred = ex.exercise_type == preferred_type
            is_fresh = ex.exercise_type not in recent_set

            if is_preferred and is_fresh:
                preferred_fresh.append(ex)
            elif is_preferred:
                preferred_stale.append(ex)
            elif is_fresh:
                other_fresh.append(ex)
            else:
                other_stale.append(ex)

        # Shuffle within each tier for variety
        for group in [preferred_fresh, preferred_stale, other_fresh, other_stale]:
            random.shuffle(group)

        return preferred_fresh + preferred_stale + other_fresh + other_stale

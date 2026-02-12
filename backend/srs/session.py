"""Review session orchestrator.

Coordinates the SRS engine, exercise selection, assessment,
and review logging into a cohesive session flow.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from backend.llm_client import LLMClient

from backend.models.card import Card
from backend.models.exercise import Exercise
from backend.models.review_log import ReviewLog
from backend.srs.assessment import (
    Assessment,
    AssessmentGrade,
    assess_exact,
    assess_fuzzy,
    assess_mcq,
)
from backend.srs.exercise_selector import ExerciseSelector
from backend.srs.fsrs import FSRS, CardState, ReviewResult
from backend.srs.queue import ReviewQueue, build_queue

logger = logging.getLogger(__name__)


@dataclass
class SessionCard:
    """A card presented during a session, with its exercise and state."""

    card: Card
    exercise: Exercise
    card_state: CardState


@dataclass
class SessionStats:
    """Statistics for a completed review session."""

    cards_reviewed: int = 0
    correct: int = 0
    close: int = 0
    incorrect: int = 0
    new_cards_seen: int = 0
    average_time_ms: float = 0.0
    total_time_ms: int = 0


@dataclass
class ReviewSession:
    """Manages an active review session for a learner."""

    learner_id: int
    queue: ReviewQueue
    fsrs: FSRS
    selector: ExerciseSelector = field(default_factory=ExerciseSelector)
    stats: SessionStats = field(default_factory=SessionStats)
    _card_index: int = 0
    _cards: list[Card] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Initialize the card list from the queue."""
        self._cards = self.queue.interleaved()

    @property
    def remaining(self) -> int:
        """Return the number of cards left to review."""
        return max(0, len(self._cards) - self._card_index)

    @property
    def is_complete(self) -> bool:
        """Return True if all cards have been reviewed."""
        return self._card_index >= len(self._cards)

    @property
    def current_card(self) -> Card | None:
        """Return the current card or None if session is complete."""
        if self._card_index < len(self._cards):
            return self._cards[self._card_index]
        return None

    async def get_next(self, db: AsyncSession) -> SessionCard | None:
        """Get the next card and exercise to present.

        Returns None if the session is complete.
        """
        card = self.current_card
        if card is None:
            return None

        exercise = await self.selector.select(db, card)
        if exercise is None:
            # Skip cards with no exercises
            logger.warning("Skipping card %d: no exercises available", card.id)
            self._card_index += 1
            return await self.get_next(db)

        state = CardState(
            stability=card.stability,
            difficulty=card.difficulty,
            due=card.due,
            reps=card.reps,
            lapses=card.lapses,
        )

        return SessionCard(card=card, exercise=exercise, card_state=state)

    async def submit_answer(
        self,
        db: AsyncSession,
        session_card: SessionCard,
        response: str,
        time_ms: int,
        llm: LLMClient | None = None,
        self_rating: int | None = None,
    ) -> tuple[Assessment, ReviewResult]:
        """Submit an answer for the current card.

        Args:
            db: Database session.
            session_card: The card being reviewed.
            response: The learner's response.
            time_ms: How long the response took in milliseconds.
            llm: Optional LLM client for fuzzy assessment.
            self_rating: Optional self-rating override (1-4).

        Returns:
            Tuple of (assessment, review_result).
        """
        exercise = session_card.exercise
        card = session_card.card
        state = session_card.card_state

        # Assess the response
        if exercise.exercise_type == "mcq":
            assessment = assess_mcq(response, exercise.answer)
        elif llm is not None:
            assessment = assess_fuzzy(response, exercise.answer, exercise.prompt, llm)
        else:
            assessment = assess_exact(response, exercise.answer)

        # Determine rating: use self-rating if provided, otherwise use assessment suggestion
        rating = self_rating if self_rating is not None else assessment.suggested_rating

        # Apply FSRS update
        review_result = self.fsrs.review(state, rating)

        # Update card in database
        card.stability = review_result.new_state.stability
        card.difficulty = review_result.new_state.difficulty
        card.due = review_result.new_state.due
        card.reps = review_result.new_state.reps
        card.lapses = review_result.new_state.lapses

        # Log the review
        log_entry = ReviewLog(
            card_id=card.id,
            learner_id=self.learner_id,
            exercise_type=exercise.exercise_type,
            rating=rating,
            time_ms=time_ms,
            stability_before=state.stability,
            stability_after=review_result.new_state.stability,
            difficulty_before=state.difficulty,
            difficulty_after=review_result.new_state.difficulty,
        )
        db.add(log_entry)
        await db.commit()

        # Update stats
        self.stats.cards_reviewed += 1
        self.stats.total_time_ms += time_ms
        self.stats.average_time_ms = self.stats.total_time_ms / self.stats.cards_reviewed
        if state.reps == 0:
            self.stats.new_cards_seen += 1
        if assessment.grade == AssessmentGrade.CORRECT:
            self.stats.correct += 1
        elif assessment.grade == AssessmentGrade.CLOSE:
            self.stats.close += 1
        else:
            self.stats.incorrect += 1

        # Advance to next card
        self._card_index += 1

        return assessment, review_result


async def start_session(
    db: AsyncSession,
    learner_id: int,
    target_retention: float = 0.9,
) -> ReviewSession:
    """Start a new review session for a learner.

    Args:
        db: Database session.
        learner_id: The learner starting the session.
        target_retention: Target retention for FSRS (default 0.9).

    Returns:
        A ReviewSession ready for use.
    """
    queue = await build_queue(db, learner_id)
    fsrs = FSRS(target_retention=target_retention)

    session = ReviewSession(
        learner_id=learner_id,
        queue=queue,
        fsrs=fsrs,
    )

    logger.info(
        "Started session for learner %d: %d cards queued",
        learner_id,
        queue.total,
    )
    return session

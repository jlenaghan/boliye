"""Scheduler Agent: wraps the SRS algorithm with adaptive behavior.

Responsibilities:
- Queue prioritization beyond raw due-date ordering
- Adaptive new card introduction based on session performance
- Focus area suggestions based on learner patterns
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.base import BaseAgent, LearnerContext
from backend.config import settings, utcnow
from backend.models.card import Card
from backend.models.content_item import ContentItem
from backend.srs.fsrs import FSRS, CardState
from backend.srs.queue import ReviewQueue

logger = logging.getLogger(__name__)


@dataclass
class SchedulerDecision:
    """The scheduler's decision about what to review next."""

    queue: ReviewQueue
    new_card_limit: int
    review_limit: int
    focus_topics: list[str]
    reasoning: str


class SchedulerAgent(BaseAgent):
    """Wraps the SRS engine with intelligent, adaptive scheduling."""

    def __init__(self, fsrs: FSRS | None = None, **kwargs) -> None:
        """Initialize the scheduler with an optional FSRS instance."""
        super().__init__(**kwargs)
        self.fsrs = fsrs or FSRS(target_retention=settings.target_retention)

    @property
    def name(self) -> str:
        """Return the agent identifier."""
        return "scheduler"

    @property
    def description(self) -> str:
        """Return what this agent does."""
        return "Manages SRS scheduling, queue prioritization, and adaptive card introduction"

    async def build_adaptive_queue(
        self,
        db: AsyncSession,
        ctx: LearnerContext,
    ) -> SchedulerDecision:
        """Build a review queue adapted to the learner's current performance.

        Adjusts new card introduction rate based on:
        - Current session accuracy
        - Recent failure streaks
        - Overall retention
        """
        # Determine adaptive limits
        new_limit, review_limit, reasoning = self._compute_limits(ctx)

        # Fetch due cards
        now = utcnow()
        due_stmt = (
            select(Card)
            .where(
                and_(
                    Card.learner_id == ctx.learner_id,
                    Card.reps > 0,
                    Card.due <= now,
                )
            )
            .order_by(Card.due.asc())
            .limit(review_limit)
        )
        due_result = await db.execute(due_stmt)
        due_cards = list(due_result.scalars().all())

        # Fetch new cards
        new_stmt = (
            select(Card)
            .where(
                and_(
                    Card.learner_id == ctx.learner_id,
                    Card.reps == 0,
                    Card.lapses == 0,
                )
            )
            .limit(new_limit)
        )
        new_result = await db.execute(new_stmt)
        new_cards = list(new_result.scalars().all())

        # Identify focus topics from struggling cards
        focus_topics = await self._identify_focus_topics(db, ctx)

        queue = ReviewQueue(
            due_cards=due_cards,
            new_cards=new_cards,
            total=len(due_cards) + len(new_cards),
        )

        return SchedulerDecision(
            queue=queue,
            new_card_limit=new_limit,
            review_limit=review_limit,
            focus_topics=focus_topics,
            reasoning=reasoning,
        )

    def _compute_limits(self, ctx: LearnerContext) -> tuple[int, int, str]:
        """Compute adaptive new/review card limits based on performance."""
        base_new = settings.max_new_cards_per_session
        base_review = settings.max_reviews_per_session

        # If accuracy is low, reduce new cards to let learner catch up
        if ctx.session_count >= 5 and ctx.session_accuracy < 0.6:
            new_limit = max(2, base_new // 3)
            reasoning = (
                f"Accuracy is {ctx.session_accuracy:.0%} — reducing new cards to "
                f"{new_limit} so you can focus on reviewing."
            )
        elif ctx.session_count >= 5 and ctx.session_accuracy < 0.75:
            new_limit = max(3, base_new // 2)
            reasoning = (
                f"Accuracy is {ctx.session_accuracy:.0%} — slightly reducing new cards to "
                f"{new_limit}."
            )
        elif ctx.session_accuracy >= 0.9 and ctx.session_count >= 10:
            new_limit = min(base_new + 5, 20)
            reasoning = (
                f"Great accuracy ({ctx.session_accuracy:.0%})! Increasing new cards to {new_limit}."
            )
        else:
            new_limit = base_new
            reasoning = f"Standard limits: {base_new} new, {base_review} reviews."

        # If there's a failure streak, pause new cards entirely
        if ctx.failure_streak() >= 3:
            new_limit = 0
            reasoning = (
                f"You've missed the last {ctx.failure_streak()} cards — "
                "pausing new cards to focus on review."
            )

        return new_limit, base_review, reasoning

    async def _identify_focus_topics(
        self,
        db: AsyncSession,
        ctx: LearnerContext,
    ) -> list[str]:
        """Identify topics where the learner is struggling."""
        if not ctx.recently_failed:
            return []

        # Get content items for failed cards and extract topics
        stmt = (
            select(ContentItem.topics)
            .join(Card, Card.content_item_id == ContentItem.id)
            .where(Card.id.in_(ctx.recently_failed))
        )
        result = await db.execute(stmt)
        topic_strings = [row[0] for row in result.all() if row[0]]

        topic_counts: dict[str, int] = {}
        for ts in topic_strings:
            try:
                topics = json.loads(ts)
            except (json.JSONDecodeError, TypeError):
                continue
            for t in topics:
                topic_counts[t] = topic_counts.get(t, 0) + 1

        # Return top 3 struggling topics
        sorted_topics = sorted(topic_counts, key=topic_counts.get, reverse=True)  # type: ignore[arg-type]
        return sorted_topics[:3]

    def get_card_state(self, card: Card) -> CardState:
        """Extract FSRS state from a database Card."""
        return CardState(
            stability=card.stability,
            difficulty=card.difficulty,
            due=card.due,
            reps=card.reps,
            lapses=card.lapses,
        )

    def review_card(self, state: CardState, rating: int) -> CardState:
        """Apply a review rating and return the new card state."""
        result = self.fsrs.review(state, rating)
        return result.new_state

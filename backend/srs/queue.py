"""Queue management for SRS review sessions.

Handles card prioritization, mixing new cards with reviews,
and session limits to prevent overwhelm.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import settings
from backend.models.card import Card

logger = logging.getLogger(__name__)


@dataclass
class QueueConfig:
    """Configuration for queue building."""

    max_reviews: int = settings.max_reviews_per_session
    max_new: int = settings.max_new_cards_per_session
    new_card_ratio: float = 0.25  # 1 new card per 4 reviews


@dataclass
class ReviewQueue:
    """A prepared queue of cards for a review session."""

    due_cards: list[Card] = field(default_factory=list)
    new_cards: list[Card] = field(default_factory=list)
    total: int = 0

    def interleaved(self) -> list[Card]:
        """Return cards interleaved: mostly reviews with new cards mixed in.

        Strategy: Insert new cards at regular intervals within the review queue
        to maintain engagement without overwhelming with unfamiliar material.
        """
        if not self.new_cards:
            return list(self.due_cards)
        if not self.due_cards:
            return list(self.new_cards)

        result: list[Card] = []
        due = list(self.due_cards)
        new = list(self.new_cards)

        # Insert a new card every N reviews
        interval = max(1, len(due) // (len(new) + 1))
        new_idx = 0

        for i, card in enumerate(due):
            result.append(card)
            if new_idx < len(new) and (i + 1) % interval == 0:
                result.append(new[new_idx])
                new_idx += 1

        # Append any remaining new cards at the end
        result.extend(new[new_idx:])
        return result


async def build_queue(
    session: AsyncSession,
    learner_id: int,
    config: QueueConfig | None = None,
    now: datetime | None = None,
) -> ReviewQueue:
    """Build a review queue for a learner.

    Fetches due cards (overdue first) and new cards (never reviewed),
    respecting session limits.

    Args:
        session: Database session.
        learner_id: The learner to build the queue for.
        config: Queue configuration (limits, ratios).
        now: Current time (defaults to utcnow).

    Returns:
        A ReviewQueue with due and new cards.
    """
    config = config or QueueConfig()
    now = now or datetime.utcnow()

    # Fetch due cards: cards with reps > 0 that are past their due date
    # Ordered by how overdue they are (most overdue first)
    due_stmt = (
        select(Card)
        .where(
            and_(
                Card.learner_id == learner_id,
                Card.reps > 0,
                Card.due <= now,
            )
        )
        .order_by(Card.due.asc())  # Most overdue first
        .limit(config.max_reviews)
        .options(selectinload(Card.content_item))
    )
    due_result = await session.execute(due_stmt)
    due_cards = list(due_result.scalars().all())

    # Calculate how many new cards to introduce
    new_card_slots = min(
        config.max_new,
        max(1, int(len(due_cards) * config.new_card_ratio)),
    )

    # Fetch new cards: cards with reps == 0 (never reviewed)
    new_stmt = (
        select(Card)
        .where(
            and_(
                Card.learner_id == learner_id,
                Card.reps == 0,
                Card.lapses == 0,
            )
        )
        .order_by(Card.id.asc())  # Oldest first (FIFO)
        .limit(new_card_slots)
        .options(selectinload(Card.content_item))
    )
    new_result = await session.execute(new_stmt)
    new_cards = list(new_result.scalars().all())

    queue = ReviewQueue(
        due_cards=due_cards,
        new_cards=new_cards,
        total=len(due_cards) + len(new_cards),
    )

    logger.info(
        "Built queue for learner %d: %d due + %d new = %d total",
        learner_id,
        len(due_cards),
        len(new_cards),
        queue.total,
    )
    return queue

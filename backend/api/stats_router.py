"""API routes for learner statistics and dashboard data."""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import and_, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.schemas import LearnerStatsResponse
from backend.database import get_session
from backend.models.card import Card
from backend.models.review_log import ReviewLog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/{learner_id}", response_model=LearnerStatsResponse)
async def get_learner_stats(
    learner_id: int,
    db: AsyncSession = Depends(get_session),
) -> LearnerStatsResponse:
    """Get overall statistics for a learner."""
    now = datetime.utcnow()

    # Total cards
    total_stmt = select(func.count(Card.id)).where(Card.learner_id == learner_id)
    total_cards = (await db.execute(total_stmt)).scalar() or 0

    # Due cards
    due_stmt = select(func.count(Card.id)).where(
        and_(Card.learner_id == learner_id, Card.reps > 0, Card.due <= now)
    )
    cards_due = (await db.execute(due_stmt)).scalar() or 0

    # New cards (never reviewed)
    new_stmt = select(func.count(Card.id)).where(
        and_(Card.learner_id == learner_id, Card.reps == 0, Card.lapses == 0)
    )
    cards_new = (await db.execute(new_stmt)).scalar() or 0

    # Mature cards (5+ reps)
    mature_stmt = select(func.count(Card.id)).where(
        and_(Card.learner_id == learner_id, Card.reps >= 5)
    )
    cards_mature = (await db.execute(mature_stmt)).scalar() or 0

    # Total reviews
    reviews_stmt = select(func.count(ReviewLog.id)).where(
        ReviewLog.learner_id == learner_id
    )
    total_reviews = (await db.execute(reviews_stmt)).scalar() or 0

    # Average retention (from recent reviews: % rated >= 3)
    recent_cutoff = now - timedelta(days=30)
    retention_total_stmt = select(func.count(ReviewLog.id)).where(
        and_(
            ReviewLog.learner_id == learner_id,
            ReviewLog.reviewed_at >= recent_cutoff,
        )
    )
    retention_pass_stmt = select(func.count(ReviewLog.id)).where(
        and_(
            ReviewLog.learner_id == learner_id,
            ReviewLog.reviewed_at >= recent_cutoff,
            ReviewLog.rating >= 3,
        )
    )
    retention_total = (await db.execute(retention_total_stmt)).scalar() or 0
    retention_pass = (await db.execute(retention_pass_stmt)).scalar() or 0
    average_retention = retention_pass / retention_total if retention_total > 0 else None

    # Streak: count consecutive days with at least one review
    streak_days = await _calculate_streak(db, learner_id, now)

    return LearnerStatsResponse(
        total_cards=total_cards,
        cards_due=cards_due,
        cards_new=cards_new,
        cards_mature=cards_mature,
        average_retention=round(average_retention, 3) if average_retention is not None else None,
        streak_days=streak_days,
        total_reviews=total_reviews,
    )


async def _calculate_streak(
    db: AsyncSession,
    learner_id: int,
    now: datetime,
) -> int:
    """Calculate the number of consecutive days the learner has reviewed."""
    # Get distinct review dates (just the date part)
    stmt = (
        select(distinct(func.date(ReviewLog.reviewed_at)))
        .where(ReviewLog.learner_id == learner_id)
        .order_by(func.date(ReviewLog.reviewed_at).desc())
    )
    result = await db.execute(stmt)
    dates = [row[0] for row in result.all()]

    if not dates:
        return 0

    today = now.date()
    streak = 0

    for i, review_date in enumerate(dates):
        expected = today - timedelta(days=i)
        if str(review_date) == str(expected):
            streak += 1
        else:
            break

    return streak

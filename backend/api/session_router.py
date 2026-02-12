"""API routes for review sessions."""

import contextlib
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.schemas import (
    AnswerRequest,
    AnswerResponse,
    ExerciseResponse,
    SessionStartResponse,
    SessionStatsResponse,
)
from backend.database import get_session
from backend.srs.session import ReviewSession, start_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/session", tags=["session"])

# In-memory session store (for MVP; move to Redis for production)
_active_sessions: dict[str, ReviewSession] = {}


@router.post("/start", response_model=SessionStartResponse)
async def session_start(
    learner_id: int,
    db: AsyncSession = Depends(get_session),
) -> SessionStartResponse:
    """Start a new review session for a learner."""
    review_session = await start_session(db, learner_id)

    if review_session.queue.total == 0:
        raise HTTPException(status_code=404, detail="No cards available for review")

    session_id = str(uuid.uuid4())
    _active_sessions[session_id] = review_session

    return SessionStartResponse(
        session_id=session_id,
        learner_id=learner_id,
        total_cards=review_session.queue.total,
        due_cards=len(review_session.queue.due_cards),
        new_cards=len(review_session.queue.new_cards),
    )


@router.get("/next/{session_id}", response_model=ExerciseResponse)
async def session_next(
    session_id: str,
    db: AsyncSession = Depends(get_session),
) -> ExerciseResponse:
    """Get the next exercise in the session."""
    review_session = _active_sessions.get(session_id)
    if not review_session:
        raise HTTPException(status_code=404, detail="Session not found")

    if review_session.is_complete:
        raise HTTPException(status_code=410, detail="Session is complete")

    session_card = await review_session.get_next(db)
    if session_card is None:
        raise HTTPException(status_code=410, detail="No more cards in session")

    # Parse MCQ options if present
    options = None
    if session_card.exercise.options:
        with contextlib.suppress(json.JSONDecodeError):
            options = json.loads(session_card.exercise.options)

    return ExerciseResponse(
        card_id=session_card.card.id,
        exercise_id=session_card.exercise.id,
        exercise_type=session_card.exercise.exercise_type,
        prompt=session_card.exercise.prompt,
        options=options,
        card_reps=session_card.card.reps,
        card_lapses=session_card.card.lapses,
        remaining=review_session.remaining,
    )


@router.post("/answer/{session_id}", response_model=AnswerResponse)
async def session_answer(
    session_id: str,
    request: AnswerRequest,
    db: AsyncSession = Depends(get_session),
) -> AnswerResponse:
    """Submit an answer for the current card."""
    review_session = _active_sessions.get(session_id)
    if not review_session:
        raise HTTPException(status_code=404, detail="Session not found")

    session_card = await review_session.get_next(db)
    if session_card is None:
        raise HTTPException(status_code=410, detail="Session is complete")

    # Verify the card/exercise match
    if session_card.card.id != request.card_id:
        raise HTTPException(status_code=400, detail="Card ID mismatch")

    assessment, review_result = await review_session.submit_answer(
        db=db,
        session_card=session_card,
        response=request.response,
        time_ms=request.time_ms,
        self_rating=request.self_rating,
    )

    return AnswerResponse(
        grade=assessment.grade.value,
        suggested_rating=assessment.suggested_rating,
        applied_rating=request.self_rating or assessment.suggested_rating,
        feedback=assessment.feedback,
        correct_answer=assessment.expected,
        next_due=review_result.new_state.due,
        interval_days=review_result.interval_days,
        remaining=review_session.remaining,
        session_complete=review_session.is_complete,
    )


@router.get("/stats/{session_id}", response_model=SessionStatsResponse)
async def session_stats(session_id: str) -> SessionStatsResponse:
    """Get stats for the current session."""
    review_session = _active_sessions.get(session_id)
    if not review_session:
        raise HTTPException(status_code=404, detail="Session not found")

    s = review_session.stats
    return SessionStatsResponse(
        cards_reviewed=s.cards_reviewed,
        correct=s.correct,
        close=s.close,
        incorrect=s.incorrect,
        new_cards_seen=s.new_cards_seen,
        average_time_ms=s.average_time_ms,
    )


@router.post("/end/{session_id}")
async def session_end(session_id: str) -> dict:
    """End a session and clean up."""
    review_session = _active_sessions.pop(session_id, None)
    if not review_session:
        raise HTTPException(status_code=404, detail="Session not found")

    s = review_session.stats
    return {
        "status": "ended",
        "cards_reviewed": s.cards_reviewed,
        "correct": s.correct,
        "incorrect": s.incorrect,
    }

"""Pydantic schemas for API request/response models."""

from datetime import datetime

from pydantic import BaseModel

# --- Session ---


class SessionStartResponse(BaseModel):
    """Response when starting a new review session."""

    session_id: str
    learner_id: int
    total_cards: int
    due_cards: int
    new_cards: int


class ExerciseResponse(BaseModel):
    """Response containing the next exercise to review."""

    card_id: int
    exercise_id: int
    exercise_type: str
    prompt: str
    options: list[str] | None = None  # For MCQ
    card_reps: int
    card_lapses: int
    remaining: int


class AnswerRequest(BaseModel):
    """Request to submit an answer for an exercise."""

    card_id: int
    exercise_id: int
    response: str
    time_ms: int
    self_rating: int | None = None  # Optional override (1-4)


class AnswerResponse(BaseModel):
    """Response after submitting an answer with feedback and scheduling info."""

    grade: str  # correct, close, partial, incorrect
    suggested_rating: int
    applied_rating: int
    feedback: str
    correct_answer: str
    next_due: datetime
    interval_days: float
    remaining: int
    session_complete: bool


class SessionStatsResponse(BaseModel):
    """Statistics for the current review session."""

    cards_reviewed: int
    correct: int
    close: int
    incorrect: int
    new_cards_seen: int
    average_time_ms: float


# --- Stats ---


class LearnerStatsResponse(BaseModel):
    """Overall statistics for a learner."""

    total_cards: int
    cards_due: int
    cards_new: int
    cards_mature: int  # reps >= 5
    average_retention: float | None
    streak_days: int
    total_reviews: int

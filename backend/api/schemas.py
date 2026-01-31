"""Pydantic schemas for API request/response models."""

from datetime import datetime

from pydantic import BaseModel


# --- Session ---


class SessionStartResponse(BaseModel):
    session_id: str
    learner_id: int
    total_cards: int
    due_cards: int
    new_cards: int


class ExerciseResponse(BaseModel):
    card_id: int
    exercise_id: int
    exercise_type: str
    prompt: str
    options: list[str] | None = None  # For MCQ
    card_reps: int
    card_lapses: int
    remaining: int


class AnswerRequest(BaseModel):
    card_id: int
    exercise_id: int
    response: str
    time_ms: int
    self_rating: int | None = None  # Optional override (1-4)


class AnswerResponse(BaseModel):
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
    cards_reviewed: int
    correct: int
    close: int
    incorrect: int
    new_cards_seen: int
    average_time_ms: float


# --- Stats ---


class LearnerStatsResponse(BaseModel):
    total_cards: int
    cards_due: int
    cards_new: int
    cards_mature: int  # reps >= 5
    average_retention: float | None
    streak_days: int
    total_reviews: int

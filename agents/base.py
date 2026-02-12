"""Base agent protocol and shared learner context.

Defines the common interface all agents implement and the shared context
object that gives every agent access to learner state, session history,
and preferences.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from backend.config import utcnow
from backend.llm_client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class ReviewEvent:
    """A single review event from the current or recent sessions."""

    card_id: int
    term: str
    definition: str
    exercise_type: str
    rating: int
    grade: str  # "correct", "close", "partial", "incorrect"
    feedback: str
    time_ms: int
    exercise_id: int | None = None
    timestamp: datetime = field(default_factory=utcnow)


@dataclass
class LearnerContext:
    """Shared context accessible to all agents.

    Aggregates learner state, session history, and preferences so
    each agent can make informed decisions.
    """

    learner_id: int
    learner_name: str = ""
    cefr_level: str = "A1"

    # Performance metrics
    total_reviews: int = 0
    average_retention: float | None = None
    streak_days: int = 0

    # Current session state
    session_reviews: list[ReviewEvent] = field(default_factory=list)
    session_correct: int = 0
    session_incorrect: int = 0
    session_start: datetime = field(default_factory=utcnow)

    # Card-level data for the current session
    struggling_terms: list[str] = field(default_factory=list)
    recently_failed: list[int] = field(default_factory=list)  # card IDs

    # Preferences
    preferred_session_length: int = 20  # cards
    preferred_difficulty: str = "balanced"  # "easy", "balanced", "challenging"

    @property
    def session_accuracy(self) -> float:
        """Current session accuracy as a fraction."""
        total = self.session_correct + self.session_incorrect
        return self.session_correct / total if total > 0 else 1.0

    @property
    def session_count(self) -> int:
        """Number of reviews in the current session."""
        return len(self.session_reviews)

    def record_review(self, event: ReviewEvent) -> None:
        """Record a review event and update running stats."""
        self.session_reviews.append(event)
        if event.grade == "correct":
            self.session_correct += 1
        else:
            self.session_incorrect += 1
            if event.rating == 1:
                self.recently_failed.append(event.card_id)
                if event.term not in self.struggling_terms:
                    self.struggling_terms.append(event.term)

    def recent_reviews(self, n: int = 5) -> list[ReviewEvent]:
        """Get the last n review events."""
        return self.session_reviews[-n:]

    def failure_streak(self) -> int:
        """Count consecutive incorrect answers from the end."""
        count = 0
        for event in reversed(self.session_reviews):
            if event.grade != "correct":
                count += 1
            else:
                break
        return count


class BaseAgent(ABC):
    """Abstract base class for all agents.

    Each agent has access to the shared learner context and an LLM client.
    Agents implement domain-specific logic and expose a clear tool interface
    that the orchestrator can invoke.
    """

    def __init__(self, llm: LLMClient | None = None) -> None:
        """Initialize the agent with an optional LLM client."""
        self.llm = llm
        self.logger = logging.getLogger(f"agents.{self.name}")

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique agent identifier."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """What this agent does, for logging and debugging."""
        ...

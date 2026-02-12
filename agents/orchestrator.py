"""Orchestrator: coordinates agents into a cohesive tutoring session.

The orchestrator is the top-level controller that:
- Starts and manages review sessions
- Delegates to the appropriate agent at each step
- Tracks conversation state and adapts behavior
- Handles interruptions and session flow
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.assessor_agent import AssessorAgent, DetailedAssessment
from agents.base import LearnerContext, ReviewEvent
from agents.content_agent import ContentAgent
from agents.scheduler_agent import SchedulerAgent, SchedulerDecision
from agents.tutor_agent import TutorAgent, TutorResponse
from backend.config import settings, utcnow
from backend.llm_client import LLMClient
from backend.models.card import Card
from backend.models.content_item import ContentItem
from backend.models.exercise import Exercise
from backend.models.learner import Learner
from backend.models.review_log import ReviewLog
from backend.srs.fsrs import FSRS

logger = logging.getLogger(__name__)


@dataclass
class PresentedCard:
    """A card currently being presented to the learner."""

    card: Card
    exercise: Exercise
    content_item: ContentItem
    selection_reasoning: str


@dataclass
class AnswerResult:
    """The result of the learner answering a presented card."""

    assessment: DetailedAssessment
    tutor_response: TutorResponse | None
    new_card_state: dict  # stability, difficulty, due, reps, lapses
    rating_used: int


@dataclass
class SessionSummary:
    """Summary of a completed session."""

    cards_reviewed: int
    correct: int
    incorrect: int
    close: int
    new_cards_seen: int
    accuracy: float
    focus_topics: list[str]
    struggling_terms: list[str]
    scheduler_reasoning: str
    duration_seconds: float


class Orchestrator:
    """Coordinates the four agents into a tutoring session.

    Flow for each card:
    1. Scheduler provides the queue (done once at session start)
    2. Content agent selects the exercise
    3. Learner responds
    4. Assessor evaluates the response
    5. Tutor explains (if needed)
    6. Scheduler updates the card state
    """

    def __init__(self, llm: LLMClient | None = None) -> None:
        """Initialize the orchestrator with all sub-agents."""
        self.llm = llm
        self.fsrs = FSRS(target_retention=settings.target_retention)
        self.scheduler = SchedulerAgent(fsrs=self.fsrs, llm=llm)
        self.content = ContentAgent(llm=llm)
        self.assessor = AssessorAgent(llm=llm)
        self.tutor = TutorAgent(llm=llm)
        self._sessions: dict[str, _ActiveSession] = {}
        self._session_ttl = settings.session_ttl_seconds

    async def start_session(
        self,
        db: AsyncSession,
        learner_id: int,
    ) -> tuple[str, SchedulerDecision]:
        """Start a new orchestrated review session.

        Returns a session_id and the scheduler's queue decision.
        """
        # Evict stale sessions before creating a new one
        self._evict_expired_sessions()

        # Load learner context
        ctx = await self._build_context(db, learner_id)

        # Get adaptive queue from scheduler
        decision = await self.scheduler.build_adaptive_queue(db, ctx)

        # Create session
        session_id = f"session-{learner_id}-{int(utcnow().timestamp())}"
        cards = decision.queue.interleaved()

        self._sessions[session_id] = _ActiveSession(
            session_id=session_id,
            ctx=ctx,
            cards=cards,
            card_index=0,
            decision=decision,
        )

        logger.info(
            "Orchestrator started session %s: %d cards, %d new, %d reviews",
            session_id,
            len(cards),
            len(decision.queue.new_cards),
            len(decision.queue.due_cards),
        )

        return session_id, decision

    async def get_next_card(
        self,
        db: AsyncSession,
        session_id: str,
    ) -> PresentedCard | None:
        """Get the next card to present to the learner.

        Returns None if the session is complete.
        """
        session = self._sessions.get(session_id)
        if session is None:
            logger.error("Session %s not found", session_id)
            return None

        while session.card_index < len(session.cards):
            card = session.cards[session.card_index]

            # Content agent selects the exercise
            selection = await self.content.select_exercise(db, card, session.ctx)
            if selection is None:
                logger.warning("Skipping card %d: no exercises", card.id)
                session.card_index += 1
                continue

            # Load the content item
            stmt = select(ContentItem).where(ContentItem.id == card.content_item_id)
            result = await db.execute(stmt)
            content_item = result.scalar_one_or_none()

            if content_item is None:
                logger.error("Content item %d not found for card %d", card.content_item_id, card.id)
                session.card_index += 1
                continue

            session.current_presented = PresentedCard(
                card=card,
                exercise=selection.exercise,
                content_item=content_item,
                selection_reasoning=selection.reasoning,
            )
            return session.current_presented

        return None

    async def submit_answer(
        self,
        db: AsyncSession,
        session_id: str,
        response: str,
        time_ms: int,
        self_rating: int | None = None,
    ) -> AnswerResult | None:
        """Submit the learner's answer and get assessment + tutoring.

        Args:
            db: Database session.
            session_id: Active session ID.
            response: The learner's typed or selected response.
            time_ms: Response time in milliseconds.
            self_rating: Optional override rating (1-4).

        Returns:
            AnswerResult with assessment, optional tutoring, and updated card state.
        """
        session = self._sessions.get(session_id)
        if session is None or session.current_presented is None:
            return None

        presented = session.current_presented
        card = presented.card
        exercise = presented.exercise
        content_item = presented.content_item
        ctx = session.ctx

        # Step 1: Assessor evaluates the response
        detailed = self.assessor.assess(response, exercise, ctx)
        assessment = detailed.assessment

        # Step 2: Determine rating
        rating = self_rating if self_rating is not None else assessment.suggested_rating

        # Step 3: Tutor explains if needed
        tutor_response = None
        if detailed.should_explain:
            tutor_response = self.tutor.explain(
                assessment=assessment,
                exercise=exercise,
                content_item=content_item,
                ctx=ctx,
                error_type=detailed.error_type,
            )

        # Step 4: Scheduler updates card state
        card_state = self.scheduler.get_card_state(card)
        new_state = self.scheduler.review_card(card_state, rating)

        # Persist to database
        card.stability = new_state.stability
        card.difficulty = new_state.difficulty
        card.due = new_state.due
        card.reps = new_state.reps
        card.lapses = new_state.lapses

        log_entry = ReviewLog(
            card_id=card.id,
            learner_id=ctx.learner_id,
            exercise_type=exercise.exercise_type,
            rating=rating,
            time_ms=time_ms,
            stability_before=card_state.stability,
            stability_after=new_state.stability,
            difficulty_before=card_state.difficulty,
            difficulty_after=new_state.difficulty,
        )
        db.add(log_entry)
        await db.commit()

        # Step 5: Update learner context
        event = ReviewEvent(
            card_id=card.id,
            term=content_item.term,
            definition=content_item.definition,
            exercise_type=exercise.exercise_type,
            rating=rating,
            grade=assessment.grade.value,
            feedback=assessment.feedback,
            time_ms=time_ms,
            exercise_id=exercise.id,
        )
        ctx.record_review(event)

        # Advance to next card
        session.card_index += 1
        session.current_presented = None

        return AnswerResult(
            assessment=detailed,
            tutor_response=tutor_response,
            new_card_state={
                "stability": new_state.stability,
                "difficulty": new_state.difficulty,
                "due": new_state.due.isoformat(),
                "reps": new_state.reps,
                "lapses": new_state.lapses,
            },
            rating_used=rating,
        )

    def get_session_summary(self, session_id: str) -> SessionSummary | None:
        """Get a summary of the session's progress."""
        session = self._sessions.get(session_id)
        if session is None:
            return None

        ctx = session.ctx
        now = utcnow()
        duration = (now - ctx.session_start).total_seconds()

        return SessionSummary(
            cards_reviewed=ctx.session_count,
            correct=ctx.session_correct,
            incorrect=ctx.session_incorrect,
            close=sum(1 for e in ctx.session_reviews if e.grade == "close"),
            new_cards_seen=sum(1 for e in ctx.session_reviews if e.rating >= 3),
            accuracy=ctx.session_accuracy,
            focus_topics=session.decision.focus_topics,
            struggling_terms=ctx.struggling_terms,
            scheduler_reasoning=session.decision.reasoning,
            duration_seconds=duration,
        )

    def end_session(self, session_id: str) -> SessionSummary | None:
        """End a session and return the final summary."""
        summary = self.get_session_summary(session_id)
        self._sessions.pop(session_id, None)
        return summary

    def _evict_expired_sessions(self) -> None:
        """Remove sessions that have exceeded the TTL."""
        now = utcnow()
        expired = [
            sid
            for sid, s in self._sessions.items()
            if (now - s.created_at).total_seconds() > self._session_ttl
        ]
        for sid in expired:
            logger.info("Evicting expired session %s", sid)
            self._sessions.pop(sid, None)

    @property
    def active_sessions(self) -> list[str]:
        """List active session IDs."""
        return list(self._sessions.keys())

    async def _build_context(
        self,
        db: AsyncSession,
        learner_id: int,
    ) -> LearnerContext:
        """Build the shared learner context from database state."""
        # Load learner
        stmt = select(Learner).where(Learner.id == learner_id)
        result = await db.execute(stmt)
        learner = result.scalar_one_or_none()

        name = learner.name if learner else ""
        level = learner.current_level if learner else "A1"

        # Count total reviews
        count_stmt = select(func.count(ReviewLog.id)).where(ReviewLog.learner_id == learner_id)
        total_reviews = (await db.execute(count_stmt)).scalar() or 0

        return LearnerContext(
            learner_id=learner_id,
            learner_name=name,
            cefr_level=level,
            total_reviews=total_reviews,
        )


@dataclass
class _ActiveSession:
    """Internal state for an active orchestrated session."""

    session_id: str
    ctx: LearnerContext
    cards: list[Card]
    card_index: int
    decision: SchedulerDecision
    current_presented: PresentedCard | None = None
    created_at: datetime = field(default_factory=lambda: utcnow())

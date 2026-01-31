"""Tests for the agent system: context, scheduler, assessor, content, tutor."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from agents.assessor_agent import AssessorAgent, DetailedAssessment
from agents.base import LearnerContext, ReviewEvent
from agents.content_agent import ContentAgent
from agents.scheduler_agent import SchedulerAgent
from agents.tutor_agent import TutorAgent
from backend.models.content_item import ContentItem
from backend.models.exercise import Exercise
from backend.srs.assessment import Assessment, AssessmentGrade
from backend.srs.fsrs import FSRS


# --- Helpers ---


def _make_context(
    learner_id: int = 1,
    reviews: list[ReviewEvent] | None = None,
    session_correct: int = 0,
    session_incorrect: int = 0,
) -> LearnerContext:
    ctx = LearnerContext(
        learner_id=learner_id,
        learner_name="Test",
        cefr_level="A1",
    )
    if reviews:
        for r in reviews:
            ctx.record_review(r)
    else:
        ctx.session_correct = session_correct
        ctx.session_incorrect = session_incorrect
    return ctx


def _make_review_event(
    term: str = "नमस्ते",
    grade: str = "correct",
    rating: int = 3,
) -> ReviewEvent:
    return ReviewEvent(
        card_id=1,
        term=term,
        definition="hello",
        exercise_type="mcq",
        rating=rating,
        grade=grade,
        feedback="",
        time_ms=5000,
    )


def _make_exercise(
    exercise_type: str = "mcq",
    prompt: str = "What does नमस्ते mean?",
    answer: str = "hello",
    options: str | None = '["hello", "goodbye", "thanks", "sorry"]',
) -> MagicMock:
    ex = MagicMock(spec=Exercise)
    ex.id = 1
    ex.content_item_id = 1
    ex.exercise_type = exercise_type
    ex.prompt = prompt
    ex.answer = answer
    ex.options = options
    ex.status = "approved"
    ex.generation_model = "test"
    ex.prompt_version = "v1"
    return ex


def _make_content_item(
    term: str = "नमस्ते",
    definition: str = "hello",
    romanization: str = "namaste",
    content_type: str = "vocab",
    context: str | None = None,
) -> MagicMock:
    item = MagicMock(spec=ContentItem)
    item.id = 1
    item.term = term
    item.definition = definition
    item.romanization = romanization
    item.content_type = content_type
    item.context = context
    item.cefr_level = "A1"
    item.topics = "[]"
    item.source_file = "test.txt"
    item.familiarity = "unknown"
    return item


# --- LearnerContext ---


class TestLearnerContext:
    def test_empty_context(self) -> None:
        ctx = _make_context()
        assert ctx.session_count == 0
        assert ctx.session_accuracy == 1.0
        assert ctx.failure_streak() == 0

    def test_record_correct(self) -> None:
        ctx = _make_context()
        ctx.record_review(_make_review_event(grade="correct"))
        assert ctx.session_correct == 1
        assert ctx.session_accuracy == 1.0

    def test_record_incorrect(self) -> None:
        ctx = _make_context()
        ctx.record_review(_make_review_event(grade="incorrect", rating=1))
        assert ctx.session_incorrect == 1
        assert ctx.session_accuracy == 0.0
        assert "नमस्ते" in ctx.struggling_terms

    def test_failure_streak(self) -> None:
        ctx = _make_context()
        ctx.record_review(_make_review_event(grade="correct"))
        ctx.record_review(_make_review_event(grade="incorrect", rating=1))
        ctx.record_review(_make_review_event(grade="incorrect", rating=1))
        assert ctx.failure_streak() == 2

    def test_recent_reviews(self) -> None:
        ctx = _make_context()
        for i in range(10):
            ctx.record_review(_make_review_event(term=f"term_{i}"))
        recent = ctx.recent_reviews(3)
        assert len(recent) == 3
        assert recent[0].term == "term_7"


# --- Scheduler Agent ---


class TestSchedulerAgent:
    def test_compute_limits_standard(self) -> None:
        agent = SchedulerAgent()
        ctx = _make_context()
        new_limit, review_limit, reasoning = agent._compute_limits(ctx)
        assert new_limit == 10  # Default from settings
        assert review_limit == 20

    def test_compute_limits_low_accuracy(self) -> None:
        agent = SchedulerAgent()
        # Simulate 10 reviews with low accuracy but ending with a correct answer
        # (so failure streak doesn't override the accuracy check)
        reviews = [
            _make_review_event(grade="incorrect", rating=1),
            _make_review_event(grade="correct"),
            _make_review_event(grade="incorrect", rating=1),
            _make_review_event(grade="correct"),
            _make_review_event(grade="incorrect", rating=1),
            _make_review_event(grade="incorrect", rating=1),
            _make_review_event(grade="incorrect", rating=1),
            _make_review_event(grade="incorrect", rating=1),
            _make_review_event(grade="incorrect", rating=1),
            _make_review_event(grade="correct"),  # ends with correct to avoid streak override
        ]
        ctx = _make_context(reviews=reviews)
        new_limit, _, reasoning = agent._compute_limits(ctx)
        assert new_limit < 10
        assert "reducing" in reasoning.lower() or "Accuracy" in reasoning

    def test_compute_limits_failure_streak(self) -> None:
        agent = SchedulerAgent()
        reviews = [_make_review_event(grade="incorrect", rating=1)] * 4
        ctx = _make_context(reviews=reviews)
        new_limit, _, reasoning = agent._compute_limits(ctx)
        assert new_limit == 0
        assert "pausing" in reasoning.lower()

    def test_compute_limits_high_accuracy(self) -> None:
        agent = SchedulerAgent()
        reviews = [_make_review_event(grade="correct")] * 12
        ctx = _make_context(reviews=reviews)
        new_limit, _, reasoning = agent._compute_limits(ctx)
        assert new_limit > 10
        assert "increasing" in reasoning.lower() or "Great" in reasoning

    def test_review_card(self) -> None:
        agent = SchedulerAgent()
        state = agent.fsrs.initial_state(rating=3)
        new_state = agent.review_card(state, rating=3)
        assert new_state.reps == 2
        assert new_state.stability > state.stability


# --- Assessor Agent ---


class TestAssessorAgent:
    def test_assess_mcq_correct(self) -> None:
        agent = AssessorAgent()
        exercise = _make_exercise(exercise_type="mcq", answer="hello")
        ctx = _make_context()
        result = agent.assess("hello", exercise, ctx)
        assert result.assessment.grade == AssessmentGrade.CORRECT
        assert result.error_type is None
        assert result.should_explain is False
        assert result.confidence == 1.0

    def test_assess_mcq_incorrect(self) -> None:
        agent = AssessorAgent()
        exercise = _make_exercise(exercise_type="mcq", answer="hello")
        ctx = _make_context()
        result = agent.assess("goodbye", exercise, ctx)
        assert result.assessment.grade == AssessmentGrade.INCORRECT
        assert result.error_type == "vocabulary"
        assert result.should_explain is True

    def test_assess_exact_match_hindi(self) -> None:
        agent = AssessorAgent()
        exercise = _make_exercise(
            exercise_type="cloze",
            prompt="___ कैसे हो?",
            answer="नमस्ते",
        )
        ctx = _make_context()
        result = agent.assess("नमस्ते", exercise, ctx)
        assert result.assessment.grade == AssessmentGrade.CORRECT

    def test_should_explain_after_streak(self) -> None:
        agent = AssessorAgent()
        exercise = _make_exercise(exercise_type="cloze", answer="नमस्ते")
        reviews = [_make_review_event(grade="incorrect", rating=1)] * 3
        ctx = _make_context(reviews=reviews)
        result = agent.assess("wrong", exercise, ctx)
        assert result.should_explain is True

    def test_no_explain_for_close(self) -> None:
        agent = AssessorAgent()
        exercise = _make_exercise(exercise_type="mcq", answer="hello")
        ctx = _make_context()
        # Correct answer -> no explain
        result = agent.assess("hello", exercise, ctx)
        assert result.should_explain is False


# --- Content Agent ---


class TestContentAgent:
    def test_pick_exercise_type_new_card(self) -> None:
        agent = ContentAgent()
        card = MagicMock()
        card.reps = 0
        card.lapses = 0
        card.stability = 0.5
        ctx = _make_context()
        ex_type, reasoning = agent._pick_exercise_type(card, ctx)
        assert ex_type == "mcq"
        assert "New card" in reasoning

    def test_pick_exercise_type_high_lapses(self) -> None:
        agent = ContentAgent()
        card = MagicMock()
        card.reps = 5
        card.lapses = 4
        card.stability = 2.0
        ctx = _make_context()
        ex_type, reasoning = agent._pick_exercise_type(card, ctx)
        assert ex_type == "mcq"
        assert "lapses" in reasoning

    def test_pick_exercise_type_mature(self) -> None:
        agent = ContentAgent()
        card = MagicMock()
        card.reps = 6
        card.lapses = 0
        card.stability = 15.0
        ctx = _make_context()
        ex_type, reasoning = agent._pick_exercise_type(card, ctx)
        assert ex_type == "cloze"
        assert "Mature" in reasoning

    def test_pick_exercise_type_low_accuracy(self) -> None:
        agent = ContentAgent()
        card = MagicMock()
        card.reps = 5
        card.lapses = 0
        card.stability = 10.0
        reviews = [_make_review_event(grade="correct")] * 2 + [
            _make_review_event(grade="incorrect", rating=1)
        ] * 5
        ctx = _make_context(reviews=reviews)
        ex_type, reasoning = agent._pick_exercise_type(card, ctx)
        assert ex_type == "mcq"
        assert "accuracy" in reasoning.lower()


# --- Tutor Agent ---


class TestTutorAgent:
    def test_determine_depth_first_failure(self) -> None:
        agent = TutorAgent()
        item = _make_content_item()
        ctx = _make_context()
        depth = agent._determine_depth(item, ctx, "typo")
        assert depth == "brief"

    def test_determine_depth_repeated_failure(self) -> None:
        agent = TutorAgent()
        item = _make_content_item()
        reviews = [_make_review_event(grade="incorrect", rating=1)] * 4
        ctx = _make_context(reviews=reviews)
        depth = agent._determine_depth(item, ctx, "vocabulary")
        assert depth == "detailed"

    def test_template_explanation_correct_answer(self) -> None:
        agent = TutorAgent()
        assessment = Assessment(
            grade=AssessmentGrade.INCORRECT,
            suggested_rating=1,
            feedback="Expected: नमस्ते",
            expected="नमस्ते",
            actual="wrong",
        )
        exercise = _make_exercise()
        item = _make_content_item()
        explanation = agent._template_explanation(assessment, exercise, item, "vocabulary")
        assert "नमस्ते" in explanation
        assert "namaste" in explanation

    def test_explain_without_llm(self) -> None:
        agent = TutorAgent()  # No LLM
        assessment = Assessment(
            grade=AssessmentGrade.INCORRECT,
            suggested_rating=1,
            feedback="Expected: नमस्ते",
            expected="नमस्ते",
            actual="wrong",
        )
        exercise = _make_exercise()
        item = _make_content_item()
        ctx = _make_context()
        response = agent.explain(assessment, exercise, item, ctx, error_type="vocabulary")
        assert response.explanation is not None
        assert response.depth in ("brief", "standard", "detailed")
        assert response.mnemonic is None  # No LLM -> no mnemonic

    def test_grammar_note_for_grammar_content(self) -> None:
        agent = TutorAgent()
        item = _make_content_item(
            content_type="grammar",
            context="Subject + object + verb (SOV order)",
        )
        note = agent._grammar_note(item)
        assert note is not None
        assert "SOV" in note

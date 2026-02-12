"""Assessor Agent: evaluates responses with detailed feedback.

Responsibilities:
- Evaluate learner responses using exact match and LLM fuzzy assessment
- Provide detailed, constructive feedback
- Suggest self-ratings based on assessment quality
- Track error patterns for the tutor agent
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agents.base import BaseAgent, LearnerContext
from backend.models.exercise import Exercise
from backend.srs.assessment import (
    Assessment,
    AssessmentGrade,
    assess_exact,
    assess_fuzzy,
    assess_mcq,
)

logger = logging.getLogger(__name__)


@dataclass
class DetailedAssessment:
    """Extended assessment with additional context from the assessor agent."""

    assessment: Assessment
    detailed_feedback: str
    error_type: str | None  # "typo", "grammar", "vocabulary", "meaning", None
    should_explain: bool  # Whether the tutor should provide an explanation
    confidence: float  # How confident the assessor is (0-1)


class AssessorAgent(BaseAgent):
    """Evaluates responses and provides detailed feedback."""

    @property
    def name(self) -> str:
        """Return the agent identifier."""
        return "assessor"

    @property
    def description(self) -> str:
        """Return what this agent does."""
        return "Evaluates learner responses with detailed feedback and error classification"

    def assess(
        self,
        response: str,
        exercise: Exercise,
        ctx: LearnerContext,
    ) -> DetailedAssessment:
        """Assess a learner's response with full context.

        Uses exact match first, then LLM fuzzy assessment if needed.
        Adds error classification and determines if tutoring is warranted.
        """
        # Step 1: Get base assessment
        if exercise.exercise_type == "mcq":
            base = assess_mcq(response, exercise.answer)
        elif self.llm is not None and exercise.exercise_type != "mcq":
            base = assess_fuzzy(response, exercise.answer, exercise.prompt, self.llm)
        else:
            base = assess_exact(response, exercise.answer)

        # Step 2: Classify the error type
        error_type = self._classify_error(base, response, exercise)

        # Step 3: Generate detailed feedback
        detailed_feedback = self._build_detailed_feedback(base, error_type, exercise)

        # Step 4: Determine if explanation is needed
        should_explain = self._should_explain(base, ctx, exercise)

        # Step 5: Assess confidence (clamped to valid range)
        confidence = max(0.0, min(1.0, self._assess_confidence(base, exercise)))

        return DetailedAssessment(
            assessment=base,
            detailed_feedback=detailed_feedback,
            error_type=error_type,
            should_explain=should_explain,
            confidence=confidence,
        )

    def _classify_error(
        self,
        assessment: Assessment,
        response: str,
        exercise: Exercise,
    ) -> str | None:
        """Classify the type of error made."""
        if assessment.grade == AssessmentGrade.CORRECT:
            return None

        if assessment.grade == AssessmentGrade.CLOSE:
            return "typo"

        # For MCQ, it's always a vocabulary/recognition error
        if exercise.exercise_type == "mcq":
            return "vocabulary"

        # For cloze, check if it's a grammar vs vocabulary issue
        if exercise.exercise_type == "cloze":
            # Empty response suggests the learner doesn't know the word (vocabulary)
            # A non-empty but wrong response in a cloze suggests a grammar issue
            if not response.strip():
                return "vocabulary"
            return "grammar"

        return "meaning"

    def _build_detailed_feedback(
        self,
        assessment: Assessment,
        error_type: str | None,
        exercise: Exercise,
    ) -> str:
        """Build human-readable detailed feedback."""
        if assessment.grade == AssessmentGrade.CORRECT:
            return assessment.feedback

        parts = [assessment.feedback]

        if error_type == "typo":
            parts.append(
                "This looks like a small spelling mistake. "
                "Pay attention to the matra marks (vowel signs)."
            )
        elif error_type == "vocabulary":
            parts.append(
                f"The correct answer is: {assessment.expected}. "
                "Try to associate this word with a visual image or situation."
            )
        elif error_type == "grammar":
            parts.append(
                "This seems to be a grammar issue. "
                "Review the pattern being tested in this exercise."
            )
        elif error_type == "meaning":
            parts.append("The meaning doesn't match. Try breaking down the sentence word by word.")

        return " ".join(parts)

    def _should_explain(
        self,
        assessment: Assessment,
        ctx: LearnerContext,
        exercise: Exercise,
    ) -> bool:
        """Determine if the tutor should provide an explanation.

        Trigger explanations when:
        - The answer is incorrect (not just close)
        - The learner has failed the same card multiple times
        - There's a failure streak
        """
        if assessment.grade == AssessmentGrade.CORRECT:
            return False

        if assessment.grade == AssessmentGrade.CLOSE:
            return False  # Typos don't need full explanations

        # Always explain after a failure streak
        if ctx.failure_streak() >= 2:
            return True

        # Explain incorrect answers
        if assessment.grade == AssessmentGrade.INCORRECT:
            return True

        # Explain partial answers for harder exercise types
        return assessment.grade == AssessmentGrade.PARTIAL and exercise.exercise_type != "mcq"

    def _assess_confidence(self, assessment: Assessment, exercise: Exercise) -> float:
        """How confident we are in this assessment (0-1).

        MCQ assessments are always high confidence. Exact match is high.
        Fuzzy LLM assessment is moderate.
        """
        if exercise.exercise_type == "mcq":
            return 1.0

        if assessment.is_exact_match:
            return 1.0

        if assessment.grade == AssessmentGrade.CORRECT:
            return 0.95

        if assessment.grade == AssessmentGrade.CLOSE:
            return 0.8

        # For partial/incorrect, confidence depends on whether LLM was used
        return 0.7

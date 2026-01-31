"""Tests for the SRS engine: FSRS algorithm, assessment, and queue logic."""

from datetime import datetime, timedelta

from backend.srs.assessment import (
    AssessmentGrade,
    assess_exact,
    assess_mcq,
    check_hindi_equivalence,
    normalize_for_comparison,
)
from backend.srs.fsrs import FSRS, CardState
from backend.srs.queue import ReviewQueue


# --- FSRS Algorithm ---


class TestFSRS:
    def setup_method(self) -> None:
        self.fsrs = FSRS(target_retention=0.9)

    def test_initial_state_good(self) -> None:
        state = self.fsrs.initial_state(rating=3)
        assert state.stability > 0
        assert 0 < state.difficulty < 1
        assert state.reps == 1
        assert state.lapses == 0
        assert state.due > datetime.utcnow()

    def test_initial_state_again(self) -> None:
        state = self.fsrs.initial_state(rating=1)
        assert state.reps == 0
        assert state.lapses == 1
        # Stability for "Again" should be lower than "Good"
        good_state = self.fsrs.initial_state(rating=3)
        assert state.stability < good_state.stability

    def test_initial_state_easy(self) -> None:
        state = self.fsrs.initial_state(rating=4)
        assert state.reps == 1
        # Easy should have higher stability than Good
        good_state = self.fsrs.initial_state(rating=3)
        assert state.stability > good_state.stability

    def test_review_good_increases_stability(self) -> None:
        state = self.fsrs.initial_state(rating=3)
        original_stability = state.stability

        # Review again with "Good" after the interval
        result = self.fsrs.review(state, rating=3, review_time=state.due)
        assert result.new_state.stability > original_stability

    def test_review_again_decreases_stability(self) -> None:
        state = self.fsrs.initial_state(rating=3)
        # Do a few successful reviews to build up stability
        for _ in range(3):
            result = self.fsrs.review(state, rating=3, review_time=state.due)
            state = result.new_state

        high_stability = state.stability
        # Now fail
        result = self.fsrs.review(state, rating=1, review_time=state.due)
        assert result.new_state.stability < high_stability
        assert result.new_state.lapses == state.lapses + 1

    def test_review_hard_shorter_interval(self) -> None:
        state = self.fsrs.initial_state(rating=3)
        good_result = self.fsrs.review(state, rating=3, review_time=state.due)
        hard_result = self.fsrs.review(state, rating=2, review_time=state.due)
        # Hard should give a shorter interval than Good
        assert hard_result.interval_days <= good_result.interval_days

    def test_review_easy_longer_interval(self) -> None:
        state = self.fsrs.initial_state(rating=3)
        good_result = self.fsrs.review(state, rating=3, review_time=state.due)
        easy_result = self.fsrs.review(state, rating=4, review_time=state.due)
        # Easy should give a longer interval than Good
        assert easy_result.interval_days >= good_result.interval_days

    def test_interval_minimum_one_day(self) -> None:
        state = self.fsrs.initial_state(rating=1)
        result = self.fsrs.review(state, rating=1)
        assert result.interval_days >= 1.0

    def test_stability_to_interval(self) -> None:
        # At 90% retention, interval should be proportional to stability
        interval = self.fsrs._stability_to_interval(10.0)
        assert interval > 0
        # Higher stability -> longer interval
        interval2 = self.fsrs._stability_to_interval(20.0)
        assert interval2 > interval

    def test_retrievability(self) -> None:
        # At time 0, retrievability should be 1
        r = self.fsrs._retrievability(0, 10.0)
        assert r == 1.0
        # Over time, retrievability decays
        r1 = self.fsrs._retrievability(5, 10.0)
        r2 = self.fsrs._retrievability(10, 10.0)
        assert r1 > r2
        # All values between 0 and 1
        assert 0 < r1 < 1
        assert 0 < r2 < 1

    def test_custom_target_retention(self) -> None:
        fsrs_80 = FSRS(target_retention=0.8)
        fsrs_95 = FSRS(target_retention=0.95)
        # Lower retention target -> longer intervals (more forgetting allowed)
        int_80 = fsrs_80._stability_to_interval(10.0)
        int_95 = fsrs_95._stability_to_interval(10.0)
        assert int_80 > int_95


# --- Assessment ---


class TestAssessment:
    def test_normalize_basic(self) -> None:
        assert normalize_for_comparison("  Hello  ") == "hello"
        assert normalize_for_comparison("Hello!") == "hello"

    def test_normalize_hindi_punctuation(self) -> None:
        assert normalize_for_comparison("नमस्ते।") == "नमस्ते"

    def test_normalize_zero_width(self) -> None:
        assert normalize_for_comparison("न\u200bम\u200cस्ते") == "नमस्ते"

    def test_hindi_equivalence_exact(self) -> None:
        assert check_hindi_equivalence("नमस्ते", "नमस्ते")

    def test_hindi_equivalence_ye_yah(self) -> None:
        assert check_hindi_equivalence("ये", "यह")
        assert check_hindi_equivalence("यह", "ये")

    def test_hindi_equivalence_vo_vah(self) -> None:
        assert check_hindi_equivalence("वो", "वह")

    def test_hindi_equivalence_no_match(self) -> None:
        assert not check_hindi_equivalence("नमस्ते", "धन्यवाद")

    def test_assess_exact_correct(self) -> None:
        result = assess_exact("नमस्ते", "नमस्ते")
        assert result.grade == AssessmentGrade.CORRECT
        assert result.is_exact_match

    def test_assess_exact_with_whitespace(self) -> None:
        result = assess_exact("  नमस्ते  ", "नमस्ते")
        assert result.grade == AssessmentGrade.CORRECT

    def test_assess_exact_incorrect(self) -> None:
        result = assess_exact("धन्यवाद", "नमस्ते")
        assert result.grade == AssessmentGrade.INCORRECT
        assert result.suggested_rating == 1

    def test_assess_mcq_correct(self) -> None:
        result = assess_mcq("hello", "hello")
        assert result.grade == AssessmentGrade.CORRECT
        assert result.suggested_rating == 3  # MCQ correct = Good, not Easy

    def test_assess_mcq_incorrect(self) -> None:
        result = assess_mcq("goodbye", "hello")
        assert result.grade == AssessmentGrade.INCORRECT
        assert result.suggested_rating == 1


# --- Queue ---


class TestReviewQueue:
    def test_interleaved_no_new(self) -> None:
        queue = ReviewQueue(due_cards=["a", "b", "c"], new_cards=[], total=3)
        assert queue.interleaved() == ["a", "b", "c"]

    def test_interleaved_no_due(self) -> None:
        queue = ReviewQueue(due_cards=[], new_cards=["x", "y"], total=2)
        assert queue.interleaved() == ["x", "y"]

    def test_interleaved_mixes(self) -> None:
        queue = ReviewQueue(
            due_cards=["a", "b", "c", "d", "e", "f"],
            new_cards=["x", "y"],
            total=8,
        )
        result = queue.interleaved()
        # All items present
        assert len(result) == 8
        assert set(result) == {"a", "b", "c", "d", "e", "f", "x", "y"}
        # New cards should not all be at the start
        first_three = result[:3]
        assert not all(item in ["x", "y"] for item in first_three)

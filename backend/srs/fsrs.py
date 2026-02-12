"""FSRS (Free Spaced Repetition Scheduler) algorithm implementation.

A simplified implementation of FSRS-4.5 for the Hindi SRS system.
Reference: https://github.com/open-spaced-repetition/fsrs4anki

Key concepts:
- Stability (S): The number of days after which retention drops to the target (90%).
- Difficulty (D): A value between 0 and 1 representing inherent item difficulty.
- Retrievability (R): The probability of recall at a given time since last review.
- Rating: 1=Again, 2=Hard, 3=Good, 4=Easy
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.config import utcnow

# FSRS-4.5 default parameters (can be optimized with user data later)
# w[0..3]: initial stability for ratings Again/Hard/Good/Easy on first review
# w[4]: difficulty mean reversion
# w[5]: difficulty update multiplier
# w[6]: stability decay factor
# w[7..10]: stability factors per rating
# w[11..12]: hard/easy penalty/bonus
DEFAULT_WEIGHTS = [
    0.4,  # w0: initial stability for Again
    0.6,  # w1: initial stability for Hard
    2.4,  # w2: initial stability for Good
    5.8,  # w3: initial stability for Easy
    4.93,  # w4: difficulty mean reversion strength
    0.94,  # w5: difficulty update factor
    0.86,  # w6: stability decay exponent
    0.01,  # w7: stability increase base (fail)
    1.49,  # w8: stability increase factor (success)
    0.14,  # w9: difficulty-stability interaction
    0.94,  # w10: stability-stability interaction (power)
    2.18,  # w11: hard penalty factor
    0.05,  # w12: easy bonus factor
]

# Target retention probability
DEFAULT_TARGET_RETENTION = 0.9

# Bounds
MIN_DIFFICULTY = 0.01
MAX_DIFFICULTY = 0.99
MIN_STABILITY = 0.1  # Minimum 0.1 days (~2.4 hours)


@dataclass
class CardState:
    """The SRS state of a card."""

    stability: float  # Days until retention = target_retention
    difficulty: float  # 0-1, inherent difficulty
    due: datetime  # When the card is next due
    reps: int  # Total successful reviews
    lapses: int  # Times the card was forgotten (rated Again)


@dataclass
class ReviewResult:
    """The result of applying a review to a card."""

    new_state: CardState
    interval_days: float
    retrievability: float  # Estimated recall probability at time of review


class FSRS:
    """Free Spaced Repetition Scheduler."""

    def __init__(
        self,
        weights: list[float] | None = None,
        target_retention: float = DEFAULT_TARGET_RETENTION,
    ) -> None:
        """Initialize FSRS with optional custom weights and target retention."""
        self.w = weights or DEFAULT_WEIGHTS
        self.target_retention = target_retention

    def initial_state(self, rating: int = 3) -> CardState:
        """Create the initial state for a new card after its first review.

        Args:
            rating: The rating from the first review (1-4).

        Returns:
            A new CardState with initial stability and difficulty.
        """
        rating = max(1, min(4, rating))
        stability = self.w[rating - 1]  # w0..w3
        difficulty = self._initial_difficulty(rating)
        interval = self._stability_to_interval(stability)
        due = utcnow() + timedelta(days=interval)

        reps = 0 if rating == 1 else 1
        lapses = 1 if rating == 1 else 0

        return CardState(
            stability=stability,
            difficulty=difficulty,
            due=due,
            reps=reps,
            lapses=lapses,
        )

    def review(
        self,
        state: CardState,
        rating: int,
        review_time: datetime | None = None,
    ) -> ReviewResult:
        """Apply a review rating to update the card state.

        Args:
            state: Current card state.
            rating: Review rating (1=Again, 2=Hard, 3=Good, 4=Easy).
            review_time: When the review happened (defaults to now).

        Returns:
            ReviewResult with the new card state.
        """
        rating = max(1, min(4, rating))
        review_time = review_time or utcnow()

        # Calculate elapsed time and current retrievability
        seconds_since_due = (review_time - state.due).total_seconds()
        interval = self._stability_to_interval(state.stability)
        elapsed_days = max(0, seconds_since_due / 86400 + interval)
        retrievability = self._retrievability(elapsed_days, state.stability)

        # Update difficulty
        new_difficulty = self._update_difficulty(state.difficulty, rating)

        # Update stability
        if rating == 1:
            # Lapse: stability is reset (with some memory from previous)
            new_stability = self._stability_after_fail(state.stability, new_difficulty)
            new_reps = state.reps
            new_lapses = state.lapses + 1
        else:
            # Success: stability increases
            new_stability = self._stability_after_success(
                state.stability, new_difficulty, retrievability, rating
            )
            new_reps = state.reps + 1
            new_lapses = state.lapses

        new_stability = max(MIN_STABILITY, new_stability)

        # Calculate next interval from stability
        interval = self._stability_to_interval(new_stability)

        # Apply hard/easy modifiers to interval
        if rating == 2:  # Hard: shorter interval
            interval *= 0.8
        elif rating == 4:  # Easy: longer interval
            interval *= 1.3

        interval = max(1.0, interval)  # Minimum 1 day
        due = review_time + timedelta(days=interval)

        new_state = CardState(
            stability=new_stability,
            difficulty=new_difficulty,
            due=due,
            reps=new_reps,
            lapses=new_lapses,
        )

        return ReviewResult(
            new_state=new_state,
            interval_days=interval,
            retrievability=retrievability,
        )

    def _initial_difficulty(self, rating: int) -> float:
        """Calculate initial difficulty from first rating."""
        # D0 = w4 - (rating - 3) * w5
        d = self.w[4] - (rating - 3) * self.w[5]
        # Normalize to 0-1 range (w4 is typically ~5, so divide by 10)
        d = d / 10.0
        return max(MIN_DIFFICULTY, min(MAX_DIFFICULTY, d))

    def _update_difficulty(self, current_d: float, rating: int) -> float:
        """Update difficulty based on rating using mean reversion."""
        # Mean reversion: pull difficulty toward initial estimate
        delta = -(rating - 3) * self.w[5] / 10.0
        new_d = current_d + delta
        # Mean reversion toward w4/10
        mean_d = self.w[4] / 10.0
        new_d = mean_d + 0.7 * (new_d - mean_d)  # 70% weight on new, 30% reversion
        return max(MIN_DIFFICULTY, min(MAX_DIFFICULTY, new_d))

    def _retrievability(self, elapsed_days: float, stability: float) -> float:
        """Calculate the probability of recall given elapsed time and stability.

        Uses the power forgetting curve: R = (1 + t/S)^(-1)
        """
        if stability <= 0 or elapsed_days <= 0:
            return 1.0
        return (1 + elapsed_days / (9 * stability)) ** -1

    def _stability_to_interval(self, stability: float) -> float:
        """Convert stability to an interval in days for the target retention.

        Derived from: target_retention = (1 + interval / (9 * stability))^(-1)
        Solving: interval = 9 * stability * (1/target_retention - 1)
        """
        return 9 * stability * (1 / self.target_retention - 1)

    def _stability_after_success(
        self,
        stability: float,
        difficulty: float,
        retrievability: float,
        rating: int,
    ) -> float:
        """Calculate new stability after a successful review (rating >= 2).

        S' = S * (1 + e^(w8) * (11 - D*10) * S^(-w10) * (e^(w9*(1-R)) - 1))
        """
        factor = (
            math.exp(self.w[8])
            * (11 - difficulty * 10)
            * stability ** (-self.w[10])
            * (math.exp(self.w[9] * (1 - retrievability)) - 1)
        )
        return stability * (1 + factor)

    def _stability_after_fail(
        self,
        stability: float,
        difficulty: float,
    ) -> float:
        """Calculate new stability after a lapse (rating = 1).

        S' = w7 * D^(-w6) * ((S+1)^w10 - 1)
        """
        new_s = self.w[7] * difficulty ** (-self.w[6]) * ((stability + 1) ** self.w[10] - 1)
        # Ensure new stability is less than old (forgetting should decrease stability)
        return min(new_s, stability * 0.5)

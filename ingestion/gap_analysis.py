"""Gap analysis: compare learner's vocabulary against standard A1-B1 word lists."""

import json
import logging
from dataclasses import dataclass, field

from ingestion.extractor import ExtractedItem
from ingestion.topics import TOPIC_TAXONOMY

logger = logging.getLogger(__name__)

# Essential topics and approximate word counts expected at each level
EXPECTED_COVERAGE: dict[str, dict[str, int]] = {
    "A1": {
        "greetings": 10,
        "introductions": 10,
        "numbers": 20,
        "colors": 10,
        "family": 15,
        "food_drink": 15,
        "daily_routine": 10,
        "time": 10,
        "body": 10,
    },
    "A2": {
        "greetings": 15,
        "introductions": 15,
        "numbers": 30,
        "colors": 12,
        "family": 20,
        "food_drink": 25,
        "clothing": 15,
        "body": 15,
        "home": 15,
        "school": 15,
        "shopping": 15,
        "weather": 10,
        "directions": 10,
        "travel": 15,
        "daily_routine": 20,
        "time": 15,
        "emotions": 10,
    },
    "B1": {
        "work": 20,
        "health": 15,
        "travel": 25,
        "hobbies": 15,
        "technology": 10,
        "nature": 15,
        "emotions": 20,
        "formal_register": 10,
        "grammar_pattern": 20,
    },
}


@dataclass
class TopicGap:
    """A gap in vocabulary coverage for a specific topic."""

    topic: str
    level: str
    expected_count: int
    actual_count: int
    coverage_pct: float


@dataclass
class GapReport:
    """Full gap analysis report."""

    total_items: int
    level_distribution: dict[str, int] = field(default_factory=dict)
    topic_distribution: dict[str, int] = field(default_factory=dict)
    gaps: list[TopicGap] = field(default_factory=list)
    uncovered_topics: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        """Render the gap report as human-readable text."""
        lines = [
            "=" * 60,
            "GAP ANALYSIS REPORT",
            "=" * 60,
            f"\nTotal content items: {self.total_items}",
            "\n--- CEFR Level Distribution ---",
        ]
        for level in ["A1", "A2", "B1", "B2", "C1", "C2"]:
            count = self.level_distribution.get(level, 0)
            lines.append(f"  {level}: {count} items")

        lines.append("\n--- Topic Coverage ---")
        for topic, count in sorted(self.topic_distribution.items(), key=lambda x: -x[1]):
            lines.append(f"  {topic}: {count} items")

        if self.strengths:
            lines.append("\n--- Strengths (well-covered topics) ---")
            for s in self.strengths:
                lines.append(f"  + {s}")

        if self.gaps:
            lines.append("\n--- Gaps (needs more content) ---")
            for gap in sorted(self.gaps, key=lambda g: g.coverage_pct):
                lines.append(
                    f"  - {gap.topic} ({gap.level}): "
                    f"{gap.actual_count}/{gap.expected_count} "
                    f"({gap.coverage_pct:.0%} coverage)"
                )

        if self.uncovered_topics:
            lines.append("\n--- Missing Topics (0 items) ---")
            for topic in self.uncovered_topics:
                lines.append(f"  ! {topic}")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)

    def to_json(self) -> str:
        """Render the report as JSON."""
        return json.dumps(
            {
                "total_items": self.total_items,
                "level_distribution": self.level_distribution,
                "topic_distribution": self.topic_distribution,
                "gaps": [
                    {
                        "topic": g.topic,
                        "level": g.level,
                        "expected": g.expected_count,
                        "actual": g.actual_count,
                        "coverage_pct": round(g.coverage_pct, 2),
                    }
                    for g in self.gaps
                ],
                "uncovered_topics": self.uncovered_topics,
                "strengths": self.strengths,
            },
            indent=2,
            ensure_ascii=False,
        )


def analyze_gaps(
    items: list[ExtractedItem],
    cefr_levels: dict[str, tuple[str, float]],
    topic_assignments: dict[str, list[str]],
) -> GapReport:
    """Analyze gaps in vocabulary coverage.

    Args:
        items: All extracted content items.
        cefr_levels: Mapping of term -> (CEFR level, confidence).
        topic_assignments: Mapping of term -> list of topic tags.

    Returns:
        A GapReport with detailed coverage analysis.
    """
    report = GapReport(total_items=len(items))

    # Build level distribution
    for item in items:
        level, _ = cefr_levels.get(item.term, ("A2", 0.5))
        report.level_distribution[level] = report.level_distribution.get(level, 0) + 1

    # Build topic distribution
    for item in items:
        topics = topic_assignments.get(item.term, [])
        for topic in topics:
            report.topic_distribution[topic] = report.topic_distribution.get(topic, 0) + 1

    # Find uncovered topics
    covered_topics = set(report.topic_distribution.keys())
    all_topics = set(TOPIC_TAXONOMY)
    report.uncovered_topics = sorted(all_topics - covered_topics)

    # Analyze against expected coverage
    for level, expected_topics in EXPECTED_COVERAGE.items():
        for topic, expected_count in expected_topics.items():
            actual_count = report.topic_distribution.get(topic, 0)
            coverage_pct = actual_count / expected_count if expected_count > 0 else 0.0

            if coverage_pct < 0.5:
                report.gaps.append(
                    TopicGap(
                        topic=topic,
                        level=level,
                        expected_count=expected_count,
                        actual_count=actual_count,
                        coverage_pct=coverage_pct,
                    )
                )
            elif coverage_pct >= 0.8:
                report.strengths.append(f"{topic} ({level}): {actual_count}/{expected_count}")

    logger.info(
        "Gap analysis: %d gaps found, %d strengths, %d uncovered topics",
        len(report.gaps),
        len(report.strengths),
        len(report.uncovered_topics),
    )
    return report

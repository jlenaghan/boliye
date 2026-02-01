"""Ingestion pipeline orchestrator: ties together all ingestion steps."""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from backend.llm_client import LLMClient
from ingestion.cefr import assign_cefr_levels
from ingestion.dedup import deduplicate
from ingestion.exercise_generator import generate_exercises
from ingestion.extractor import ExtractedItem, extract_items
from ingestion.familiarity import assign_familiarity
from ingestion.file_handlers import RawDocument, read_directory, read_file
from ingestion.gap_analysis import GapReport, analyze_gaps
from ingestion.topics import assign_topics

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result of running the full ingestion pipeline."""

    documents_read: int = 0
    items_extracted: int = 0
    items_after_dedup: int = 0
    exercises_generated: int = 0
    gap_report: GapReport | None = None
    items: list[ExtractedItem] = field(default_factory=list)
    cefr_levels: dict[str, tuple[str, float]] = field(default_factory=dict)
    topic_assignments: dict[str, list[str]] = field(default_factory=dict)
    exercises: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def run_pipeline(
    source: Path,
    llm: LLMClient,
    skip_exercises: bool = False,
    skip_gap_analysis: bool = False,
    exercise_types: list[str] | None = None,
) -> PipelineResult:
    """Run the full ingestion pipeline on a file or directory.

    Steps:
    1. Read source files
    2. Extract structured items via LLM
    3. Deduplicate
    4. Infer familiarity
    5. Assign CEFR levels via LLM
    6. Assign topics via LLM
    7. Generate exercises via LLM (optional)
    8. Run gap analysis (optional)

    Args:
        source: Path to a file or directory of source materials.
        llm: Configured LLM client.
        skip_exercises: If True, skip exercise generation.
        skip_gap_analysis: If True, skip gap analysis.
        exercise_types: Which exercise types to generate (default: mcq + cloze).

    Returns:
        PipelineResult with all extracted and enriched data.
    """
    result = PipelineResult()

    # Step 1: Read source files
    logger.info("Step 1: Reading source files from %s", source)
    documents: list[RawDocument] = []
    if source.is_dir():
        documents = read_directory(source)
    elif source.is_file():
        documents = [read_file(source)]
    else:
        result.errors.append(f"Source path does not exist: {source}")
        return result

    result.documents_read = len(documents)
    if not documents:
        result.errors.append("No readable documents found")
        return result
    logger.info("Read %d documents", len(documents))

    # Step 2: Extract structured items
    logger.info("Step 2: Extracting structured items via LLM")
    all_items: list[ExtractedItem] = []
    for doc in documents:
        try:
            items = extract_items(doc.content, doc.source_path, doc.file_type, llm)
            all_items.extend(items)
        except Exception as e:
            msg = f"Failed to extract from {doc.source_path}: {e}"
            logger.error(msg)
            result.errors.append(msg)

    result.items_extracted = len(all_items)
    logger.info("Extracted %d total items", len(all_items))

    # Step 3: Deduplicate
    logger.info("Step 3: Deduplicating items")
    deduped = deduplicate(all_items)
    result.items_after_dedup = len(deduped)

    # Step 4: Infer familiarity
    logger.info("Step 4: Inferring familiarity levels")
    familiarity_groups = assign_familiarity(deduped)
    # Store familiarity back on items for convenience
    for level, group_items in familiarity_groups.items():
        for item in group_items:
            item.familiarity_signals = [level]  # Overwrite with resolved level

    # Step 5: Assign CEFR levels
    logger.info("Step 5: Assigning CEFR levels via LLM")
    try:
        cefr_levels = assign_cefr_levels(deduped, llm)
        result.cefr_levels = cefr_levels
    except Exception as e:
        msg = f"CEFR assignment failed: {e}"
        logger.error(msg)
        result.errors.append(msg)
        cefr_levels = {}

    # Step 6: Assign topics
    logger.info("Step 6: Assigning topics via LLM")
    try:
        topic_assignments = assign_topics(deduped, llm)
        result.topic_assignments = topic_assignments
    except Exception as e:
        msg = f"Topic assignment failed: {e}"
        logger.error(msg)
        result.errors.append(msg)
        topic_assignments = {}

    result.items = deduped

    # Step 7: Generate exercises (optional)
    if not skip_exercises:
        logger.info("Step 7: Generating exercises via LLM")
        try:
            exercises = generate_exercises(deduped, llm, exercise_types=exercise_types)
            result.exercises = exercises
            result.exercises_generated = len(exercises)
        except Exception as e:
            msg = f"Exercise generation failed: {e}"
            logger.error(msg)
            result.errors.append(msg)
    else:
        logger.info("Step 7: Skipping exercise generation")

    # Step 8: Gap analysis (optional)
    if not skip_gap_analysis:
        logger.info("Step 8: Running gap analysis")
        try:
            result.gap_report = analyze_gaps(deduped, cefr_levels, topic_assignments)
        except Exception as e:
            msg = f"Gap analysis failed: {e}"
            logger.error(msg)
            result.errors.append(msg)
    else:
        logger.info("Step 8: Skipping gap analysis")

    # Summary
    cost = llm.get_cost_estimate()
    logger.info(
        "Pipeline complete: %d docs -> %d items -> %d deduped -> %d exercises | Cost: $%.4f",
        result.documents_read,
        result.items_extracted,
        result.items_after_dedup,
        result.exercises_generated,
        cost["estimated_cost_usd"],
    )
    if result.errors:
        logger.warning("Pipeline completed with %d errors", len(result.errors))

    return result


def save_results(result: PipelineResult, output_dir: Path) -> None:
    """Save pipeline results to JSON files for inspection and later DB import."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save extracted items
    items_data = [
        {
            "term": item.term,
            "definition": item.definition,
            "romanization": item.romanization,
            "context": item.context,
            "content_type": item.content_type,
            "source_file": item.source_file,
            "familiarity": item.familiarity_signals[0] if item.familiarity_signals else "unknown",
            "cefr_level": result.cefr_levels.get(item.term, ("", 0.0))[0],
            "cefr_confidence": result.cefr_levels.get(item.term, ("", 0.0))[1],
            "topics": result.topic_assignments.get(item.term, []),
        }
        for item in result.items
    ]
    items_path = output_dir / "content_items.json"
    items_path.write_text(json.dumps(items_data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved %d items to %s", len(items_data), items_path)

    # Save exercises
    if result.exercises:
        exercises_path = output_dir / "exercises.json"
        exercises_path.write_text(
            json.dumps(result.exercises, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("Saved %d exercises to %s", len(result.exercises), exercises_path)

    # Save gap report
    if result.gap_report:
        report_path = output_dir / "gap_report.txt"
        report_path.write_text(result.gap_report.to_text(), encoding="utf-8")
        report_json_path = output_dir / "gap_report.json"
        report_json_path.write_text(result.gap_report.to_json(), encoding="utf-8")
        logger.info("Saved gap report to %s", report_path)

    # Save summary
    summary = {
        "documents_read": result.documents_read,
        "items_extracted": result.items_extracted,
        "items_after_dedup": result.items_after_dedup,
        "exercises_generated": result.exercises_generated,
        "errors": result.errors,
    }
    summary_path = output_dir / "ingestion_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("Saved summary to %s", summary_path)

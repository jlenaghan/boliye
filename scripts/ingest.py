"""CLI script to run the ingestion pipeline.

Usage:
    python -m scripts.ingest ~/hindi-corpus/
    python -m scripts.ingest notes.txt --skip-exercises
    python -m scripts.ingest ~/hindi-corpus/ --output ./data/processed
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.llm_client import LLMClient
from ingestion.pipeline import run_pipeline, save_results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest Hindi learning materials into the SRS system",
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Path to a file or directory of source materials",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed"),
        help="Output directory for processed results (default: data/processed)",
    )
    parser.add_argument(
        "--skip-exercises",
        action="store_true",
        help="Skip exercise generation (faster, cheaper)",
    )
    parser.add_argument(
        "--skip-gap-analysis",
        action="store_true",
        help="Skip gap analysis",
    )
    parser.add_argument(
        "--exercise-types",
        nargs="+",
        choices=["mcq", "cloze"],
        default=None,
        help="Which exercise types to generate (default: both)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Validate source
    source = args.source.resolve()
    if not source.exists():
        print(f"Error: Source path does not exist: {source}", file=sys.stderr)
        sys.exit(1)

    print(f"Source: {source}")
    print(f"Output: {args.output.resolve()}")
    print()

    # Initialize LLM client
    llm = LLMClient()

    # Run pipeline
    result = run_pipeline(
        source=source,
        llm=llm,
        skip_exercises=args.skip_exercises,
        skip_gap_analysis=args.skip_gap_analysis,
        exercise_types=args.exercise_types,
    )

    # Save results
    save_results(result, args.output.resolve())

    # Print summary
    print()
    print("=" * 50)
    print("INGESTION COMPLETE")
    print("=" * 50)
    print(f"Documents read:    {result.documents_read}")
    print(f"Items extracted:   {result.items_extracted}")
    print(f"After dedup:       {result.items_after_dedup}")
    print(f"Exercises created: {result.exercises_generated}")
    if result.errors:
        print(f"\nWarnings/Errors ({len(result.errors)}):")
        for err in result.errors:
            print(f"  - {err}")

    # Print gap report summary if available
    if result.gap_report:
        print()
        print(result.gap_report.to_text())

    # Print cost estimate
    cost = llm.get_cost_estimate()
    print(f"\nLLM cost estimate: ${cost['estimated_cost_usd']:.4f}")
    print(f"  Input tokens:  {cost['input_tokens']:,}")
    print(f"  Output tokens: {cost['output_tokens']:,}")


if __name__ == "__main__":
    main()

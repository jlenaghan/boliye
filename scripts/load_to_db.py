"""Load processed ingestion results into the database.

Usage:
    python -m scripts.load_to_db data/processed/content_items.json
    python -m scripts.load_to_db data/processed/content_items.json --exercises data/processed/exercises.json
    python -m scripts.load_to_db data/processed/content_items.json --exercises data/processed/exercises.json --learner-id 1
"""

import argparse
import asyncio
import json
import logging
from pathlib import Path

from sqlalchemy import select

from backend.config import settings, utcnow
from backend.database import async_session, engine
from backend.models import Base
from backend.models.card import Card
from backend.models.content_item import ContentItem
from backend.models.exercise import Exercise
from backend.models.learner import Learner


async def load_content_items(items_path: Path) -> dict[str, int]:
    """Load content items from JSON into the database.

    Returns a mapping of term -> content_item_id for linking exercises.
    """
    data = json.loads(items_path.read_text(encoding="utf-8"))
    term_to_id: dict[str, int] = {}

    async with async_session() as session:
        for entry in data:
            # Check if already exists
            stmt = select(ContentItem).where(ContentItem.term == entry["term"])
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing:
                logging.info("Skipping duplicate: %s", entry["term"])
                term_to_id[entry["term"]] = existing.id
                continue

            item = ContentItem(
                term=entry["term"],
                definition=entry["definition"],
                romanization=entry.get("romanization", ""),
                context=entry.get("context"),
                content_type=entry.get("content_type", "vocab"),
                cefr_level=entry.get("cefr_level"),
                cefr_confidence=entry.get("cefr_confidence"),
                topics=json.dumps(entry.get("topics", []), ensure_ascii=False),
                source_file=entry.get("source_file"),
                familiarity=entry.get("familiarity", "unknown"),
            )
            session.add(item)
            await session.flush()
            term_to_id[entry["term"]] = item.id

        await session.commit()

    logging.info("Loaded %d content items", len(term_to_id))
    return term_to_id


async def load_exercises(exercises_path: Path, term_to_id: dict[str, int]) -> int:
    """Load exercises from JSON into the database, linked to content items."""
    data = json.loads(exercises_path.read_text(encoding="utf-8"))
    loaded = 0

    async with async_session() as session:
        for entry in data:
            term = entry.get("term", "")
            content_item_id = term_to_id.get(term)
            if not content_item_id:
                logging.warning("No content item found for exercise term: %s", term)
                continue

            exercise = Exercise(
                content_item_id=content_item_id,
                exercise_type=entry.get("exercise_type", "mcq"),
                prompt=entry["prompt"],
                answer=entry["answer"],
                options=entry.get("options"),
                status="generated",
                generation_model=settings.anthropic_model,
                prompt_version="v1",
            )
            session.add(exercise)
            loaded += 1

        await session.commit()

    logging.info("Loaded %d exercises", loaded)
    return loaded


async def create_cards(learner_id: int, term_to_id: dict[str, int]) -> int:
    """Create review cards linking a learner to loaded content items.

    Skips cards that already exist for this learner, making it safe to re-run.
    Returns the number of cards created.
    """
    async with async_session() as session:
        # Verify the learner exists
        learner = (
            await session.execute(select(Learner).where(Learner.id == learner_id))
        ).scalar_one_or_none()
        if not learner:
            logging.error("Learner with id=%d not found", learner_id)
            raise SystemExit(1)

        # Find which content items already have cards for this learner
        existing_stmt = select(Card.content_item_id).where(Card.learner_id == learner_id)
        existing_ids = set((await session.execute(existing_stmt)).scalars().all())

        created = 0
        now = utcnow()
        for content_item_id in term_to_id.values():
            if content_item_id in existing_ids:
                continue
            session.add(
                Card(
                    learner_id=learner_id,
                    content_item_id=content_item_id,
                    stability=0.5,
                    difficulty=0.3,
                    due=now,
                    reps=0,
                    lapses=0,
                )
            )
            created += 1

        await session.commit()

    logging.info(
        "Created %d cards for learner %d (%d already existed)",
        created,
        learner_id,
        len(existing_ids),
    )
    return created


async def main_async(args: argparse.Namespace) -> None:
    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Load content items
    term_to_id = await load_content_items(args.items)

    # Load exercises if provided
    if args.exercises:
        await load_exercises(args.exercises, term_to_id)

    # Create cards if learner-id provided
    if args.learner_id is not None:
        created = await create_cards(args.learner_id, term_to_id)
        print(f"Created {created} cards for learner {args.learner_id}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Load ingestion results into the database")
    parser.add_argument(
        "items",
        type=Path,
        help="Path to content_items.json from ingestion pipeline",
    )
    parser.add_argument(
        "--exercises",
        type=Path,
        default=None,
        help="Path to exercises.json (optional)",
    )
    parser.add_argument(
        "--learner-id",
        type=int,
        default=None,
        help="Create review cards for this learner ID (run 'hindi-srs stats' first to create the default learner)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    asyncio.run(main_async(args))
    print("Done.")


if __name__ == "__main__":
    main()

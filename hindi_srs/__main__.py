"""CLI interface for Hindi SRS.

Usage:
    python -m hindi_srs review              Start a review session
    python -m hindi_srs stats               Show your statistics
    python -m hindi_srs add "term" "def"    Add a new content item
    python -m hindi_srs due                 Show how many cards are due
    python -m hindi_srs render "नमस्ते"     Render Devanagari text cleanly
"""

import argparse
import asyncio
import contextlib
import json
import logging
import time

from sqlalchemy import and_, func, select

from backend.config import settings, utcnow
from backend.database import async_session, engine
from backend.models import Base
from backend.models.card import Card
from backend.models.content_item import ContentItem
from backend.models.exercise import Exercise
from backend.models.learner import Learner
from backend.models.review_log import ReviewLog
from backend.srs.assessment import assess_exact, assess_mcq
from backend.srs.fsrs import FSRS, CardState
from hindi_srs.devanagari_renderer import is_devanagari, render_card_display, render_if_devanagari


async def ensure_db() -> None:
    """Create tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def ensure_learner() -> int:
    """Ensure there's a default learner and return the ID."""
    async with async_session() as db:
        stmt = select(Learner).limit(1)
        result = await db.execute(stmt)
        learner = result.scalar_one_or_none()
        if learner:
            return learner.id

        learner = Learner(name="Jonathan", current_level="A1")
        db.add(learner)
        await db.commit()
        await db.refresh(learner)
        return learner.id


async def cmd_review(args: argparse.Namespace) -> None:
    """Run an interactive review session."""
    await ensure_db()
    learner_id = await ensure_learner()
    fsrs = FSRS(target_retention=settings.target_retention)
    max_cards = args.max_cards
    now = utcnow()

    async with async_session() as db:
        # Get due cards
        due_stmt = (
            select(Card)
            .where(and_(Card.learner_id == learner_id, Card.reps > 0, Card.due <= now))
            .order_by(Card.due.asc())
            .limit(max_cards)
        )
        due_result = await db.execute(due_stmt)
        due_cards = list(due_result.scalars().all())

        # Get new cards
        new_limit = min(args.new_cards, max_cards - len(due_cards))
        new_stmt = (
            select(Card)
            .where(and_(Card.learner_id == learner_id, Card.reps == 0, Card.lapses == 0))
            .limit(max(0, new_limit))
        )
        new_result = await db.execute(new_stmt)
        new_cards = list(new_result.scalars().all())

        all_cards = due_cards + new_cards

        if not all_cards:
            print("\nNo cards due for review. You're all caught up!")
            return

        print("\n  Review Session")
        print(f"  {len(due_cards)} due + {len(new_cards)} new = {len(all_cards)} cards\n")
        print("  Ratings: 1=Again  2=Hard  3=Good  4=Easy")
        print("  Type 'q' to quit\n")

        correct = 0
        reviewed = 0

        for i, card in enumerate(all_cards, 1):
            # Load content item and exercise
            content_stmt = select(ContentItem).where(ContentItem.id == card.content_item_id)
            content_result = await db.execute(content_stmt)
            content_item = content_result.scalar_one_or_none()
            if not content_item:
                continue

            ex_stmt = (
                select(Exercise).where(Exercise.content_item_id == card.content_item_id).limit(1)
            )
            ex_result = await db.execute(ex_stmt)
            exercise = ex_result.scalar_one_or_none()
            if not exercise:
                continue

            # Display the exercise
            card_label = f"  [{i}/{len(all_cards)}]"
            if card.reps == 0:
                card_label += " (NEW)"
            print(card_label)

            # Render Devanagari prompts using the font renderer for clean display.
            if is_devanagari(exercise.prompt):
                print(render_if_devanagari(exercise.prompt))
            else:
                print(f"  {exercise.prompt}")

            if exercise.exercise_type == "mcq":
                options = []
                if exercise.options:
                    with contextlib.suppress(json.JSONDecodeError):
                        options = json.loads(exercise.options)
                for j, opt in enumerate(options, 1):
                    if is_devanagari(opt):
                        print(f"    {j}.")
                        print(render_if_devanagari(opt, indent="      "))
                    else:
                        print(f"    {j}. {opt}")

            # Get response
            start_time = time.time()
            response = input("\n  Your answer: ").strip()
            time_ms = int((time.time() - start_time) * 1000)

            if response.lower() == "q":
                print("\n  Session ended early.")
                break

            # Handle MCQ numeric input
            if exercise.exercise_type == "mcq" and response.isdigit():
                idx = int(response) - 1
                options = []
                if exercise.options:
                    with contextlib.suppress(json.JSONDecodeError):
                        options = json.loads(exercise.options)
                if 0 <= idx < len(options):
                    response = options[idx]

            # Assess
            if exercise.exercise_type == "mcq":
                assessment = assess_mcq(response, exercise.answer)
            else:
                assessment = assess_exact(response, exercise.answer)

            # Display result
            if assessment.grade.value == "correct":
                print("  Correct!")
                correct += 1
            else:
                print(f"  {assessment.feedback}")
                print()
                print(
                    render_card_display(
                        content_item.term,
                        romanization=content_item.romanization or "",
                        definition=content_item.definition or "",
                    )
                )

            # Get rating (use suggested or ask)
            rating = assessment.suggested_rating
            rate_input = input(f"  Rate [1-4, enter={rating}]: ").strip()
            if rate_input.isdigit() and 1 <= int(rate_input) <= 4:
                rating = int(rate_input)

            # Apply FSRS update
            state = CardState(
                stability=card.stability,
                difficulty=card.difficulty,
                due=card.due,
                reps=card.reps,
                lapses=card.lapses,
            )
            result = fsrs.review(state, rating)

            card.stability = result.new_state.stability
            card.difficulty = result.new_state.difficulty
            card.due = result.new_state.due
            card.reps = result.new_state.reps
            card.lapses = result.new_state.lapses

            # Log review
            log = ReviewLog(
                card_id=card.id,
                learner_id=learner_id,
                exercise_type=exercise.exercise_type,
                rating=rating,
                time_ms=time_ms,
                stability_before=state.stability,
                stability_after=result.new_state.stability,
                difficulty_before=state.difficulty,
                difficulty_after=result.new_state.difficulty,
            )
            db.add(log)
            await db.commit()
            reviewed += 1
            print(f"  Next review in {result.interval_days:.1f} days\n")

    # Summary
    accuracy = correct / reviewed * 100 if reviewed else 0
    print("\n  Session Complete!")
    print(f"  Reviewed: {reviewed}  Correct: {correct}  Accuracy: {accuracy:.0f}%\n")


async def cmd_stats(args: argparse.Namespace) -> None:
    """Show learner statistics."""
    await ensure_db()
    learner_id = await ensure_learner()
    now = utcnow()

    async with async_session() as db:
        # Total cards
        total = (
            await db.execute(select(func.count(Card.id)).where(Card.learner_id == learner_id))
        ).scalar() or 0

        # Due cards
        due = (
            await db.execute(
                select(func.count(Card.id)).where(
                    and_(Card.learner_id == learner_id, Card.reps > 0, Card.due <= now)
                )
            )
        ).scalar() or 0

        # New cards
        new = (
            await db.execute(
                select(func.count(Card.id)).where(
                    and_(Card.learner_id == learner_id, Card.reps == 0, Card.lapses == 0)
                )
            )
        ).scalar() or 0

        # Total reviews
        reviews = (
            await db.execute(
                select(func.count(ReviewLog.id)).where(ReviewLog.learner_id == learner_id)
            )
        ).scalar() or 0

        # Mature cards
        mature = (
            await db.execute(
                select(func.count(Card.id)).where(
                    and_(Card.learner_id == learner_id, Card.reps >= 5)
                )
            )
        ).scalar() or 0

    print("\n  Hindi SRS Statistics")
    print(f"  {'Total cards:':<20} {total}")
    print(f"  {'Due now:':<20} {due}")
    print(f"  {'New (unseen):':<20} {new}")
    print(f"  {'Mature (5+ reps):':<20} {mature}")
    print(f"  {'Total reviews:':<20} {reviews}")
    print()


async def cmd_add(args: argparse.Namespace) -> None:
    """Add a new content item and card."""
    await ensure_db()
    learner_id = await ensure_learner()

    async with async_session() as db:
        # Check for duplicate
        existing = (
            await db.execute(select(ContentItem).where(ContentItem.term == args.term))
        ).scalar_one_or_none()

        if existing:
            print(f"  '{args.term}' already exists (id={existing.id}).")
            return

        # Create content item
        item = ContentItem(
            term=args.term,
            definition=args.definition,
            romanization=args.romanization or "",
            content_type="vocab",
            source_file="cli",
            familiarity="unknown",
        )
        db.add(item)
        await db.flush()

        # Create card
        card = Card(
            learner_id=learner_id,
            content_item_id=item.id,
            stability=0.5,
            difficulty=0.3,
            due=utcnow(),
            reps=0,
            lapses=0,
        )
        db.add(card)
        await db.commit()

        print("  Added (card ready for review):")
        print(
            render_card_display(
                args.term,
                romanization=args.romanization or "",
                definition=args.definition,
            )
        )


async def cmd_due(args: argparse.Namespace) -> None:
    """Show how many cards are due."""
    await ensure_db()
    learner_id = await ensure_learner()
    now = utcnow()

    async with async_session() as db:
        due = (
            await db.execute(
                select(func.count(Card.id)).where(
                    and_(Card.learner_id == learner_id, Card.reps > 0, Card.due <= now)
                )
            )
        ).scalar() or 0

        new = (
            await db.execute(
                select(func.count(Card.id)).where(
                    and_(Card.learner_id == learner_id, Card.reps == 0, Card.lapses == 0)
                )
            )
        ).scalar() or 0

    print(f"  {due} cards due, {new} new cards available")


def cmd_render(args: argparse.Namespace) -> None:
    """Render Devanagari text in the terminal (sync, no DB needed)."""
    print()
    print(render_if_devanagari(args.text, font_size=args.font_size))
    print()


def main() -> None:
    """Entry point for the Hindi SRS CLI application."""
    parser = argparse.ArgumentParser(
        prog="hindi_srs",
        description="Hindi SRS Language Learning System",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # review
    review_parser = subparsers.add_parser("review", help="Start a review session")
    review_parser.add_argument("--max-cards", type=int, default=20, help="Max cards per session")
    review_parser.add_argument("--new-cards", type=int, default=10, help="Max new cards")

    # stats
    subparsers.add_parser("stats", help="Show your statistics")

    # add
    add_parser = subparsers.add_parser("add", help="Add a new content item")
    add_parser.add_argument("term", help="Hindi term (Devanagari)")
    add_parser.add_argument("definition", help="English definition")
    add_parser.add_argument("-r", "--romanization", default="", help="Romanization")

    # due
    subparsers.add_parser("due", help="Show cards due for review")

    # render
    render_parser = subparsers.add_parser("render", help="Render Devanagari text in the terminal")
    render_parser.add_argument("text", help="Devanagari text to render")
    render_parser.add_argument(
        "-s", "--font-size", type=int, default=22, help="Font size in points (default: 22)"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    if not args.command:
        parser.print_help()
        return

    # render is synchronous, all others are async.
    if args.command == "render":
        cmd_render(args)
        return

    cmd_map = {
        "review": cmd_review,
        "stats": cmd_stats,
        "add": cmd_add,
        "due": cmd_due,
    }

    asyncio.run(cmd_map[args.command](args))


if __name__ == "__main__":
    main()

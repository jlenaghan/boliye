"""Tests for CLI commands (non-interactive paths)."""


import pytest

from hindi_srs.__main__ import ensure_db, ensure_learner


@pytest.mark.asyncio
async def test_ensure_db() -> None:
    """Database tables can be created."""
    await ensure_db()


@pytest.mark.asyncio
async def test_ensure_learner() -> None:
    """Default learner is created on first call."""
    await ensure_db()
    learner_id = await ensure_learner()
    assert learner_id >= 1

    # Second call returns same ID
    learner_id2 = await ensure_learner()
    assert learner_id2 == learner_id

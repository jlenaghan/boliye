from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from sqlalchemy import text

from backend.api.session_router import router as session_router
from backend.api.stats_router import router as stats_router
from backend.database import async_session, engine
from backend.models import Base


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Create tables on startup (for development; use Alembic in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="Hindi SRS",
    description="Spaced repetition language learning system for Hindi",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(session_router)
app.include_router(stats_router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    async with async_session() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok"}

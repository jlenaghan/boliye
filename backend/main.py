"""FastAPI application entry point and configuration."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from backend.api.session_router import router as session_router
from backend.api.stats_router import router as stats_router
from backend.database import async_session, engine
from backend.models import Base


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize database on startup and cleanup on shutdown."""
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(session_router)
app.include_router(stats_router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Check database connectivity and return status."""
    async with async_session() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok"}


# Serve built frontend if it exists (must be last — catch-all mount)
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/app", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

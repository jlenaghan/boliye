from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


class ReviewLog(Base):
    __tablename__ = "review_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id"), nullable=False)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"), nullable=False)
    exercise_type: Mapped[str] = mapped_column(String(50), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # 1=Again, 2=Hard, 3=Good, 4=Easy
    time_ms: Mapped[int] = mapped_column(Integer, nullable=False)  # Response time in ms
    stability_before: Mapped[float] = mapped_column(Float, nullable=False)
    stability_after: Mapped[float] = mapped_column(Float, nullable=False)
    difficulty_before: Mapped[float] = mapped_column(Float, nullable=False)
    difficulty_after: Mapped[float] = mapped_column(Float, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(UTC))

    card: Mapped["Card"] = relationship(back_populates="review_logs")  # type: ignore[name-defined] # noqa: F821
    learner: Mapped["Learner"] = relationship(back_populates="review_logs")  # type: ignore[name-defined] # noqa: F821

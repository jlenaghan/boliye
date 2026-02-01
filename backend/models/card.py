from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, TimestampMixin


class Card(Base, TimestampMixin):
    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"), nullable=False)
    content_item_id: Mapped[int] = mapped_column(ForeignKey("content_items.id"), nullable=False)
    stability: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    difficulty: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    due: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    reps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lapses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    learner: Mapped["Learner"] = relationship(back_populates="cards")  # type: ignore[name-defined] # noqa: F821
    content_item: Mapped["ContentItem"] = relationship(back_populates="cards")  # type: ignore[name-defined] # noqa: F821
    review_logs: Mapped[list["ReviewLog"]] = relationship(back_populates="card")  # type: ignore[name-defined] # noqa: F821

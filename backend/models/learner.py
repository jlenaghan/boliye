from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, TimestampMixin


class Learner(Base, TimestampMixin):
    __tablename__ = "learners"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    current_level: Mapped[str | None] = mapped_column(String(10), nullable=True)  # CEFR: A1-C2
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    cards: Mapped[list["Card"]] = relationship(back_populates="learner")  # type: ignore[name-defined] # noqa: F821
    review_logs: Mapped[list["ReviewLog"]] = relationship(back_populates="learner")  # type: ignore[name-defined] # noqa: F821

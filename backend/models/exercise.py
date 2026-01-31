from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, TimestampMixin


class Exercise(Base, TimestampMixin):
    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    content_item_id: Mapped[int] = mapped_column(ForeignKey("content_items.id"), nullable=False)
    exercise_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # mcq, cloze, translation
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON for MCQ options
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="generated"
    )  # generated, approved, rejected
    generation_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)

    content_item: Mapped["ContentItem"] = relationship(back_populates="exercises")  # type: ignore[name-defined] # noqa: F821

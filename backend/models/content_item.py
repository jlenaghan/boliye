from sqlalchemy import Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, TimestampMixin


class ContentItem(Base, TimestampMixin):
    __tablename__ = "content_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    term: Mapped[str] = mapped_column(String(500), nullable=False)  # Hindi text
    definition: Mapped[str] = mapped_column(String(500), nullable=False)  # English translation
    romanization: Mapped[str | None] = mapped_column(String(500), nullable=True)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)  # Example sentence or usage
    content_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="vocab"
    )  # vocab, phrase, grammar
    cefr_level: Mapped[str | None] = mapped_column(String(10), nullable=True)  # A1-C2
    cefr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    topics: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array of topic tags
    source_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    familiarity: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unknown"
    )  # unknown, seen, known
    audio_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    exercises: Mapped[list["Exercise"]] = relationship(back_populates="content_item")  # type: ignore[name-defined] # noqa: F821
    cards: Mapped[list["Card"]] = relationship(back_populates="content_item")  # type: ignore[name-defined] # noqa: F821

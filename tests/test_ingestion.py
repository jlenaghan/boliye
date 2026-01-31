"""Tests for ingestion pipeline components."""

import json
import tempfile
from pathlib import Path

from ingestion.dedup import deduplicate, normalize_hindi
from ingestion.extractor import ExtractedItem, _parse_response, _split_into_chunks
from ingestion.familiarity import assign_familiarity, infer_familiarity
from ingestion.file_handlers import read_csv_file, read_file, read_text_file
from ingestion.gap_analysis import analyze_gaps


def _make_item(
    term: str = "नमस्ते",
    definition: str = "hello",
    romanization: str = "namaste",
    context: str | None = None,
    content_type: str = "vocab",
    familiarity_signals: list[str] | None = None,
    source_file: str = "test.txt",
) -> ExtractedItem:
    return ExtractedItem(
        term=term,
        definition=definition,
        romanization=romanization,
        context=context,
        content_type=content_type,
        familiarity_signals=familiarity_signals or [],
        source_file=source_file,
    )


# --- File handlers ---


class TestFileHandlers:
    def test_read_text_file(self, tmp_path: Path) -> None:
        f = tmp_path / "notes.txt"
        f.write_text("नमस्ते - hello\nधन्यवाद - thank you", encoding="utf-8")
        doc = read_text_file(f)
        assert doc.file_type == "txt"
        assert "नमस्ते" in doc.content
        assert doc.source_path == str(f)

    def test_read_csv_file(self, tmp_path: Path) -> None:
        f = tmp_path / "vocab.csv"
        f.write_text("hindi,english\nनमस्ते,hello\nधन्यवाद,thank you", encoding="utf-8")
        doc = read_csv_file(f)
        assert doc.file_type == "csv"
        data = json.loads(doc.content)
        assert len(data) == 2
        assert data[0]["hindi"] == "नमस्ते"

    def test_read_file_dispatches(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_text("# Hindi Notes\nनमस्ते", encoding="utf-8")
        doc = read_file(f)
        assert doc.file_type == "md"

    def test_read_file_unsupported(self, tmp_path: Path) -> None:
        f = tmp_path / "audio.mp3"
        f.write_bytes(b"fake audio")
        try:
            read_file(f)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Unsupported" in str(e)


# --- Extractor ---


class TestExtractor:
    def test_parse_response_valid(self) -> None:
        response = json.dumps(
            [
                {
                    "term": "नमस्ते",
                    "definition": "hello",
                    "romanization": "namaste",
                    "context": "greeting",
                    "content_type": "vocab",
                    "familiarity_signals": ["known"],
                }
            ]
        )
        items = _parse_response(response, "test.txt")
        assert len(items) == 1
        assert items[0].term == "नमस्ते"
        assert items[0].definition == "hello"

    def test_parse_response_with_code_fences(self) -> None:
        response = '```json\n[{"term": "हाँ", "definition": "yes"}]\n```'
        items = _parse_response(response, "test.txt")
        assert len(items) == 1
        assert items[0].term == "हाँ"

    def test_parse_response_invalid_json(self) -> None:
        items = _parse_response("not json at all", "test.txt")
        assert items == []

    def test_split_into_chunks_small(self) -> None:
        chunks = _split_into_chunks("small text", max_chars=100)
        assert len(chunks) == 1

    def test_split_into_chunks_large(self) -> None:
        text = "\n\n".join(f"Paragraph {i}: " + "x" * 100 for i in range(20))
        chunks = _split_into_chunks(text, max_chars=500)
        assert len(chunks) > 1
        # All content should be preserved
        rejoined = "\n\n".join(chunks)
        assert "Paragraph 0" in rejoined
        assert "Paragraph 19" in rejoined


# --- Deduplication ---


class TestDedup:
    def test_normalize_hindi(self) -> None:
        # Basic normalization
        assert normalize_hindi("  नमस्ते  ") == "नमस्ते"
        # Zero-width characters stripped
        assert normalize_hindi("न\u200bम\u200cस्ते") == "नमस्ते"

    def test_deduplicate_no_dupes(self) -> None:
        items = [_make_item(term="नमस्ते"), _make_item(term="धन्यवाद", definition="thank you")]
        result = deduplicate(items)
        assert len(result) == 2

    def test_deduplicate_merges(self) -> None:
        items = [
            _make_item(term="नमस्ते", definition="hello"),
            _make_item(term="नमस्ते", definition="hello/greetings", context="Used as a greeting"),
        ]
        result = deduplicate(items)
        assert len(result) == 1
        # Should keep the richer version (with context)
        assert result[0].context is not None


# --- Familiarity ---


class TestFamiliarity:
    def test_unknown_default(self) -> None:
        item = _make_item(familiarity_signals=[])
        assert infer_familiarity(item) == "unknown"

    def test_known_signals(self) -> None:
        item = _make_item(familiarity_signals=["✓", "known"])
        assert infer_familiarity(item) == "known"

    def test_seen_signals(self) -> None:
        item = _make_item(familiarity_signals=["~", "review"])
        assert infer_familiarity(item) == "seen"

    def test_assign_familiarity_groups(self) -> None:
        items = [
            _make_item(term="a", familiarity_signals=["✓"]),
            _make_item(term="b", familiarity_signals=["?"]),
            _make_item(term="c", familiarity_signals=[]),
        ]
        groups = assign_familiarity(items)
        assert len(groups["known"]) == 1
        assert len(groups["unknown"]) == 2  # "?" and empty both -> unknown


# --- Gap analysis ---


class TestGapAnalysis:
    def test_analyze_gaps_empty(self) -> None:
        report = analyze_gaps([], {}, {})
        assert report.total_items == 0
        assert len(report.uncovered_topics) > 0

    def test_analyze_gaps_with_items(self) -> None:
        items = [
            _make_item(term="नमस्ते"),
            _make_item(term="धन्यवाद", definition="thank you"),
        ]
        cefr = {"नमस्ते": ("A1", 0.9), "धन्यवाद": ("A1", 0.8)}
        topics = {"नमस्ते": ["greetings"], "धन्यवाद": ["greetings"]}
        report = analyze_gaps(items, cefr, topics)
        assert report.total_items == 2
        assert report.level_distribution.get("A1") == 2
        assert report.topic_distribution.get("greetings") == 2

    def test_gap_report_to_text(self) -> None:
        report = analyze_gaps([], {}, {})
        text = report.to_text()
        assert "GAP ANALYSIS REPORT" in text
        assert "Missing Topics" in text

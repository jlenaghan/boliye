"""Extract Hindi vocabulary items from raw PDF text dump.

Parses the Learn Hindi on the Go course materials to extract
structured vocabulary items (term, definition, romanization, context).
"""

import json
import re
import unicodedata
from pathlib import Path

RAW_TEXT_PATH = Path("data/processed/raw_text_dump.json")
OUTPUT_PATH = Path("data/processed/extracted_items.json")

# Regex for Devanagari script (including common marks/signs)
DEVANAGARI_RE = re.compile(r"[\u0900-\u097F\u0980-\u09FF]+")
# A Hindi "word or phrase" chunk: Devanagari chars plus spaces between them
HINDI_CHUNK_RE = re.compile(
    r"[\u0900-\u097F][\u0900-\u097F\s\u0900-\u097F\.\,\!\?।]*[\u0900-\u097F।\?\!]"
)

# Pattern: "romanization means 'definition'"
MEANS_PATTERN = re.compile(
    r"([a-zA-Zāīūéñṛḍṭōśṣṇñ\s\-]+?)\s+means?\s+['\"](.+?)['\"]",
    re.IGNORECASE,
)

# Pattern: "'english' is translated as – romanization Devanagari"
TRANSLATED_AS_PATTERN = re.compile(
    r"['\"]?(.+?)['\"]?\s+(?:is\s+)?translated\s+as\s*[–\-]?\s*(.+)",
    re.IGNORECASE,
)

# Pattern for numbered idioms: "1. Hindi\n romanization\n Literal Translation: ...\n Meaning: ..."
IDIOM_BLOCK_RE = re.compile(
    r"(\d+)\.\s*([\u0900-\u097F][^\n]+)\n\s*([a-zA-Zāīūéñṛḍṭōśṣṇ][^\n]+)\n"
    r"\s*Literal\s+Translation:\s*([^\n]+)\n"
    r"\s*Meaning:\s*([^\n]+)",
    re.MULTILINE,
)

# Bold pattern from PDF: "romanization Devanagari" on its own line followed by translation
BOLD_VOCAB_RE = re.compile(
    r"([a-zA-Zāīūéñṛḍṭōśṣṇñ][a-zA-Zāīūéñṛḍṭōśṣṇñ\s\-']+?)\s+"
    r"([\u0900-\u097F][\u0900-\u097F\s]*[\u0900-\u097F])\s+"
    r"(?:I'll repeat\s+.+?\s+)?means?\s+['\"](.+?)['\"]",
    re.IGNORECASE,
)


def classify_level(filename: str) -> tuple[str, float]:
    """Infer CEFR level from filename."""
    fn = filename.lower()
    if any(x in fn for x in ["foundation", "f1.", "efd", "fodw", "pdfw", "pdiw"]):
        return "A2", 0.8
    if any(x in fn for x in ["intermediate", "ic1.", "iew", "iodw"]):
        return "B1", 0.8
    if any(x in fn for x in ["advanced", "ahlw"]):
        return "B2", 0.7
    if any(x in fn for x in ["bollywood", "lyrics", "song"]):
        return "B1", 0.6
    if any(x in fn for x in ["insider tale", "aaiit"]):
        return "B2", 0.6
    if "hindipod101" in fn or fn == "hindi.pdf":
        return "B1", 0.6
    return "A2", 0.5


def classify_topics(filename: str, definition: str) -> list[str]:
    """Infer topics from filename and definition."""
    fn = filename.lower()
    defn = definition.lower()
    topics = []

    topic_keywords = {
        "greetings": ["greeting", "hello", "namaste", "goodbye"],
        "time": ["time", "o'clock", "hour", "bajé", "baje", "when do"],
        "weather": ["weather", "rain", "snow", "humid", "cloudy", "sunny", "wind", "storm"],
        "travel": ["taxi", "train", "airport", "boarding", "bus", "travel", "trip"],
        "shopping": ["shop", "buy", "gift", "price", "costly", "cheap", "market"],
        "food_drink": [
            "breakfast",
            "dinner",
            "coffee",
            "beer",
            "restaurant",
            "samosa",
            "food",
            "eat",
            "drink",
            "lunch",
        ],
        "daily_routine": ["routine", "morning", "office", "leave", "reach", "ready", "wake"],
        "work": ["office", "work", "meeting", "schedule", "boss", "job", "studio", "finish work"],
        "family": ["sister", "brother", "mother", "father", "parent", "family"],
        "emotions": ["emotion", "love", "angry", "happy", "sad", "feel", "afraid"],
        "directions": ["behind", "center", "direction", "way", "shorter", "between"],
        "grammar_pattern": [
            "verb",
            "tense",
            "present simple",
            "past",
            "future",
            "subjunctive",
            "comparative",
            "superlative",
            "plural",
            "adjective",
            "postposition",
        ],
        "idiom": ["idiom", "proverb", "saying", "literal translation"],
        "religion_culture": ["culture", "india", "bollywood", "diwali"],
        "numbers": ["number", "count"],
        "home": ["house", "home", "door", "room", "bed"],
        "health": ["health", "smoking", "doctor"],
        "animals": ["animal", "dog", "bird"],
        "nature": ["nature", "tree", "sky", "mountain"],
        "hobbies": ["film", "movie", "tennis", "play", "song", "music", "yoga"],
    }

    combined = fn + " " + defn
    for topic, keywords in topic_keywords.items():
        if any(kw in combined for kw in keywords):
            topics.append(topic)

    return topics[:3] if topics else ["daily_routine"]


def normalize_hindi(text: str) -> str:
    """NFC normalize Hindi text and strip whitespace."""
    return unicodedata.normalize("NFC", text.strip())


def extract_from_idiom_pdf(text: str, filename: str) -> list[dict]:
    """Extract idioms from HindiPod101-style PDFs."""
    items = []
    for match in IDIOM_BLOCK_RE.finditer(text):
        hindi = normalize_hindi(match.group(2).strip())
        roman = match.group(3).strip().rstrip(".")
        literal = match.group(4).strip()
        meaning = match.group(5).strip()

        items.append(
            {
                "term": hindi,
                "definition": meaning,
                "romanization": roman,
                "context": f"Literal: {literal}",
                "content_type": "phrase",
                "source_file": filename,
            }
        )
    return items


def extract_means_patterns(text: str, filename: str) -> list[dict]:
    """Extract 'X means Y' patterns from course transcripts."""
    items = []
    lines = text.split("\n")

    for i, line in enumerate(lines):
        # Look for "romanization Devanagari means 'definition'" pattern
        for m in BOLD_VOCAB_RE.finditer(line):
            roman = m.group(1).strip()
            hindi = normalize_hindi(m.group(2))
            defn = m.group(3).strip().rstrip(".")

            if len(hindi) < 2:
                continue

            # Try to find context from nearby lines
            context = ""
            for j in range(max(0, i - 3), min(len(lines), i + 4)):
                if j != i and HINDI_CHUNK_RE.search(lines[j]) and len(lines[j]) > 20:
                    context = lines[j].strip()
                    break

            items.append(
                {
                    "term": hindi,
                    "definition": defn,
                    "romanization": roman,
                    "context": context,
                    "content_type": "vocab" if " " not in hindi else "phrase",
                    "source_file": filename,
                }
            )

    return items


def extract_translated_as(text: str, filename: str) -> list[dict]:
    """Extract 'X is translated as Y' patterns."""
    items = []
    lines = text.split("\n")

    for i, line in enumerate(lines):
        m = TRANSLATED_AS_PATTERN.search(line)
        if not m:
            continue

        english = m.group(1).strip().strip("'\"–- ")
        rest = m.group(2).strip()

        # Find Hindi text in the rest of the line or next lines
        hindi_match = HINDI_CHUNK_RE.search(rest)
        if not hindi_match and i + 1 < len(lines):
            # Check next line
            hindi_match = HINDI_CHUNK_RE.search(lines[i + 1])

        if not hindi_match:
            continue

        hindi = normalize_hindi(hindi_match.group(0))
        if len(hindi) < 2 or len(english) < 2:
            continue

        # Find romanization (text before the Hindi in the rest)
        roman = ""
        hindi_pos = rest.find(hindi_match.group(0))
        if hindi_pos > 0:
            roman = rest[:hindi_pos].strip().rstrip("–- ")

        items.append(
            {
                "term": hindi,
                "definition": english,
                "romanization": roman,
                "context": "",
                "content_type": "phrase" if " " in hindi else "vocab",
                "source_file": filename,
            }
        )

    return items


def extract_vocabulary_table(text: str, filename: str) -> list[dict]:
    """Extract vocabulary from worksheet-style tables.

    Pattern: Hindi text on one line, romanization on next, English on next.
    """
    items = []
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    for i in range(len(lines) - 1):
        line = lines[i]
        # Check if this line is primarily Hindi
        hindi_chars = sum(1 for c in line if "\u0900" <= c <= "\u097f")
        total_chars = len(line.replace(" ", ""))

        if total_chars > 0 and hindi_chars / total_chars > 0.6 and len(line) > 2:
            hindi = normalize_hindi(line)

            # Next line might be romanization
            roman = ""
            defn = ""
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                next_hindi = sum(1 for c in next_line if "\u0900" <= c <= "\u097f")
                if next_hindi == 0 and len(next_line) > 2:
                    # This is likely romanization or English
                    if any(c in next_line for c in "āīūéñṛ") or next_line[0].islower():
                        roman = next_line.strip()
                        # Check line after for English
                        if i + 2 < len(lines):
                            defn = lines[i + 2].strip()
                    else:
                        defn = next_line.strip()

            # Only add if we got a definition
            if defn and len(defn) > 2 and not defn.startswith("http"):
                items.append(
                    {
                        "term": hindi,
                        "definition": defn,
                        "romanization": roman,
                        "context": "",
                        "content_type": "phrase" if " " in hindi else "vocab",
                        "source_file": filename,
                    }
                )

    return items


def clean_item(item: dict) -> dict | None:
    """Clean up an extracted item. Returns None if item should be discarded."""
    term = item.get("term", "").strip()
    defn = item.get("definition", "").strip()
    roman = item.get("romanization", "").strip()

    # Remove leading bullets, numbers, "Example:", "•", "S:", "R:" prefixes
    term = re.sub(r"^[\s•\-\*]+", "", term)
    term = re.sub(r"^(Example\s*:\s*)", "", term, flags=re.IGNORECASE)
    term = re.sub(r"^(\d+[\.\)]\s*)", "", term)
    term = normalize_hindi(term)

    # Clean definition: remove "S:", "R:", numbered prefixes, "Here,"
    defn = re.sub(r"^\d+\.\s*[SR]\s*:\s*", "", defn)
    defn = re.sub(r"^[SR]\s*:\s*", "", defn)
    defn = re.sub(r"^Here,?\s*", "", defn, flags=re.IGNORECASE)
    defn = re.sub(r"^And\s+", "", defn, flags=re.IGNORECASE)
    defn = re.sub(r"^So,?\s*", "", defn, flags=re.IGNORECASE)
    defn = defn.strip().strip("'\"–- ")

    # Clean romanization: remove "I'll repeat" and trailing junk
    roman = re.sub(r"I'll repeat.*", "", roman, flags=re.IGNORECASE).strip()
    roman = re.sub(r"^['\"\-–\s]+", "", roman)
    roman = roman.strip().rstrip(".")

    # Discard items that are too short or garbage
    if len(term) < 2:
        return None
    if not defn or len(defn) < 2:
        return None

    # Discard if term is mostly non-Devanagari
    hindi_chars = sum(1 for c in term if "\u0900" <= c <= "\u097f")
    if hindi_chars < 1:
        return None

    # Discard boilerplate
    boilerplate = [
        "hindipod101",
        "click here",
        "free lifetime",
        "patreon",
        "innovative language",
        "the fastest",
        "download",
    ]
    if any(bp in defn.lower() for bp in boilerplate):
        return None
    if any(bp in term.lower() for bp in boilerplate):
        return None

    # Discard if definition is just a number or too short
    if defn.isdigit() or len(defn) < 3:
        return None

    # Discard if definition is a meta-instruction rather than a translation
    meta_phrases = [
        "translated as",
        "translated into",
        "shall we do the role play",
        "the line is translated",
        "these lines are translated",
        "i'll repeat",
        "i'll say it again",
        "listener",
        "shall we give",
        "here we go",
        "ready?",
        "let's do",
        "once again",
        "changed r",
        "हिन्दी में अनुवाद",
        "अनुवाद कीजिए",
    ]
    if any(mp in defn.lower() for mp in meta_phrases):
        return None

    # Discard instruction terms
    term_lower = term.lower()
    if "अनुवाद" in term and "कीजिए" in term:
        return None

    # Clean definition: remove leading quotes
    defn = defn.strip("'\"")

    item["term"] = term
    item["definition"] = defn
    item["romanization"] = roman
    return item


def deduplicate(items: list[dict]) -> list[dict]:
    """Deduplicate by normalized Hindi term, keeping richest entry."""
    groups: dict[str, list[dict]] = {}
    for item in items:
        key = normalize_hindi(item["term"])
        groups.setdefault(key, []).append(item)

    deduped = []
    for key, group in groups.items():
        # Score each entry
        def score(item):
            s = len(item.get("definition", ""))
            s += len(item.get("context", "")) * 2
            s += 5 if item.get("romanization") else 0
            return s

        best = max(group, key=score)
        deduped.append(best)

    return deduped


def main():
    with open(RAW_TEXT_PATH, encoding="utf-8") as f:
        raw_data: dict[str, str] = json.load(f)

    print(f"Processing {len(raw_data)} files...")

    all_items = []

    for filename, text in raw_data.items():
        # Try all extraction strategies
        items = []

        # Strategy 1: Idiom blocks
        idiom_items = extract_from_idiom_pdf(text, filename)
        items.extend(idiom_items)

        # Strategy 2: "means" patterns
        means_items = extract_means_patterns(text, filename)
        items.extend(means_items)

        # Strategy 3: "translated as" patterns
        trans_items = extract_translated_as(text, filename)
        items.extend(trans_items)

        # Strategy 4: Table/structured vocab
        if len(items) < 3:
            table_items = extract_vocabulary_table(text, filename)
            items.extend(table_items)

        all_items.extend(items)

    print(f"Extracted {len(all_items)} items before cleanup")

    # Clean items
    cleaned = []
    for item in all_items:
        c = clean_item(item)
        if c is not None:
            cleaned.append(c)
    print(f"After cleanup: {len(cleaned)} items")

    # Deduplicate
    deduped = deduplicate(cleaned)
    print(f"After dedup: {len(deduped)} items")

    # Enrich with CEFR levels and topics
    for item in deduped:
        level, confidence = classify_level(item["source_file"])
        item["cefr_level"] = level
        item["cefr_confidence"] = confidence
        item["topics"] = classify_topics(item["source_file"], item.get("definition", ""))
        item["familiarity"] = "unknown"

    # Save
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(deduped)} items to {OUTPUT_PATH}")

    # Print stats
    by_level = {}
    by_type = {}
    for item in deduped:
        by_level[item["cefr_level"]] = by_level.get(item["cefr_level"], 0) + 1
        by_type[item["content_type"]] = by_type.get(item["content_type"], 0) + 1

    print("\nBy CEFR level:")
    for level in sorted(by_level):
        print(f"  {level}: {by_level[level]}")
    print("\nBy content type:")
    for ct in sorted(by_type):
        print(f"  {ct}: {by_type[ct]}")


if __name__ == "__main__":
    main()

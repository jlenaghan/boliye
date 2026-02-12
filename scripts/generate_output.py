#!/usr/bin/env python3
"""Generate content_items.json and exercises.json from clean Hindi corpus files.

Processes markdown and PDF files from ~/hindi-corpus, skipping corrupted PDFs,
and generates properly-encoded Devanagari output.
"""

import json
import random
import re

# Add project to path
import sys
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.file_handlers import SUPPORTED_EXTENSIONS, read_file

DEVANAGARI_RANGE = range(0x0900, 0x0980)
REPLACEMENT_CHAR = '\ufffd'
CORPUS_DIR = Path.home() / "hindi-corpus"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "processed"


@dataclass
class ContentItem:
    term: str
    definition: str
    romanization: str = ""
    context: str = ""
    content_type: str = "phrase"
    source_file: str = ""
    cefr_level: str = "A2"
    cefr_confidence: float = 0.7
    topics: str = "[]"
    familiarity: str = "unknown"


def has_devanagari(text: str) -> bool:
    return any(ord(c) in DEVANAGARI_RANGE for c in text)


def clean_text(text: str) -> str:
    text = re.sub(r'[_*#]+', '', text)
    text = ' '.join(text.split())
    return unicodedata.normalize('NFC', text).strip()


def infer_cefr(text: str) -> tuple[str, float]:
    words = text.split()
    if len(words) <= 3:
        return "A1", 0.8
    elif len(words) <= 6:
        return "A2", 0.7
    elif len(words) <= 12:
        return "B1", 0.6
    return "B2", 0.5


def infer_topics(hindi: str, english: str) -> list[str]:
    text = (hindi + " " + english).lower()
    topic_keywords = {
        "greetings": ["hello", "goodbye", "namaste", "नमस्ते", "अलविदा"],
        "food_drink": ["food", "eat", "drink", "खाना", "पानी", "भूख", "pizza"],
        "family": ["mother", "father", "brother", "माँ", "पिता", "भाई"],
        "travel": ["go", "come", "car", "train", "जाना", "आना", "गाड़ी"],
        "daily_routine": ["morning", "night", "time", "सुबह", "रात", "समय"],
        "work": ["work", "office", "meeting", "काम", "दफ्तर"],
        "emotions": ["happy", "sad", "angry", "खुश", "गुस्सा", "proud"],
        "weather": ["weather", "rain", "cold", "मौसम", "बारिश"],
        "questions": ["what", "where", "when", "क्या", "कहाँ", "कब"],
    }
    topics = [t for t, kws in topic_keywords.items() if any(k in text for k in kws)]
    return topics[:3] if topics else ["general"]


def parse_markdown(content: str, source_file: str) -> list[ContentItem]:
    items = []
    lines = content.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        if not line or line in ['-', '--'] or (line.startswith('#') and not has_devanagari(line)):
            i += 1
            continue

        # Pattern 1: "- Hindi" with indented romanization/definition
        if line.startswith('- ') and has_devanagari(line):
            hindi = clean_text(line[2:])
            romanization, definition = "", ""
            j = i + 1
            while j < len(lines) and lines[j].startswith('    '):
                subline = lines[j].strip()
                if subline.startswith('__') and '__' in subline[2:]:
                    romanization = re.sub(r'__([^_]+)__', r'\1', subline).strip()
                elif subline.startswith('- ') and not has_devanagari(subline):
                    definition = clean_text(subline[2:])
                elif not has_devanagari(subline) and not romanization:
                    romanization = subline.lstrip('- ')
                j += 1

            if hindi and definition:
                cefr, conf = infer_cefr(hindi)
                items.append(ContentItem(
                    term=hindi, definition=definition, romanization=romanization,
                    content_type="phrase" if len(hindi.split()) > 2 else "vocab",
                    source_file=source_file, cefr_level=cefr, cefr_confidence=conf,
                    topics=json.dumps(infer_topics(hindi, definition))
                ))
            i = j
            continue

        # Pattern 2: "Hindi // English"
        if '//' in line and has_devanagari(line):
            parts = line.split('//')
            if len(parts) >= 2:
                hindi = clean_text(parts[0].lstrip('- '))
                definition = clean_text(parts[1])
                if hindi and definition:
                    cefr, conf = infer_cefr(hindi)
                    items.append(ContentItem(
                        term=hindi, definition=definition,
                        content_type="phrase" if len(hindi.split()) > 2 else "vocab",
                        source_file=source_file, cefr_level=cefr, cefr_confidence=conf,
                        topics=json.dumps(infer_topics(hindi, definition))
                    ))
            i += 1
            continue

        # Pattern 3: "### Hindi" followed by English
        if line.startswith('### ') and has_devanagari(line):
            hindi = clean_text(line[4:])
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line and not has_devanagari(next_line) and not next_line.startswith('#'):
                    definition = clean_text(next_line.lstrip('- '))
                    cefr, conf = infer_cefr(hindi)
                    items.append(ContentItem(
                        term=hindi, definition=definition,
                        content_type="phrase" if len(hindi.split()) > 2 else "vocab",
                        source_file=source_file, cefr_level=cefr, cefr_confidence=conf,
                        topics=json.dumps(infer_topics(hindi, definition))
                    ))
                    i += 2
                    continue

        # Pattern 4: "Hindi" followed by "- English"
        if line.startswith('- ') and has_devanagari(line) and i + 1 < len(lines):
            hindi = clean_text(line[2:])
            next_line = lines[i + 1].strip()
            if next_line.startswith('- ') and not has_devanagari(next_line):
                definition = clean_text(next_line[2:])
                cefr, conf = infer_cefr(hindi)
                items.append(ContentItem(
                    term=hindi, definition=definition,
                    content_type="phrase" if len(hindi.split()) > 2 else "vocab",
                    source_file=source_file, cefr_level=cefr, cefr_confidence=conf,
                    topics=json.dumps(infer_topics(hindi, definition))
                ))
                i += 2
                continue

        i += 1

    return items


def parse_pdf(content: str, source_file: str) -> list[ContentItem]:
    items = []
    if content.count(REPLACEMENT_CHAR) > 10:
        return []

    for sep in [' - ', ' – ', ' = ', ': ']:
        for line in content.split('\n'):
            line = line.strip()
            if REPLACEMENT_CHAR in line or sep not in line:
                continue
            if not has_devanagari(line):
                continue

            parts = line.split(sep, 1)
            if len(parts) != 2:
                continue

            hindi_count_0 = sum(1 for c in parts[0] if ord(c) in DEVANAGARI_RANGE)
            hindi_count_1 = sum(1 for c in parts[1] if ord(c) in DEVANAGARI_RANGE)

            if hindi_count_0 > hindi_count_1 and hindi_count_1 < 2:
                hindi, english = parts[0].strip(), parts[1].strip()
            elif hindi_count_1 > hindi_count_0 and hindi_count_0 < 2:
                english, hindi = parts[0].strip(), parts[1].strip()
            else:
                continue

            if len(hindi) > 2 and len(english) > 2 and len(english) < 200:
                cefr, conf = infer_cefr(hindi)
                items.append(ContentItem(
                    term=clean_text(hindi), definition=clean_text(english),
                    content_type="phrase" if len(hindi.split()) > 2 else "vocab",
                    source_file=source_file, cefr_level=cefr, cefr_confidence=conf,
                    topics=json.dumps(infer_topics(hindi, english))
                ))

    return items


def process_corpus() -> list[ContentItem]:
    all_items = []

    for ext in SUPPORTED_EXTENSIONS:
        for filepath in sorted(CORPUS_DIR.rglob(f'*{ext}')):
            if filepath.is_dir():
                continue
            try:
                doc = read_file(filepath)
                if doc.content.count(REPLACEMENT_CHAR) > 10:
                    print(f"Skip corrupted: {filepath.name}")
                    continue

                if ext in ['.md', '.txt']:
                    items = parse_markdown(doc.content, filepath.name)
                else:
                    items = parse_pdf(doc.content, filepath.name)

                if items:
                    print(f"  {len(items):3d} items: {filepath.name[:50]}")
                    all_items.extend(items)
            except Exception as e:
                print(f"Error {filepath.name}: {e}")

    return all_items


def deduplicate(items: list[ContentItem]) -> list[ContentItem]:
    seen = {}
    for item in items:
        key = unicodedata.normalize('NFC', item.term.lower().strip())
        if key not in seen or len(item.definition) > len(seen[key].definition):
            seen[key] = item
    return list(seen.values())


def generate_exercises(items: list[ContentItem]) -> list[dict]:
    exercises = []
    all_defs = [i.definition for i in items if i.definition]

    for item in items:
        if not item.definition:
            continue

        wrong = [d for d in all_defs if d != item.definition]
        if len(wrong) >= 3:
            options = [item.definition] + random.sample(wrong, 3)
            random.shuffle(options)
            exercises.append({
                "term": item.term, "exercise_type": "mcq",
                "prompt": f"What is the meaning of: {item.term}?",
                "answer": item.definition, "options": options,
                "status": "generated", "generation_model": "local",
                "prompt_version": "v1"
            })

        words = item.term.split()
        if len(words) >= 3:
            idx = random.randint(1, len(words) - 2)
            cloze = ' '.join(words[:idx] + ['___'] + words[idx+1:])
            exercises.append({
                "term": item.term, "exercise_type": "cloze",
                "prompt": f"Fill in the blank: {cloze}",
                "answer": words[idx], "options": [],
                "status": "generated", "generation_model": "local",
                "prompt_version": "v1"
            })

    return exercises


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Processing Hindi corpus...")
    items = process_corpus()
    print(f"\nTotal: {len(items)} items")

    items = deduplicate(items)
    print(f"After dedup: {len(items)} items")

    # Save content items
    with open(OUTPUT_DIR / "content_items.json", 'w', encoding='utf-8') as f:
        json.dump([asdict(i) for i in items], f, ensure_ascii=False, indent=2)
    print("Saved content_items.json")

    # Generate exercises
    exercises = generate_exercises(items)
    with open(OUTPUT_DIR / "exercises.json", 'w', encoding='utf-8') as f:
        json.dump(exercises, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(exercises)} exercises")

    print("\n=== Sample items ===")
    for item in items[:5]:
        print(f"  {item.term}")
        print(f"    → {item.definition}")


if __name__ == "__main__":
    main()

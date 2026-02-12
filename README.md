# Boliye

Spaced repetition language learning system for Hindi, powered by LLM-generated exercises and an agent-based adaptive tutoring architecture.

Boliye ingests your existing Hindi notes (messy or structured), extracts vocabulary and phrases, generates exercises, assigns CEFR levels, and schedules reviews using the FSRS-4.5 spaced repetition algorithm. An LLM-powered agent system provides assessment, tutoring feedback, and session adaptation.

## Prerequisites

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/) (used for content ingestion, exercise generation, and fuzzy assessment)

## Installation

```bash
# Clone the repository
git clone https://github.com/jlenaghan/boliye.git
cd boliye

# Install the package and dependencies
pip install -e .

# Install dev dependencies (for tests, linting, type checking)
pip install -e ".[dev]"
```

This installs three CLI entry points:

| Command | Purpose |
|---------|---------|
| `hindi-srs` | Main CLI for daily review, stats, and adding items |
| `hindi-srs-ingest` | Run the ingestion pipeline on source materials |
| `hindi-srs-load` | Load processed JSON into the database |

## Configuration

All settings are configured via environment variables prefixed with `HINDI_SRS_` or through a `.env` file in the project root.

```bash
# Required
HINDI_SRS_ANTHROPIC_API_KEY=sk-ant-...

# Optional (shown with defaults)
HINDI_SRS_ANTHROPIC_MODEL=claude-sonnet-4-20250514
HINDI_SRS_TARGET_RETENTION=0.9
HINDI_SRS_MAX_NEW_CARDS_PER_SESSION=10
HINDI_SRS_MAX_REVIEWS_PER_SESSION=20
HINDI_SRS_DEBUG=false
```

Create a `.env` file:

```bash
echo 'HINDI_SRS_ANTHROPIC_API_KEY=sk-ant-your-key-here' > .env
```

The SQLite database is stored at `data/hindi_srs.db` and is created automatically on first use.

---

## CLI Reference

All commands can be run as `hindi-srs <command>` (if installed) or `python -m hindi_srs <command>`.

### `review` — Start a review session

```bash
hindi-srs review [--max-cards N] [--new-cards N]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--max-cards` | 20 | Maximum total cards in the session |
| `--new-cards` | 10 | Maximum new (unseen) cards to introduce |

Presents due cards and new cards in an interleaved order. For each card you see an exercise (multiple choice, cloze, or translation), provide your answer, then rate your recall from 1-4:

- **1 (Again)** — Failed, will see again soon
- **2 (Hard)** — Got it but struggled
- **3 (Good)** — Correct, normal pace
- **4 (Easy)** — Knew it instantly

Type `q` at any prompt to end the session early. A summary with accuracy percentage is shown at the end.

### `stats` — View your statistics

```bash
hindi-srs stats
```

Displays: total cards, cards due now, new (unseen) cards, mature cards (5+ successful reviews), and total lifetime reviews.

### `due` — Quick due-card check

```bash
hindi-srs due
```

One-line output showing how many cards are due and how many new cards are available.

### `add` — Add a single content item

```bash
hindi-srs add <term> <definition> [-r ROMANIZATION]
```

| Argument | Required | Description |
|----------|----------|-------------|
| `term` | Yes | Hindi term in Devanagari script |
| `definition` | Yes | English translation |
| `-r`, `--romanization` | No | Romanized pronunciation |

Creates a content item and a review card immediately ready for your next session. Skips duplicates if the term already exists.

Examples:

```bash
hindi-srs add "नमस्ते" "hello" -r "namaste"
hindi-srs add "धन्यवाद" "thank you" -r "dhanyavaad"
hindi-srs add "मुझे हिंदी सीखनी है" "I want to learn Hindi"
```

### Global flags

| Flag | Description |
|------|-------------|
| `-v`, `--verbose` | Enable debug logging |

---

## Running the Web UI

Boliye includes a FastAPI backend that serves the review API and can host a frontend.

### Start the API server

```bash
uvicorn backend.main:app --reload
```

The server runs at `http://localhost:8000` with:

- **API docs:** `http://localhost:8000/docs` (Swagger UI)
- **Health check:** `GET /health`

### API endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/session/start?learner_id=1` | Start a review session |
| `GET` | `/api/session/next/{session_id}` | Get the next exercise |
| `POST` | `/api/session/answer/{session_id}` | Submit an answer |
| `GET` | `/api/session/stats/{session_id}` | Session statistics |
| `POST` | `/api/session/end/{session_id}` | End session and clean up |
| `GET` | `/api/stats/{learner_id}` | Overall learner statistics |

### Frontend

If a built frontend exists at `frontend/dist/`, the server serves it at `/app`. CORS is enabled for `localhost:5173` (Vite) and `localhost:3000` for local frontend development.

---

## Cold-Start: Bootstrapping from Existing Notes

The cold-start workflow transforms your existing Hindi learning materials into a working review deck. This is how you establish your baseline — the system infers which words you already know, which you've seen, and which are new to you.

### Step 1: Organize your materials

Create a directory with your Hindi notes. Supported formats:

| Format | Description |
|--------|-------------|
| `.txt`, `.md` | Plain text notes, vocabulary lists |
| `.csv` | Structured vocabulary (columns: hindi, english, romanization, notes) |
| `.json` | Structured exports from other apps |
| `.docx` | Google Docs or Word exports |
| `.pdf` | PDF files with extractable text (not scanned) |

```bash
mkdir -p ~/hindi-corpus
# Copy your notes, vocab lists, etc. into this directory
```

**Familiarity signals:** The ingestion pipeline detects annotations in your notes that indicate how well you know each term. Mark items in your source materials using:

| Signal | Meaning | Effect on scheduling |
|--------|---------|---------------------|
| `✓` `✔` `✅` `known` `mastered` | You know this well | Longer initial interval |
| `~` `seen` `learning` `ok` `review` | You've encountered this | Medium initial interval |
| `?` `??` `unknown` `new` `hard` | New or difficult | Short initial interval |

### Step 2: Run the ingestion pipeline

```bash
hindi-srs-ingest ~/hindi-corpus/
```

This runs an 8-step LLM-powered pipeline:

1. **Read** source files from the directory
2. **Extract** structured items (term, definition, romanization, context) via LLM
3. **Deduplicate** by normalizing Hindi text (Unicode NFC)
4. **Infer familiarity** from signals in your notes
5. **Assign CEFR levels** (A1–C2) via LLM
6. **Assign topics** from a 29-topic taxonomy via LLM
7. **Generate exercises** (multiple choice and cloze) via LLM
8. **Run gap analysis** comparing your coverage against expected A1–B1 vocabulary

Results are saved to `data/processed/`:

```
data/processed/
├── content_items.json      # Extracted and enriched vocabulary
├── exercises.json          # Generated exercises
├── gap_report.txt          # Human-readable coverage analysis
├── gap_report.json         # Machine-readable gap data
└── ingestion_summary.json  # Pipeline statistics
```

#### Ingestion options

```bash
# Skip exercise generation (faster, cheaper)
hindi-srs-ingest ~/hindi-corpus/ --skip-exercises

# Skip gap analysis
hindi-srs-ingest ~/hindi-corpus/ --skip-gap-analysis

# Generate only specific exercise types
hindi-srs-ingest ~/hindi-corpus/ --exercise-types mcq cloze

# Custom output directory
hindi-srs-ingest ~/hindi-corpus/ --output ./my-output

# Ingest a single file
hindi-srs-ingest ~/hindi-corpus/vocab-list.csv

# Verbose logging
hindi-srs-ingest ~/hindi-corpus/ -v
```

The pipeline prints a cost estimate for LLM usage at the end.

### Step 3: Load content into the database and create review cards

First, initialize your learner profile (only needed once):

```bash
hindi-srs stats
```

Then load the ingested content and create review cards in one step:

```bash
hindi-srs-load data/processed/content_items.json \
  --exercises data/processed/exercises.json \
  --learner-id 1
```

This creates content items, exercises, and review cards in the database. The `--learner-id 1` flag creates a card for each content item, linking it to your learner profile. Duplicates are automatically skipped, making it safe to re-run.

#### Load options

```bash
# Load content items only (no exercises, no cards)
hindi-srs-load data/processed/content_items.json

# Load content and exercises without creating cards
hindi-srs-load data/processed/content_items.json --exercises data/processed/exercises.json

# Verbose logging
hindi-srs-load data/processed/content_items.json --exercises data/processed/exercises.json --learner-id 1 -v
```

### Step 4: Start reviewing

```bash
hindi-srs review
```

The system will present your cards starting with due reviews interleaved with new cards. Your responses and ratings train the FSRS scheduler to optimize your review intervals.

### Review the gap analysis

Check `data/processed/gap_report.txt` to see which topics and CEFR levels have weak coverage. This helps you decide what content to add next.

---

## Adding New Content After Cold Start

Once the system is running, there are two ways to add content:

### Option A: Add individual items via CLI

For quick additions — a new word you encountered, something from a conversation:

```bash
hindi-srs add "बिल्कुल" "absolutely, exactly" -r "bilkul"
```

This creates both the content item and a review card in one step. The card is immediately available in your next review session.

### Option B: Re-run the ingestion pipeline on new materials

For larger batches — a new set of notes, a vocabulary list from a lesson, a new text:

```bash
# 1. Ingest the new material
hindi-srs-ingest ~/hindi-corpus/new-lesson-notes.md

# 2. Load into the database and create cards (duplicates are skipped)
hindi-srs-load data/processed/content_items.json \
  --exercises data/processed/exercises.json \
  --learner-id 1
```

Both the content loading and card creation are idempotent — they skip items that already exist, so it's safe to point the pipeline at a directory that contains both old and new files.

---

## Running Tests

```bash
pytest
```

Tests cover the FSRS algorithm, assessment logic, queue interleaving, CLI commands, API endpoints, agent orchestration, and the ingestion pipeline.

---

## Project Structure

```
boliye/
├── backend/                # FastAPI application
│   ├── main.py             # App initialization, CORS, static files
│   ├── config.py           # Settings (env vars, .env file)
│   ├── database.py         # SQLAlchemy async engine
│   ├── llm_client.py       # Anthropic API wrapper with rate limiting
│   ├── models/             # SQLAlchemy ORM models
│   │   ├── learner.py      # User profile
│   │   ├── content_item.py # Hindi terms with metadata
│   │   ├── card.py         # SRS card (learner ↔ content)
│   │   ├── exercise.py     # MCQ, cloze, translation exercises
│   │   └── review_log.py   # Review history
│   ├── srs/                # Spaced repetition engine
│   │   ├── fsrs.py         # FSRS-4.5 algorithm
│   │   ├── assessment.py   # Response grading (exact, MCQ, fuzzy)
│   │   ├── queue.py        # Review queue with interleaving
│   │   ├── session.py      # Session orchestration
│   │   └── exercise_selector.py
│   └── api/                # HTTP endpoints
│       ├── session_router.py
│       ├── stats_router.py
│       └── schemas.py
├── agents/                 # LLM-powered agent system
│   ├── orchestrator.py     # Top-level session controller
│   ├── scheduler_agent.py  # Adaptive card scheduling
│   ├── content_agent.py    # Exercise selection
│   ├── assessor_agent.py   # Response evaluation
│   └── tutor_agent.py      # Explanations and mnemonics
├── ingestion/              # Content processing pipeline
│   ├── pipeline.py         # 8-step orchestrator
│   ├── file_handlers.py    # File format readers
│   ├── extractor.py        # LLM-powered extraction
│   ├── dedup.py            # Hindi text deduplication
│   ├── familiarity.py      # Familiarity inference from signals
│   ├── cefr.py             # CEFR level assignment
│   ├── topics.py           # Topic tagging (29 categories)
│   ├── exercise_generator.py
│   └── gap_analysis.py     # Coverage analysis
├── hindi_srs/              # CLI entry point
│   └── __main__.py
├── scripts/                # Data loading utilities
│   ├── ingest.py           # Ingestion CLI wrapper
│   └── load_to_db.py       # JSON → database loader
├── tests/
├── data/                   # SQLite database (created at runtime)
├── pyproject.toml
└── tech-req.md             # Full project specification
```

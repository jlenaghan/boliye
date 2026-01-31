# Project Plan: Hindi SRS Language Learning System

**Owner:** Jonathan  
**Start Date:** Week of Feb 3, 2025  
**Target MVP:** 4-6 weeks  
**First User:** Jonathan (dogfooding)

-----

## Executive Summary

Build a spaced repetition language learning system bootstrapped from existing Hindi notes, powered by LLM-generated exercises, with an agent-based architecture for adaptive tutoring. Jonathan serves as the first user to validate the system before broader release.

-----

## Phase 0: Foundation & Data Gathering

**Duration:** 3-4 days  
**Goal:** Collect all existing learning materials and set up infrastructure

### 0.1 Gather Existing Corpus

- [ ] **Inventory existing materials** (Day 1)
  - Google Docs with Hindi notes
  - Any Anki decks or flashcard exports
  - Text files, PDFs, screenshots
  - WhatsApp/message conversations in Hindi
  - Bookmarked websites or resources
  - Duolingo/other app progress exports (if available)
- [ ] **Organize into ingestible formats** (Day 1)
  - Create `~/hindi-corpus/` directory
  - Subdirectories: `notes/`, `vocab-lists/`, `audio/`, `reference/`
  - Convert images with text to searchable format (OCR if needed)
- [ ] **Document your current level** (Day 1)
  - Self-assessment: What can you do? (read signs, basic conversation, etc.)
  - Known grammar patterns
  - Estimated vocabulary size
  - Specific gaps you’re aware of

### 0.2 Infrastructure Setup

- [ ] **Repository setup** (Day 2)
  
  ```
  hindi-srs/
  ├── backend/           # Python FastAPI
  ├── agents/            # Agent implementations
  ├── ingestion/         # Corpus processing
  ├── frontend/          # React/Next.js (later)
  ├── data/              # SQLite for MVP, migrations
  ├── scripts/           # Bootstrap & maintenance
  └── tests/
  ```
- [ ] **Database schema** (Day 2)
  - SQLite for MVP (easy to inspect, no infra)
  - Tables: learners, content_items, exercises, cards, review_logs
  - Migrations via Alembic
- [ ] **LLM client setup** (Day 2)
  - Anthropic API client wrapper
  - Rate limiting and retry logic
  - Cost tracking (this will use tokens)
- [ ] **Development environment** (Day 2)
  - Python 3.11+ with uv or poetry
  - Pre-commit hooks (ruff, mypy)
  - Basic CI with GitHub Actions

### Phase 0 Deliverables

- [ ] All Hindi materials in one place
- [ ] Empty but functional database
- [ ] LLM client that can make calls
- [ ] Git repo with basic structure

-----

## Phase 1: Corpus Ingestion & Content Generation

**Duration:** 5-7 days  
**Goal:** Transform raw notes into structured, reviewable content

### 1.1 Build Ingestion Pipeline

- [ ] **File format handlers** (Day 1-2)
  
  ```python
  # Priority order based on your likely materials:
  1. .txt, .md    - Plain text notes
  2. .csv         - Vocabulary lists
  3. .json        - Structured exports
  4. .docx        - Google Docs exports
  5. .pdf         - Reference materials
  6. .apkg        - Anki decks (if any)
  ```
- [ ] **LLM extraction prompt** (Day 2)
  - Parse messy notes into structured items
  - Handle: vocab, phrases, grammar patterns
  - Detect familiarity signals (checkmarks, question marks, repetition)
  - Output: JSON with term, definition, romanization, context
- [ ] **Deduplication logic** (Day 3)
  - Normalize Hindi text (Unicode NFC)
  - Merge multiple entries for same term
  - Preserve richest context/examples
- [ ] **Familiarity inference** (Day 3)
  - Map signals to initial SRS state
  - “Known” items start with longer intervals
  - “Unknown” items start as new

### 1.2 Content Calibration

- [ ] **CEFR level assignment** (Day 4)
  - LLM prompt to estimate A1-C2 level per item
  - Batch processing (50-100 items per call)
  - Store confidence scores
- [ ] **Topic tagging** (Day 4)
  - Assign topics: greetings, food, travel, family, etc.
  - Build topic hierarchy for curriculum
- [ ] **Gap analysis** (Day 5)
  - Compare coverage against standard A1-B1 vocabulary
  - Identify missing essential topics
  - Generate report: “You have 12 food words but 0 direction words”

### 1.3 Exercise Generation

- [ ] **Exercise type templates** (Day 5-6)
  
  ```
  Priority for MVP:
  1. MCQ (recognition) - easiest to generate, low risk
  2. Cloze (fill-in-blank) - needs good sentence generation
  3. Translation (L1→L2) - harder, save for later
  ```
- [ ] **Batch generation pipeline** (Day 6-7)
  - Generate 2-3 exercises per content item
  - Store with status: “generated” (needs review)
  - Track generation model and prompt version
- [ ] **Quality sampling** (Day 7)
  - Manually review ~50 generated exercises
  - Flag common errors for prompt refinement
  - Approve high-quality items, reject bad ones

### Phase 1 Deliverables

- [ ] All notes ingested into `content_items` table
- [ ] Each item has: CEFR level, topics, difficulty estimate
- [ ] 2-3 exercises generated per item
- [ ] Gap analysis report
- [ ] ~200-500 content items ready for review

-----

## Phase 2: Core SRS Engine

**Duration:** 4-5 days  
**Goal:** Working spaced repetition scheduler

### 2.1 FSRS Algorithm Implementation

- [ ] **Card state model** (Day 1)
  
  ```python
  @dataclass
  class CardState:
      stability: float      # Days until 90% retention
      difficulty: float     # 0-1, inherent difficulty
      due: datetime
      reps: int
      lapses: int
  ```
- [ ] **Interval calculation** (Day 1-2)
  - Implement FSRS-4.5 or simplified version
  - Rating → stability update
  - Stability → next interval
  - Target retention: 90%
- [ ] **Queue management** (Day 2)
  - Get due cards ordered by urgency
  - Mix new cards with reviews
  - Session limits (don’t overwhelm)

### 2.2 Review Session Logic

- [ ] **Session orchestration** (Day 3)
  
  ```python
  async def run_session(learner_id, max_cards=20):
      queue = get_due_cards(learner_id)
      for card in queue[:max_cards]:
          exercise = select_exercise(card)
          response = await present_exercise(exercise)
          assessment = assess_response(exercise, response)
          rating = get_rating(assessment)  # or self-rating
          update_card(card, rating)
  ```
- [ ] **Exercise selection** (Day 3)
  - Vary exercise types for same card
  - Easier exercises for struggling cards
  - Track recent types to avoid repetition
- [ ] **Review logging** (Day 4)
  - Log every review: card_id, rating, time_ms, exercise_type
  - Snapshot SRS state for algorithm analysis
  - This is your training data for improvements

### 2.3 Basic Assessment

- [ ] **Exact match checking** (Day 4)
  - Normalize: lowercase, strip whitespace
  - Handle common variations (ये/यह, है/हैं)
- [ ] **LLM fuzzy assessment** (Day 5)
  - For typed responses, check if “close enough”
  - Detect typos vs fundamental errors
  - Suggest rating based on assessment

### Phase 2 Deliverables

- [ ] Working SRS scheduler
- [ ] Can run a review session end-to-end
- [ ] Review history being logged
- [ ] Basic assessment working

-----

## Phase 3: Agent System

**Duration:** 5-7 days  
**Goal:** Intelligent tutoring beyond simple flashcards

### 3.1 Core Agents

- [ ] **Scheduler Agent** (Day 1)
  - Wraps SRS algorithm
  - Handles queue prioritization
  - Adaptive new card introduction
- [ ] **Content Agent** (Day 2)
  - Selects/generates exercises
  - Manages variety and difficulty progression
  - Caches generated content
- [ ] **Assessor Agent** (Day 2-3)
  - Evaluates responses
  - Provides detailed feedback
  - Suggests ratings
- [ ] **Tutor Agent** (Day 3-4)
  - Explains errors
  - Provides mnemonics for repeated failures
  - Adjusts explanation depth based on history

### 3.2 Orchestrator

- [ ] **Session management** (Day 4-5)
  - Coordinates agents
  - Manages conversation state
  - Handles interruptions gracefully
- [ ] **Adaptive behavior** (Day 5-6)
  - Learn optimal session length from your data
  - Adjust difficulty based on performance
  - Suggest focus areas

### 3.3 Agent Communication

- [ ] **Shared context** (Day 6)
  - Learner state accessible to all agents
  - Recent session history
  - Current goals/preferences
- [ ] **Tool definitions** (Day 7)
  - Each agent has clear tool interface
  - Orchestrator can invoke any agent
  - Logging for debugging

### Phase 3 Deliverables

- [ ] All 4 agents implemented
- [ ] Orchestrator coordinating sessions
- [ ] Tutor providing explanations on errors
- [ ] Adaptive behavior visible

-----

## Phase 4: MVP Interface

**Duration:** 5-7 days  
**Goal:** Usable interface for daily practice

### 4.1 CLI Interface (Quick Win)

- [ ] **Basic CLI** (Day 1-2)
  
  ```bash
  # Start a review session
  $ python -m hindi_srs review
  
  # Check stats
  $ python -m hindi_srs stats
  
  # Add new content
  $ python -m hindi_srs add "नमस्ते" "hello"
  ```
  - Good enough for dogfooding
  - Fast iteration on core logic

### 4.2 Simple Web UI

- [ ] **FastAPI backend** (Day 2-3)
  - `/api/session/start` - Begin review session
  - `/api/session/answer` - Submit answer
  - `/api/session/rate` - Self-rate
  - `/api/stats` - Dashboard data
- [ ] **React frontend** (Day 3-5)
  - Single-page app
  - Card display with Hindi text (proper font)
  - Answer input (support Devanagari keyboard)
  - Rating buttons
  - Session progress indicator
- [ ] **Basic styling** (Day 5-6)
  - Clean, mobile-friendly
  - Large text for Hindi script
  - Dark mode (easier on eyes for daily use)

### 4.3 Audio Integration

- [ ] **TTS generation** (Day 6-7)
  - Azure Cognitive Services or Google TTS
  - Generate audio for all content items
  - Store as MP3 in blob storage or local
- [ ] **Playback in UI** (Day 7)
  - Play button on cards
  - Auto-play option for listening practice

### Phase 4 Deliverables

- [ ] Working CLI for reviews
- [ ] Basic web UI
- [ ] Audio playback working
- [ ] Can do a full review session in browser

-----

## Phase 5: First User Onboarding (You!)

**Duration:** 3-4 days  
**Goal:** Calibrate the system to your level

### 5.1 Placement Test

- [ ] **Build placement flow** (Day 1)
  - 15-25 adaptive questions
  - Start at estimated level (A2? B1?)
  - Binary search through difficulty
- [ ] **Run placement** (Day 1)
  - Take the test yourself
  - Note any weird questions or calibration issues
  - Record your estimated level

### 5.2 Initial Deck Setup

- [ ] **Seed your deck** (Day 2)
  - Import all ingested content as cards
  - Set initial SRS state based on familiarity inference
  - Items you “know” start with 7+ day intervals
  - Unknown items due immediately
- [ ] **Review seed quality** (Day 2)
  - Spot-check 20-30 cards
  - Fix any obvious errors
  - Adjust levels if way off

### 5.3 First Week of Use

- [ ] **Daily sessions** (Day 3-7)
  - Commit to 10-15 min/day
  - Track: session length, completion, accuracy
  - Note pain points
- [ ] **Feedback log** (Ongoing)
  
  ```markdown
  ## Day 1 Notes
  - Exercise X was confusing because...
  - Audio didn't play for...
  - Would be nice to have...
  ```
- [ ] **Algorithm tuning** (Day 7)
  - Review your retention curve
  - Adjust target retention if needed
  - Tune new card introduction rate

### Phase 5 Deliverables

- [ ] Placement test completed
- [ ] Deck seeded with your content
- [ ] 7 days of usage data
- [ ] Prioritized list of improvements

-----

## Phase 6: Polish & Expand

**Duration:** Ongoing  
**Goal:** Make it actually good

### 6.1 Based on Dogfooding Feedback

- [ ] Fix top 5 pain points from first week
- [ ] Improve exercise quality
- [ ] Better error explanations
- [ ] Smoother session flow

### 6.2 Content Expansion

- [ ] Fill gaps identified in Phase 1
- [ ] Add grammar pattern cards
- [ ] Sentence-level content (not just vocab)
- [ ] Contextual dialogues

### 6.3 Advanced Features (Future)

- [ ] Speech recognition for pronunciation practice
- [ ] Goal-directed learning (“I want to order food in Hindi”)
- [ ] Spaced writing practice
- [ ] Integration with Hindi media (news, videos)

-----

## Technical Decisions Summary

|Decision         |Choice                      |Rationale                            |
|-----------------|----------------------------|-------------------------------------|
|**Database**     |SQLite → PostgreSQL         |Start simple, migrate when multi-user|
|**Backend**      |Python + FastAPI            |Your expertise, good async support   |
|**Frontend**     |React (Vite)                |Fast dev, can go mobile later        |
|**LLM**          |Claude API                  |Best for nuanced language tasks      |
|**TTS**          |Azure Cognitive Services    |Already on Azure, good Hindi voices  |
|**SRS Algorithm**|FSRS (simplified)           |Modern, well-researched              |
|**Hosting**      |Local → Azure Container Apps|Your existing infra                  |

-----

## Success Metrics

### Week 1 (End of Phase 5)

- [ ] 200+ cards in your deck
- [ ] 7 consecutive days of practice
- [ ] Retention rate visible in dashboard

### Month 1

- [ ] 80%+ retention rate on mature cards
- [ ] 500+ cards reviewed
- [ ] 3+ new grammar patterns learned
- [ ] Can identify specific improvements in comprehension

### Month 3

- [ ] System feels natural (low friction)
- [ ] Measurable vocabulary growth
- [ ] Ready to onboard second user

-----

## Risk Mitigation

|Risk                        |Mitigation                                    |
|----------------------------|----------------------------------------------|
|LLM generates bad exercises |Human review queue, quality sampling          |
|SRS intervals too aggressive|Conservative defaults, easy adjustment        |
|Lose motivation after week 1|Streak tracking, low daily commitment (10 min)|
|Scope creep                 |Strict MVP focus, features list for “later”   |
|Hindi rendering issues      |Test on multiple devices early                |

-----

## Time Investment Estimate

|Phase              |Duration     |Hours/Week     |Total Hours      |
|-------------------|-------------|---------------|-----------------|
|Phase 0: Foundation|3-4 days     |15-20          |15-20            |
|Phase 1: Ingestion |5-7 days     |20-25          |20-25            |
|Phase 2: SRS Engine|4-5 days     |15-20          |15-20            |
|Phase 3: Agents    |5-7 days     |20-25          |20-25            |
|Phase 4: Interface |5-7 days     |20-25          |20-25            |
|Phase 5: Onboarding|3-4 days     |10-15          |10-15            |
|**Total MVP**      |**4-6 weeks**|**~15-20/week**|**100-130 hours**|

-----

## Next Actions (This Week)

1. **Today:** Inventory all Hindi materials, create `~/hindi-corpus/`
1. **Tomorrow:** Set up git repo, basic Python project structure
1. **Day 3:** Build first ingestion script, test on one file
1. **Day 4:** LLM extraction working, process all notes
1. **Day 5:** Review extracted content, fix obvious issues

-----

## Appendix: File Locations

```
~/hindi-corpus/
├── raw/
│   ├── google-docs-export/
│   ├── text-notes/
│   └── vocab-lists/
├── processed/
│   ├── content_items.json
│   └── extraction_log.json
└── reference/
    ├── frequency-lists/
    └── grammar-guides/

~/hindi-srs/
├── backend/
│   ├── main.py
│   ├── models/
│   ├── agents/
│   └── api/
├── data/
│   └── hindi_srs.db
├── scripts/
│   ├── ingest.py
│   ├── generate_exercises.py
│   └── bootstrap.py
└── frontend/
    └── (React app)
```

-----

*Last updated: January 30, 2025*
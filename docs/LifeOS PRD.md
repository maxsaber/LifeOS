# LifeOS PRD

Personal assistant system for semantic search and synthesis across Obsidian vault and Google Suite.

Related files:
- [[LifeOS Backlog]]
- [[LifeOS original vision and context]]

---

## System Overview

**Architecture:**
- Mac Mini (always-on) hosts all components
- Tailscale-only access (no public auth)
- Obsidian vault already synced to Mac Mini
- Local embeddings (sentence-transformers)
- Local vector DB (ChromaDB)
- FastAPI backend + vanilla HTML/JS frontend

**Data Sources:**
- Obsidian vault (~4,500 markdown files)
- Google suite from personal (e.g., nbramia@gmail.com) and work (e.g., nathanramia@movementlabs.com) accounts. For each:
	- Google Calendar (hybrid: indexed + live)
	- Google Gmail (live queries only)
	- Google Drive (hybrid: key docs indexed, rest live)

---

## Development Workspace

This project is designed for autonomous execution using the Ralph Wiggum technique (AI agent loop until completion).

**Directory Structure:**
```
/path/to/LifeOS/   # (e.g., /Users/nathanramia/Documents/Code/LifeOS/)
├── .ralph/                  # Ralph loop state (gitignored)
│   ├── scratchpad.md        # Cross-iteration notes and progress
│   ├── checkpoints/         # Git checkpoint tags
│   └── metrics/             # Execution statistics
├── PROMPT.md                # Current task description for Ralph
├── api/
│   ├── main.py
│   ├── routes/
│   └── services/
├── tests/
├── web/
├── config/
├── scripts/
├── requirements.txt
├── pyproject.toml
└── README.md
```

**Vault Path:** `/path/to/vault/` (e.g., `/Users/nathanramia/Notes 2025/`)

---

## Ralph Execution Guidelines

Each phase is designed for autonomous execution. Use the Ralph Wiggum orchestration pattern where a main agent delegates to specialized sub-agents, each with their own context and tools. You will continue until all specifications are complete or you reach the point that you can't continue without something from me (e.g. an auth token or login). Follow this process:

### Standard Iteration Process

1. **Read scratchpad** (`.ralph/scratchpad.md`) for context from previous iterations
2. **Check acceptance criteria** - identify which are complete vs remaining
3. **Write/update tests** for the next incomplete criterion
4. **Implement** minimum code to pass tests
5. **Run tests:** `pytest tests/ -v`
6. **If tests pass:** Update scratchpad, proceed to next criterion
7. **If tests fail:** Debug, fix, re-run (max 3 attempts per issue)
8. **When all criteria met:** Output completion promise

### Escape Hatch Protocol

**If stuck after 10 iterations without progress:**
1. Document what was attempted in scratchpad
2. Document specific blockers with error messages
3. Suggest 2-3 alternative approaches
4. Output: `<promise>PHASE-BLOCKED</promise>` with summary

### Scratchpad Format

```markdown
# LifeOS Development Scratchpad

## Current Phase: P1.1

## Completed Criteria:
- [x] Criterion 1 - completed iteration 3
- [x] Criterion 2 - completed iteration 5

## In Progress:
- [ ] Criterion 3 - attempting, see notes below

## Notes:
- Iteration 7: Tried X, got error Y
- Iteration 8: Fixed by Z

## Blockers:
(none currently)
```

---

## Phase 0: Vault Conventions & Conformance ✅ COMPLETE

**Status:** Completed 2025-01-07

**What was done:**
- Created ML subfolder structure (Finance, Meetings, People, Strategy and planning, Other, Daily Notes)
- Stripped Notion hex suffixes from ~200 filenames
- Organized 77 ML top-level files into appropriate subfolders
- Processed 127 lifelogs → created Highlights files + extracted meeting notes to Work/ML/Meetings/
- Extracted 9 therapy sessions to dedicated files with full transcripts (8 Amy Morgan individual, 1 Erica Turner couples)
- Fixed "Haley" → "Hayley" across 125 files

---

### Vault Standards (defined manually, before development)

**Folder Structure:**
```
/vault/
├── Granola/                 # INBOX - meeting notes land here, then get processed
├── Personal/
│   ├── Coding/              # Technical projects, side projects
│   ├── Finance/             # Financial records, planning
│   ├── Lifelogs/            # Voice transcription logs
│   │   ├── Raw/             # Original unprocessed transcripts
│   │   └── Highlights/      # Processed daily highlights
│   ├── Malea/               # Daughter-related
│   ├── Recipes/             # Cooking
│   ├── Relationship/        # Taylor, family
│   ├── Self-improvement/    # Growth, habits
│   │   └── Therapy and coaching/  # Therapy sessions (Amy Morgan, Erica Turner)
│   ├── Thoughts and Ideas/  # Freeform thinking
│   ├── TTI/                 # Treasure hunt project
│   ├── User Manual/         # Self-documentation
│   └── zArchive/            # Old jobs, historical (lower priority for indexing)
├── Work/
│   ├── ML/                  # Movement Labs (current job)
│   │   ├── Daily Notes/     # Daily work logs
│   │   ├── Finance/         # Budget, compensation, insurance
│   │   ├── Meetings/        # All meeting notes (flat structure)
│   │   ├── Other/           # Misc notes, templates
│   │   ├── People/          # Personnel-related
│   │   │   ├── Hiring/      # Interview notes, JDs
│   │   │   ├── Performance/ # Reviews, feedback
│   │   │   └── Union/       # Union-related
│   │   └── Strategy and planning/  # Org charts, proposals, roadmaps, branding
│   └── Job Search/          # Career exploration
├── LifeOS/                  # Generated by LifeOS
│   ├── Briefings/
│   ├── Summaries/
│   └── Research/
└── Attachments/             # Images, PDFs, etc.
```

**Required YAML Frontmatter:**
```yaml
---
created: YYYY-MM-DD           # Required (from filename/content, NOT filesystem)
modified: YYYY-MM-DD          # Optional, auto-updated
tags: [tag1, tag2]            # Required, at least one
type: meeting | note | reference | project | log  # Required
people: [Name1, Name2]        # Optional, extracted from content
status: active | archived     # Optional, default: active
---
```

**Date Handling Rules:**
- Extract `created` from filename if present (e.g., `20251217` → `2025-12-17`)
- Extract from Granola frontmatter `created_at` field
- Extract from content if clearly stated
- **Leave blank if no reliable date source** - filesystem dates are unreliable

**Tag Taxonomy:**

| Category | Tags | Usage |
|----------|------|-------|
| **Type** | `meeting`, `reference`, `log`, `project`, `reflection` | What kind of note |
| **Domain** | `work`, `personal`, `therapy`, `relationship`, `finance` | Area of life |
| **Work** | `ml`, `hiring`, `strategy`, `1-1` | Movement Labs specific |
| **Action** | `actionable`, `archived` | Status flags |

**Naming Conventions:**
- Meetings: `[Topic] YYYYMMDD.md` (Granola default)
- Daily logs: `YYYY-MM-DD.md`
- Projects: `[Project Name].md`
- References: `[Descriptive Title].md`
- No Notion hex suffixes (strip during processing)

**Content Conventions:**
- H1 (`#`) reserved for title (matches filename sans date)
- H2 (`##`) for major sections
- Action items use `- [ ]` checkbox syntax
- People names in **bold** on first mention (aids extraction)
- Wiki-links `[[Note Name]]` for internal references

**People Dictionary (for extraction/fuzzy matching):**
- Nathan (me)
- Taylor (partner)
- Malea (daughter, often misspelled "Malia")
- Yoni (boss)
- Madi (CTO/peer)
- Hayley (head of HR, direct report)

---

### P0.1: Granola Inbox Processor

**Requirements:**
Granola is an inbox - notes land there and get automatically processed and moved to their proper location.

**Processing Logic:**
1. Watch `Granola/` folder for new/modified files
2. Parse existing Granola frontmatter (preserve `granola_id`, `granola_url`, `created_at`, `updated_at`)
3. Classify note by content patterns:

| Pattern | Destination | Tags |
|---------|-------------|------|
| `therapy`, `Amy Morgan`, `Erica Turner` | `Personal/Self-improvement/Therapy and coaching/` | `meeting`, `therapy` |
| 1-1 with ML person (Yoni, Madi, etc.) | `Work/ML/Meetings/` | `meeting`, `work`, `ml`, `1-1` |
| Interview, hiring, JD keywords | `Work/ML/People/Hiring/` | `meeting`, `work`, `ml`, `hiring` |
| Budget, revenue, finance keywords | `Work/ML/Finance/` | `meeting`, `work`, `ml`, `finance` |
| All-hands, team standup, retreat | `Work/ML/Meetings/` | `meeting`, `work`, `ml` |
| Strategy, planning, goals, OKRs | `Work/ML/Strategy and planning/` | `meeting`, `work`, `ml`, `strategy` |
| Union keywords | `Work/ML/People/Union/` | `meeting`, `work`, `ml` |
| Personal/Taylor/family | `Personal/Relationship/` | `meeting`, `personal`, `relationship` |
| Default (other work) | `Work/ML/Meetings/` | `meeting`, `work`, `ml` |

4. Extract `created` date from Granola `created_at` field
5. Extract `people` from content and attendee mentions
6. Add/update frontmatter with required fields
7. **Move file** to destination folder
8. Log: original path, new path, classification rationale

**Acceptance Criteria:**
```
[ ] Processor watches Granola/ folder for new files
[ ] Correctly classifies therapy sessions
[ ] Correctly classifies 1-1s by person
[ ] Correctly classifies by topic (finance, strategy, hiring, etc.)
[ ] Preserves all Granola-specific frontmatter fields
[ ] Extracts created date from Granola created_at
[ ] Extracts people from content
[ ] Moves files to correct destination
[ ] Adds appropriate tags based on classification
[ ] Logs all moves with rationale
[ ] Does not modify note content (only frontmatter)
[ ] Handles edge cases (ambiguous content) gracefully
```

**Completion Promise:** `<promise>P0.1-GRANOLA-PROCESSOR-COMPLETE</promise>`

---

### P0.2: Lifelog Processor (One-Time Batch)

**Requirements:**
**One-time batch job** to process existing voice transcription lifelogs from `Personal/Lifelogs/` into structured highlights and meeting notes. See [[Lifelog parsing]] for full spec.

This is NOT an ongoing service - just a one-time cleanup of the ~131 existing lifelog files. If we start generating more in the future, maybe we'll run this again.

**Input:** Raw `YYYY-MM-DD.md` files with timestamped voice transcriptions

**Processing Pipeline:**
1. Segment transcript into sessions by time continuity (≤15 min gaps)
2. Classify each session:
   - `work_meeting` → business/branding/ops language, deliverables
   - `therapy` → usually but not always Mon 8-9pm or Tue 7-8pm, reflective language, therapists named Erika Turner (may be transcribed Erica) for couples therapy and Amy Morgan for individual therapy
   - `personal_meaningful` → substantive Taylor/Malea conversations
   - `noise` → brief commands, TV, filler (drop)
3. Match work meetings to calendar events by time overlap
4. Generate outputs:

**Output Files:**

| Type               | Filename                                   | Location                                          |
| ------------------ | ------------------------------------------ | ------------------------------------------------- |
| Original raw file  | `YYYY-MM-DD.md`                            | Move to `Lifelogs/Raw/`                           |
| Daily highlights   | `YYYY-MM-DD Highlights.md`                 | `Lifelogs/Highlights/`                            |
| Work meeting notes | `Topic YYYYMMDD.md`                        | `Work/ML/Meetings/`                               |
| Therapy (individual) | `Amy Morgan therapy YYYYMMDD.md`         | `Personal/Self-improvement/Therapy and coaching/` |
| Therapy (couples)  | `Erica Turner couples therapy YYYYMMDD.md` | `Personal/Self-improvement/Therapy and coaching/` |

**Highlights Structure:**
```markdown
# Highlights — YYYY-MM-DD

## Work Meetings
### <Title> (Start–End)
- **TL;DR:** <1-2 sentences>
- **Decisions:** <bullets>
- **Action Items:** Owner → Task (Due: date)
- **Key Points:** <bullets>
- **Open Questions:** <bullets>
- **Source:** [[YYYY-MM-DD]] @ start–end
- **Confidence:** 0.00–1.00 — rationale

## Therapy
### Session (Start–End)
- **TL;DR:** ...
- **Insights:** ...
- **Action Items:** ...

## Personal — Meaningful Conversations
### Taylor (Start–End)
- **TL;DR:** ...
- **Decisions:** ...
```

**Work Meeting and Therapy File Structure:**
```markdown
# [[Topic]] — YYYY-MM-DD

**When:** Start–End
**Calendar:** Event Title or "—"
**Attendees:** Name1, Name2
**Source:** [[YYYY-MM-DD]] @ start–end

## TL;DR
- <summary>

## Decisions
- <decision>

## Discussion Notes
- <bullets>

## Action Items
- Owner → Task (Due: date)

## Raw Transcript
<rawtranscript>
```

**Acceptance Criteria:**
```
[ ] Processor detects new files in Lifelogs/
[ ] Segments transcripts into sessions by time
[ ] Correctly classifies work meetings
[ ] Correctly classifies therapy sessions (Mon 8-9pm, Tue 7-8pm)
[ ] Correctly classifies personal meaningful (Taylor/Malea)
[ ] Drops noise/incidental content
[ ] Matches meetings to calendar events
[ ] Generates Highlights file with correct structure
[ ] Generates individual meeting files for work meetings and therapy sessions
[ ] Moves raw files to Raw/ subfolder
[ ] Extracts action items with owners
[ ] Uses wiki-links for cross-references
[ ] Fuzzy matches names (Malea/Malia, etc.)
[ ] Never modifies original raw file content
[ ] Logs processing with confidence scores
```

**Completion Promise:** `<promise>P0.2-LIFELOG-PROCESSOR-COMPLETE</promise>`

---

### P0.3: General Conformance Processor

**Requirements:**
For files outside Granola/Lifelogs that need frontmatter cleanup.

**Processing Logic:**
1. Watch vault for new/modified files (excluding Granola/, Lifelogs/Raw/)
2. Detect files missing required frontmatter
3. Add missing fields:
   - `created`: from filename date pattern or leave blank
   - `tags`: infer from folder path + content
   - `type`: infer from folder
   - `people`: extract from content
4. Does NOT move files (only frontmatter + rename)

**Acceptance Criteria:**
```
[ ] Detects files without frontmatter
[ ] Adds missing tags based on folder + content
[ ] Adds missing type based on folder
[ ] Extracts people from content
[ ] Strips Notion hex suffixes from filenames
[ ] Preserves existing frontmatter fields
[ ] Does not modify note content
[ ] Logs all changes
```

**Completion Promise:** `<promise>P0.3-CONFORMANCE-COMPLETE</promise>`

---

### P0.4: LifeOS Write Standards

**Requirements:**
All content written by LifeOS (Save to Vault, generated briefings, etc.) must:
- Include complete YAML frontmatter with all required fields
- Follow folder placement conventions
- Follow naming conventions
- Include `source: lifeos` in frontmatter
- Use wiki-links for references to existing notes

**Acceptance Criteria:**
```
[ ] All LifeOS-generated notes include complete frontmatter
[ ] Frontmatter includes `source: lifeos`
[ ] Notes placed in correct folder based on content type
[ ] Filenames follow naming conventions
[ ] Internal references use [[wiki-link]] syntax
[ ] Generated notes pass conformance check (no processing needed)
```

**Completion Promise:** `<promise>P0.2-WRITE-STANDARDS-COMPLETE</promise>`

---

## Phase 1: Core Retrieval Engine

### P1.1: Indexer Service

**Requirements:**
- Watch Obsidian vault folder for file changes (create, modify, delete)
- Parse markdown files and extract content
- Chunk notes according to type:
  - Granola meetings: by section (headers) + action items as separate chunks
  - Long notes (>500 tokens): ~500 token chunks with 50 token overlap
  - Short notes (<500 tokens): whole note as single chunk
- Generate embeddings using sentence-transformers (`all-MiniLM-L6-v2`)
- Store in ChromaDB with metadata

**Metadata per chunk:**
- `file_path` (string): absolute path to source file
- `file_name` (string): filename without path
- `modified_date` (datetime): file modification time
- `note_type` (string): inferred from folder (Personal/Work/Granola)
- `chunk_index` (int): position within document
- `people` (list[string]): extracted names from content
- `tags` (list[string]): from YAML frontmatter if present

**Process:**
1. Set up project structure with FastAPI skeleton
2. Write tests for markdown parsing and chunking
3. Implement chunking logic (by headers, with overlap)
4. Write tests for embedding generation
5. Implement sentence-transformers embedding
6. Write tests for ChromaDB storage
7. Implement ChromaDB integration with metadata
8. Write tests for file watcher
9. Implement watchdog-based file monitoring
10. Integration test: full index of test vault
11. Run tests, iterate until all pass

**Acceptance Criteria:**
```
[ ] Indexer starts and watches vault folder without errors
[ ] Initial full index completes for all ~4,500 files
[ ] New file creation triggers indexing within 5 seconds
[ ] File modification triggers re-indexing within 5 seconds
[ ] File deletion removes chunks from ChromaDB
[ ] Granola notes are chunked by section headers
[ ] Long notes are chunked with overlap
[ ] Short notes stored as single chunk
[ ] All metadata fields populated correctly
[ ] Indexer recovers gracefully from restart (no duplicate chunks)
[ ] Unit tests pass for chunking logic
[ ] Integration test: create file, verify in ChromaDB within 10s
```

**Completion Promise:** `<promise>P1.1-INDEXER-COMPLETE</promise>`

---

### P1.2: Vector Search API

**Requirements:**
- FastAPI endpoint: `POST /api/search`
- Accept query string and optional filters (date range, note_type, people)
- Embed query using same model as indexer
- Search ChromaDB for top-k similar chunks (default k=20)
- Return ranked results with metadata and relevance scores

**API Schema:**
```python
# Request
{
    "query": str,
    "filters": {
        "note_type": Optional[list[str]],
        "people": Optional[list[str]],
        "date_from": Optional[datetime],
        "date_to": Optional[datetime]
    },
    "top_k": int = 20
}

# Response
{
    "results": [
        {
            "content": str,
            "file_path": str,
            "file_name": str,
            "note_type": str,
            "modified_date": datetime,
            "people": list[str],
            "score": float
        }
    ],
    "query_time_ms": int
}
```

**Process:**
1. Write tests for search endpoint request/response
2. Implement FastAPI endpoint with Pydantic models
3. Write tests for query embedding
4. Implement query → embedding conversion
5. Write tests for ChromaDB similarity search
6. Implement search with filters
7. Write tests for result ranking
8. Implement score-based ranking and deduplication
9. Integration test: end-to-end search flow
10. Run tests, iterate until all pass

**Acceptance Criteria:**
```
[ ] API starts and accepts requests on configured port
[ ] Query returns relevant chunks (manual verification on 5 test queries)
[ ] Filters correctly narrow results by note_type
[ ] Filters correctly narrow results by people
[ ] Filters correctly narrow results by date range
[ ] Response includes all required metadata fields
[ ] Query latency <500ms for typical queries
[ ] Empty query returns error, not crash
[ ] Invalid filters return 400 with clear message
[ ] Unit tests for search logic
[ ] Integration test: index test file, search for content, verify found
```

**Completion Promise:** `<promise>P1.2-SEARCH-API-COMPLETE</promise>`

---

### P1.3: RAG Synthesis Endpoint

**Requirements:**
- FastAPI endpoint: `POST /api/ask`
- Accept user question
- Call vector search internally
- Construct prompt with retrieved context
- Call Claude API for synthesis
- Return answer with source citations

**Prompt Construction:**
- System prompt includes user preferences (concise, Paul Graham style)
- Retrieved chunks formatted with source attribution
- User question appended

**Process:**
1. Write tests for prompt construction
2. Implement prompt template with context injection
3. Write tests for Claude API integration
4. Implement Claude API call with streaming
5. Write tests for source extraction from response
6. Implement source citation parsing
7. Write tests for end-to-end synthesis
8. Integration test: ask real questions, verify quality
9. Run tests, iterate until all pass

**API Schema:**
```python
# Request
{
    "question": str,
    "include_sources": bool = True
}

# Response
{
    "answer": str,
    "sources": [
        {
            "file_name": str,
            "file_path": str,
            "relevance": float
        }
    ],
    "retrieval_time_ms": int,
    "synthesis_time_ms": int
}
```

**Acceptance Criteria:**
```
[ ] Endpoint accepts questions and returns synthesized answers
[ ] Answers cite sources from retrieved chunks
[ ] Answers reflect Paul Graham writing style (concise, clear)
[ ] Sources list is deduplicated by file
[ ] Total latency <3 seconds for vault-only queries
[ ] Claude API errors return graceful error response
[ ] Empty question returns 400 error
[ ] Unit tests for prompt construction
[ ] Integration test: ask question about known content, verify accurate answer
```

**Completion Promise:** `<promise>P1.3-RAG-COMPLETE</promise>`

---

### P1.4: People Tracking

**Requirements:**
- Extract person mentions from notes using NER and pattern matching
- Build canonical person registry with aliases and fuzzy matching
- Track last-mention date per person from note dates
- Enable person-scoped queries ("prep me for [person]", "what do I know about [person]")

**Person Registry Schema:**
```python
{
    "canonical_name": "Yoni Landau",
    "aliases": ["Yoni", "yoni@movementlabs.com"],
    "category": "work",  # work | personal | family
    "last_mention_date": "2025-01-05",
    "mention_count": 47,
    "related_notes": ["Meeting with Yoni 20250105.md", ...]
}
```

**Fuzzy Matching Rules:**
- Nathan = me (exclude from people tracking)
- Taylor = Taylor (partner) - don't confuse with other Taylors
- Malea = Malia = Malea (daughter)
- Email addresses map to canonical names
- First names resolve to most-frequent full name in context

**Process:**
1. Write tests for person extraction from sample notes
2. Implement NER + pattern extraction
3. Build alias resolution with People Dictionary
4. Create person registry storage (JSON or SQLite)
5. Implement `search_by_person(name, query)`
6. Run tests, iterate until passing

**Acceptance Criteria:**
```
[ ] Extracts person names from note content
[ ] Handles aliases (Yoni → Yoni Landau)
[ ] Handles misspellings (Malia → Malea)
[ ] Tracks last-mention date per person
[ ] Person filter works in search API
[ ] "What do I know about Yoni" returns relevant context
[ ] Excludes self-references (Nathan)
[ ] Unit tests for extraction logic
[ ] Integration test: create note with names, verify extraction
```

**Completion Promise:** `<promise>P1.4-PEOPLE-COMPLETE</promise>`

---

### P1.5: Action Item Extraction

**Requirements:**
- Detect action items in notes using patterns
- Extract owner, task description, optional due date
- Store in queryable format
- Enable queries: "my open action items", "what did I commit to [person]"

**Detection Patterns:**
- `- [ ] Task description` (Obsidian checkbox)
- `- [x] Completed task` (completed, track separately)
- `Action: Owner → Task`
- `TODO: Task`
- `Next steps:` followed by bullets
- `@Nathan` or `Nathan →` indicates ownership

**Action Item Schema:**
```python
{
    "task": "Send budget proposal to Kevin",
    "owner": "Nathan",  # or "Yoni", etc.
    "status": "open",  # open | completed
    "due_date": "2025-01-15",  # optional
    "source_file": "Budget Planning 20250105.md",
    "source_date": "2025-01-05",
    "extracted_text": "- [ ] Send budget proposal to Kevin by EOW"
}
```

**Process:**
1. Write tests for action item detection patterns
2. Implement regex + heuristic extraction
3. Build owner resolution using People registry
4. Store action items with source tracking
5. Implement query endpoints
6. Run tests, iterate until passing

**Acceptance Criteria:**
```
[ ] Detects `- [ ]` checkbox syntax
[ ] Detects `Action:` pattern
[ ] Detects `TODO:` pattern
[ ] Extracts owner when specified
[ ] Extracts due date when present
[ ] Links action items to source note
[ ] "What are my open action items" returns list
[ ] "What did I commit to Yoni" filters by person
[ ] Completed items tracked separately
[ ] Unit tests for extraction patterns
[ ] Integration test: create note with todos, verify extraction
```

**Completion Promise:** `<promise>P1.5-ACTIONS-COMPLETE</promise>`

---

## Phase 2: Web Interface

### P2.1: Basic Chat UI

**Requirements:**
- Single HTML page served by FastAPI
- Chat interface with input field and send button
- Display conversation as message bubbles (user/assistant)
- Stream responses as they arrive (SSE or chunked response)
- Clickable source links using `obsidian://` URI scheme
- Mobile-responsive layout
- Status indicator (ready/loading/error)

**UI Elements:**
- Header: "LifeOS" + status badge
- Message area: scrollable, newest at bottom
- Input area: text field + send button
- Messages show: content, timestamp, sources (for assistant messages)

**Acceptance Criteria:**
```
[ ] Page loads and displays chat interface
[ ] User can type question and submit
[ ] Assistant response appears in chat
[ ] Response streams incrementally (not all-at-once)
[ ] Sources displayed as clickable links
[ ] obsidian:// links open correct note in Obsidian
[ ] Status shows "loading" during request
[ ] Status shows "error" if request fails
[ ] Interface works on mobile viewport (375px width)
[ ] Enter key submits question
[ ] Input clears after submission
[ ] Chat scrolls to newest message automatically
```

**Completion Promise:** `<promise>P2.1-CHAT-UI-COMPLETE</promise>`

---

### P2.2: Save to Vault Feature

**Requirements:**
- "Save to vault" button appears after assistant responses
- Clicking triggers separate Claude call to synthesize save-worthy content
- Claude determines:
  - What content is worth preserving (not raw chat)
  - Where to save (folder based on topic)
  - How to structure (proper note format, not transcript)
  - Title and metadata
- Writes formatted markdown to vault
- Confirms save to user with link to new note

**Save Prompt Instructs Claude To:**
1. Assess what's worth saving from the conversation
2. Determine appropriate location:
   - Work-related → `Work/ML/[topic].md`
   - Personal → `Personal/[category]/[topic].md`
   - Meeting follow-up → link to original meeting note
   - General → `LifeOS/Research/[topic].md`
3. Structure as proper note:
   - Clear title
   - TL;DR summary at top
   - Key points/decisions
   - Source links as wiki-links
   - Relevant tags
4. Add YAML frontmatter (created date, source: lifeos, tags)

**Acceptance Criteria:**
```
[ ] Save button appears on assistant messages
[ ] Clicking save triggers synthesis call
[ ] Synthesized note is well-structured (not chat transcript)
[ ] Note saved to appropriate folder based on content
[ ] Note includes YAML frontmatter with required fields
[ ] Note includes TL;DR section
[ ] Source notes linked with [[wiki-link]] syntax
[ ] User sees confirmation with link to saved note
[ ] Link opens saved note in Obsidian
[ ] Save button disabled/hidden after successful save
[ ] Error during save shows clear message to user
```

**Completion Promise:** `<promise>P2.2-SAVE-VAULT-COMPLETE</promise>`

---

### P2.3: Stakeholder Briefings

**Requirements:**
- "Tell me about [person]" or "Prep me for [person]" queries
- Aggregate all context about a specific person from vault
- Synthesize into actionable briefing format
- Include: background, recent interactions, open items, relationship context

**Briefing Structure:**
```markdown
## [Person Name] — Briefing

**Role/Relationship:** [inferred from notes]
**Last Interaction:** [date and context]
**Interaction Frequency:** [X meetings in past 90 days]

### Recent Context
- [Key points from recent notes mentioning this person]

### Open Items
- [Action items involving this person]
- [Decisions pending with them]

### Relationship Notes
- [Any personal context: preferences, communication style, etc.]

### Suggested Topics
- [Based on open items and recent discussions]
```

**Process:**
1. Write tests for briefing generation
2. Use People registry to resolve person
3. Query vault for all mentions (semantic + exact match)
4. Query action items involving person
5. Use Claude to synthesize into briefing format
6. Run tests, iterate until passing

**Acceptance Criteria:**
```
[ ] "Tell me about Yoni" generates briefing
[ ] "Prep me for meeting with Madi" generates briefing
[ ] Briefing includes last interaction date
[ ] Briefing includes open action items
[ ] Briefing includes recent discussion context
[ ] Handles unknown people gracefully ("I don't have notes about X")
[ ] Sources cited with links
[ ] Response time <5 seconds
[ ] Unit tests for briefing construction
```

**Completion Promise:** `<promise>P2.3-STAKEHOLDER-COMPLETE</promise>`

---

## Phase 3: Google Integration

### P3.1: Google OAuth Setup

**Requirements:**
- Google Cloud project with Calendar, Gmail, Drive APIs enabled (including for Docs and sheets) for both personal account (e.g., nbramia@gmail.com) and work account (e.g., nathanramia@movementlabs.com) - read-only for work and read-write for personal
- OAuth 2.0 credentials (desktop app type)
- One-time browser-based auth flow
- Token storage (access + refresh) in local file
- Auto-refresh of expired tokens

**Acceptance Criteria:**
```
[ ] OAuth flow completes successfully in browser for personal account (e.g., nbramia@gmail.com)
[ ] OAuth flow completes successfully in browser for work account (e.g., nathanramia@movementlabs.com)
[ ] Access tokens stored locally
[ ] Refresh tokens stored locally
[ ] Tokens auto-refresh when expired
[ ] Credentials file excluded from any version control
[ ] Clear error message if auth fails
[ ] Re-auth flow works if tokens are revoked
```

**Completion Promise:** `<promise>P3.1-GOOGLE-AUTH-COMPLETE</promise>`

---

### P3.2: Google Calendar Integration

**Requirements:**
- Fetch upcoming events (next 7 days by default)
- Fetch past events (for "what meetings did I have with X")
- Index calendar events into ChromaDB (daily sync)
- Live query for real-time calendar questions

**Indexed Metadata:**
- `event_id`, `title`, `start_time`, `end_time`
- `attendees` (list of emails/names)
- `description`, `location`
- `source: google_calendar`

**API Additions:**
- `GET /api/calendar/upcoming` - next N events
- `GET /api/calendar/search?q=...&attendee=...` - search events

**Acceptance Criteria:**
```
[ ] Can fetch upcoming events from Google Calendar
[ ] Can fetch past events within date range
[ ] Events indexed to ChromaDB with correct metadata
[ ] Daily sync updates index (cron or scheduler)
[ ] Search by attendee name returns correct events
[ ] Search by keyword in title/description works
[ ] "What's on my calendar tomorrow" returns correct events
[ ] Event times displayed in local timezone
[ ] All-day events handled correctly
```

**Completion Promise:** `<promise>P3.2-CALENDAR-COMPLETE</promise>`

**Implementation Notes (added 2026-01-09):**

*Multi-Account Support:*
- Queries both GoogleAccount.PERSONAL and GoogleAccount.WORK accounts
- Results merged and sorted by start_time
- Prevents duplicate events when same calendar synced to multiple accounts

---

### P3.3: Gmail Integration

**Requirements:**
- Search emails by query (sender, subject, date range, keywords)
- Fetch email content for relevant messages
- Live queries only (no bulk indexing)
- Rate limiting to avoid API quota issues

**API Addition:**
- `GET /api/gmail/search?q=...&from=...&after=...&before=...`

**Acceptance Criteria:**
```
[ ] Can search emails by keyword
[ ] Can filter by sender
[ ] Can filter by date range
[ ] Returns email subject, sender, date, snippet
[ ] Can fetch full email body when needed
[ ] Rate limiting prevents quota errors
[ ] "Did Kevin email about the budget" returns relevant emails
[ ] Empty results return empty list, not error
```

**Completion Promise:** `<promise>P3.3-GMAIL-COMPLETE</promise>`

**Implementation Notes (added 2026-01-09):**

*Multi-Account Support:*
- Queries both GoogleAccount.PERSONAL and GoogleAccount.WORK accounts
- Results merged, most recent first
- Keyword extraction from queries for better search results

---

### P3.4: Google Drive Integration

**Requirements:**
- Search Drive files by name and content
- Index frequently-accessed docs (manual selection or usage-based)
- Live query for ad-hoc searches
- Support Google Docs, Sheets (export as text)

**Acceptance Criteria:**
```
[ ] Can search Drive by filename
[ ] Can search Drive by content
[ ] Can fetch and parse Google Doc content
[ ] Can fetch and parse Google Sheet content
[ ] Key docs indexable to ChromaDB
[ ] "Find the budget spreadsheet" returns correct file
[ ] Results include file name, link, last modified
```

**Completion Promise:** `<promise>P3.4-DRIVE-COMPLETE</promise>`

**Implementation Notes (added 2026-01-09):**

*Adaptive Retrieval:*
- Initial read: 2 files maximum, 1000 characters each
- Files are sorted by relevance: name-matched files prioritized over content-matched
- Truncated files include `[EXPAND:filename]` marker showing total chars available
- Unread files include `[READ_MORE:filename]` marker
- Claude can request more content using these markers in its response
- Follow-up fetch reads up to 2 additional files at 4000 chars each
- Second Claude call incorporates expanded content for synthesis

*Multi-Account Support:*
- Queries both GoogleAccount.PERSONAL and GoogleAccount.WORK accounts
- Results merged and deduplicated by file ID
- Name-matched files prioritized across both accounts

*Search Optimization:*
- Keyword extraction from queries (proper nouns, meaningful terms)
- Stop words filtered (articles, pronouns, temporal words)
- Search by BOTH name and full_text for better recall
- Maximum 5 keywords used per search

---

### P3.5: Local LLM Query Router

**Requirements:**
- Local LLM (Ollama + Llama 3.2 3B) classifies queries and routes to appropriate data sources
- Runs entirely on Mac Mini M4 (16GB RAM) - no cloud calls for routing decisions
- Sub-second routing latency for responsive UX
- Intelligently combines multiple sources when query requires it

**Architecture:**
```
User Query → Local LLM Router → [Sources] → Aggregate Results → Claude Synthesis
                   ↓
            Classification:
            - vault: Obsidian notes, general knowledge
            - calendar: Schedule, meetings, events
            - gmail: Email correspondence
            - drive: Documents, spreadsheets
            - people: Person briefings, stakeholder prep
            - actions: Open tasks, commitments
```

**Local LLM Setup:**
- Framework: Ollama (brew install ollama)
- Model: Llama 3.2 3B (2GB download, ~4GB RAM when loaded)
- Runs as background service on Mac Mini
- API: `http://localhost:11434/api/generate`

**Router Prompt Template:**
```
You are a query router for a personal knowledge system. Classify the user's query into one or more data sources to search.

Available sources:
- vault: Personal notes, meeting notes, documents in Obsidian
- calendar: Google Calendar events, schedule, meetings
- gmail: Email messages, correspondence
- drive: Google Drive files, spreadsheets, documents
- people: Information about specific people, stakeholder briefings
- actions: Open tasks, action items, commitments

Respond with ONLY a JSON object like: {"sources": ["vault", "calendar"], "reasoning": "brief explanation"}

User query: {query}
```

**Router Response Schema:**
```python
{
    "sources": list[str],      # ["vault", "calendar", etc.]
    "reasoning": str,          # Brief explanation for logging
    "confidence": float,       # 0.0-1.0
    "latency_ms": int          # Router decision time
}
```

**Routing Logic:**
1. Send query to local Llama model with classification prompt
2. Parse JSON response to extract sources
3. Query each source in parallel
4. Aggregate results with source attribution
5. Pass combined context to Claude for synthesis

**Fallback Behavior:**
- If Ollama unavailable: Fall back to keyword-based routing
- If model returns invalid JSON: Default to vault search
- If confidence < 0.3: Include vault as additional source

**Process:**
1. Write tests for Ollama client (connection, query, response parsing)
2. Implement OllamaClient service with retry logic
3. Write tests for router classification accuracy
4. Implement QueryRouter service with prompt template
5. Write tests for multi-source aggregation
6. Implement parallel source querying
7. Write tests for fallback behavior
8. Implement graceful degradation
9. Integration test: end-to-end routing flow
10. Run tests, iterate until all pass

**Acceptance Criteria:**
```
[ ] Ollama installed and Llama 3.2 3B model pulled
[ ] OllamaClient connects to local Ollama server
[ ] Router correctly classifies calendar queries (>90% accuracy on test set)
[ ] Router correctly classifies email queries (>90% accuracy on test set)
[ ] Router correctly classifies drive queries (>90% accuracy on test set)
[ ] Router correctly classifies people queries (>90% accuracy on test set)
[ ] Router correctly classifies action item queries (>90% accuracy on test set)
[ ] Router correctly identifies multi-source queries
[ ] Routing latency <500ms (p95)
[ ] Fallback to keywords works when Ollama unavailable
[ ] Invalid model response falls back to vault search
[ ] Source attribution in final response shows which sources were queried
[ ] Unit tests for OllamaClient
[ ] Unit tests for QueryRouter classification
[ ] Unit tests for fallback behavior
[ ] Integration test: route query, verify correct sources queried
```

**Test Query Set (for accuracy validation):**
```python
ROUTING_TEST_CASES = [
    # Calendar queries
    ("What meetings do I have tomorrow?", ["calendar"]),
    ("When is my next 1-1 with Yoni?", ["calendar", "people"]),
    ("What's on my schedule this week?", ["calendar"]),

    # Email queries
    ("Did Kevin email me about the budget?", ["gmail"]),
    ("What did Madi say in her last email?", ["gmail", "people"]),
    ("Show me emails from last week", ["gmail"]),

    # Drive queries
    ("Find the Q4 budget spreadsheet", ["drive"]),
    ("What's in the strategy document?", ["drive", "vault"]),

    # People queries
    ("Tell me about Yoni", ["people", "vault"]),
    ("Prep me for meeting with Hayley", ["people", "vault", "calendar"]),

    # Action queries
    ("What are my open action items?", ["actions"]),
    ("What did I commit to in the last meeting?", ["actions", "vault"]),

    # Vault queries (default)
    ("What did we decide about the rebrand?", ["vault"]),
    ("Summarize the therapy session themes", ["vault"]),

    # Multi-source queries
    ("What's happening with the ML budget?", ["vault", "drive", "gmail"]),
    ("Prepare me for tomorrow", ["calendar", "actions", "vault"]),
]
```

**Completion Promise:** `<promise>P3.5-LOCAL-LLM-ROUTER-COMPLETE</promise>`

---

## Phase 4: Production Hardening

### P4.1: Service Management

**Requirements:**
- All services run as launchd daemons on Mac Mini
- Auto-start on boot
- Auto-restart on crash
- Log rotation
- Health check endpoint

**Acceptance Criteria:**
```
[ ] Services start automatically on Mac Mini boot
[ ] Services restart automatically after crash
[ ] Logs written to file with rotation (max 100MB)
[ ] Health endpoint returns service status
[ ] Can check status via `launchctl list | grep lifeos`
```

**Completion Promise:** `<promise>P4.1-SERVICE-MGMT-COMPLETE</promise>`

---

### P4.2: Error Handling & Resilience

**Requirements:**
- Graceful degradation if Google APIs unavailable
- Retry logic for transient failures
- Clear error messages to user
- No crashes on malformed input

**Acceptance Criteria:**
```
[ ] Google API timeout returns partial results + warning
[ ] Claude API timeout returns graceful error
[ ] Malformed requests return 400 with helpful message
[ ] Service continues running after any single request error
[ ] Retry logic for 5xx errors (max 3 retries)
```

**Completion Promise:** `<promise>P4.2-ERROR-HANDLING-COMPLETE</promise>`

---

## Phase 5: Enhanced Retrieval & Conversations

### P5.1: Conversation Threads

**Requirements:**
- Persist conversation history to enable multi-turn interactions
- Support multiple named conversation threads
- Resume past conversations with full context
- Include conversation history in Claude synthesis prompts
- Automatic thread titling based on first message

**Architecture:**
```
┌─────────────────────────────────────────────────────────────┐
│                      SQLite Database                         │
│  ┌─────────────────┐  ┌─────────────────────────────────┐   │
│  │  conversations  │  │           messages              │   │
│  │  - id (UUID)    │  │  - id (UUID)                    │   │
│  │  - title        │  │  - conversation_id (FK)         │   │
│  │  - created_at   │  │  - role (user/assistant)        │   │
│  │  - updated_at   │  │  - content                      │   │
│  │                 │  │  - sources (JSON)               │   │
│  │                 │  │  - routing (JSON)               │   │
│  │                 │  │  - created_at                   │   │
│  └─────────────────┘  └─────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

**API Endpoints:**
```python
# List all conversations
GET /api/conversations
Response: {
    "conversations": [
        {"id": "uuid", "title": "...", "created_at": "...", "updated_at": "...", "message_count": int}
    ]
}

# Get single conversation with messages
GET /api/conversations/{id}
Response: {
    "id": "uuid",
    "title": "...",
    "messages": [
        {"role": "user", "content": "...", "created_at": "..."},
        {"role": "assistant", "content": "...", "sources": [...], "created_at": "..."}
    ]
}

# Create new conversation
POST /api/conversations
Request: {"title": "optional title"}
Response: {"id": "uuid", "title": "..."}

# Delete conversation
DELETE /api/conversations/{id}

# Ask within conversation (streaming)
POST /api/conversations/{id}/ask
Request: {"question": "..."}
Response: SSE stream (same as /api/ask/stream but persisted)
```

**Context Window Management:**
- Include last N messages (default 10) in Claude prompt
- Truncate older messages if context exceeds limit
- Always include system prompt + current query + retrieved chunks

**Process:**
1. Write tests for SQLite conversation storage
2. Implement ConversationStore service
3. Write tests for conversation API endpoints
4. Implement conversation routes
5. Write tests for context inclusion in synthesis
6. Update synthesizer to include conversation history
7. Write tests for UI conversation list/selection
8. Update web UI with conversation sidebar
9. Integration test: full conversation flow
10. Run tests, iterate until all pass

**Acceptance Criteria:**
```
[ ] SQLite database created on first run
[ ] Conversations table stores thread metadata
[ ] Messages table stores all messages with foreign key
[ ] GET /api/conversations returns list sorted by updated_at desc
[ ] GET /api/conversations/{id} returns full message history
[ ] POST /api/conversations creates new thread, returns ID
[ ] DELETE /api/conversations/{id} removes thread and messages
[ ] POST /api/conversations/{id}/ask streams response AND persists
[ ] New conversation auto-generates title from first message
[ ] Conversation history (last 10 messages) included in Claude prompt
[ ] Context truncation works when history exceeds token limit
[ ] Web UI shows conversation list in sidebar
[ ] Web UI allows creating new conversation
[ ] Web UI allows selecting/resuming past conversation
[ ] Web UI shows conversation title
[ ] Unit tests for ConversationStore CRUD operations
[ ] Unit tests for context window management
[ ] Integration test: create conversation, send 3 messages, verify persistence
[ ] Integration test: resume conversation, verify history in context
```

**Completion Promise:** `<promise>P5.1-CONVERSATION-THREADS-COMPLETE</promise>`

---

### P5.2: Hybrid Retrieval (Dense + BM25)

**Requirements:**
- Add BM25 keyword index alongside vector embeddings
- Query both indices in parallel
- Merge results using Reciprocal Rank Fusion (RRF)
- Improve recall for exact-match queries (names, acronyms, specific terms)
- Maintain existing recency bias

**Architecture:**
```
┌─────────────────────────────────────────────────────────────┐
│                     Query Processing                         │
│                           │                                  │
│              ┌────────────┴────────────┐                    │
│              ▼                         ▼                    │
│     ┌─────────────────┐      ┌─────────────────┐           │
│     │  Vector Search  │      │   BM25 Search   │           │
│     │   (ChromaDB)    │      │   (SQLite FTS)  │           │
│     │                 │      │                 │           │
│     │  Semantic       │      │  Keyword        │           │
│     │  Similarity     │      │  Matching       │           │
│     └────────┬────────┘      └────────┬────────┘           │
│              │                         │                    │
│              └────────────┬────────────┘                    │
│                           ▼                                  │
│              ┌─────────────────────────┐                    │
│              │  Reciprocal Rank Fusion │                    │
│              │  + Recency Boost        │                    │
│              └────────────┬────────────┘                    │
│                           ▼                                  │
│              ┌─────────────────────────┐                    │
│              │    Final Ranked List    │                    │
│              └─────────────────────────┘                    │
└─────────────────────────────────────────────────────────────┘
```

**BM25 Index:**
- Use SQLite FTS5 (full-text search) for efficiency
- Index: chunk content, file name, extracted people names
- Tokenization: standard whitespace + punctuation splitting
- Store alongside ChromaDB (separate concern)

**Reciprocal Rank Fusion (RRF):**
```python
# RRF formula: score = sum(1 / (k + rank)) for each list
# k = 60 (standard constant)
# Example: doc ranked #1 in vector, #5 in BM25
# RRF = 1/(60+1) + 1/(60+5) = 0.0164 + 0.0154 = 0.0318

def reciprocal_rank_fusion(
    vector_results: list[str],  # doc IDs ranked by vector similarity
    bm25_results: list[str],    # doc IDs ranked by BM25
    k: int = 60
) -> list[tuple[str, float]]:
    scores = defaultdict(float)
    for rank, doc_id in enumerate(vector_results):
        scores[doc_id] += 1 / (k + rank + 1)
    for rank, doc_id in enumerate(bm25_results):
        scores[doc_id] += 1 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: -x[1])
```

**Combined Scoring:**
```python
final_score = rrf_score * (1 + recency_boost)
# where recency_boost = 0.0 to 0.5 based on document age
```

**Process:**
1. Write tests for SQLite FTS5 index creation
2. Implement BM25Index service with FTS5
3. Write tests for BM25 search
4. Implement BM25 search method
5. Write tests for RRF fusion
6. Implement RRF fusion logic
7. Write tests for hybrid search integration
8. Update VectorStore to use hybrid search
9. Write tests for recency + hybrid combination
10. Integrate recency boost with RRF scores
11. Benchmark: compare retrieval quality vs pure vector
12. Run tests, iterate until all pass

**Acceptance Criteria:**
```
[ ] SQLite FTS5 table created for BM25 indexing
[ ] BM25 index populated during initial indexing
[ ] BM25 index updated when documents change
[ ] BM25 search returns results ranked by term frequency
[ ] RRF fusion correctly merges two ranked lists
[ ] Hybrid search queries both indices in parallel
[ ] Hybrid search returns merged results
[ ] Recency boost applied after RRF fusion
[ ] Exact name matches ranked higher than with pure vector
[ ] Acronym searches (e.g., "ML", "Q4") return relevant docs
[ ] Hybrid search latency <500ms (p95)
[ ] Pure vector search still available as fallback
[ ] Unit tests for BM25Index CRUD
[ ] Unit tests for RRF fusion algorithm
[ ] Unit tests for hybrid search
[ ] Integration test: index docs, hybrid search, verify improved recall
[ ] Benchmark test: 10 queries comparing vector vs hybrid recall
```

**Benchmark Test Queries:**
```python
HYBRID_BENCHMARK_QUERIES = [
    # Exact match queries (should improve with BM25)
    ("Q4 budget", "should find docs with exact 'Q4 budget' mention"),
    ("ML infrastructure", "should find ML folder docs"),
    ("Yoni", "exact name match"),
    ("rebrand decision", "specific topic"),

    # Semantic queries (should stay good with vector)
    ("what are my priorities", "conceptual query"),
    ("meeting preparation tips", "semantic similarity"),

    # Mixed queries (benefit from both)
    ("Kevin email about budget", "name + topic"),
    ("therapy session insights", "topic + context"),
]
```

**Completion Promise:** `<promise>P5.2-HYBRID-RETRIEVAL-COMPLETE</promise>`

---

## Phase 6: Intelligence & Observability

### P6.1: Smart Model Selection

**Requirements:**
- Query router recommends Claude model (Haiku/Sonnet/Opus) based on query complexity
- Simple lookups and factual queries → Haiku (fast, cheap)
- Standard synthesis and reasoning → Sonnet (balanced)
- Complex multi-step reasoning, analysis → Opus (powerful, expensive)
- Cost-aware: default to cheaper models, upgrade only when needed

**Model Pricing (approximate):**
```
Haiku:  $0.25/1M input, $1.25/1M output  (~$0.001 per query)
Sonnet: $3/1M input, $15/1M output       (~$0.01 per query)
Opus:   $15/1M input, $75/1M output      (~$0.05-0.10 per query)
```

**Classification Logic:**
```python
COMPLEXITY_SIGNALS = {
    "haiku": [
        # Simple lookups
        "what time", "when is", "who is", "where is",
        "list my", "show me", "find the",
        # Single-source queries
        len(sources) == 1,
        # Short expected response
        query_type in ["lookup", "list", "simple_fact"]
    ],
    "sonnet": [
        # Standard synthesis
        "summarize", "explain", "describe",
        "what happened", "tell me about",
        # Multi-source queries
        1 < len(sources) <= 3,
        # Default for most queries
    ],
    "opus": [
        # Complex reasoning
        "analyze", "compare", "evaluate", "strategy",
        "implications", "trade-offs", "recommend",
        # Many sources or long context
        len(sources) > 3 or context_tokens > 8000,
        # Multi-step reasoning
        "step by step", "think through", "consider"
    ]
}
```

**Router Response Update:**
```python
@dataclass
class RoutingResult:
    sources: list[str]
    reasoning: str
    confidence: float
    latency_ms: int
    recommended_model: str  # NEW: "haiku", "sonnet", or "opus"
    complexity_score: float  # NEW: 0.0-1.0
```

**Process:**
1. Write tests for complexity classification
2. Update QueryRouter to assess complexity
3. Write tests for model recommendation
4. Implement model selection logic
5. Update synthesizer to use recommended model
6. Write tests for cost tracking integration
7. Integration test: verify model selection accuracy
8. Run tests, iterate until all pass

**Acceptance Criteria:**
```
[ ] Router returns recommended_model in RoutingResult
[ ] Simple queries ("What time is my meeting?") → haiku
[ ] Standard queries ("Summarize the budget discussion") → sonnet
[ ] Complex queries ("Analyze the strategic implications") → opus
[ ] Model selection adds <50ms latency
[ ] Synthesizer respects recommended model
[ ] Can override model selection via API parameter
[ ] Unit tests for complexity classification
[ ] Integration test: 10 queries, verify appropriate model selection
```

**Completion Promise:** `<promise>P6.1-SMART-MODEL-SELECTION-COMPLETE</promise>`

---

### P6.2: API Cost Tracking

**Requirements:**
- Track token usage for every Claude API call
- Calculate cost based on model and token counts
- Display cost per query in UI
- Show running totals per conversation and session
- Store cost data for historical analysis

**Architecture:**
```
┌─────────────────────────────────────────────────────────────┐
│                     API Response                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  usage: {                                            │    │
│  │    input_tokens: 1523,                              │    │
│  │    output_tokens: 487                               │    │
│  │  }                                                   │    │
│  └─────────────────────────────────────────────────────┘    │
│                           │                                  │
│                           ▼                                  │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Cost Calculator                         │    │
│  │  cost = (input_tokens * input_price) +              │    │
│  │         (output_tokens * output_price)              │    │
│  └─────────────────────────────────────────────────────┘    │
│                           │                                  │
│              ┌────────────┴────────────┐                    │
│              ▼                         ▼                    │
│     ┌─────────────┐           ┌─────────────┐              │
│     │   SQLite    │           │     UI      │              │
│     │   Storage   │           │   Display   │              │
│     └─────────────┘           └─────────────┘              │
└─────────────────────────────────────────────────────────────┘
```

**Database Schema:**
```sql
CREATE TABLE api_usage (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    message_id TEXT,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,
    created_at TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);
```

**API Response Update:**
```python
# SSE stream includes cost info
{"type": "usage", "input_tokens": 1523, "output_tokens": 487, "cost_usd": 0.0089, "model": "sonnet"}
```

**UI Display:**
```
┌─────────────────────────────────────────┐
│  Query cost: $0.009 (1.5k in / 487 out) │
│  Conversation total: $0.047             │
│  Session total: $0.23                   │
└─────────────────────────────────────────┘
```

**Process:**
1. Write tests for cost calculation
2. Implement CostTracker service
3. Write tests for usage storage
4. Implement SQLite storage for usage data
5. Write tests for SSE cost events
6. Update chat routes to emit usage events
7. Write tests for UI cost display
8. Update web UI with cost indicators
9. Integration test: full cost tracking flow
10. Run tests, iterate until all pass

**Acceptance Criteria:**
```
[ ] CostTracker calculates cost from token counts
[ ] Cost calculation accurate for all three models
[ ] Usage stored in SQLite with conversation association
[ ] SSE stream includes "type": "usage" event
[ ] UI displays cost per query
[ ] UI displays conversation running total
[ ] UI displays session running total
[ ] Historical usage queryable via API
[ ] Unit tests for cost calculation
[ ] Integration test: send query, verify cost tracked and displayed
```

**Completion Promise:** `<promise>P6.2-COST-TRACKING-COMPLETE</promise>`

---

### P6.3: Persistent Memories

**Requirements:**
- Special conversation type for storing memories
- Memories persist across all conversations
- Relevant memories surface in future query context
- UI support: "Remember this..." button or /remember command
- Memory management: view, edit, delete memories

**Architecture:**
```
┌─────────────────────────────────────────────────────────────┐
│                    Memory System                             │
│                                                              │
│  User: "Remember that Kevin prefers async communication"    │
│                           │                                  │
│                           ▼                                  │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                 Memory Store                         │    │
│  │  - id: uuid                                         │    │
│  │  - content: "Kevin prefers async communication"     │    │
│  │  - category: "people" (auto-classified)             │    │
│  │  - keywords: ["Kevin", "communication", "async"]    │    │
│  │  - created_at: timestamp                            │    │
│  │  - embedding: vector (for semantic retrieval)       │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  Future query: "Prep me for meeting with Kevin"             │
│                           │                                  │
│                           ▼                                  │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Memory Retrieval                        │    │
│  │  1. Semantic search on query                        │    │
│  │  2. Keyword match on extracted entities             │    │
│  │  3. Return top-k relevant memories                  │    │
│  └─────────────────────────────────────────────────────┘    │
│                           │                                  │
│                           ▼                                  │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Prompt Construction                     │    │
│  │  ## Your Memories                                   │    │
│  │  - Kevin prefers async communication                │    │
│  │                                                     │    │
│  │  ## Context from Vault                              │    │
│  │  [retrieved chunks...]                              │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

**Database Schema:**
```sql
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    category TEXT,  -- people, preferences, facts, decisions, etc.
    keywords TEXT,  -- JSON array of extracted keywords
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

-- Store embeddings for semantic search
CREATE TABLE memory_embeddings (
    memory_id TEXT PRIMARY KEY,
    embedding BLOB,
    FOREIGN KEY (memory_id) REFERENCES memories(id)
);
```

**API Endpoints:**
```python
# Create memory
POST /api/memories
Request: {"content": "Kevin prefers async communication"}
Response: {"id": "uuid", "content": "...", "category": "people", "keywords": [...]}

# List memories
GET /api/memories
GET /api/memories?category=people
Response: {"memories": [...]}

# Get single memory
GET /api/memories/{id}

# Update memory
PUT /api/memories/{id}
Request: {"content": "updated content"}

# Delete memory
DELETE /api/memories/{id}

# Search memories (for debugging/management)
POST /api/memories/search
Request: {"query": "Kevin"}
Response: {"memories": [...], "scores": [...]}
```

**Memory Categories (auto-classified):**
- `people` - Information about specific individuals
- `preferences` - User preferences and habits
- `facts` - Important facts to remember
- `decisions` - Past decisions and rationale
- `reminders` - Things to remember for the future
- `context` - Background context for ongoing projects

**Process:**
1. Write tests for memory storage
2. Implement MemoryStore service
3. Write tests for memory embedding
4. Implement embedding generation for memories
5. Write tests for memory retrieval
6. Implement semantic + keyword memory search
7. Write tests for prompt integration
8. Update synthesizer to include memories
9. Write tests for memory API endpoints
10. Implement memory routes
11. Write tests for UI memory features
12. Update web UI with memory button/command
13. Integration test: create memory, verify in future queries
14. Run tests, iterate until all pass

**Acceptance Criteria:**
```
[ ] Memories stored in SQLite with embeddings
[ ] Auto-categorization of memory content
[ ] Keyword extraction from memory content
[ ] Semantic search retrieves relevant memories
[ ] Memories included in prompt under "## Your Memories"
[ ] Only top-k most relevant memories included (prevent context bloat)
[ ] POST /api/memories creates new memory
[ ] GET /api/memories lists all memories
[ ] DELETE /api/memories/{id} removes memory
[ ] UI has "Remember this" button or /remember command
[ ] UI shows memory creation confirmation
[ ] UI allows viewing/managing memories
[ ] Unit tests for MemoryStore CRUD
[ ] Unit tests for memory retrieval
[ ] Integration test: create memory, new conversation, verify memory surfaces
```

**Completion Promise:** `<promise>P6.3-PERSISTENT-MEMORIES-COMPLETE</promise>`

---

### P6.4: Test Optimization

**Requirements:**
- Reduce test suite runtime from 30+ min to <5 min
- Unit tests should run in <60 seconds
- Proper test categorization with markers
- Parallel test execution support
- CI-friendly test configuration

**Test Categories:**
```python
# pytest markers
@pytest.mark.unit      # Fast, isolated tests (<1s each)
@pytest.mark.slow      # Tests requiring ChromaDB/external services
@pytest.mark.integration  # End-to-end tests
@pytest.mark.api       # Tests requiring running API server
```

**Configuration (pytest.ini):**
```ini
[pytest]
markers =
    unit: Fast unit tests (no external dependencies)
    slow: Slow tests (ChromaDB, embeddings)
    integration: End-to-end integration tests
    api: Tests requiring API server

# Default: run only fast tests
addopts = -m "not slow and not integration"

# Parallel execution
# pip install pytest-xdist
# pytest -n auto  # Use all CPU cores
```

**Lazy Import Pattern:**
```python
# BAD: Imports ChromaDB at module load
from api.services.vectorstore import VectorStore

# GOOD: Import only when needed
def get_vector_store():
    from api.services.vectorstore import VectorStore
    return VectorStore()
```

**Test Fixtures:**
```python
@pytest.fixture(scope="session")
def chromadb_client():
    """Shared ChromaDB client for all tests in session."""
    # Initialize once, reuse across tests
    ...

@pytest.fixture
def mock_vector_store():
    """Mock vector store for unit tests."""
    store = MagicMock()
    store.search.return_value = [{"id": "1", "content": "test"}]
    return store
```

**Pre-commit Hook Update:**
```bash
#!/bin/bash
# Only run fast tests before commit
pytest -m "unit" --tb=short -q
```

**CI Configuration:**
```yaml
# Run full suite in CI
test:
  script:
    - pytest tests/ -v --tb=short -n auto
  timeout: 10m
```

**Process:**
1. Audit all tests, add appropriate markers
2. Update pytest.ini with marker configuration
3. Fix slow imports (lazy loading)
4. Add session-scoped fixtures for heavy resources
5. Update pre-commit hook for fast tests only
6. Add pytest-xdist for parallel execution
7. Verify unit tests run in <60s
8. Verify full suite runs in <5min
9. Document test running conventions

**Acceptance Criteria:**
```
[ ] All tests have appropriate markers (@unit, @slow, @integration)
[ ] pytest.ini configured with default fast-only execution
[ ] Lazy imports for ChromaDB and heavy dependencies
[ ] Session-scoped fixtures for shared resources
[ ] Pre-commit hook runs only unit tests (<30s)
[ ] pytest -m "unit" completes in <60s
[ ] pytest (full suite) completes in <5min
[ ] pytest-xdist installed and working
[ ] CI configuration documented
[ ] Developer documentation for running tests
```

**Completion Promise:** `<promise>P6.4-TEST-OPTIMIZATION-COMPLETE</promise>`

---

## Phase 7: Multi-Modal Attachments

### P7.1: Multi-Modal Chat Support

**Requirements:**
Enable users to include images and files as context when asking questions. Attachments are ephemeral - sent to Claude for that single request, not stored or indexed.

**Core Use Case:**
- User drags/drops or pastes a screenshot, image, or file
- User types a question about it
- Attachment is sent to Claude Vision API alongside the query
- Claude responds with context from the attachment
- Attachment is discarded after the request (not persisted)

**Supported Attachment Types:**

| Type | Extensions | Max Size | Claude Handling |
|------|------------|----------|-----------------|
| Images | PNG, JPG, JPEG, GIF, WebP | 5MB each | Sent as base64 image blocks |
| PDFs | PDF | 10MB | Sent as document blocks |
| Text files | TXT, MD, CSV, JSON | 1MB | Decoded and appended to prompt text |

**Constraints:**
- Maximum 5 attachments per message
- Maximum 20MB total attachment size per message
- Images resized client-side if over 1568px (Claude's max dimension)

**Frontend Changes (web/index.html):**

1. **Drag-and-Drop Zone:**
   - Entire input area acts as drop zone
   - Visual feedback on drag-over (border highlight, background change)
   - Accepts files dragged from Finder/Explorer or browser

2. **Clipboard Paste:**
   - Cmd+V / Ctrl+V captures images from clipboard
   - Works with screenshots (Cmd+Shift+4 on Mac)
   - Works with copied images from browser/apps

3. **Attach Button:**
   - Paperclip icon button next to send button
   - Opens native file picker filtered to supported types

4. **Attachment Preview:**
   - Horizontal row above input field shows queued attachments
   - Image attachments show thumbnail preview
   - Non-image attachments show file icon + filename
   - X button on each to remove before sending
   - Shows file size for each attachment

5. **Send Behavior:**
   - Attachments sent as base64-encoded data with the request
   - Preview area clears after successful send
   - Attachments persist in preview if send fails

**UI Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│  [Attachment Preview Row - only visible when attachments]   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                    │
│  │ 🖼️      x│ │ 📄      x│ │ 📋      x│                    │
│  │ thumb    │ │ doc.pdf  │ │ data.csv │                    │
│  │ 245 KB   │ │ 1.2 MB   │ │ 12 KB    │                    │
│  └──────────┘ └──────────┘ └──────────┘                    │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────┐ ┌───┐ ┌───┐   │
│  │ Ask a question...                       │ │ 📎│ │ ➤ │   │
│  └─────────────────────────────────────────┘ └───┘ └───┘   │
└─────────────────────────────────────────────────────────────┘

Drag-over state: Input area border turns accent color, subtle background tint
```

**Backend Changes (api/routes/chat.py):**

1. **Updated Request Model:**
```python
class Attachment(BaseModel):
    """Single attachment in a message."""
    filename: str
    media_type: str  # MIME type: image/png, application/pdf, text/plain
    data: str        # Base64 encoded content

class AskStreamRequest(BaseModel):
    """Request for streaming ask endpoint."""
    question: str
    include_sources: bool = True
    conversation_id: Optional[str] = None
    attachments: Optional[list[Attachment]] = None  # NEW
```

2. **Validation:**
   - Reject unsupported media types (400 error)
   - Reject files over size limit (400 error)
   - Reject if total size exceeds 20MB (400 error)
   - Reject if more than 5 attachments (400 error)

3. **Processing:**
   - Pass validated attachments to synthesizer
   - Log attachment metadata (filename, type, size) but NOT content

**Synthesizer Changes (api/services/synthesizer.py):**

1. **Updated Interface:**
```python
async def stream_response(
    self,
    prompt: str,
    attachments: list[dict] = None,  # NEW: [{filename, media_type, data}]
    max_tokens: int = 1024,
    model: str = None,
    model_tier: str = None
)
```

2. **Message Construction:**
```python
def build_message_content(prompt: str, attachments: list[dict] = None):
    """Build Claude message content, handling multi-modal if needed."""
    if not attachments:
        return prompt  # Simple text message (backwards compatible)

    content = []

    # Process attachments by type
    for att in attachments:
        if att["media_type"].startswith("image/"):
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": att["media_type"],
                    "data": att["data"]
                }
            })
        elif att["media_type"] == "application/pdf":
            content.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": att["data"]
                }
            })
        elif att["media_type"].startswith("text/"):
            # Decode text files and include in prompt
            import base64
            text_content = base64.b64decode(att["data"]).decode("utf-8")
            prompt += f"\n\n--- Attached File: {att['filename']} ---\n{text_content}\n--- End of {att['filename']} ---"

    # Add text prompt (goes after images for Claude)
    content.append({"type": "text", "text": prompt})

    return content
```

3. **API Call Update:**
```python
# Current (text only):
messages=[{"role": "user", "content": prompt}]

# Updated (multi-modal):
message_content = build_message_content(prompt, attachments)
messages=[{"role": "user", "content": message_content}]
```

**Message History Display:**
- User messages that had attachments show a small indicator: "📎 2 attachments"
- Actual attachment content is NOT stored or re-displayed
- This is just a visual indicator that attachments were part of that query

**Acceptance Criteria:**

Frontend - Drag and Drop:
```
[ ] Dragging file over input area shows visual drop zone indicator
[ ] Drop zone highlight uses accent color border
[ ] Dropping valid image file creates attachment preview
[ ] Dropping valid PDF creates attachment preview with icon
[ ] Dropping valid text file creates attachment preview with icon
[ ] Dropping multiple files creates multiple attachment previews
[ ] Dropping invalid file type shows error toast/message
[ ] Dropping file over size limit shows error toast/message
[ ] Drag leave removes drop zone indicator
```

Frontend - Clipboard Paste:
```
[ ] Pasting screenshot from clipboard creates attachment preview
[ ] Pasting copied image from browser creates attachment preview
[ ] Pasting when no image in clipboard does nothing (normal paste)
[ ] Paste still works for text in input field
```

Frontend - Attach Button:
```
[ ] Paperclip button visible next to send button
[ ] Clicking opens native file picker
[ ] File picker filters to supported types
[ ] Selecting file creates attachment preview
[ ] Selecting multiple files creates multiple previews
```

Frontend - Attachment Preview:
```
[ ] Preview row only visible when attachments exist
[ ] Image attachments show thumbnail
[ ] Non-image attachments show appropriate icon
[ ] Each attachment shows filename (truncated if long)
[ ] Each attachment shows file size
[ ] X button removes attachment from queue
[ ] Maximum 5 attachments enforced client-side
[ ] Total size limit (20MB) enforced client-side
```

Frontend - Send Flow:
```
[ ] Send button works with attachments
[ ] Attachments included in request body as base64
[ ] Preview clears after successful send
[ ] Preview persists if send fails (network error, etc.)
[ ] Large images resized before base64 encoding
```

Backend - Validation:
```
[ ] Request accepts optional attachments array
[ ] Rejects unsupported media types with 400 + clear message
[ ] Rejects individual files over size limit with 400
[ ] Rejects total size over 20MB with 400
[ ] Rejects more than 5 attachments with 400
[ ] Valid requests with no attachments work unchanged
```

Backend - Processing:
```
[ ] Attachments passed to synthesizer
[ ] Attachment metadata logged (filename, type, size)
[ ] Attachment content NOT logged
```

Synthesizer - Multi-Modal:
```
[ ] stream_response accepts attachments parameter
[ ] Text-only requests work unchanged (backwards compatible)
[ ] Image attachments sent as image blocks to Claude
[ ] PDF attachments sent as document blocks to Claude
[ ] Text file attachments decoded and appended to prompt
[ ] Multiple attachments of same type handled correctly
[ ] Mixed attachment types handled correctly
[ ] Response streams correctly with attachments
```

Integration:
```
[ ] Can drag screenshot, ask "what's in this image?", get response
[ ] Can paste screenshot, ask question, get response
[ ] Can attach PDF, ask for summary, get response
[ ] Can attach CSV, ask about data, get response
[ ] Error messages are user-friendly
[ ] Mobile: attach button works (no drag-drop expected)
```

**Process:**
1. Create feature branch
2. Implement frontend attachment UI (drag-drop, paste, preview)
3. Write tests for backend attachment validation
4. Update backend request model and validation
5. Write tests for synthesizer multi-modal support
6. Update synthesizer to build multi-modal messages
7. Integration testing with real Claude API
8. Polish UX (error messages, loading states)
9. Run full test suite

**Completion Promise:** `<promise>P7.1-MULTIMODAL-COMPLETE</promise>`

---

## Configuration

**Environment Variables:**
```
LIFEOS_VAULT_PATH=/path/to/obsidian/vault
LIFEOS_CHROMA_PATH=/path/to/chromadb
LIFEOS_PORT=8080
ANTHROPIC_API_KEY=sk-...
GOOGLE_CREDENTIALS_PATH=/path/to/credentials.json
GOOGLE_TOKEN_PATH=/path/to/token.json

# Local LLM Router (P3.5)
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
OLLAMA_TIMEOUT=10  # seconds
```

**File Structure:**
```
/lifeos/
├── api/
│   ├── main.py              # FastAPI app
│   ├── routes/
│   │   ├── search.py
│   │   ├── ask.py
│   │   ├── chat.py
│   │   ├── conversations.py # Conversation threads (P5.1)
│   │   ├── calendar.py
│   │   ├── gmail.py
│   │   └── drive.py
│   └── services/
│       ├── indexer.py
│       ├── embeddings.py
│       ├── vectorstore.py
│       ├── bm25_index.py    # BM25 keyword index (P5.2)
│       ├── hybrid_search.py # RRF fusion (P5.2)
│       ├── conversation_store.py # SQLite conversations (P5.1)
│       ├── synthesizer.py
│       ├── google_auth.py
│       ├── ollama_client.py # Local LLM client (P3.5)
│       └── query_router.py  # Query routing logic (P3.5)
├── web/
│   └── index.html           # Chat UI with conversation sidebar
├── config/
│   ├── settings.py
│   └── prompts/
│       └── query_router.txt
├── data/
│   ├── chromadb/            # Vector store
│   ├── conversations.db     # SQLite conversations (P5.1)
│   └── bm25_index.db        # SQLite FTS5 index (P5.2)
├── tests/
│   ├── test_conversations.py
│   ├── test_bm25_index.py
│   ├── test_hybrid_search.py
│   └── ...
├── scripts/
│   ├── pre-commit
│   └── setup.sh
├── requirements.txt
└── README.md
```

---

## Phase 8: People System v2

### P8.1: Entity Resolution & Interaction History

**Requirements:**
Redesign people system to provide robust entity resolution across all sources with queryable interaction history. Enable queries like "Give me everything I know about the person I'm about to meet with."

**Key Changes from Current System:**
- Email becomes primary identifier (not name)
- Fuzzy name matching with vault context boost
- Domain → vault folder mapping for intelligent resolution
- Interaction log with links to sources (metadata only, not full content)

**Data Model:**

`PersonEntity` replaces `PersonRecord`:
```python
@dataclass
class PersonEntity:
    id: str                          # UUID
    canonical_name: str              # "Sarah Chen"
    display_name: str                # "Sarah Chen (Movement)" if disambiguation needed
    emails: list[str]                # Primary identifier
    linkedin_url: Optional[str]
    company: Optional[str]
    position: Optional[str]
    category: str                    # "work", "personal", "family"
    vault_contexts: list[str]        # ["Work/ML/"] - folders where they appear
    email_count: int
    meeting_count: int
    mention_count: int
    first_seen: datetime
    last_seen: datetime
    aliases: list[str]
    confidence_score: float          # 0.0-1.0
```

`Interaction` - lightweight record with links:
```python
@dataclass
class Interaction:
    id: str
    person_id: str
    timestamp: datetime
    source_type: str                 # "gmail" | "calendar" | "vault" | "granola"
    title: str                       # Email subject, meeting title, note filename
    snippet: Optional[str]           # First 100 chars
    source_link: str                 # Gmail URL, obsidian:// link, calendar URL
    source_id: Optional[str]
```

**Entity Resolution Algorithm:**

1. **Pass 1 - Email Anchoring:** Same email across sources = same person
2. **Pass 2 - Fuzzy Matching:** Score candidates by name similarity + context boost
3. **Pass 3 - Disambiguation:** If ambiguous, create separate entities ("Sarah (Movement)" vs "Sarah (Murmuration)")

**Configuration:**
```python
DOMAIN_CONTEXT_MAP = {
    "movementlabs.xyz": ["Work/ML/"],
    "murmuration.org": ["Personal/zArchive/Murm/"],
    "bluelabs.com": ["Personal/zArchive/BlueLabs/"],
}

COMPANY_NORMALIZATION = {
    "Movement Labs": {"domains": ["movementlabs.xyz"], "vault_contexts": ["Work/ML/"]},
    "Murmuration": {"domains": ["murmuration.org"], "vault_contexts": ["Personal/zArchive/Murm/"]},
}
```

**Sync Strategy:**
- Nightly: Incremental sync (24h of new data), ~2-5 min
- Query-time: Per-person refresh with 15-30 min cache TTL
- On-demand: Full historical sync available (`?full=true`)

**Interaction Display Format:**
```markdown
## Sarah Chen — Interaction History

**Summary:** 12 interactions since Oct 2025 | Last: 3 days ago
📧 5 emails | 📅 4 meetings | 📝 3 notes

### Recent Activity
- 📅 Jan 6: 1:1 re: Q1 planning — [View in Calendar](link)
- 📧 Jan 4: Re: Budget draft — [View in Gmail](link)
- 📝 Jan 3: ML Strategy meeting notes — [[ML Strategy meeting notes]]
```

**Process:**
1. Create domain/company mapping configuration
2. Write tests for entity resolution algorithm
3. Implement PersonEntity model and storage
4. Implement entity resolver with fuzzy matching
5. Write tests for interaction storage
6. Implement Interaction SQLite table and CRUD
7. Update BriefingsService to include interaction history
8. Update API routes to return new fields
9. Migration: convert existing people_aggregated.json
10. Integration testing

**Acceptance Criteria:**
```
[ ] Email-based matching works across Gmail/Calendar/LinkedIn
[ ] Fuzzy name matching with context boost works for vault mentions
[ ] Ambiguous names create separate entities with disambiguation suffix
[ ] LinkedIn company names resolve to email domains
[ ] Confidence scores track merge quality
[ ] Interactions stored with metadata + links (no full content)
[ ] Query by person returns reverse-chronological list
[ ] 90-day default window, expandable per-query
[ ] Source badges display correctly
[ ] All links functional (Gmail, Calendar, Obsidian)
[ ] Nightly sync completes in <5 min
[ ] Query-time refresh with cache TTL works
[ ] Full historical sync available on-demand
[ ] BriefingsService includes interaction history
[ ] Existing vault search with people filter still works
[ ] Existing action items by person still works
[ ] No regression in existing functionality
```

**Design Document:** See `docs/plans/2026-01-09-people-system-v2-design.md` in repo for full technical details.

**Completion Promise:** `<promise>P8.1-PEOPLE-V2-COMPLETE</promise>`

---

### P8.2: Data Migration & Source Integration

**Requirements:**
Integrate People System v2 with existing data sources to populate entities and interactions.

**Components:**

1. **Data Migration Script** (`scripts/migrate_people_v1_to_v2.py`)
   - Import ~1,900 records from `people_aggregated.json`
   - Convert PersonRecord → PersonEntity using `from_person_record()`
   - Apply entity resolution to detect duplicates
   - Infer vault_contexts from related_notes paths
   - Generate migration report with merge decisions

2. **Gmail Integration**
   - Query sent emails only (`in:sent`) to capture intentional communication
   - Filter out commercial emails (noreply, marketing, mailchimp, etc.)
   - Use EntityResolver to resolve recipients by email
   - Create Interaction for each email touchpoint
   - Update entity email_count and last_seen

3. **Calendar Integration**
   - Process all events with attendees (no attendee count limit)
   - Skip all-day events without attendees
   - Skip declined events
   - Use EntityResolver to resolve attendees by name/email
   - Create Interaction for each meeting
   - Update entity meeting_count and last_seen

4. **Vault Indexer Integration**
   - Hook into existing people extraction in indexer.py
   - Use EntityResolver with context_path for domain boost
   - Create Interaction for vault mentions
   - Context mapping:
     - `Work/ML/` ↔ `movementlabs.xyz`, `movementlabs.com`
     - `Personal/zArchive/Murm/` ↔ `murmuration.org`
     - `Personal/zArchive/BlueLabs/` ↔ `bluelabs.com`
     - `Personal/zArchive/Deck/` ↔ `deck.tools`
   - Update entity mention_count and related_notes

5. **Orchestration & Scheduling**

   **Nightly Sync (3 AM Eastern):**
   The `_nightly_sync_loop()` in `main.py` runs the following operations in order:

   1. **Vault Reindex** - Full reindex of all vault notes
      - Triggers `_sync_people_to_v2()` hook for each file
      - Extracts people mentions and creates vault interactions
      - Updates entity mention_count and related_notes

   2. **LinkedIn Sync** - Processes `./data/LinkedInConnections.csv`
      - Creates/updates entities with company, position, LinkedIn URL
      - Runs first to provide company context for email matching

   3. **Gmail Sync** - Queries sent emails from last 24h
      - Only processes `in:sent` emails (intentional communication)
      - Filters out commercial/automated emails
      - Creates email interactions

   4. **Calendar Sync** - Queries meetings from last 24h
      - Processes both PERSONAL and WORK calendars
      - Creates meeting interactions for each attendee

   **Real-Time Processing:**
   - Granola notes: Watched by `GranolaProcessor`, processed immediately
   - Calendar events: Indexed 3x daily (8 AM, noon, 3 PM) for search

   **Assumptions:**
   - LinkedIn CSV is manually updated when new export is downloaded
   - All vault notes (not just Granola) are reindexed nightly
   - Gmail/Calendar APIs are available at 3 AM (no rate limiting expected)
   - Mac Mini is always on and running the API server

**Email Exclusion Patterns:**
```python
EXCLUDED_EMAIL_PATTERNS = [
    r".*noreply.*",
    r".*no-reply.*",
    r".*notifications?@.*",
    r".*marketing@.*",
    r".*support@.*",
    r".*@mailchimp\.com",
    r".*@sendgrid\..*",
    r".*@intercom\..*",
]
```

**Acceptance Criteria:**
```
[ ] Migration script imports all v1 records without data loss
[ ] Migration creates backup of original people_aggregated.json
[ ] Duplicate detection identifies same person across sources
[ ] LinkedIn sync creates entities with company/position/URL
[ ] Gmail sync only processes sent emails
[ ] Commercial/automated emails filtered out
[ ] Calendar sync processes all meetings regardless of size
[ ] Declined events skipped
[ ] Vault indexer resolves people with context boost
[ ] Domain → vault context mapping works bidirectionally
[ ] Interactions created with valid source links
[ ] Gmail links open correct email
[ ] Calendar links open correct event
[ ] Obsidian links open correct note
[ ] Nightly sync runs at 3 AM: vault reindex → LinkedIn → Gmail → Calendar
[ ] Nightly sync completes successfully in <5 min
[ ] No regression in existing people search/filter functionality
```

**Design Document:** See `docs/plans/2026-01-09-people-system-v2-integration-design.md` for full details.

**Completion Promise:** `<promise>P8.2-PEOPLE-V2-INTEGRATION-COMPLETE</promise>`

---

### P8.3: Phone Contacts Import

**Requirements:**
Import phone contacts from CSV export to enhance people entities with phone numbers and fill gaps in contact information.

**Data Source:**
- One-time CSV export from iOS Contacts app: `data/phonecontacts*.csv`
- ~1175 contacts with fields: First Name, Last Name, Display Name, Nickname, E-mail Address (1-3), Home Phone, Business Phone, Home Fax, Business Fax, Pager, Mobile Phone, Organization, Notes

**Processing Logic:**

1. **Parse CSV** using Python csv module
2. **For each contact:**
   - Normalize phone numbers to E.164 format (+1XXXXXXXXXX)
   - Collect all email addresses (up to 3 per contact)
   - Build full name from First + Last, or use Display Name
3. **Entity Resolution:**
   - First try: Match by email address (highest confidence)
   - Second try: Match by exact name (after normalization)
   - Third try: Fuzzy match by name with >90% similarity
   - If no match: Create new entity
4. **Update matched entities:**
   - Add phone numbers to entity (primary key: phone number list)
   - Add any new email addresses found
   - Set/update company from Organization field
   - Store original CSV record in notes for reference
5. **Track import statistics:**
   - Matched by email
   - Matched by exact name
   - Matched by fuzzy name
   - New entities created
   - Skipped (insufficient data)

**Phone Number Normalization:**
```python
def normalize_phone(raw: str) -> Optional[str]:
    """
    Normalize phone number to E.164 format.

    Examples:
    - "(901) 229-5017" → "+19012295017"
    - "901-229-5017" → "+19012295017"
    - "+1 901 229 5017" → "+19012295017"
    - "9012295017" → "+19012295017"  (assumes US)
    """
    digits = re.sub(r'\D', '', raw)
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits[0] == '1':
        return f"+{digits}"
    elif len(digits) > 11:
        return f"+{digits}"  # International
    return None  # Invalid
```

**PersonEntity Updates:**
```python
@dataclass
class PersonEntity:
    # ... existing fields ...
    phone_numbers: list[str]  # NEW: E.164 format phones
    phone_primary: Optional[str]  # NEW: Preferred phone (mobile > business > home)
```

**Script:** `scripts/import_phone_contacts.py`
- Standalone script for one-time or periodic import
- Can be run manually or triggered via API
- Idempotent: safe to run multiple times

**Acceptance Criteria:**
```
[ ] CSV parser handles all contact fields correctly
[ ] Phone numbers normalized to E.164 format
[ ] US numbers assumed for 10-digit inputs
[ ] International numbers preserved
[ ] Invalid phone numbers (< 10 digits) skipped with warning
[ ] Email-based matching works across multiple email fields
[ ] Exact name matching uses normalized names (lowercase, trimmed)
[ ] Fuzzy name matching uses >90% threshold
[ ] New entities created only when no match found
[ ] Existing entities updated with new phone numbers
[ ] Duplicate phone numbers not added
[ ] Import statistics logged and returned
[ ] Script is idempotent (re-running doesn't duplicate data)
[ ] Unit tests for phone normalization
[ ] Unit tests for entity matching logic
[ ] Integration test: import sample contacts, verify entity updates
```

**Completion Promise:** `<promise>P8.3-PHONE-CONTACTS-COMPLETE</promise>`

---

### P8.4: iMessage Integration

**Requirements:**
Export iMessage history to local SQLite database and join with people entities to enable queries like "what have I discussed with [person] over text?" and "show me my recent text conversations."

**Architecture:**
```
┌─────────────────────────────────────────────────────────────┐
│                   iMessage Integration                       │
│                                                              │
│  ┌────────────────┐    ┌─────────────────┐                  │
│  │ ~/Library/     │    │ scripts/        │                  │
│  │ Messages/      │───▶│ export_imessage │                  │
│  │ chat.db        │    │ .py             │                  │
│  │ (289k msgs)    │    └────────┬────────┘                  │
│  └────────────────┘             │                           │
│                                 ▼                           │
│  ┌─────────────────────────────────────────┐               │
│  │          data/imessage.db                │               │
│  │  ┌──────────────┐  ┌──────────────────┐ │               │
│  │  │   messages   │  │   sync_state     │ │               │
│  │  │ - rowid      │  │ - last_rowid     │ │               │
│  │  │ - phone      │  │ - last_sync      │ │               │
│  │  │ - timestamp  │  │                  │ │               │
│  │  │ - is_from_me │  └──────────────────┘ │               │
│  │  │ - text       │                       │               │
│  │  │ - person_id  │◀──────────────────────┤               │
│  │  └──────────────┘   EntityResolver      │               │
│  └─────────────────────────────────────────┘               │
│                                                              │
│                         │                                    │
│                         ▼                                    │
│  ┌─────────────────────────────────────────┐               │
│  │              BriefingsService            │               │
│  │  "What have I texted Taylor about?"     │               │
│  │  → Query imessage.db WHERE person_id    │               │
│  │  → Return recent messages + summary     │               │
│  └─────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────┘
```

**Data Source:**
- macOS iMessage database: `~/Library/Messages/chat.db`
- ~289k messages from 2016 to present
- ~2755 unique phone numbers/email addresses

**Export Database Schema:**
```sql
-- Main messages table
CREATE TABLE messages (
    rowid INTEGER PRIMARY KEY,  -- Original ROWID from chat.db
    phone TEXT NOT NULL,        -- E.164 format or email
    timestamp DATETIME NOT NULL,
    is_from_me INTEGER NOT NULL,
    text TEXT,
    has_attachment INTEGER DEFAULT 0,
    attachment_filename TEXT,
    person_id TEXT,             -- FK to people entity (populated by resolver)
    UNIQUE(rowid)
);

CREATE INDEX idx_messages_phone ON messages(phone);
CREATE INDEX idx_messages_timestamp ON messages(timestamp);
CREATE INDEX idx_messages_person_id ON messages(person_id);

-- Sync state tracking
CREATE TABLE sync_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_rowid INTEGER DEFAULT 0,
    last_sync DATETIME
);
```

**Export Script:** `scripts/export_imessage.py`

1. **Initial Full Export:**
   - Query all messages from chat.db
   - Join with handle table to get phone/email
   - Convert Apple timestamp to ISO 8601
   - Normalize phone numbers to E.164
   - Store in data/imessage.db
   - Track highest ROWID for incremental

2. **Incremental Export (nightly):**
   - Read last_rowid from sync_state
   - Query only WHERE ROWID > last_rowid
   - Append new messages
   - Update sync_state

**Apple Timestamp Conversion:**
```python
def apple_to_datetime(apple_timestamp: int) -> datetime:
    """
    Convert Apple CFAbsoluteTime (nanoseconds since 2001-01-01) to datetime.
    """
    # Apple epoch is 2001-01-01 00:00:00 UTC
    # Unix epoch is 1970-01-01 00:00:00 UTC
    # Difference: 978307200 seconds
    unix_timestamp = (apple_timestamp / 1_000_000_000) + 978307200
    return datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)
```

**Entity Resolution:**

After export, run entity resolution to link messages to people:

```python
def resolve_imessage_entities():
    """
    Link messages to PersonEntity records by phone number.
    """
    resolver = get_entity_resolver()

    # Get all unique phones from messages without person_id
    unresolved = db.execute("""
        SELECT DISTINCT phone FROM messages
        WHERE person_id IS NULL
    """).fetchall()

    for (phone,) in unresolved:
        # Try to resolve by phone number
        entity = resolver.resolve_by_phone(phone)
        if entity:
            db.execute("""
                UPDATE messages SET person_id = ? WHERE phone = ?
            """, (entity.id, phone))

    db.commit()
```

**EntityResolver Update:**
```python
class EntityResolver:
    def resolve_by_phone(self, phone: str) -> Optional[PersonEntity]:
        """
        Find entity by phone number.

        Args:
            phone: E.164 format phone number

        Returns:
            Matching PersonEntity or None
        """
        normalized = normalize_phone(phone)
        if not normalized:
            return None

        # Search entities with matching phone
        for entity in self.entities.values():
            if normalized in entity.phone_numbers:
                return entity

        return None
```

**Interaction Creation:**

Don't create individual Interaction records for every message (too many). Instead:
- Create one Interaction per person per day with iMessage activity
- Store message count and snippet of most recent message
- Link type: "imessage"

```python
@dataclass
class Interaction:
    # ... existing fields ...
    source_type: str  # "gmail" | "calendar" | "vault" | "granola" | "imessage"
    message_count: Optional[int]  # For imessage: number of messages that day
```

**BriefingsService Integration:**

Add iMessage context to person briefings:

```python
def get_person_briefing(self, name: str) -> dict:
    # ... existing code ...

    # Add iMessage summary
    if entity.phone_numbers:
        imessage_stats = self._get_imessage_stats(entity.id)
        briefing["imessage"] = {
            "total_messages": imessage_stats["total"],
            "messages_sent": imessage_stats["sent"],
            "messages_received": imessage_stats["received"],
            "last_text": imessage_stats["last_timestamp"],
            "recent_topics": imessage_stats["recent_topics"],  # Optional: Claude summary
        }
```

**Query Examples:**
- "What have I texted Taylor about recently?" → Query messages by person_id, summarize
- "When did I last text Mom?" → Query MAX(timestamp) WHERE person_id = X
- "Show me my text conversations from last week" → Query and group by person

**Nightly Sync Addition:**

Add to `_nightly_sync_loop()` in main.py:

```python
# === Step 4: iMessage Incremental Export ===
try:
    logger.info("Nightly sync: Starting iMessage export...")
    from scripts.export_imessage import incremental_export
    imessage_stats = incremental_export()
    logger.info(f"Nightly sync: iMessage export completed: {imessage_stats}")
except Exception as e:
    logger.error(f"Nightly sync: iMessage export failed: {e}")
```

**Acceptance Criteria:**

Export Script:
```
[ ] Reads from ~/Library/Messages/chat.db successfully
[ ] Converts Apple timestamps to ISO 8601 correctly
[ ] Normalizes phone numbers to E.164 format
[ ] Handles email-based iMessage IDs (keep as-is)
[ ] Creates data/imessage.db with correct schema
[ ] Full export completes in <5 minutes for 289k messages
[ ] Incremental export only processes new messages (ROWID > last_rowid)
[ ] sync_state table tracks last processed ROWID
[ ] Attachment metadata (filename, has_attachment) captured
[ ] Actual attachment files NOT copied (metadata only)
[ ] Script handles missing/locked chat.db gracefully
```

Entity Resolution:
```
[ ] resolve_by_phone finds entities with matching phone numbers
[ ] Phone normalization handles various input formats
[ ] Messages linked to person_id after resolution
[ ] Unresolved phones logged for manual review
[ ] Re-running resolution updates newly matched phones
```

Interaction Creation:
```
[ ] One Interaction per person per day (not per message)
[ ] Interaction includes message count
[ ] source_type = "imessage"
[ ] source_link points to Messages app (messages://)
```

Briefings Integration:
```
[ ] Person briefing includes iMessage stats when phone numbers exist
[ ] Stats show: total messages, sent/received split, last text date
[ ] "What have I texted X about?" returns relevant summary
[ ] Query latency <2 seconds for message search
```

Nightly Sync:
```
[ ] Incremental export runs after Gmail/Calendar sync
[ ] New messages exported and entities resolved
[ ] Sync completes in <30 seconds for typical daily volume
[ ] Failures logged but don't block other sync operations
```

Tests:
```
[ ] Unit tests for Apple timestamp conversion
[ ] Unit tests for phone number normalization
[ ] Unit tests for entity phone matching
[ ] Integration test: export sample messages, verify resolution
[ ] Integration test: briefing includes iMessage stats
```

**Completion Promise:** `<promise>P8.4-IMESSAGE-INTEGRATION-COMPLETE</promise>`

---

## Success Metrics

After Phase 2 complete:
- Can ask "What did we decide about X?" and get accurate answer with sources
- Can ask "Prep me for meeting with Y" and get useful context
- Query latency <3 seconds
- Save to vault produces well-organized notes

After Phase 3 complete:
- Can ask about calendar, email, drive seamlessly
- "What's on my calendar tomorrow?" works
- "Did X email me about Y?" works

---

## Out of Scope (See Backlog [[LifeOS Backlog]])

- Proactive notifications
- Voice input
- Slack/Telegram interface
- Multi-step reasoning

*Note: Lightweight orchestrator agent moved to P3.5 (Local LLM Query Router)*
*Note: Conversation threads moved to P5.1*
*Note: Hybrid retrieval moved to P5.2*

---

*Last updated: 2026-01-09*

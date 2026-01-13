# Instructions for AI Coding Agents

This file contains critical instructions for AI agents (Claude, Cursor, Copilot, etc.) working on this codebase. Read this thoroughly before making changes.

## Server Management — CRITICAL

**NEVER run uvicorn or start the server directly.** Always use the provided scripts:

```bash
./scripts/server.sh start    # Start server
./scripts/server.sh stop     # Stop server
./scripts/server.sh restart  # Restart after code changes
./scripts/server.sh status   # Check if running
```

### Why This Matters

Running `uvicorn api.main:app` directly causes **ghost server processes**:

1. The script binds to `0.0.0.0:8000` (all interfaces including Tailscale)
2. Direct uvicorn often binds only to `127.0.0.1:8000` (localhost)
3. This creates TWO servers on different interfaces
4. User sees different behavior via localhost vs Tailscale/network
5. Code changes appear to "not work" because the wrong server handles requests

The `server.sh` script prevents this by:
- Killing ALL existing server processes first
- Binding to `0.0.0.0` (required for Tailscale access)
- Waiting for health check before returning
- Cleaning up stale HuggingFace lock files

### After Code Changes

Always restart the server after modifying Python files:

```bash
./scripts/server.sh restart
```

The server does NOT auto-reload. Changes won't take effect until restart.

---

## Hybrid Search System

LifeOS uses a hybrid search system combining vector similarity and keyword matching. Understanding this is essential for debugging search issues or extending search functionality.

### The 5-Stage Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  User Query: "What is Al's phone number?"                                    │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Stage 1: PERSON NAME EXPANSION                                              │
│                                                                              │
│  • "Al's phone" → "Alex's phone"                                            │
│  • Configured via config/people_dictionary.json                              │
│  • Handles possessives: "Al's" and "als" both → "Alex's"                    │
│  • ALIAS_MAP built at startup from people_dictionary.json                    │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Stage 2: DUAL SEARCH (parallel)                                             │
│                                                                              │
│  ┌─────────────────────────────┐    ┌─────────────────────────────┐         │
│  │ Vector Search (ChromaDB)   │    │ BM25 Search (SQLite FTS5)  │         │
│  │                            │    │                            │         │
│  │ • Semantic similarity      │    │ • Exact keyword matching   │         │
│  │ • all-MiniLM-L6-v2 model   │    │ • Porter stemmer tokenizer │         │
│  │ • Good for concepts        │    │ • OR semantics (any term)  │         │
│  │ • May miss exact terms     │    │ • Finds names, IDs, codes  │         │
│  └─────────────────────────────┘    └─────────────────────────────┘         │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Stage 3: RECIPROCAL RANK FUSION (RRF)                                       │
│                                                                              │
│  Formula: score(doc) = Σ 1/(k + rank)  where k=60                           │
│                                                                              │
│  • Merges ranked lists without score normalization                           │
│  • Documents found by BOTH methods score higher                              │
│  • k=60 is standard constant from academic literature                        │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Stage 4: SCORE BOOSTING                                                     │
│                                                                              │
│  Recency Boost (0-50%):                                                      │
│  • Today: +50%, 6 months: ~25%, 1+ year: +0%                                │
│  • Exponential decay: boost = 0.5 × (1 - (days/365)^0.5)                    │
│                                                                              │
│  Filename Boost (2x multiplier):                                             │
│  • If person name in query matches filename → double the score              │
│  • "Alex's phone" + "Alex.md" → 2x boost applied                            │
│  • Critical for person-specific queries                                      │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Stage 5: FINAL RANKING                                                      │
│                                                                              │
│  Results sorted by: hybrid_score = rrf_score × (1 + recency) × filename     │
│  Return top_k results (default 20)                                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions & Rationale

| Decision | Problem It Solves |
|----------|-------------------|
| **BM25 uses OR semantics** | AND requires ALL terms to match. Query "Alex phone birthday" would fail because no single chunk contains all three terms. OR finds chunks with ANY term. |
| **Filename boost is 2x** | Without this, a file mentioning "phone" 10 times could outrank "Alex.md" when user asks about "Alex's phone". Person-specific files must rank first. |
| **Possessive handling** | "Alex's" must become "alex" (not "alexs") for ALIAS_MAP lookup. We strip `'s` before the lookup. |
| **Query sanitization** | FTS5 has special syntax chars that cause errors: `'`, `"`, `?`, `.` must be stripped. |
| **Stop word removal** | Words like "what", "is", "the" add noise. Removed before BM25 search. |

### Search-Related Files

| File | Purpose |
|------|---------|
| `api/services/hybrid_search.py` | Main orchestrator - runs the 5-stage pipeline |
| `api/services/bm25_index.py` | SQLite FTS5 keyword index |
| `api/services/vectorstore.py` | ChromaDB vector search wrapper |
| `api/services/people.py` | Builds ALIAS_MAP from people_dictionary.json |
| `api/routes/search.py` | `/api/search` endpoint |
| `config/people_dictionary.json` | Known people and their aliases |
| `data/bm25_index.db` | SQLite database for BM25 (auto-created) |
| `data/chromadb/` | ChromaDB vector store (auto-created) |

### Debugging Search Issues

**Problem: Search not finding expected content**

```bash
# 1. Check if content exists in BM25 index
sqlite3 ./data/bm25_index.db "SELECT doc_id, substr(content,1,100) FROM chunks_fts WHERE content LIKE '%search_term%'"

# 2. Check if person alias is configured
cat config/people_dictionary.json | jq '.Alex'

# 3. Test search API directly and inspect scores
curl -s -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "your query here"}' | jq '.results[:5] | .[] | {file_name, score}'

# 4. Check server logs for expansion/search details
tail -f logs/server.log | grep -i "expand\|search\|bm25"

# 5. Verify correct server is running (not ghost process)
./scripts/server.sh status
```

**Problem: Person name not expanding**

1. Check `config/people_dictionary.json` has the alias
2. Restart server after editing: `./scripts/server.sh restart`
3. ALIAS_MAP is built at import time, requires restart

**Problem: File ranks too low despite containing the answer**

1. Check if filename boost is applying (person name must match)
2. Verify the chunk containing the answer is indexed
3. Consider if the query has too many terms (dilutes relevance)

### Adding New People

To enable nickname expansion for a new person:

```json
// config/people_dictionary.json
{
  "Alex": {
    "canonical": "Alex",
    "aliases": ["Al", "Alexander", "alex"],
    "category": "family"
  }
}
```

Then restart: `./scripts/server.sh restart`

Now queries like "Al's birthday" will expand to "Alex's birthday" and Alex.md will get the 2x filename boost.

---

## Architecture Overview

### Data Flow

```
User Query → Query Router (Ollama) → Data Source → Synthesizer (Claude) → Response
                    ↓
            Routes to: vault, calendar, gmail, drive, imessage, people, actions, memories
```

### Core Services

| Service | Location | Purpose |
|---------|----------|---------|
| Query Router | `api/services/query_router.py` | LLM routes queries to data sources |
| Hybrid Search | `api/services/hybrid_search.py` | Vector + BM25 search |
| Synthesizer | `api/services/synthesizer.py` | Claude generates responses |
| Indexer | `api/services/indexer.py` | Indexes vault files |
| Chunker | `api/services/chunker.py` | Splits documents for embedding |

### Data Sources

| Source | Service | Description |
|--------|---------|-------------|
| Vault | `hybrid_search.py` | Obsidian notes (ChromaDB + BM25) |
| Calendar | `calendar.py` | Google Calendar events |
| Gmail | `gmail.py` | Email messages |
| Drive | `drive.py` | Google Drive files |
| iMessage | `imessage.py` | macOS Messages database |
| People | `people_aggregator.py` | Cross-source person profiles |

---

## Development Workflow

### Making Changes

1. **Edit code**
2. **Restart server**: `./scripts/server.sh restart`
3. **Test manually** or run tests: `./scripts/test.sh`
4. **Deploy**: `./scripts/deploy.sh "Your commit message"`

### Testing

```bash
./scripts/test.sh              # Unit tests (fast, ~30s)
./scripts/test.sh integration  # Requires running server
./scripts/test.sh browser      # Playwright UI tests
./scripts/test.sh smoke        # Unit + critical browser (used by deploy)
./scripts/test.sh all          # Everything
```

### Key Scripts

| Script | Purpose |
|--------|---------|
| `./scripts/server.sh` | Start/stop/restart server |
| `./scripts/deploy.sh` | Test → restart → commit → push |
| `./scripts/test.sh` | Run test suites |
| `./scripts/service.sh` | launchd service management |

---

## Common Mistakes to Avoid

1. **Running uvicorn directly** → Use `./scripts/server.sh start`
2. **Forgetting to restart after code changes** → Use `./scripts/server.sh restart`
3. **Committing without testing** → Use `./scripts/deploy.sh`
4. **Editing people_dictionary.json without restart** → ALIAS_MAP requires restart
5. **Using AND semantics in BM25** → Use OR, AND fails for multi-term queries
6. **Assuming vector search finds everything** → BM25 needed for exact matches
7. **Starting server on localhost only** → Must use 0.0.0.0 for Tailscale

---

## Environment & Configuration

### Key Environment Variables (`.env`)

```bash
LIFEOS_VAULT_PATH=/path/to/obsidian/vault    # Required
LIFEOS_CHROMA_PATH=./data/chromadb           # Vector store location
ANTHROPIC_API_KEY=sk-ant-...                 # For Claude synthesis
OLLAMA_HOST=http://localhost:11434           # Local LLM for routing
```

### Configuration Files

| File | Purpose |
|------|---------|
| `.env` | Environment variables |
| `config/settings.py` | Pydantic settings model |
| `config/people_dictionary.json` | Known people and aliases |
| `config/gdoc_sync.yaml` | Google Docs to sync |
| `config/prompts/query_router.txt` | LLM routing prompt |

---

## Nightly Sync

Automated sync runs at **3 AM Eastern** daily:

1. **Vault Reindex** — Full reindex of Obsidian notes
2. **People Sync** — LinkedIn CSV, Gmail, Calendar contacts
3. **Google Docs Sync** — Configured docs → vault as Markdown
4. **iMessage Sync** — Export new messages from macOS

Manual trigger: `./scripts/server.sh restart` (runs startup tasks)

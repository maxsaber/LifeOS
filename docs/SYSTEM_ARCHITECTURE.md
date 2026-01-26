# LifeOS System Architecture

## Overview

LifeOS is a personal knowledge management system that indexes your Obsidian vault, calendar, messages, and other data sources for semantic search and AI-powered retrieval.

---

## Scheduled & Continuous Processes

### Summary

| Process | Schedule | Reads From | Writes To |
|---------|----------|------------|-----------|
| **Launchd API Service** | Continuous (boot) | All data | API logs |
| **Nightly Sync** | Daily 3:00 AM ET | Vault, Gmail, Calendar, LinkedIn, iMessages | ChromaDB, BM25, Vault, PersonEntity |
| **Calendar Indexer** | 8 AM, 12 PM, 3 PM ET | Google Calendar (personal + work) | ChromaDB (`lifeos_calendar`) |
| **Vault File Watcher** | Continuous (event-based) | Vault filesystem | ChromaDB, BM25 |
| **Granola Processor** | Every 5 minutes | `Granola/` folder | Vault (classified files) |
| **Omi Processor** | Every 5 minutes | `Omi/Events/` folder | Vault (classified files) |

---

## Process Details

### 1. Launchd API Service

**Purpose**: Starts the LifeOS FastAPI application on system boot

**Configuration**: `config/launchd/com.lifeos.api.plist`

- Host: `0.0.0.0`, Port: `8000`
- Working directory: `/Users/nathanramia/Documents/Code/LifeOS`
- Auto-restart on crash (KeepAlive + ThrottleInterval 10s)
- Logs: `./logs/lifeos-api.log` + `./logs/lifeos-api-error.log`

---

### 2. Nightly Sync (3:00 AM Eastern)

**Purpose**: Coordinated multi-step sync running daily at 3 AM

**Code**: `api/main.py:46-137`

**Steps** (60-second delays between each):

| Step | Process | Reads | Writes |
|------|---------|-------|--------|
| 1 | Vault Reindex | All vault `.md` files | ChromaDB, BM25 index |
| 2 | People v2 Sync | LinkedIn CSV, Gmail (24h), Calendar (24h) | PersonEntity, InteractionStore |
| 3 | Google Docs Sync | Configured Google Docs | Vault markdown files |
| 4 | iMessage Sync | macOS Messages DB | `data/imessage.db`, PersonEntity |

**Error Handling**: Each step catches exceptions independently and continues to next step.

---

### 3. Calendar Indexer

**Purpose**: Fetches Google Calendar events and indexes them for semantic search

**Schedule**: 8:00 AM, 12:00 PM, 3:00 PM Eastern

**Code**: `api/services/calendar_indexer.py:300-329`

**Data Flow**:
- Reads: Google Calendar API (personal + work accounts)
- Stores: Past 30 days + future 30 days of events
- Writes: ChromaDB `lifeos_calendar` collection

---

### 4. Vault File Watcher

**Purpose**: Real-time monitoring of vault filesystem changes

**Code**: `api/services/indexer.py:37-88`

**Behavior**:
- Trigger: Immediate on file create/modify/delete/move
- Debounce: 1 second delay to batch rapid changes
- Actions:
  - File created → `index_file()`
  - File modified → `index_file()`
  - File deleted → `delete_file()`
  - File moved → `delete_file()` + `index_file()`

---

### 5. Granola Processor

**Purpose**: Monitors `Granola/` folder for meeting notes, classifies by content, moves to appropriate vault folders

**Schedule**: Every 5 minutes

**Code**: `api/services/granola_processor.py:121-151`

**Classification Rules** (priority order):
1. Filename patterns (highest priority)
2. 1-1 meetings with known ML people
3. Content patterns (therapy, hiring, strategy, union, personal)
4. Default: `Work/ML/Meetings`

**Deduplication**: Tracks `granola_id` in frontmatter to prevent duplicates

---

### 6. Omi Processor

**Purpose**: Monitors `Omi/Events/` folder for event notes from Omi wearable

**Schedule**: Every 5 minutes

**Code**: `api/services/omi_processor.py:83-101`

**Output Folders**:
- `Personal/Omi` (default)
- `Personal/Self-Improvement/Therapy and coaching/Omi` (therapy)
- `Work/ML/Meetings/Omi` (work events)

---

## Data Stores

| Store | Location | Purpose | Updated By |
|-------|----------|---------|------------|
| **ChromaDB** | `data/chromadb/` | Vector embeddings for semantic search | Nightly reindex, File watcher, Calendar indexer |
| **BM25 Index** | `data/chromadb/bm25_index.db` | Keyword-based search | Nightly reindex, File watcher |
| **Vault** | `~/Notes 2025/` (configurable) | Primary knowledge base (Markdown) | User, Granola, Omi, GDoc Sync |
| **PersonEntity** | In-memory + persistence | Resolved people identities | People v2 sync, iMessage sync |
| **InteractionStore** | In-memory + persistence | Tracked interactions per person | People v2 sync |
| **iMessage Store** | `data/imessage.db` | Local message export cache | iMessage sync |
| **LinkedIn CSV** | `data/LinkedInConnections.csv` | Contacts source (manual export) | External (user) |

---

## Search Pipeline

```
Query → Name Expansion → [Vector Search + BM25 Search] → RRF Fusion → Boosting → Reranking → Results
```

### Components

1. **Name Expansion**: Nicknames → canonical names ("Al" → "Alex")
2. **Dual Search**:
   - Vector (semantic similarity via ChromaDB)
   - BM25 (keyword matching via SQLite FTS5)
3. **RRF Fusion**: `score = Σ 1/(60 + rank)`
4. **Boosting**: Recency (0-50%) + Filename match (2x)
5. **Query-Aware Reranking** (Phase 9.2):
   - Factual queries: Protect top BM25 matches
   - Semantic queries: Full cross-encoder reranking

### Key Files
- `api/services/hybrid_search.py` - Main search logic
- `api/services/query_classifier.py` - Factual vs semantic detection
- `api/services/reranker.py` - Cross-encoder reranking
- `api/services/vectorstore.py` - ChromaDB wrapper
- `api/services/bm25_index.py` - BM25 index

---

## Configuration Files

| File | Purpose |
|------|---------|
| `config/launchd/com.lifeos.api.plist` | Launchd service configuration |
| `config/settings.py` | Environment variables, paths, API keys |
| `config/gdoc_sync.yaml` | Google Docs → vault mapping |
| `config/prompts/*.txt` | LLM prompt templates |

---

## Daily Timeline

```
00:00 - 03:00  System running, handling API requests, watching vault changes
03:00          Nightly sync starts
03:00          └─ Step 1: Vault reindex (all files → ChromaDB + BM25)
03:01          └─ Step 2: People v2 sync (LinkedIn + Gmail + Calendar)
03:02          └─ Step 3: Google Docs sync (configured docs → vault)
03:03          └─ Step 4: iMessage sync (macOS Messages → local store)
03:04          Nightly sync complete

08:00          Calendar sync (Google Calendar → ChromaDB)
12:00          Calendar sync
15:00          Calendar sync

24/7           File watcher (real-time vault changes → ChromaDB + BM25)
24/7           Granola processor (every 5 min, Granola/ → vault)
24/7           Omi processor (every 5 min, Omi/Events/ → vault)
```

---

## API Endpoints

### Search
- `POST /api/search` - Hybrid search with reranking
- `POST /api/ask` - RAG-powered question answering

### Admin
- `GET /api/admin/status` - Index status and document count
- `POST /api/admin/reindex` - Trigger background reindex
- `POST /api/admin/reindex/sync` - Trigger blocking reindex

### Calendar
- `GET /api/admin/calendar/status` - Calendar sync status
- `POST /api/admin/calendar/sync` - Trigger calendar sync
- `POST /api/admin/calendar/scheduler/start` - Start calendar scheduler
- `POST /api/admin/calendar/scheduler/stop` - Stop calendar scheduler

### Conversations
- `GET /api/conversations` - List conversations
- `POST /api/chat` - Send message in conversation

---

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `LIFEOS_VAULT_PATH` | Path to Obsidian vault | `./vault` |
| `LIFEOS_CHROMA_PATH` | Path to ChromaDB data | `./data/chromadb` |
| `LIFEOS_PORT` | API server port | `8000` |
| `ANTHROPIC_API_KEY` | Claude API key | Required |
| `OLLAMA_HOST` | Local LLM endpoint | `http://localhost:11434` |

---

## Timezone

All scheduled times use **America/New_York** (Eastern Time).

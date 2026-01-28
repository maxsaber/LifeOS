# LifeOS

Personal AI assistant for semantic search and synthesis across your digital life — Obsidian notes, Google Suite, iMessage, and more.

## Overview

LifeOS is a self-hosted RAG (Retrieval-Augmented Generation) system that provides intelligent search and synthesis across your personal knowledge base. It runs on a Mac Mini with local embeddings, local vector database, and a local LLM for query routing. All your data stays local.

**Key Features:**
- **Semantic + Keyword Search** — Hybrid search (vector + BM25) across Obsidian notes with recency bias
- **Google Suite Integration** — Calendar, Gmail, Drive with multi-account support
- **iMessage History** — Query your text message conversations (requires Full Disk Access)
- **People Intelligence** — Entity resolution linking contacts across vault, email, calendar, LinkedIn, and iMessage
- **Stakeholder Briefings** — Generate context about people before meetings
- **Local LLM Routing** — Ollama + Llama 3.2 routes queries to relevant data sources
- **Streaming Chat** — Claude-powered synthesis with source citations
- **Conversation Memory** — Persistent conversations with cost tracking
- **Save to Vault** — Save AI responses directly to Obsidian
- **File Attachments** — Attach images and files to queries
- **Nightly Sync** — Automated sync of all data sources at 3 AM Eastern

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              Web UI (Vanilla HTML/JS)                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Chat + SSE  │  │Conversations│  │   Memories  │  │  File Attachments   │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │ SSE Stream
┌──────────────────────────────────▼───────────────────────────────────────────┐
│                           FastAPI Backend                                     │
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                         Query Router (Ollama)                          │  │
│  │                      Routes to relevant data sources                   │  │
│  └────────────────────────────────┬───────────────────────────────────────┘  │
│                                   │                                           │
│  ┌────────────────────────────────▼───────────────────────────────────────┐  │
│  │                        Hybrid Search Engine                            │  │
│  │  ┌─────────────────┐           ┌─────────────────┐                     │  │
│  │  │ ChromaDB        │           │ BM25 Index      │                     │  │
│  │  │ (Vector Search) │           │ (Keyword Search)│                     │  │
│  │  └─────────────────┘           └─────────────────┘                     │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                          Data Sources                                  │  │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐          │  │
│  │  │ Vault   │ │ Gmail   │ │Calendar │ │  Drive  │ │iMessage │          │  │
│  │  │(Obsidian)│ │         │ │         │ │         │ │         │          │  │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘          │  │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐                                  │  │
│  │  │ People  │ │ Actions │ │Memories │                                  │  │
│  │  │(Entity) │ │ (Tasks) │ │         │                                  │  │
│  │  └─────────┘ └─────────┘ └─────────┘                                  │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                         Synthesizer (Claude)                           │  │
│  │              Generates responses with source citations                 │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                       Nightly Sync (3 AM Eastern)                      │  │
│  │   Vault Reindex → LinkedIn → Gmail → Calendar → GDocs → iMessage      │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Background Processes & Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SCHEDULED PROCESSES                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  NIGHTLY SYNC (3:00 AM Eastern)                                     │    │
│  │                                                                      │    │
│  │  Step 1          Step 2           Step 3          Step 4            │    │
│  │  ┌──────────┐   ┌──────────┐    ┌──────────┐   ┌──────────┐         │    │
│  │  │  Vault   │──▶│ People   │──▶ │  GDocs   │──▶│ iMessage │         │    │
│  │  │ Reindex  │   │   Sync   │    │   Sync   │   │   Sync   │         │    │
│  │  └────┬─────┘   └────┬─────┘    └────┬─────┘   └────┬─────┘         │    │
│  │       │              │               │              │                │    │
│  │       ▼              ▼               ▼              ▼                │    │
│  │   ChromaDB      PersonEntity      Vault        imessage.db          │    │
│  │   BM25 Index    Interactions                   PersonEntity         │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  CALENDAR INDEXER (8 AM, 12 PM, 3 PM Eastern)                       │    │
│  │                                                                      │    │
│  │   Google Calendar ────────▶ ChromaDB (lifeos_calendar collection)   │    │
│  │   (personal + work)          Past 30 days + Future 30 days          │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                        CONTINUOUS PROCESSES                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐           │
│  │   FILE WATCHER   │  │ GRANOLA (5 min)  │  │   OMI (5 min)    │           │
│  │   (real-time)    │  │                  │  │                  │           │
│  │                  │  │ Granola/         │  │ Omi/Events/      │           │
│  │ Vault changes ──▶│  │      │           │  │      │           │           │
│  │      │           │  │      ▼           │  │      ▼           │           │
│  │      ▼           │  │ Work/ML/Meetings │  │ Personal/Omi     │           │
│  │ ChromaDB + BM25  │  │ Personal/...     │  │ Work/ML/Omi      │           │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                              DATA STORES                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   data/chromadb/          data/chromadb/        ~/Notes 2025/               │
│  ┌──────────────┐        ┌──────────────┐      ┌──────────────┐             │
│  │   ChromaDB   │        │  BM25 Index  │      │    Vault     │             │
│  │  (vectors)   │        │  (keywords)  │      │  (markdown)  │             │
│  └──────────────┘        └──────────────┘      └──────────────┘             │
│                                                                              │
│   data/imessage.db       data/person_         data/interactions.db          │
│  ┌──────────────┐        entities.db          ┌──────────────┐              │
│  │   iMessage   │       ┌──────────────┐      │ Interactions │              │
│  │    Cache     │       │ PersonEntity │      │   per Person │              │
│  └──────────────┘       └──────────────┘      └──────────────┘              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

Daily Timeline (Eastern Time):
───────────────────────────────────────────────────────────────────────────────
 00:00 ─────────────────────────────────────────────────────────────────────▶
   │
   │    03:00  Nightly Sync (Vault → People → GDocs → iMessage)
   │      │
   │      ▼
   │    08:00  Calendar Sync
   │      │
   │      ▼
   │    12:00  Calendar Sync
   │      │
   │      ▼
   │    15:00  Calendar Sync
   │      │
   │      ▼
   │    24/7   File Watcher (real-time) + Granola/Omi (every 5 min)
   │
 23:59 ─────────────────────────────────────────────────────────────────────▶
```

> **See also:** [System Architecture](docs/SYSTEM_ARCHITECTURE.md) for detailed process specifications, data store schemas, and API endpoint documentation.

**Core Components:**
| Component | Technology | Location |
|-----------|------------|----------|
| Embeddings | sentence-transformers (`all-MiniLM-L6-v2`) | Local |
| Vector DB | ChromaDB (server mode, port 8001) | Local |
| Keyword Index | SQLite FTS5 (BM25) | Local |
| Query Router | Ollama + Llama 3.2 3B | Local |
| Synthesis | Claude API (Anthropic) | Cloud |
| Backend | FastAPI + Python 3.13 | Local |
| iMessage DB | SQLite (macOS Messages) | Local |
| Storage | SQLite (conversations, costs, entities) | Local |

## Quick Start

### Prerequisites

- Python 3.11+
- ChromaDB server (runs on port 8001)
- Ollama (for local LLM routing)
- Anthropic API key (for Claude synthesis)
- Google OAuth credentials (for Calendar/Gmail/Drive)

### Installation

```bash
# Clone the repository
git clone https://github.com/nbramia/LifeOS.git
cd LifeOS

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Ollama and pull model
brew install ollama
ollama serve &
ollama pull llama3.2:3b
```

### Configuration

Create a `.env` file in the project root:

```bash
# Paths
LIFEOS_VAULT_PATH=/path/to/obsidian/vault
LIFEOS_CHROMA_PATH=./data/chromadb          # ChromaDB data directory

# ChromaDB Server
LIFEOS_CHROMA_URL=http://localhost:8001     # ChromaDB server URL

# LifeOS API Server
LIFEOS_HOST=0.0.0.0
LIFEOS_PORT=8000

# API Keys
ANTHROPIC_API_KEY=sk-ant-...

# Google OAuth
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_TOKEN_PATH=./config/google_token.json

# Local LLM Router (Ollama)
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
OLLAMA_TIMEOUT=10
```

### Running the Server

> **⚠️ IMPORTANT: Always use the server script, never run uvicorn directly!**
>
> Running `uvicorn` manually can create ghost processes that cause different behavior
> when accessing via localhost vs Tailscale/network. The script ensures clean startup.

```bash
# Start ChromaDB server (required dependency)
./scripts/chromadb.sh start

# Start Ollama (if not running)
ollama serve &

# Start the server (ALWAYS use this)
./scripts/server.sh start     # Auto-starts ChromaDB if not running

# Other server commands
./scripts/server.sh stop      # Stop server
./scripts/server.sh restart   # Restart after code changes
./scripts/server.sh status    # Check server status

# ChromaDB management
./scripts/chromadb.sh status  # Check ChromaDB status
./scripts/chromadb.sh stop    # Stop ChromaDB
./scripts/chromadb.sh restart # Restart ChromaDB
```

The web UI will be available at `http://localhost:8000` (and via Tailscale if configured).

## Development

### IMPORTANT: Always Use the Deploy Script

**After ANY code changes, you MUST run the deploy script to restart the server:**

```bash
./scripts/deploy.sh "Your commit message"
```

The server does NOT auto-reload. Direct `git commit` will NOT restart the server. The deploy script:
1. Runs tests
2. Restarts the server (required for changes to take effect)
3. Verifies health
4. Commits and pushes

### Scripts

LifeOS uses shell scripts for testing, deployment, and server management:

```bash
# === ChromaDB Server (required dependency) ===
./scripts/chromadb.sh start    # Start ChromaDB server on port 8001
./scripts/chromadb.sh stop     # Stop ChromaDB server
./scripts/chromadb.sh restart  # Restart ChromaDB server
./scripts/chromadb.sh status   # Check ChromaDB status

# === Server Management (use this for day-to-day operations) ===
./scripts/server.sh start      # Kill existing, start server (auto-starts ChromaDB)
./scripts/server.sh stop       # Stop the server
./scripts/server.sh restart    # Full restart (recommended after code changes)
./scripts/server.sh status     # Check server status and health

# === Testing ===
./scripts/test.sh              # Run unit tests (default)
./scripts/test.sh unit         # Fast unit tests (~30s)
./scripts/test.sh integration  # Tests requiring server
./scripts/test.sh browser      # Playwright browser tests
./scripts/test.sh smoke        # Unit + critical browser test (used by deploy)
./scripts/test.sh all          # Run all tests
./scripts/test.sh health       # Quick health check

# === Deployment (use for commits/releases) ===
./scripts/deploy.sh                      # Test, restart, commit, push
./scripts/deploy.sh "Add new feature"    # With custom commit message
./scripts/deploy.sh --no-push "WIP"      # Commit without pushing
./scripts/deploy.sh --skip-tests         # Skip tests (use with caution)

# === Service Management (launchd - for auto-start on boot) ===
./scripts/service.sh install   # Install as launchd service
./scripts/service.sh status    # Check launchd service status
./scripts/service.sh logs      # Tail service logs
```

### Server Startup Details

**Expected startup time: 30-60 seconds**

The server takes 30-60 seconds to start because it loads the sentence-transformers ML model (`all-MiniLM-L6-v2`) at startup. The `server.sh` script handles this automatically:

1. Kills any existing server processes
2. Cleans up stale HuggingFace lock files (prevents hangs)
3. Starts uvicorn with `--host 0.0.0.0` (allows network/Tailscale access)
4. Waits up to 90 seconds for health check to pass
5. Shows Tailscale URL if available

**Important**: Always use `./scripts/server.sh restart` after code changes. The server does NOT auto-reload.

### Running Tests Manually

Tests must pass before any commit. The pre-commit hook enforces this automatically.

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_query_router.py -v

# Run with coverage
pytest tests/ -v --cov=api --cov-report=term-missing

# Run browser tests with Playwright
pytest tests/test_ui_browser.py -v --browser chromium
pytest tests/test_e2e_flow.py::TestRealUserFlow -v --browser chromium
```

### Test Suite Structure

| Test File | Description | Tests |
|-----------|-------------|-------|
| `test_query_router.py` | Local LLM routing | 21 |
| `test_qa_suite.py` | QA validation suite | 10 |
| `test_vectorstore.py` | ChromaDB operations | 12 |
| `test_indexer.py` | Document indexing | 11 |
| `test_chunking.py` | Text chunking logic | 9 |
| `test_embeddings.py` | Embedding generation | 5 |
| `test_search_api.py` | Search endpoint | 8 |
| `test_ask_api.py` | Ask endpoint | 12 |
| `test_chat_api.py` | Chat streaming | 10 |
| `test_calendar.py` | Google Calendar | 15 |
| `test_gmail.py` | Gmail integration | 12 |
| `test_drive.py` | Google Drive | 11 |
| `test_google_auth.py` | OAuth flow | 14 |
| `test_people.py` | People extraction | 11 |
| `test_people_aggregator.py` | Stakeholder briefings | 13 |
| `test_briefings.py` | Briefing synthesis | 14 |
| `test_actions.py` | Action items | 12 |
| `test_resilience.py` | Error handling | 13 |
| `test_service_management.py` | launchd integration | 7 |
| `test_admin.py` | Admin endpoints | 4 |
| `test_integration.py` | End-to-end tests | 8 |
| `test_e2e_flow.py` | E2E flow & error handling | 12 |
| `test_ui_browser.py` | Playwright UI tests | 25 |
| `test_gdoc_sync.py` | Google Docs sync | 17 |
| `test_imessage.py` | iMessage integration | 15 |
| `test_phone_utils.py` | Phone normalization | 8 |
| `test_person_entity.py` | PersonEntity store | 12 |
| `test_entity_resolver.py` | Entity resolution | 14 |

**Total: 580+ tests**

### Pre-commit Hook

A pre-commit hook runs tests automatically before each commit:

```bash
# Install the pre-commit hook
cp scripts/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

The hook will:
1. Run the full test suite
2. Block the commit if any tests fail
3. Show test output for debugging

### Project Structure

```
LifeOS/
├── api/
│   ├── main.py                    # FastAPI app + nightly sync scheduler
│   ├── routes/
│   │   ├── chat.py                # /api/ask/stream (SSE streaming)
│   │   ├── search.py              # /api/search (vector + keyword)
│   │   ├── calendar.py            # Google Calendar endpoints
│   │   ├── gmail.py               # Gmail endpoints
│   │   ├── drive.py               # Google Drive endpoints
│   │   ├── people.py              # People/briefings endpoints
│   │   └── admin.py               # Admin/health endpoints
│   └── services/
│       ├── vectorstore.py         # ChromaDB operations
│       ├── bm25_index.py          # Keyword search index
│       ├── hybrid_search.py       # Combined vector + BM25 search
│       ├── indexer.py             # Document indexing
│       ├── chunker.py             # Text chunking
│       ├── embeddings.py          # Embedding generation
│       ├── synthesizer.py         # Claude synthesis
│       ├── query_router.py        # LLM query routing
│       ├── ollama_client.py       # Ollama client
│       ├── google_auth.py         # Google OAuth
│       ├── calendar.py            # Calendar API
│       ├── calendar_indexer.py    # Calendar event indexing
│       ├── gmail.py               # Gmail API
│       ├── drive.py               # Drive API
│       ├── gdoc_sync.py           # Google Docs → Obsidian sync
│       ├── imessage.py            # iMessage export/query
│       ├── phone_utils.py         # Phone number normalization
│       ├── person_entity.py       # PersonEntity store
│       ├── entity_resolver.py     # Fuzzy name matching
│       ├── people.py              # People extraction
│       ├── people_aggregator.py   # Multi-source people aggregation
│       ├── briefings.py           # Stakeholder briefing synthesis
│       ├── actions.py             # Action item extraction
│       ├── conversation_store.py  # Conversation persistence
│       ├── memory_store.py        # User memories
│       ├── cost_tracker.py        # API cost tracking
│       ├── interaction_store.py   # People interaction tracking
│       ├── granola_processor.py   # Granola meeting notes processor
│       ├── omi_processor.py       # Omi events processor
│       ├── model_selector.py      # Claude model selection
│       └── resilience.py          # Error handling/retries
├── config/
│   ├── settings.py                # Application settings
│   ├── gdoc_sync.yaml             # Google Docs sync config
│   ├── people_dictionary.json     # Known people (gitignored)
│   ├── people_dictionary.example.json  # Template
│   └── prompts/
│       └── query_router.txt       # Router prompt (editable)
├── data/                          # Local databases (gitignored)
│   ├── chromadb/                  # Vector store
│   ├── imessage.db                # iMessage export
│   ├── conversations.db           # Chat history
│   ├── cost_tracker.db            # Usage costs
│   └── person_entities.db         # People data
├── web/
│   └── index.html                 # Chat UI (vanilla JS)
├── tests/                         # Test suite (580+ tests)
├── scripts/
│   ├── deploy.sh                  # Test → restart → commit → push
│   ├── test.sh                    # Test runner
│   ├── server.sh                  # Server management
│   ├── chromadb.sh                # ChromaDB server management
│   ├── service.sh                 # launchd service management
│   ├── authenticate_google.py     # Google OAuth setup
│   └── import_phone_contacts.py   # Import contacts from CSV
├── docs/
│   ├── LifeOS PRD.md              # Product requirements
│   └── LifeOS Backlog.md          # Feature backlog
├── requirements.txt
├── pyproject.toml
└── README.md
```

## API Endpoints

### Chat

- `POST /api/ask/stream` - Streaming chat with RAG
  - Returns SSE stream with routing, sources, content, and done events

### Search

- `POST /api/search` - Vector similarity search
- `GET /api/search/recent` - Recent documents

### Google Integration

- `GET /api/calendar/events` - Calendar events
- `GET /api/gmail/messages` - Email messages
- `GET /api/drive/files` - Drive files

### People

- `GET /api/people/{name}` - Person information
- `GET /api/people/{name}/briefing` - Stakeholder briefing

### Memories

- `POST /api/memories` - Create a new memory (with optional Claude synthesis)
- `GET /api/memories` - List all memories (filter by category)
- `GET /api/memories/{id}` - Get a specific memory
- `DELETE /api/memories/{id}` - Delete a memory
- `GET /api/memories/search/{query}` - Search memories by keyword

### Conversations

- `GET /api/conversations` - List all conversations
- `POST /api/conversations` - Create new conversation
- `GET /api/conversations/{id}` - Get conversation with messages
- `DELETE /api/conversations/{id}` - Delete conversation

### Admin

- `GET /api/admin/health` - Health check
- `POST /api/admin/reindex` - Trigger vault reindex
- `GET /api/admin/calendar/status` - Calendar indexer status
- `POST /api/admin/calendar/sync` - Trigger calendar sync
- `POST /api/admin/calendar/start` - Start calendar scheduler
- `POST /api/admin/calendar/stop` - Stop calendar scheduler
- `GET /api/admin/granola/status` - Granola processor status
- `POST /api/admin/granola/process` - Process Granola inbox
- `GET /api/admin/omi/status` - Omi processor status
- `POST /api/admin/omi/process` - Process Omi events

## Query Routing

The local LLM (Llama 3.2 3B via Ollama) routes queries to appropriate data sources:

| Source | Content | Example Queries |
|--------|---------|-----------------|
| `vault` | Obsidian notes, meeting notes, personal docs | "What did we discuss about the product launch?" |
| `calendar` | Google Calendar events and schedules | "What's on my calendar tomorrow?" |
| `gmail` | Email messages and correspondence | "What did John email about?" |
| `drive` | Google Drive files and spreadsheets | "Find the Q4 budget spreadsheet" |
| `imessage` | iMessage/SMS conversation history | "What did I text Sarah about dinner?" |
| `people` | Stakeholder profiles and context | "Tell me about Alex before my meeting" |
| `actions` | Open tasks and commitments | "What are my open action items?" |
| `memories` | User-saved memories and notes | "What did I want to remember about the project?" |

The router prompt is editable at `config/prompts/query_router.txt`.

**Fallback:** If Ollama is unavailable, keyword-based routing kicks in automatically.


## Hybrid Search System

LifeOS combines vector similarity and keyword matching to find both conceptual and exact matches.

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              User Query                                      │
│                       "What is Alex's phone number?"                         │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  1. Person Name Expansion                                                    │
│     • Nicknames → canonical: "Al's phone" → "Alex's phone"                  │
│     • Configured in config/people_dictionary.json                            │
└─────────────────────────────────────┬───────────────────────────────────────┘
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
┌───────────────────────────────────┐   ┌───────────────────────────────────┐
│  2a. Vector Search (ChromaDB)     │   │  2b. BM25 Search (SQLite FTS5)    │
│  • Semantic similarity            │   │  • Exact keyword matching         │
│  • Good for concepts              │   │  • OR semantics (any term)        │
└───────────────────┬───────────────┘   └───────────────────┬───────────────┘
                    └─────────────────┬─────────────────────┘
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  3. Reciprocal Rank Fusion (RRF)                                             │
│     • score = Σ 1/(60 + rank) — docs found by BOTH methods score higher     │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  4. Score Boosting                                                           │
│     • Recency: 0-50% bonus for newer documents                              │
│     • Filename: 2x if person name matches file (Alex → Alex.md)             │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  5. Final Ranking — sorted by hybrid_score descending                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Contextual chunking** | Each chunk includes document context (filename, folder, type) for better retrieval |
| **OR semantics for BM25** | AND fails when no single chunk contains all query terms |
| **2x filename boost** | Person-specific files must rank first for person queries |
| **RRF fusion (k=60)** | Score-agnostic merging, no parameter tuning needed |

### Configuration

Add people to `config/people_dictionary.json` for nickname expansion:

```json
{
  "Alex": {
    "canonical": "Alex",
    "aliases": ["Al", "Alexander"]
  }
}
```

### Debugging

```bash
# Check if content exists in index
sqlite3 ./data/bm25_index.db "SELECT doc_id FROM chunks_fts WHERE content LIKE '%term%'"

# Test search ranking
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "your query"}' | jq '.results[:3] | .[] | {file_name, score}'
```

## Google Docs Sync

LifeOS can sync specific Google Docs to your Obsidian vault as Markdown files. This is a one-way sync that runs nightly at 3 AM Eastern (alongside other nightly sync operations).

### Configuration

Edit `config/gdoc_sync.yaml` to add documents:

```yaml
sync_enabled: true

documents:
  - doc_id: "1ABC123..."
    vault_path: "Work/Meeting Notes.md"
    account: "work"

  - doc_id: "1DEF456..."
    vault_path: "Personal/Goals.md"
    account: "personal"
```

To get the `doc_id` from a Google Docs URL:
```
https://docs.google.com/document/d/[DOC_ID_HERE]/edit
```

### How It Works

1. Exports each Google Doc as HTML
2. Converts HTML to Markdown (preserving headings, lists, links, bold/italic)
3. Adds frontmatter with sync metadata (`gdoc_sync: true`, `gdoc_id`, `last_synced`)
4. Adds warning callout with link to edit in Google Docs
5. Writes to the specified vault path (creates directories if needed)

**Important:** Local edits will be overwritten on next sync. Edit in Google Docs.

### Manual Sync

To run sync manually (without waiting for nightly):

```bash
source .venv/bin/activate
python -c "from api.services.gdoc_sync import sync_gdocs; print(sync_gdocs())"
```

## Google Sheets Sync

LifeOS can sync Google Sheets (e.g., form responses from Google Forms) to your vault. Useful for daily journals, habit tracking, or any structured data collection.

### Prerequisites

1. **Enable Google Sheets API** in your Google Cloud Console project
2. The Sheets API scope is included in the default OAuth scopes

### Configuration

Edit `config/gsheet_sync.yaml`:

```yaml
sync_enabled: true

sheets:
  - sheet_id: "1ABC123..."  # From the Google Sheets URL
    name: "Daily Journal"
    account: "personal"
    range: "Form Responses 1"  # Sheet tab name
    timestamp_column: "Timestamp"

    outputs:
      rolling_document:
        enabled: true
        path: "Personal/Daily Journal Log.md"

      daily_notes:
        enabled: true
        path_pattern: "Daily Notes/{date}.md"
        section_header: "## Daily Journal"
        insert_after: "## Meetings"
        create_if_missing: false
```

### How It Works

1. Reads all rows from the configured Google Sheet
2. Tracks synced rows in SQLite (`data/gsheet_sync.db`) to avoid duplicates
3. Creates/updates a **rolling document** with all entries (most recent first)
4. Optionally **appends to daily notes** under a configurable section header
5. Runs nightly at 3 AM Eastern alongside other sync operations

### Manual Sync

```bash
source .venv/bin/activate
python -c "from api.services.gsheet_sync import sync_gsheets; print(sync_gsheets())"
```

## iMessage Integration

LifeOS can query your iMessage/SMS history by reading from the macOS Messages database.

### Prerequisites

1. **Full Disk Access**: Grant Full Disk Access to Terminal (or your IDE) in System Preferences → Privacy & Security → Full Disk Access
2. The source database is at `~/Library/Messages/chat.db`

### How It Works

1. **Export**: Messages are exported from macOS Messages to a local SQLite database (`./data/imessage.db`)
2. **Incremental Sync**: Only new messages (by ROWID) are synced each night
3. **Entity Mapping**: Phone numbers are matched to PersonEntity records for "Who did I text?" queries
4. **Privacy**: All data stays local; messages are never sent to external services

### Manual Sync

```bash
source venv/bin/activate
python -c "from api.services.imessage import sync_and_join_imessages; print(sync_and_join_imessages())"
```

### Querying Messages

Ask natural language questions like:
- "What did I text Mom about last week?"
- "Show me my recent messages with John"
- "Did Sarah confirm dinner plans?"

## People & Entity Resolution

LifeOS maintains a unified view of people across all data sources using the PersonEntity system.

### Data Sources for People

| Source | What's Extracted |
|--------|------------------|
| Obsidian Vault | Names mentioned in notes, meeting attendees |
| Gmail | Sender/recipient names and emails |
| Google Calendar | Event attendees |
| LinkedIn Export | Professional connections (CSV import) |
| iMessage | Phone contacts |
| Phone Contacts | Contact names and numbers |

### Entity Resolution

The system uses fuzzy matching to link the same person across sources:
- "John Smith" in your notes
- "john.smith@company.com" in email
- "+1-555-123-4567" in iMessage

All get resolved to a single PersonEntity with a unified profile.

### Configuration

Create `config/people_dictionary.json` to define known people and aliases:

```json
{
  "John Smith": {
    "aliases": ["Johnny", "J. Smith"],
    "email": "john@example.com",
    "phone": "+15551234567"
  }
}
```

See `config/people_dictionary.example.json` for the format.

### Stakeholder Briefings

Before a meeting, ask: "Brief me on John Smith"

LifeOS will synthesize:
- Recent email threads
- Past meeting notes
- Calendar history
- iMessage conversations
- LinkedIn connection info

## Nightly Sync

LifeOS runs automated sync operations at **3 AM Eastern** daily.

### Sync Operations (in order)

1. **Vault Reindex** — Full reindex of all Obsidian notes
2. **LinkedIn Sync** — Import connections from CSV (if updated)
3. **Gmail Sync** — Fetch recent emails for people context
4. **Calendar Sync** — Update calendar event index
5. **Google Docs Sync** — Sync configured docs to vault
6. **iMessage Sync** — Export new messages from macOS Messages

### Manual Trigger

To run all sync operations manually:

```bash
# Individual syncs
python -c "from api.services.imessage import sync_and_join_imessages; sync_and_join_imessages()"
python -c "from api.services.gdoc_sync import sync_gdocs; sync_gdocs()"

# Or restart server to trigger startup sync
./scripts/server.sh restart
```

### Monitoring

Check sync status via admin endpoints:
- `GET /api/admin/health` — Overall health
- `GET /api/admin/calendar/status` — Calendar indexer status
- `GET /api/admin/granola/status` — Granola processor status
- `GET /api/admin/omi/status` — Omi processor status

## Omi Events Processor

LifeOS automatically processes events captured by [Omi](https://www.omi.me/) (wearable AI device) and routes them to the appropriate folders in your Obsidian vault.

### Source Folder

Events land in `Omi/Events/` with frontmatter containing:
- `category` — Omi's classification (work, psychology, romantic, parenting, etc.)
- `omi_id` — Unique identifier for deduplication
- `date`, `duration_minutes`, `started_at`, `finished_at`

### Destination Folders

| Destination | Criteria |
|-------------|----------|
| `Personal/Self-Improvement/Therapy and coaching/Omi` | Content contains therapy patterns (therapist, therapy session, etc.) |
| `Work/ML/Meetings/Omi` | Category is `work`, `business`, `finance`, or `technology` |
| `Personal/Omi` | Everything else (default) |

**Note:** Therapy detection requires content patterns — category alone is not sufficient. A `psychology` event without "therapist" in the content goes to `Personal/Omi`.

### Processing

- Runs automatically every 5 minutes (alongside Granola processor)
- Starts on server boot via launchd
- Updates frontmatter with LifeOS tags and type
- Handles duplicates via `omi_id`

### Manual Processing

```bash
# Process all pending Omi events now
curl -X POST http://localhost:8000/api/admin/omi/process

# Check status
curl http://localhost:8000/api/admin/omi/status

# Reclassify files in a folder
curl -X POST http://localhost:8000/api/admin/omi/reclassify \
  -H "Content-Type: application/json" \
  -d '{"folder": "Personal/Omi"}'
```

## Cost Tracking

LifeOS tracks Claude API costs per conversation and session.

- **Session Cost**: Displayed in the UI header (resets on page refresh)
- **Conversation Cost**: Stored per conversation in SQLite
- **Usage History**: View historical costs via the usage modal

Data stored in `./data/cost_tracker.db`.

## Documentation

- **System Architecture**: `docs/SYSTEM_ARCHITECTURE.md` — Detailed process specs, data stores, and API docs
- **PRD**: `docs/LifeOS PRD.md`
- **Backlog**: `docs/LifeOS Backlog.md`
- **Router Prompt**: `config/prompts/query_router.txt`

## Version History

- **v0.9.0** - People System v2 & iMessage Integration
  - iMessage history export and querying
  - PersonEntity system with cross-source entity resolution
  - Phone contacts import
  - Fuzzy name matching for people lookup
  - UI improvements: keyboard shortcuts, conversation search, collapsible sources
  - Open sourced under GPL-3.0
- **v0.8.0** - PRD Completion Release
  - Persistent memories with Claude synthesis
  - Calendar event indexing with daily sync
  - Remember button in UI for quick memory entry
  - Save to vault button
  - Cost tracking per conversation/session
- **v0.7.0** - Local LLM Query Router
  - Ollama + Llama 3.2 for query routing
  - Fallback to keyword-based routing
- **v0.6.0** - Error handling and resilience
- **v0.5.0** - Service management with launchd
- **v0.4.0** - Stakeholder briefings

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

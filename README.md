# LifeOS

Personal assistant system for semantic search and synthesis across Obsidian vault and Google Suite.

## Overview

LifeOS is a self-hosted RAG (Retrieval-Augmented Generation) system that provides intelligent search and synthesis across your personal knowledge base. It runs entirely on a Mac Mini with local embeddings, local vector database, and a local LLM for query routing.

**Key Features:**
- Semantic search across ~4,500 Obsidian notes
- Google Suite integration (Calendar, Gmail, Drive)
- Local LLM query routing (Ollama + Llama 3.2)
- Streaming chat interface with Claude synthesis
- Recency-biased search results
- Stakeholder briefings and people context

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Web UI                                │
│                   (Vanilla HTML/JS)                          │
└─────────────────────────┬───────────────────────────────────┘
                          │ SSE Stream
┌─────────────────────────▼───────────────────────────────────┐
│                     FastAPI Backend                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Query Router│  │  Synthesizer│  │   Data Sources      │  │
│  │  (Ollama)   │  │   (Claude)  │  │ ┌─────┐ ┌────────┐  │  │
│  └──────┬──────┘  └──────┬──────┘  │ │Vault│ │Calendar│  │  │
│         │                │         │ └─────┘ └────────┘  │  │
│         ▼                │         │ ┌─────┐ ┌────────┐  │  │
│  ┌─────────────┐         │         │ │Gmail│ │ Drive  │  │  │
│  │  ChromaDB   │◄────────┘         │ └─────┘ └────────┘  │  │
│  │(Vector Store)│                  └─────────────────────┘  │
│  └─────────────┘                                            │
└─────────────────────────────────────────────────────────────┘
```

**Components:**
- **Embeddings**: sentence-transformers (`all-MiniLM-L6-v2`) - local
- **Vector DB**: ChromaDB - local
- **Query Router**: Ollama + Llama 3.2 3B - local
- **Synthesis**: Claude API (Anthropic)
- **Backend**: FastAPI + Python 3.13

## Quick Start

### Prerequisites

- Python 3.11+
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
LIFEOS_CHROMA_PATH=./data/chromadb

# Server
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

```bash
# Activate virtual environment
source venv/bin/activate

# Start Ollama (if not running)
ollama serve &

# Run the API server
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

The web UI will be available at `http://localhost:8000`.

## Development

### Scripts

LifeOS uses shell scripts for testing and deployment:

```bash
# Run tests (default: unit tests only)
./scripts/test.sh

# Run specific test levels
./scripts/test.sh unit         # Fast unit tests (~30s)
./scripts/test.sh integration  # Tests requiring server
./scripts/test.sh browser      # Playwright browser tests
./scripts/test.sh all          # Run all tests
./scripts/test.sh health       # Quick health check

# Deploy (runs tests, restarts server, commits, pushes)
./scripts/deploy.sh

# Deploy with custom message
./scripts/deploy.sh "Add new feature"

# Deploy without pushing
./scripts/deploy.sh --no-push "WIP changes"

# Skip tests (use with caution)
./scripts/deploy.sh --skip-tests

# Manage the service
./scripts/service.sh status    # Check service status
./scripts/service.sh restart   # Restart the server
./scripts/service.sh logs      # Tail logs
```

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

**Total: 371+ tests**

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
│   ├── main.py              # FastAPI application
│   ├── routes/
│   │   ├── chat.py          # /api/ask/stream endpoint
│   │   ├── search.py        # /api/search endpoint
│   │   ├── calendar.py      # Calendar endpoints
│   │   ├── gmail.py         # Gmail endpoints
│   │   ├── drive.py         # Drive endpoints
│   │   ├── people.py        # People/briefings endpoints
│   │   └── admin.py         # Admin endpoints
│   └── services/
│       ├── vectorstore.py   # ChromaDB operations
│       ├── indexer.py       # Document indexing
│       ├── chunking.py      # Text chunking
│       ├── embeddings.py    # Embedding generation
│       ├── synthesizer.py   # Claude synthesis
│       ├── ollama_client.py # Local LLM client
│       ├── query_router.py  # Query routing logic
│       ├── google_auth.py   # OAuth handling
│       └── ...
├── config/
│   ├── settings.py          # Application settings
│   └── prompts/
│       └── query_router.txt # Router prompt (editable)
├── web/
│   └── index.html           # Chat UI
├── tests/                   # Test suite (371+ tests)
├── scripts/
│   ├── deploy.sh            # Deployment script (test, restart, commit, push)
│   ├── test.sh              # Test runner (unit, integration, browser)
│   ├── service.sh           # Service management (start, stop, status)
│   └── pre-commit           # Git pre-commit hook
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

## Query Routing

The local LLM (Llama 3.2 3B via Ollama) routes queries to appropriate data sources:

| Source | Content |
|--------|---------|
| `vault` | Obsidian notes, meeting notes, personal docs |
| `calendar` | Google Calendar events and schedules |
| `gmail` | Email messages and correspondence |
| `drive` | Google Drive files and spreadsheets |
| `people` | Stakeholder profiles and context |
| `actions` | Open tasks and commitments |

The router prompt is editable at `config/prompts/query_router.txt`.

**Fallback:** If Ollama is unavailable, keyword-based routing kicks in automatically.

## Documentation

- **PRD**: `/Users/nathanramia/Notes 2025/LifeOS/LifeOS PRD.md`
- **Backlog**: `/Users/nathanramia/Notes 2025/LifeOS/LifeOS Backlog.md`
- **Router Prompt**: `config/prompts/query_router.txt`

## Version History

- **v0.8.0** - PRD Completion Release
  - Persistent memories with Claude synthesis (P6.3)
  - Calendar event indexing with daily sync (P3.2)
  - Remember button in UI for quick memory entry
  - Save to vault button improvements (hide after save, better errors)
  - Session-scoped test fixtures for faster tests
- **v0.7.0** - Local LLM Query Router (P3.5)
- **v0.6.2** - Recency bias and QA test suite
- **v0.6.1** - Admin endpoints and setup utilities
- **v0.6.0** - Error handling and resilience (P4.2)
- **v0.5.0** - Service management with launchd (P4.1)
- **v0.4.0** - Stakeholder briefings (P2.3)

## License

Private - All rights reserved.

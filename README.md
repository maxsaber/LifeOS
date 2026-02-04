# LifeOS

Personal AI assistant for semantic search and synthesis across your digital life — Obsidian notes, Google Suite, iMessage, Slack, and more.

## What is LifeOS?

LifeOS is a self-hosted RAG (Retrieval-Augmented Generation) system that provides intelligent search and synthesis across your personal knowledge base. It runs on a Mac Mini with local embeddings, local vector database, and a local LLM for query routing. All your data stays local.

**Key Features:**
- Semantic + keyword hybrid search across Obsidian notes
- Google Suite integration (Calendar, Gmail, Drive) with multi-account support
- iMessage, WhatsApp, and Slack message history
- People intelligence with entity resolution across all sources
- Personal CRM with network visualization
- Stakeholder briefings before meetings
- Claude-powered synthesis with source citations
- Nightly automated sync of all data sources

## Documentation

| Document | Description |
|----------|-------------|
| **PRDs** | |
| [Chat UI PRD](docs/prd/CHAT-UI.md) | Chat interface requirements and phases |
| [CRM UI PRD](docs/prd/CRM-UI.md) | Personal CRM requirements and phases |
| [MCP Tools PRD](docs/prd/MCP-TOOLS.md) | MCP server tools for AI assistants |
| **Architecture** | |
| [Data & Sync](docs/architecture/DATA-AND-SYNC.md) | Data sources, sync processes, entity resolution |
| [API & MCP Reference](docs/architecture/API-MCP-REFERENCE.md) | API endpoints and MCP tool specs |
| [Frontend](docs/architecture/FRONTEND.md) | UI components and patterns |

## Quick Start

### Prerequisites

- Python 3.11+
- ChromaDB server (runs on port 8001)
- Ollama (for local LLM routing)
- Anthropic API key (for Claude synthesis)
- Google OAuth credentials (for Calendar/Gmail/Drive)

### Installation

```bash
git clone https://github.com/nbramia/LifeOS.git
cd LifeOS
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Install Ollama and pull model
brew install ollama
ollama serve &
ollama pull qwen2.5:7b-instruct
```

### Configuration

Create a `.env` file:

```bash
LIFEOS_VAULT_PATH=/path/to/obsidian/vault
LIFEOS_CHROMA_PATH=./data/chromadb
LIFEOS_CHROMA_URL=http://localhost:8001
LIFEOS_HOST=0.0.0.0
LIFEOS_PORT=8000
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b-instruct
```

### Running

```bash
# Start ChromaDB server
./scripts/chromadb.sh start

# Start LifeOS server (ALWAYS use this, never run uvicorn directly)
./scripts/server.sh start

# Other commands
./scripts/server.sh restart   # After code changes
./scripts/server.sh status    # Check status
```

Web UI available at `http://localhost:8000`

## Development

### Scripts

```bash
# Server management
./scripts/server.sh start|stop|restart|status
./scripts/chromadb.sh start|stop|restart|status

# Testing
./scripts/test.sh              # Unit tests (~30s)
./scripts/test.sh smoke        # Unit + critical browser
./scripts/test.sh all          # Full test suite

# Deployment
./scripts/deploy.sh "message"  # Test, restart, commit, push

# Nightly sync (runs via launchd at 3 AM)
./scripts/run_all_syncs.py --execute --force  # Manual run
# Errors logged to ~/Notes 2025/LifeOS/sync_errors.md
```

### Project Structure

```
LifeOS/
├── api/
│   ├── main.py              # FastAPI app + schedulers
│   ├── routes/              # API endpoints
│   └── services/            # Business logic
├── config/
│   ├── settings.py          # Environment config
│   └── prompts/             # LLM prompts
├── data/                    # Local databases (gitignored)
├── web/
│   ├── index.html           # Chat UI
│   └── crm.html             # CRM UI
├── tests/                   # 580+ tests
├── scripts/                 # Server, deploy, sync scripts
└── docs/                    # Documentation
    ├── prd/                 # Product requirements
    └── architecture/        # Technical architecture
```

### Key Files

| File | Purpose |
|------|---------|
| `api/main.py` | FastAPI app + health check scheduler |
| `config/settings.py` | Environment configuration |
| `config/people_dictionary.json` | Known people and aliases |

## Core Technologies

| Component | Technology |
|-----------|------------|
| Embeddings | sentence-transformers (`all-MiniLM-L6-v2`) |
| Vector DB | ChromaDB (server mode, port 8001) |
| Keyword Index | SQLite FTS5 (BM25) |
| Query Router | Ollama + Qwen 2.5 7B |
| Synthesis | Claude API (Anthropic) |
| Backend | FastAPI + Python 3.13 |

## License

GNU General Public License v3.0 - see [LICENSE](LICENSE)

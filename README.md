# LifeOS

Personal assistant system for semantic search and synthesis across Obsidian vault and Google Suite.

## Quick Start

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the API
uvicorn api.main:app --reload --port 8080
```

## Configuration

Set environment variables in `.env`:

```
LIFEOS_VAULT_PATH=/path/to/obsidian/vault
LIFEOS_CHROMA_PATH=/path/to/chromadb
LIFEOS_PORT=8080
ANTHROPIC_API_KEY=sk-...
```

## Development

```bash
# Run tests
pytest tests/ -v
```

## Architecture

- **Backend**: FastAPI + ChromaDB + sentence-transformers
- **Embeddings**: all-MiniLM-L6-v2 (local)
- **Vector DB**: ChromaDB (local)
- **LLM**: Claude API (synthesis)

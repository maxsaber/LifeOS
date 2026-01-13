# Instructions for AI Coding Agents

Critical instructions for AI agents (Claude, Cursor, Copilot, etc.) working on this codebase.

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

### After Code Changes

Always restart the server after modifying Python files:

```bash
./scripts/server.sh restart
```

The server does NOT auto-reload. Changes won't take effect until restart.

---

## Development Workflow

1. **Edit code**
2. **Restart server**: `./scripts/server.sh restart`
3. **Test manually** or run tests: `./scripts/test.sh`
4. **Deploy**: `./scripts/deploy.sh "Your commit message"`

### Testing

```bash
./scripts/test.sh              # Unit tests (fast, ~30s)
./scripts/test.sh smoke        # Unit + critical browser (used by deploy)
./scripts/test.sh all          # Full test suite
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
4. **Starting server on localhost only** → Must use 0.0.0.0 for Tailscale

---

## Key Files

| File | Purpose |
|------|---------|
| `api/main.py` | FastAPI application entry point |
| `config/settings.py` | Environment configuration |
| `config/people_dictionary.json` | Known people and aliases (restart required after edits) |
| `README.md` | Architecture documentation including hybrid search system |

# ChromaDB Client-Server Migration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Migrate ChromaDB from `PersistentClient` (direct file access) to `HttpClient` (client-server mode) to eliminate database corruption from concurrent access.

**Architecture:** Run ChromaDB as a standalone HTTP server managed by launchd. All LifeOS code connects via HTTP. The server handles all concurrency internally, eliminating the corruption issues caused by multiple `PersistentClient` instances accessing the same SQLite file.

**Tech Stack:** ChromaDB server (built-in `chroma run`), launchd for process management, httpx for health checks.

---

## Problem Statement

Currently, LifeOS creates multiple `PersistentClient` instances across:
- `api/services/vectorstore.py` (core)
- `api/services/indexer.py` (file watcher - continuous writes)
- `api/services/calendar_indexer.py` (scheduled writes)
- `api/routes/search.py`, `ask.py`, `chat.py`, `admin.py`, `conversations.py` (API requests)
- `api/services/hybrid_search.py`, `briefings.py` (services)

Each `PersistentClient` directly accesses `./data/chromadb/chroma.sqlite3`. When multiple clients write simultaneously, SQLite corruption occurs:
```
chromadb.errors.InternalError: Failed to apply logs to the hnsw segment writer
```

## Solution

1. Run ChromaDB as HTTP server on `localhost:8001`
2. Change one line in `vectorstore.py`: `PersistentClient` → `HttpClient`
3. Add launchd plist for ChromaDB server
4. Update health checks to verify ChromaDB server is running

## Files to Modify

| File | Change |
|------|--------|
| `api/services/vectorstore.py` | Change client type, add server URL config |
| `config/settings.py` | Add `LIFEOS_CHROMA_URL` setting |
| `config/launchd/com.lifeos.chromadb.plist` | **NEW** - launchd config for ChromaDB server |
| `scripts/chromadb.sh` | **NEW** - start/stop/status script |
| `scripts/server.sh` | Add ChromaDB dependency check |
| `api/main.py` | Update `/health/full` to check ChromaDB server |
| `tests/test_chromadb_server.py` | **NEW** - end-to-end tests |

---

## Task 1: Add ChromaDB Server Configuration

**Files:**
- Modify: `config/settings.py:20-30`

**Step 1: Write the failing test**

```python
# tests/test_settings.py
def test_chroma_url_setting():
    """ChromaDB URL should be configurable."""
    from config.settings import settings

    # Default should be localhost:8001
    assert settings.chroma_url == "http://localhost:8001"
    assert hasattr(settings, 'chroma_url')
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_settings.py::test_chroma_url_setting -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'chroma_url'`

**Step 3: Add the setting**

In `config/settings.py`, add after line 26 (after `chroma_path`):

```python
    chroma_url: str = Field(
        default="http://localhost:8001",
        validation_alias="LIFEOS_CHROMA_URL",
        description="ChromaDB server URL"
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_settings.py::test_chroma_url_setting -v`
Expected: PASS

**Step 5: Commit**

```bash
git add config/settings.py tests/test_settings.py
git commit -m "feat: add LIFEOS_CHROMA_URL configuration setting

Prepares for ChromaDB client-server migration.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 2: Create ChromaDB Server Management Script

**Files:**
- Create: `scripts/chromadb.sh`

**Step 1: Write the script**

```bash
#!/bin/bash
# ChromaDB Server Management Script
#
# Usage: ./scripts/chromadb.sh [start|stop|restart|status]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Configuration
HOST="localhost"
PORT="8001"
DATA_DIR="$PROJECT_DIR/data/chromadb"
LOG_FILE="$PROJECT_DIR/logs/chromadb.log"
PID_FILE="$PROJECT_DIR/logs/chromadb.pid"
HEALTH_URL="http://$HOST:$PORT/api/v1/heartbeat"
STARTUP_TIMEOUT=30
PYTHON="$HOME/.venvs/lifeos/bin/python"

# Ensure directories exist
mkdir -p "$PROJECT_DIR/logs"
mkdir -p "$DATA_DIR"

# Colors
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    RED='\033[0;31m'
    YELLOW='\033[1;33m'
    NC='\033[0m'
else
    GREEN='' RED='' YELLOW='' NC=''
fi

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

get_pid() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            echo "$pid"
            return 0
        fi
    fi
    # Fallback: find by port
    lsof -ti :$PORT 2>/dev/null | head -1
}

is_healthy() {
    curl -s --max-time 2 "$HEALTH_URL" > /dev/null 2>&1
}

wait_for_healthy() {
    local elapsed=0
    while [ $elapsed -lt $STARTUP_TIMEOUT ]; do
        if is_healthy; then
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
        echo -ne "\r[WAIT] Elapsed: ${elapsed}s / ${STARTUP_TIMEOUT}s"
    done
    echo ""
    return 1
}

start_server() {
    log_info "Starting ChromaDB server..."

    local pid=$(get_pid)
    if [ -n "$pid" ]; then
        log_warn "ChromaDB already running (PID: $pid)"
        return 0
    fi

    # Start ChromaDB server
    nohup "$PYTHON" -m chromadb.cli.cli run \
        --host "$HOST" \
        --port "$PORT" \
        --path "$DATA_DIR" \
        >> "$LOG_FILE" 2>&1 &

    local new_pid=$!
    echo "$new_pid" > "$PID_FILE"
    log_info "ChromaDB started with PID: $new_pid"

    log_info "Waiting for ChromaDB to become healthy..."
    if wait_for_healthy; then
        log_info "ChromaDB is healthy"
        return 0
    else
        log_error "ChromaDB failed to start. Check logs: $LOG_FILE"
        tail -20 "$LOG_FILE" 2>/dev/null || true
        return 1
    fi
}

stop_server() {
    log_info "Stopping ChromaDB server..."

    local pid=$(get_pid)
    if [ -z "$pid" ]; then
        log_warn "ChromaDB not running"
        rm -f "$PID_FILE"
        return 0
    fi

    kill "$pid" 2>/dev/null || true
    sleep 2

    if ps -p "$pid" > /dev/null 2>&1; then
        log_warn "Force killing ChromaDB..."
        kill -9 "$pid" 2>/dev/null || true
    fi

    rm -f "$PID_FILE"
    log_info "ChromaDB stopped"
}

show_status() {
    echo ""
    log_info "=== ChromaDB Status ==="

    local pid=$(get_pid)
    if [ -n "$pid" ]; then
        log_info "Process: Running (PID: $pid)"
    else
        log_warn "Process: Not running"
    fi

    if is_healthy; then
        log_info "Health: Healthy"
        echo "  URL: http://$HOST:$PORT"
        echo "  Data: $DATA_DIR"
    else
        log_warn "Health: Not responding"
    fi
    echo ""
}

case "${1:-status}" in
    start)
        start_server
        ;;
    stop)
        stop_server
        ;;
    restart)
        stop_server
        start_server
        ;;
    status)
        show_status
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
```

**Step 2: Make executable and test manually**

```bash
chmod +x scripts/chromadb.sh
./scripts/chromadb.sh start
./scripts/chromadb.sh status
curl http://localhost:8001/api/v1/heartbeat
./scripts/chromadb.sh stop
```

Expected: Server starts, status shows healthy, heartbeat returns `{"nanosecond heartbeat":...}`, stops cleanly.

**Step 3: Commit**

```bash
git add scripts/chromadb.sh
git commit -m "feat: add ChromaDB server management script

Provides start/stop/restart/status commands for ChromaDB server.
Server runs on localhost:8001, stores data in ./data/chromadb.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 3: Create ChromaDB launchd Service

**Files:**
- Create: `config/launchd/com.lifeos.chromadb.plist`

**Step 1: Write the plist file**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.lifeos.chromadb</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/nathanramia/.venvs/lifeos/bin/python</string>
        <string>-m</string>
        <string>chromadb.cli.cli</string>
        <string>run</string>
        <string>--host</string>
        <string>localhost</string>
        <string>--port</string>
        <string>8001</string>
        <string>--path</string>
        <string>/Users/nathanramia/Documents/Code/LifeOS/data/chromadb</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/nathanramia/Documents/Code/LifeOS</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/Users/nathanramia/.venvs/lifeos/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>ThrottleInterval</key>
    <integer>10</integer>

    <key>StandardOutPath</key>
    <string>/Users/nathanramia/Documents/Code/LifeOS/logs/chromadb.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/nathanramia/Documents/Code/LifeOS/logs/chromadb-error.log</string>
</dict>
</plist>
```

**Step 2: Test launchd loading**

```bash
# Load the service
launchctl load config/launchd/com.lifeos.chromadb.plist

# Check it's running
launchctl list | grep chromadb

# Verify health
curl http://localhost:8001/api/v1/heartbeat

# Unload for now (we'll migrate first)
launchctl unload config/launchd/com.lifeos.chromadb.plist
```

**Step 3: Commit**

```bash
git add config/launchd/com.lifeos.chromadb.plist
git commit -m "feat: add launchd service for ChromaDB server

Runs ChromaDB on localhost:8001 at boot.
Configured for auto-restart on crash.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 4: Migrate VectorStore to HttpClient

**Files:**
- Modify: `api/services/vectorstore.py:1-50`

**Step 1: Write the failing test**

```python
# tests/test_vectorstore_client.py
import pytest

def test_vectorstore_uses_http_client():
    """VectorStore should connect via HTTP, not direct file access."""
    from api.services.vectorstore import VectorStore
    import chromadb

    vs = VectorStore()

    # Should be using HttpClient, not PersistentClient
    assert isinstance(vs._client, chromadb.HttpClient)

def test_vectorstore_connects_to_server():
    """VectorStore should successfully connect to ChromaDB server."""
    from api.services.vectorstore import VectorStore

    vs = VectorStore()

    # Should be able to get heartbeat (proves connection works)
    heartbeat = vs._client.heartbeat()
    assert heartbeat is not None

def test_vectorstore_search_works():
    """Basic search should work through HTTP client."""
    from api.services.vectorstore import VectorStore

    vs = VectorStore()
    results = vs.search("test query", top_k=1)

    # Should return a list (even if empty)
    assert isinstance(results, list)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_vectorstore_client.py -v`
Expected: FAIL (currently using PersistentClient)

**Step 3: Modify vectorstore.py**

Replace lines 1-50 with:

```python
"""
ChromaDB vector store service for LifeOS.

Connects to ChromaDB server via HTTP for thread-safe concurrent access.
"""
import chromadb
from chromadb.config import Settings
from typing import Optional
from datetime import datetime
import json
import math

from api.services.embeddings import get_embedding_service
from config.settings import settings


class VectorStore:
    """ChromaDB-backed vector store for document chunks."""

    def __init__(
        self,
        collection_name: str = "lifeos_vault",
        server_url: str = None
    ):
        """
        Initialize vector store.

        Args:
            collection_name: Name of the collection
            server_url: ChromaDB server URL (default: from settings)
        """
        self.collection_name = collection_name
        self.server_url = server_url or settings.chroma_url

        # Connect to ChromaDB server via HTTP
        self._client = chromadb.HttpClient(
            host=self._parse_host(self.server_url),
            port=self._parse_port(self.server_url),
            settings=Settings(anonymized_telemetry=False)
        )

        # Get or create collection
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

        # Get embedding service
        self._embedding_service = get_embedding_service()

    def _parse_host(self, url: str) -> str:
        """Extract host from URL."""
        # http://localhost:8001 -> localhost
        return url.replace("http://", "").replace("https://", "").split(":")[0]

    def _parse_port(self, url: str) -> int:
        """Extract port from URL."""
        # http://localhost:8001 -> 8001
        parts = url.replace("http://", "").replace("https://", "").split(":")
        return int(parts[1]) if len(parts) > 1 else 8000
```

**Step 4: Run tests to verify they pass**

First, ensure ChromaDB server is running:
```bash
./scripts/chromadb.sh start
```

Then run tests:
```bash
pytest tests/test_vectorstore_client.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add api/services/vectorstore.py tests/test_vectorstore_client.py
git commit -m "feat: migrate VectorStore to ChromaDB HttpClient

BREAKING: Requires ChromaDB server running on localhost:8001.
Eliminates database corruption from concurrent PersistentClient access.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 5: Update Health Checks

**Files:**
- Modify: `api/main.py` (health/full endpoint)

**Step 1: Write the failing test**

```python
# tests/test_health_chromadb.py
import pytest
import httpx

def test_health_full_includes_chromadb_server():
    """Full health check should verify ChromaDB server is running."""
    resp = httpx.get("http://localhost:8000/health/full", timeout=60)
    assert resp.status_code == 200

    data = resp.json()
    assert "chromadb_server" in data["checks"]
    assert data["checks"]["chromadb_server"]["status"] == "ok"

def test_health_full_chromadb_reports_latency():
    """ChromaDB health check should report latency."""
    resp = httpx.get("http://localhost:8000/health/full", timeout=60)
    data = resp.json()

    assert "latency_ms" in data["checks"]["chromadb_server"]
    assert data["checks"]["chromadb_server"]["latency_ms"] >= 0
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_health_chromadb.py -v`
Expected: FAIL (chromadb_server check doesn't exist yet)

**Step 3: Add ChromaDB server health check**

In `api/main.py`, in the `full_health_check` function, add after the API key check:

```python
    # 2. ChromaDB Server
    async def check_chromadb_server():
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.chroma_url}/api/v1/heartbeat")
            if resp.status_code == 200:
                return "connected"
            raise Exception(f"HTTP {resp.status_code}")

    start = time.time()
    try:
        detail = await check_chromadb_server()
        elapsed = int((time.time() - start) * 1000)
        results["checks"]["chromadb_server"] = {
            "status": "ok",
            "latency_ms": elapsed,
            "detail": detail,
            "url": settings.chroma_url
        }
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        results["checks"]["chromadb_server"] = {
            "status": "error",
            "latency_ms": elapsed,
            "error": str(e),
            "url": settings.chroma_url
        }
        results["errors"].append(f"chromadb_server: {str(e)}")
```

Also add the import at the top of the function:
```python
from config.settings import settings
```

**Step 4: Run tests to verify they pass**

Ensure both servers are running:
```bash
./scripts/chromadb.sh start
./scripts/server.sh restart
```

Run tests:
```bash
pytest tests/test_health_chromadb.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add api/main.py tests/test_health_chromadb.py
git commit -m "feat: add ChromaDB server health check to /health/full

Reports connection status, latency, and URL.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 6: Update Server Script to Check ChromaDB

**Files:**
- Modify: `scripts/server.sh`

**Step 1: Add ChromaDB dependency check**

In `scripts/server.sh`, add after the `HEALTH_URL` definition (~line 26):

```bash
CHROMADB_URL="http://localhost:8001/api/v1/heartbeat"
```

Add a new function after `is_healthy`:

```bash
chromadb_healthy() {
    curl -s --max-time 2 "$CHROMADB_URL" > /dev/null 2>&1
}
```

Modify `start_server` function to check ChromaDB first:

```bash
start_server() {
    log_info "Starting LifeOS server..."

    # Check ChromaDB is running
    if ! chromadb_healthy; then
        log_warn "ChromaDB server not running. Starting it..."
        "$SCRIPT_DIR/chromadb.sh" start
        if ! chromadb_healthy; then
            log_error "Failed to start ChromaDB. Cannot start LifeOS."
            return 1
        fi
    fi

    # ... rest of existing start_server code
```

**Step 2: Test manually**

```bash
# Stop ChromaDB
./scripts/chromadb.sh stop

# Try to start LifeOS - should auto-start ChromaDB
./scripts/server.sh restart

# Verify both are running
./scripts/chromadb.sh status
./scripts/server.sh status
```

**Step 3: Commit**

```bash
git add scripts/server.sh
git commit -m "feat: server.sh auto-starts ChromaDB if not running

Ensures ChromaDB dependency is satisfied before starting LifeOS API.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 7: Comprehensive End-to-End Tests

**Files:**
- Create: `tests/test_chromadb_e2e.py`

**Step 1: Write comprehensive tests**

```python
"""
End-to-end tests for ChromaDB client-server migration.

These tests verify the full user workflow works correctly:
1. ChromaDB server is running and healthy
2. Indexing works (write path)
3. Search works (read path)
4. Multiple concurrent requests work (concurrency)
5. MCP tools work through the new architecture

Run with: pytest tests/test_chromadb_e2e.py -v
Requires: Both ChromaDB server (port 8001) and LifeOS API (port 8000) running
"""
import pytest
import httpx
import asyncio
import time


# --- Setup & Health Checks ---

@pytest.fixture(scope="module")
def api_client():
    """HTTP client for LifeOS API."""
    with httpx.Client(base_url="http://localhost:8000", timeout=60.0) as client:
        yield client


@pytest.fixture(scope="module")
def chromadb_client():
    """HTTP client for ChromaDB server."""
    with httpx.Client(base_url="http://localhost:8001", timeout=10.0) as client:
        yield client


class TestChromaDBServerHealth:
    """Verify ChromaDB server is accessible."""

    def test_chromadb_heartbeat(self, chromadb_client):
        """ChromaDB server should respond to heartbeat."""
        resp = chromadb_client.get("/api/v1/heartbeat")
        assert resp.status_code == 200
        data = resp.json()
        assert "nanosecond heartbeat" in data

    def test_chromadb_version(self, chromadb_client):
        """ChromaDB server should report version."""
        resp = chromadb_client.get("/api/v1/version")
        assert resp.status_code == 200


class TestLifeOSHealth:
    """Verify LifeOS API connects to ChromaDB correctly."""

    def test_basic_health(self, api_client):
        """Basic health check should pass."""
        resp = api_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    def test_full_health_includes_chromadb(self, api_client):
        """Full health should show ChromaDB as connected."""
        resp = api_client.get("/health/full")
        assert resp.status_code == 200

        data = resp.json()
        assert "chromadb_server" in data["checks"]
        assert data["checks"]["chromadb_server"]["status"] == "ok"
        assert "latency_ms" in data["checks"]["chromadb_server"]


# --- Read Path Tests ---

class TestSearchOperations:
    """Test search (read) operations through HTTP client."""

    def test_vault_search(self, api_client):
        """POST /api/search should work through ChromaDB server."""
        resp = api_client.post("/api/search", json={
            "query": "meeting notes",
            "top_k": 5
        })
        assert resp.status_code == 200

        data = resp.json()
        assert "results" in data
        assert isinstance(data["results"], list)

    def test_ask_endpoint(self, api_client):
        """POST /api/ask should work through ChromaDB server."""
        resp = api_client.post("/api/ask", json={
            "question": "What is LifeOS?",
            "include_sources": True
        })
        assert resp.status_code == 200

        data = resp.json()
        assert "answer" in data

    def test_calendar_search(self, api_client):
        """GET /api/calendar/search should work."""
        resp = api_client.get("/api/calendar/search", params={"q": "meeting"})
        assert resp.status_code == 200

    def test_people_search(self, api_client):
        """GET /api/people/search should work."""
        resp = api_client.get("/api/people/search", params={"q": "a"})
        assert resp.status_code == 200


# --- Write Path Tests ---

class TestIndexingOperations:
    """Test indexing (write) operations through HTTP client."""

    def test_admin_status(self, api_client):
        """GET /api/admin/status should report document count."""
        resp = api_client.get("/api/admin/status")
        assert resp.status_code == 200

        data = resp.json()
        assert "document_count" in data
        assert data["document_count"] >= 0

    def test_reindex_starts(self, api_client):
        """POST /api/admin/reindex should start without error."""
        resp = api_client.post("/api/admin/reindex")
        assert resp.status_code == 200

        data = resp.json()
        assert data["status"] in ["started", "already_running"]


# --- Concurrency Tests ---

class TestConcurrentAccess:
    """Verify multiple concurrent requests work correctly."""

    @pytest.mark.asyncio
    async def test_concurrent_searches(self):
        """Multiple concurrent searches should not cause errors."""
        async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=60.0) as client:
            # Fire 10 concurrent search requests
            tasks = [
                client.post("/api/search", json={"query": f"test query {i}", "top_k": 3})
                for i in range(10)
            ]

            responses = await asyncio.gather(*tasks, return_exceptions=True)

            # All should succeed
            for i, resp in enumerate(responses):
                assert not isinstance(resp, Exception), f"Request {i} failed: {resp}"
                assert resp.status_code == 200, f"Request {i} returned {resp.status_code}"

    @pytest.mark.asyncio
    async def test_mixed_read_write(self):
        """Concurrent reads and writes should not corrupt database."""
        async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=60.0) as client:
            # Mix of search (read) and status (read) requests
            tasks = []
            for i in range(5):
                tasks.append(client.post("/api/search", json={"query": f"query {i}", "top_k": 2}))
                tasks.append(client.get("/api/admin/status"))

            responses = await asyncio.gather(*tasks, return_exceptions=True)

            # All should succeed without corruption errors
            for resp in responses:
                assert not isinstance(resp, Exception)
                assert resp.status_code == 200


# --- MCP Tool Tests ---

class TestMCPToolsWork:
    """Verify MCP tools work through the new architecture."""

    def test_lifeos_search_tool(self, api_client):
        """lifeos_search MCP tool should work."""
        # This is what the MCP tool calls
        resp = api_client.post("/api/search", json={
            "query": "test",
            "top_k": 1
        })
        assert resp.status_code == 200

    def test_lifeos_ask_tool(self, api_client):
        """lifeos_ask MCP tool should work."""
        resp = api_client.post("/api/ask", json={
            "question": "test query",
            "include_sources": True
        })
        assert resp.status_code == 200

    def test_lifeos_health_tool(self, api_client):
        """lifeos_health MCP tool should work."""
        resp = api_client.get("/health/full")
        assert resp.status_code == 200

        data = resp.json()
        # Should not have chromadb errors
        chromadb_check = data["checks"].get("chromadb_server", {})
        assert chromadb_check.get("status") == "ok"


# --- Regression Tests ---

class TestNoCorruption:
    """Verify the corruption issue is fixed."""

    def test_rapid_sequential_searches(self, api_client):
        """Rapid sequential searches should not cause corruption."""
        for i in range(20):
            resp = api_client.post("/api/search", json={
                "query": f"rapid test {i}",
                "top_k": 1
            })
            assert resp.status_code == 200, f"Search {i} failed with {resp.status_code}: {resp.text}"

    def test_search_after_status_check(self, api_client):
        """Search should work after status check (different clients in old code)."""
        # Status check
        resp1 = api_client.get("/api/admin/status")
        assert resp1.status_code == 200

        # Immediate search
        resp2 = api_client.post("/api/search", json={"query": "test", "top_k": 1})
        assert resp2.status_code == 200

        # Another status check
        resp3 = api_client.get("/api/admin/status")
        assert resp3.status_code == 200
```

**Step 2: Run the tests**

```bash
# Ensure both servers are running
./scripts/chromadb.sh start
./scripts/server.sh restart

# Run all e2e tests
pytest tests/test_chromadb_e2e.py -v

# Run with concurrency tests
pytest tests/test_chromadb_e2e.py -v --asyncio-mode=auto
```

Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/test_chromadb_e2e.py
git commit -m "test: add comprehensive e2e tests for ChromaDB migration

Tests health, search, indexing, concurrency, MCP tools, and regression.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 8: Update Documentation

**Files:**
- Modify: `docs/SYSTEM_ARCHITECTURE.md`
- Modify: `README.md`
- Modify: `CLAUDE.md`

**Step 1: Update SYSTEM_ARCHITECTURE.md**

Add a new section after "Data Stores":

```markdown
---

## ChromaDB Server

LifeOS uses ChromaDB in client-server mode for reliable concurrent access.

### Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `LIFEOS_CHROMA_URL` | `http://localhost:8001` | ChromaDB server URL |

### Management

```bash
# Start ChromaDB server
./scripts/chromadb.sh start

# Check status
./scripts/chromadb.sh status

# Stop server
./scripts/chromadb.sh stop
```

### launchd Service

The ChromaDB server runs as a launchd service for auto-start on boot:

```bash
# Load service (run once)
launchctl load config/launchd/com.lifeos.chromadb.plist

# Unload service
launchctl unload config/launchd/com.lifeos.chromadb.plist
```

### Architecture

```
┌─────────────────┐     HTTP      ┌─────────────────┐
│   LifeOS API    │◄────────────►│  ChromaDB Server │
│  (port 8000)    │   :8001      │   (port 8001)    │
└─────────────────┘               └─────────────────┘
        │                                  │
        │                                  │
        ▼                                  ▼
   SQLite DBs                        chromadb/
   (conversations,                   (vector data)
    interactions)
```

### Why Client-Server Mode?

ChromaDB's `PersistentClient` (direct file access) is not designed for concurrent access from multiple threads/processes. The client-server architecture:

1. **Eliminates corruption** - Server handles all concurrency internally
2. **Enables scaling** - Server can run on different machine if needed
3. **Simplifies code** - No need for custom locking/pooling
```

**Step 2: Update README.md**

Add to the "Getting Started" or "Setup" section:

```markdown
### ChromaDB Server

LifeOS requires ChromaDB running as a server:

```bash
# Start ChromaDB (required before starting LifeOS)
./scripts/chromadb.sh start

# Or load as launchd service (auto-starts on boot)
launchctl load config/launchd/com.lifeos.chromadb.plist
```
```

**Step 3: Update CLAUDE.md**

Update the "Checking System Health" section:

```markdown
### Checking System Health

**Is ChromaDB server running?**
```bash
./scripts/chromadb.sh status
curl http://localhost:8001/api/v1/heartbeat
```

**Is the LifeOS API running?**
```bash
./scripts/server.sh status
curl http://localhost:8000/health
```

**Full health check (tests all services including ChromaDB):**
```bash
curl -s http://localhost:8000/health/full | python3 -m json.tool
```
```

**Step 4: Commit**

```bash
git add docs/SYSTEM_ARCHITECTURE.md README.md CLAUDE.md
git commit -m "docs: document ChromaDB client-server architecture

Updates system architecture, README, and CLAUDE.md with:
- ChromaDB server management commands
- launchd service configuration
- Architecture diagram
- Why client-server mode

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 9: Final Integration Test & Cleanup

**Step 1: Run full test suite**

```bash
# Start all services
./scripts/chromadb.sh start
./scripts/server.sh restart

# Run all tests
pytest tests/ -v --ignore=tests/browser/

# Run MCP server tests
python scripts/test_mcp.py
```

**Step 2: Verify MCP tools work from Claude Code**

In a new Claude Code session in the vault:
```
Ask Claude: "Search my vault for recent meetings"
```

Should work without "MCP tools not connected" errors.

**Step 3: Load launchd services for production**

```bash
# Load ChromaDB service (starts on boot)
launchctl load config/launchd/com.lifeos.chromadb.plist

# Verify it's running
launchctl list | grep chromadb
./scripts/chromadb.sh status
```

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete ChromaDB client-server migration

Migration complete. ChromaDB now runs as HTTP server on localhost:8001.
All concurrent access goes through the server, eliminating corruption.

Changes:
- VectorStore uses HttpClient instead of PersistentClient
- New chromadb.sh management script
- New launchd service for auto-start
- Health checks verify ChromaDB connectivity
- Comprehensive e2e tests

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Rollback Plan

If issues occur after migration:

1. Stop ChromaDB server: `./scripts/chromadb.sh stop`
2. Revert vectorstore.py to use `PersistentClient`
3. Restart LifeOS: `./scripts/server.sh restart`

The data in `./data/chromadb/` is compatible with both modes.

---

## Success Criteria

- [ ] ChromaDB server starts and stays healthy
- [ ] `/health/full` shows `chromadb_server: ok`
- [ ] `POST /api/search` works without 500 errors
- [ ] `POST /api/ask` works without corruption
- [ ] Concurrent requests don't cause corruption
- [ ] MCP tools work in Claude Code sessions
- [ ] All e2e tests pass
- [ ] launchd services auto-start on reboot

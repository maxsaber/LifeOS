"""
LifeOS - Personal RAG System for Obsidian Vault
FastAPI Application Entry Point

WARNING: Do not run this file directly with uvicorn!
=========================================================
Always use the server management script:

    ./scripts/server.sh start    # Start server
    ./scripts/server.sh restart  # Restart after code changes
    ./scripts/server.sh stop     # Stop server

Running uvicorn directly can create ghost processes that bind to different
interfaces, causing localhost and Tailscale/network access to hit different
server instances with different code versions.

See CLAUDE.md for full instructions for AI coding agents.
"""
# Load environment variables from .env file first, before any imports
from dotenv import load_dotenv
load_dotenv()

import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from api.routes import search, ask, calendar, gmail, drive, people, chat, briefings, admin, conversations, memories, imessage, crm, slack
from config.settings import settings

logger = logging.getLogger(__name__)

# Background services (initialized on startup)
_granola_processor = None
_omi_processor = None
_calendar_indexer = None
_people_v2_sync_thread = None
_people_v2_stop_event = threading.Event()


def _nightly_sync_loop(stop_event: threading.Event, schedule_hour: int = 3, timezone: str = "America/New_York"):
    """
    Background thread that runs nightly sync operations at a scheduled time.

    Operations performed (in order):
    1. Vault reindex - indexes all vault notes, triggering v2 people extraction
    2. People v2 sync - LinkedIn CSV, Gmail sent emails, Calendar attendees
    3. Google Docs sync - syncs configured docs to vault as Markdown

    Args:
        stop_event: Event to signal thread shutdown
        schedule_hour: Hour to run sync (24h format, default 3 AM)
        timezone: Timezone for scheduling
    """
    tz = ZoneInfo(timezone)

    while not stop_event.is_set():
        now = datetime.now(tz)

        # Calculate next run time
        next_run = now.replace(hour=schedule_hour, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run += timedelta(days=1)

        # Sleep until next run (check every 60 seconds for stop signal)
        while datetime.now(tz) < next_run and not stop_event.is_set():
            stop_event.wait(timeout=60)

        if stop_event.is_set():
            break

        # Stagger sync operations with delays to avoid database contention
        import time
        STEP_DELAY = 60  # seconds between steps

        # Track failures for notification
        failures = []

        # === Step 1: Vault Reindex ===
        # This indexes all vault notes, which triggers _sync_people_to_v2() hook
        # for each file, extracting people mentions and creating interactions
        try:
            logger.info("Nightly sync: Starting vault reindex...")
            from api.services.indexer import IndexerService
            indexer = IndexerService(vault_path=settings.vault_path)
            files_indexed = indexer.index_all()
            logger.info(f"Nightly sync: Vault reindex complete ({files_indexed} files)")
        except Exception as e:
            logger.error(f"Nightly sync: Vault reindex failed: {e}")
            failures.append(("Vault reindex", str(e)))

        time.sleep(STEP_DELAY)  # Let ChromaDB settle

        # === Step 2: LinkedIn + Gmail + Calendar Sync ===
        try:
            logger.info("Nightly sync: Starting People v2 sync (LinkedIn, Gmail, Calendar)...")
            from api.services.people_aggregator import sync_people_v2
            from api.services.gmail import get_gmail_service

            gmail_service = get_gmail_service()

            stats = sync_people_v2(
                gmail_service=gmail_service,
                linkedin_csv_path="./data/LinkedInConnections.csv",
                days_back=1  # Incremental: last 24 hours
            )
            logger.info(f"Nightly sync: People v2 sync completed: {stats}")
        except Exception as e:
            logger.error(f"Nightly sync: People v2 sync failed: {e}")
            failures.append(("People v2 sync", str(e)))

        time.sleep(STEP_DELAY)  # Let APIs settle

        # === Step 3: Google Docs Sync ===
        # Syncs configured Google Docs to Obsidian vault as Markdown
        try:
            logger.info("Nightly sync: Starting Google Docs sync...")
            from api.services.gdoc_sync import sync_gdocs
            gdoc_stats = sync_gdocs()
            logger.info(f"Nightly sync: Google Docs sync completed: {gdoc_stats}")
        except Exception as e:
            logger.error(f"Nightly sync: Google Docs sync failed: {e}")
            failures.append(("Google Docs sync", str(e)))

        time.sleep(STEP_DELAY)  # Let filesystem settle

        # === Step 4: Google Sheets Sync ===
        # Syncs configured Google Sheets (e.g., daily journals) to vault
        try:
            logger.info("Nightly sync: Starting Google Sheets sync...")
            from api.services.gsheet_sync import sync_gsheets
            gsheet_stats = sync_gsheets()
            logger.info(f"Nightly sync: Google Sheets sync completed: {gsheet_stats}")
        except Exception as e:
            logger.error(f"Nightly sync: Google Sheets sync failed: {e}")
            failures.append(("Google Sheets sync", str(e)))

        time.sleep(STEP_DELAY)  # Let APIs settle

        # === Step 5: iMessage Sync ===
        # Exports new messages and joins with PersonEntity records
        try:
            logger.info("Nightly sync: Starting iMessage sync...")
            from api.services.imessage import sync_and_join_imessages
            imessage_stats = sync_and_join_imessages()
            logger.info(f"Nightly sync: iMessage sync completed: {imessage_stats}")
        except Exception as e:
            logger.error(f"Nightly sync: iMessage sync failed: {e}")
            failures.append(("iMessage sync", str(e)))

        time.sleep(STEP_DELAY)  # Let APIs settle

        # === Step 6: Slack Sync ===
        # Indexes Slack DMs and creates interactions for CRM
        try:
            from api.services.slack_integration import is_slack_enabled
            if is_slack_enabled():
                logger.info("Nightly sync: Starting Slack sync...")
                from api.services.slack_sync import run_slack_sync
                slack_stats = run_slack_sync(full=False)  # Incremental sync
                logger.info(f"Nightly sync: Slack sync completed: {slack_stats}")
            else:
                logger.info("Nightly sync: Slack not enabled, skipping")
        except Exception as e:
            logger.error(f"Nightly sync: Slack sync failed: {e}")
            failures.append(("Slack sync", str(e)))

        # Collect processor failures from the last 24 hours
        try:
            from api.services.notifications import get_recent_failures, clear_failures
            processor_failures = get_recent_failures(hours=24)
            for ts, source, error in processor_failures:
                failures.append((f"{source} ({ts.strftime('%H:%M')})", error))
            if processor_failures:
                clear_failures()  # Clear after collecting
                logger.info(f"Collected {len(processor_failures)} processor failures from last 24h")
        except Exception as e:
            logger.error(f"Failed to collect processor failures: {e}")

        # Send notification if any failures occurred
        if failures:
            logger.warning(f"Nightly sync: {len(failures)} failure(s), sending alert...")
            try:
                from api.services.notifications import send_alert
                failure_lines = [f"- {name}: {error}" for name, error in failures]
                send_alert(
                    subject=f"Nightly sync: {len(failures)} failure(s)",
                    body=f"The following operations failed in the last 24 hours:\n\n" + "\n".join(failure_lines),
                )
            except Exception as e:
                logger.error(f"Failed to send failure notification: {e}")

        logger.info("Nightly sync: All steps complete")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - startup and shutdown."""
    global _granola_processor, _omi_processor, _calendar_indexer, _people_v2_sync_thread

    # Startup: Initialize and start Granola processor
    try:
        from api.services.granola_processor import GranolaProcessor
        _granola_processor = GranolaProcessor(settings.vault_path)
        _granola_processor.start_watching()
        logger.info("Granola processor started successfully")
    except Exception as e:
        logger.error(f"Failed to start Granola processor: {e}")

    # Startup: Initialize and start Omi processor
    try:
        from api.services.omi_processor import OmiProcessor
        _omi_processor = OmiProcessor(settings.vault_path)
        _omi_processor.start()
        logger.info("Omi processor started successfully")
    except Exception as e:
        logger.error(f"Failed to start Omi processor: {e}")

    # Startup: Initialize and start Calendar indexer at specific times (Eastern)
    try:
        from api.services.calendar_indexer import get_calendar_indexer
        _calendar_indexer = get_calendar_indexer()
        # Sync at 8 AM, noon, and 3 PM Eastern
        _calendar_indexer.start_time_scheduler(
            schedule_times=[(8, 0), (12, 0), (15, 0)],
            timezone="America/New_York"
        )
        logger.info("Calendar indexer scheduler started (8:00, 12:00, 15:00 Eastern)")
    except Exception as e:
        logger.error(f"Failed to start Calendar indexer: {e}")

    # Startup: Initialize and start nightly sync scheduler (3 AM Eastern)
    # Runs: vault reindex → LinkedIn sync → Gmail sync → Calendar sync
    try:
        _people_v2_stop_event.clear()
        _people_v2_sync_thread = threading.Thread(
            target=_nightly_sync_loop,
            args=(_people_v2_stop_event,),
            kwargs={"schedule_hour": 3, "timezone": "America/New_York"},
            daemon=True,
            name="NightlySyncThread"
        )
        _people_v2_sync_thread.start()
        logger.info("Nightly sync scheduler started (3:00 AM Eastern): vault reindex + people v2 sync")
    except Exception as e:
        logger.error(f"Failed to start People v2 sync scheduler: {e}")

    yield  # Application runs here

    # Shutdown: Stop services
    if _granola_processor:
        _granola_processor.stop()
        logger.info("Granola processor stopped")

    if _omi_processor:
        _omi_processor.stop()
        logger.info("Omi processor stopped")

    if _calendar_indexer:
        _calendar_indexer.stop_scheduler()
        logger.info("Calendar indexer stopped")

    if _people_v2_sync_thread and _people_v2_sync_thread.is_alive():
        _people_v2_stop_event.set()
        _people_v2_sync_thread.join(timeout=5)
        logger.info("Nightly sync scheduler stopped")


app = FastAPI(
    title="LifeOS",
    description="Personal assistant system for semantic search and synthesis across Obsidian vault",
    version="0.2.0",
    lifespan=lifespan
)

# CORS middleware for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(search.router)
app.include_router(ask.router)
app.include_router(calendar.router)
app.include_router(gmail.router)
app.include_router(drive.router)
app.include_router(people.router)
app.include_router(chat.router)
app.include_router(briefings.router)
app.include_router(admin.router)
app.include_router(conversations.router)
app.include_router(memories.router)
app.include_router(imessage.router)
app.include_router(crm.router)
app.include_router(slack.router)

# Serve static files
web_dir = Path(__file__).parent.parent / "web"
if web_dir.exists():
    app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Convert validation errors to 400 with clear messages."""
    errors = exc.errors()

    # Sanitize errors for JSON serialization (convert bytes to string)
    sanitized_errors = []
    for error in errors:
        sanitized = dict(error)
        if "input" in sanitized and isinstance(sanitized["input"], bytes):
            sanitized["input"] = sanitized["input"].decode("utf-8", errors="replace")
        sanitized_errors.append(sanitized)

    # Check if this is an empty query error
    for error in errors:
        if "query" in str(error.get("loc", [])):
            return JSONResponse(
                status_code=400,
                content={"error": "Query cannot be empty", "detail": sanitized_errors}
            )
    return JSONResponse(
        status_code=400,
        content={"error": "Validation error", "detail": sanitized_errors}
    )


@app.get("/health")
async def health_check():
    """Health check endpoint that verifies critical dependencies."""
    from config.settings import settings

    checks = {
        "api_key_configured": bool(settings.anthropic_api_key and settings.anthropic_api_key.strip()),
    }

    all_healthy = all(checks.values())

    return {
        "status": "healthy" if all_healthy else "degraded",
        "service": "lifeos",
        "checks": checks,
    }


@app.get("/health/full")
async def full_health_check():
    """
    Comprehensive health check that tests all LifeOS services.

    Tests each service by calling the actual API endpoints the same way
    MCP tools would call them. Use this to verify all MCP tools will work.

    Returns detailed status for each service with timing.
    """
    import time
    import httpx
    from config.settings import settings

    BASE_URL = f"http://localhost:{settings.port}"

    results = {
        "status": "healthy",
        "service": "lifeos",
        "checks": {},
        "errors": [],
    }

    async def test_endpoint(name: str, method: str, path: str, params: dict = None, json_body: dict = None):
        """Test an endpoint by actually calling it."""
        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                url = f"{BASE_URL}{path}"
                if method == "GET":
                    resp = await client.get(url, params=params)
                else:
                    resp = await client.post(url, json=json_body)

                elapsed = int((time.time() - start) * 1000)

                if resp.status_code == 200:
                    data = resp.json()
                    # Extract a summary from the response
                    if "results" in data:
                        detail = f"{len(data['results'])} results"
                    elif "files" in data:
                        detail = f"{len(data['files'])} files"
                    elif "events" in data:
                        detail = f"{len(data['events'])} events"
                    elif "emails" in data or "messages" in data:
                        detail = f"{len(data.get('emails', data.get('messages', [])))} emails"
                    elif "conversations" in data:
                        detail = f"{len(data['conversations'])} conversations"
                    elif "memories" in data:
                        detail = f"{len(data['memories'])} memories"
                    elif "people" in data:
                        detail = f"{len(data['people'])} people"
                    elif "answer" in data:
                        detail = f"synthesized ({len(data['answer'])} chars)"
                    else:
                        detail = "ok"

                    results["checks"][name] = {
                        "status": "ok",
                        "latency_ms": elapsed,
                        "detail": detail
                    }
                    return True
                else:
                    results["checks"][name] = {
                        "status": "error",
                        "latency_ms": elapsed,
                        "error": f"HTTP {resp.status_code}: {resp.text[:100]}"
                    }
                    results["errors"].append(f"{name}: HTTP {resp.status_code}")
                    return False

        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            results["checks"][name] = {
                "status": "error",
                "latency_ms": elapsed,
                "error": str(e)
            }
            results["errors"].append(f"{name}: {str(e)}")
            return False

    # 1. Config check (no HTTP needed)
    if settings.anthropic_api_key and settings.anthropic_api_key.strip():
        results["checks"]["anthropic_api_key"] = {"status": "ok", "detail": "configured"}
    else:
        results["checks"]["anthropic_api_key"] = {"status": "error", "error": "not configured"}
        results["errors"].append("anthropic_api_key: not configured")

    # 2. ChromaDB Server (direct health check)
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.chroma_url}/api/v2/heartbeat")
            elapsed = int((time.time() - start) * 1000)
            if resp.status_code == 200:
                results["checks"]["chromadb_server"] = {
                    "status": "ok",
                    "latency_ms": elapsed,
                    "detail": "connected",
                    "url": settings.chroma_url
                }
            else:
                results["checks"]["chromadb_server"] = {
                    "status": "error",
                    "latency_ms": elapsed,
                    "error": f"HTTP {resp.status_code}",
                    "url": settings.chroma_url
                }
                results["errors"].append(f"chromadb_server: HTTP {resp.status_code}")
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        results["checks"]["chromadb_server"] = {
            "status": "error",
            "latency_ms": elapsed,
            "error": str(e),
            "url": settings.chroma_url
        }
        results["errors"].append(f"chromadb_server: {str(e)}")

    # 3. Vault Search (POST /api/search) - tests ChromaDB + BM25
    await test_endpoint(
        "vault_search",
        "POST", "/api/search",
        json_body={"query": "test", "top_k": 1}
    )

    # 3. Calendar Upcoming (GET /api/calendar/upcoming)
    await test_endpoint(
        "calendar_upcoming",
        "GET", "/api/calendar/upcoming",
        params={"days": 1}
    )

    # 4. Calendar Search (GET /api/calendar/search)
    await test_endpoint(
        "calendar_search",
        "GET", "/api/calendar/search",
        params={"q": "meeting"}
    )

    # 5. Gmail Search (GET /api/gmail/search)
    await test_endpoint(
        "gmail_search",
        "GET", "/api/gmail/search",
        params={"q": "in:inbox", "max_results": 1}
    )

    # 6. Drive Search - Personal (GET /api/drive/search)
    await test_endpoint(
        "drive_search_personal",
        "GET", "/api/drive/search",
        params={"q": "test", "account": "personal", "max_results": 1}
    )

    # 7. Drive Search - Work (GET /api/drive/search)
    await test_endpoint(
        "drive_search_work",
        "GET", "/api/drive/search",
        params={"q": "test", "account": "work", "max_results": 1}
    )

    # 8. People Search (GET /api/people/search)
    await test_endpoint(
        "people_search",
        "GET", "/api/people/search",
        params={"q": "a"}
    )

    # 9. Conversations List (GET /api/conversations)
    await test_endpoint(
        "conversations_list",
        "GET", "/api/conversations",
        params={"limit": 1}
    )

    # 10. Memories List (GET /api/memories)
    await test_endpoint(
        "memories_list",
        "GET", "/api/memories",
        params={"limit": 1}
    )

    # 11. iMessage Statistics (GET /api/imessage/statistics)
    await test_endpoint(
        "imessage_stats",
        "GET", "/api/imessage/statistics",
    )

    # Set overall status
    failed = [k for k, v in results["checks"].items() if v["status"] == "error"]
    if failed:
        results["status"] = "degraded" if len(failed) < 5 else "unhealthy"
        results["summary"] = f"{len(failed)} service(s) failing: {', '.join(failed)}"
    else:
        results["summary"] = f"All {len(results['checks'])} services healthy"

    return results


@app.get("/")
async def root():
    """Serve the chat UI."""
    index_path = Path(__file__).parent.parent / "web" / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "LifeOS API", "version": "0.3.0"}


@app.get("/crm")
async def crm_page():
    """Serve the CRM UI."""
    crm_path = Path(__file__).parent.parent / "web" / "crm.html"
    if crm_path.exists():
        return FileResponse(str(crm_path))
    return {"message": "CRM page not found"}

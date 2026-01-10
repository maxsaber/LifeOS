"""
LifeOS - Personal RAG System for Obsidian Vault
FastAPI Application Entry Point
"""
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
from api.routes import search, ask, calendar, gmail, drive, people, chat, briefings, admin, conversations, memories
from config.settings import settings

logger = logging.getLogger(__name__)

# Background services (initialized on startup)
_granola_processor = None
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

        # === Step 2: LinkedIn + Gmail + Calendar Sync ===
        try:
            logger.info("Nightly sync: Starting People v2 sync (LinkedIn, Gmail, Calendar)...")
            from api.services.people_aggregator import sync_people_v2
            from api.services.gmail_service import get_gmail_service

            gmail_service = get_gmail_service()

            stats = sync_people_v2(
                gmail_service=gmail_service,
                linkedin_csv_path="./data/LinkedInConnections.csv",
                days_back=1  # Incremental: last 24 hours
            )
            logger.info(f"Nightly sync: People v2 sync completed: {stats}")
        except Exception as e:
            logger.error(f"Nightly sync: People v2 sync failed: {e}")

        # === Step 3: Google Docs Sync ===
        # Syncs configured Google Docs to Obsidian vault as Markdown
        try:
            logger.info("Nightly sync: Starting Google Docs sync...")
            from api.services.gdoc_sync import sync_gdocs
            gdoc_stats = sync_gdocs()
            logger.info(f"Nightly sync: Google Docs sync completed: {gdoc_stats}")
        except Exception as e:
            logger.error(f"Nightly sync: Google Docs sync failed: {e}")

        # === Step 4: iMessage Sync ===
        # Exports new messages and joins with PersonEntity records
        try:
            logger.info("Nightly sync: Starting iMessage sync...")
            from api.services.imessage import sync_and_join_imessages
            imessage_stats = sync_and_join_imessages()
            logger.info(f"Nightly sync: iMessage sync completed: {imessage_stats}")
        except Exception as e:
            logger.error(f"Nightly sync: iMessage sync failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - startup and shutdown."""
    global _granola_processor, _calendar_indexer, _people_v2_sync_thread

    # Startup: Initialize and start Granola processor
    try:
        from api.services.granola_processor import GranolaProcessor
        _granola_processor = GranolaProcessor(settings.vault_path)
        _granola_processor.start_watching()
        logger.info("Granola processor started successfully")
    except Exception as e:
        logger.error(f"Failed to start Granola processor: {e}")

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


@app.get("/")
async def root():
    """Serve the chat UI."""
    index_path = Path(__file__).parent.parent / "web" / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "LifeOS API", "version": "0.3.0"}

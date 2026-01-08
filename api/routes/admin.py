"""
Admin API endpoints for LifeOS.

Provides:
- Reindexing endpoint
- System status
- Configuration info
"""
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
import logging

from api.services.indexer import IndexerService
from api.services.vectorstore import VectorStore
from config.settings import settings

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger(__name__)


class IndexStatus(BaseModel):
    """Status of the index."""
    status: str
    document_count: int
    vault_path: str
    message: Optional[str] = None


class ReindexResponse(BaseModel):
    """Response from reindex operation."""
    status: str
    message: str
    files_indexed: Optional[int] = None


# Track reindex state
_reindex_in_progress = False
_last_reindex_count = 0


@router.get("/status", response_model=IndexStatus)
async def get_status() -> IndexStatus:
    """
    Get current system status.

    Returns document count and configuration info.
    """
    try:
        vs = VectorStore()
        # Get approximate count from ChromaDB
        count = len(vs.search("", top_k=10000))  # Workaround for count
    except Exception as e:
        logger.error(f"Error getting document count: {e}")
        count = 0

    global _reindex_in_progress

    return IndexStatus(
        status="reindexing" if _reindex_in_progress else "ready",
        document_count=count,
        vault_path=str(settings.vault_path),
        message=f"Last reindex: {_last_reindex_count} files" if _last_reindex_count > 0 else None,
    )


def _do_reindex():
    """Background task to reindex vault."""
    global _reindex_in_progress, _last_reindex_count

    _reindex_in_progress = True
    try:
        indexer = IndexerService(vault_path=settings.vault_path)
        count = indexer.index_all()
        _last_reindex_count = count
        logger.info(f"Reindex complete: {count} files")
    except Exception as e:
        logger.error(f"Reindex failed: {e}")
    finally:
        _reindex_in_progress = False


@router.post("/reindex", response_model=ReindexResponse)
async def reindex(background_tasks: BackgroundTasks) -> ReindexResponse:
    """
    Trigger a full reindex of the vault.

    Runs in the background. Use /api/admin/status to check progress.
    """
    global _reindex_in_progress

    if _reindex_in_progress:
        return ReindexResponse(
            status="already_running",
            message="Reindex is already in progress. Check /api/admin/status for updates.",
        )

    background_tasks.add_task(_do_reindex)

    return ReindexResponse(
        status="started",
        message="Reindex started in background. Check /api/admin/status for progress.",
    )


@router.post("/reindex/sync", response_model=ReindexResponse)
async def reindex_sync() -> ReindexResponse:
    """
    Trigger a synchronous reindex of the vault.

    Blocks until complete. Use for initial setup.
    """
    global _reindex_in_progress, _last_reindex_count

    if _reindex_in_progress:
        return ReindexResponse(
            status="already_running",
            message="Reindex is already in progress.",
        )

    _reindex_in_progress = True
    try:
        indexer = IndexerService(vault_path=settings.vault_path)
        count = indexer.index_all()
        _last_reindex_count = count

        return ReindexResponse(
            status="success",
            message=f"Reindex complete.",
            files_indexed=count,
        )
    except Exception as e:
        logger.error(f"Reindex failed: {e}")
        return ReindexResponse(
            status="error",
            message=f"Reindex failed: {str(e)}",
        )
    finally:
        _reindex_in_progress = False


# ============ Granola Processor Endpoints ============


class GranolaStatus(BaseModel):
    """Status of the Granola processor."""
    status: str
    watching: bool
    granola_path: str
    pending_files: int
    interval_seconds: int
    message: Optional[str] = None


class GranolaProcessResponse(BaseModel):
    """Response from Granola processing operation."""
    status: str
    message: str
    processed: int
    failed: int
    skipped: int
    moves: list[dict] = []


@router.get("/granola/status", response_model=GranolaStatus)
async def get_granola_status() -> GranolaStatus:
    """
    Get status of the Granola inbox processor.

    Returns whether it's running and how many files are pending.
    """
    from pathlib import Path

    granola_path = Path(settings.vault_path) / "Granola"
    pending_count = len(list(granola_path.glob("*.md"))) if granola_path.exists() else 0

    # Try to get the processor instance from main
    try:
        from api.main import _granola_processor
        running = _granola_processor.is_running if _granola_processor else False
        interval = _granola_processor.interval_seconds if _granola_processor else 300
    except Exception:
        running = False
        interval = 300

    return GranolaStatus(
        status="running" if running else "stopped",
        watching=running,
        granola_path=str(granola_path),
        pending_files=pending_count,
        interval_seconds=interval,
        message=f"{pending_count} files pending in Granola inbox" if pending_count > 0 else "Inbox is empty"
    )


@router.post("/granola/process", response_model=GranolaProcessResponse)
async def process_granola_backlog() -> GranolaProcessResponse:
    """
    Process all pending files in the Granola inbox immediately.

    Classifies and moves files to appropriate destinations based on content.
    """
    try:
        from api.services.granola_processor import GranolaProcessor

        processor = GranolaProcessor(settings.vault_path)
        results = processor.process_backlog()

        return GranolaProcessResponse(
            status="success",
            message=f"Processed {results['processed']} files",
            processed=results["processed"],
            failed=results["failed"],
            skipped=results["skipped"],
            moves=results["moves"]
        )
    except Exception as e:
        logger.error(f"Granola processing failed: {e}")
        return GranolaProcessResponse(
            status="error",
            message=f"Processing failed: {str(e)}",
            processed=0,
            failed=0,
            skipped=0
        )


@router.post("/granola/start")
async def start_granola_processor():
    """Start the Granola processor (runs every 5 minutes)."""
    try:
        from api.main import _granola_processor
        if _granola_processor:
            _granola_processor.start()
            return {"status": "started", "message": "Granola processor started (runs every 5 minutes)"}
        else:
            # Create new processor if not initialized
            from api.services.granola_processor import GranolaProcessor
            import api.main as main_module
            main_module._granola_processor = GranolaProcessor(settings.vault_path)
            main_module._granola_processor.start()
            return {"status": "started", "message": "Granola processor created and started"}
    except Exception as e:
        logger.error(f"Failed to start Granola processor: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/granola/stop")
async def stop_granola_processor():
    """Stop the Granola processor."""
    try:
        from api.main import _granola_processor
        if _granola_processor:
            _granola_processor.stop()
            return {"status": "stopped", "message": "Granola processor stopped"}
        return {"status": "not_running", "message": "Granola processor was not running"}
    except Exception as e:
        logger.error(f"Failed to stop Granola processor: {e}")
        return {"status": "error", "message": str(e)}


class ReclassifyRequest(BaseModel):
    """Request to reclassify files in a folder."""
    folder: str = "Work/ML/People/Hiring"


@router.post("/granola/reclassify", response_model=GranolaProcessResponse)
async def reclassify_granola_files(request: ReclassifyRequest) -> GranolaProcessResponse:
    """
    Reclassify Granola files that may have been incorrectly categorized.

    Scans the specified folder and moves any Granola files to their correct
    destination based on the updated classification rules.

    Default folder: Work/ML/People/Hiring (where files were incorrectly placed)
    """
    try:
        from api.services.granola_processor import GranolaProcessor
        from pathlib import Path

        processor = GranolaProcessor(settings.vault_path)
        folder_path = Path(settings.vault_path) / request.folder

        results = processor.reclassify_folder(str(folder_path))

        return GranolaProcessResponse(
            status="success",
            message=f"Reclassified {results['reclassified']} files from {request.folder}",
            processed=results["reclassified"],
            failed=results["failed"],
            skipped=results["skipped"],
            moves=results["moves"]
        )
    except Exception as e:
        logger.error(f"Reclassification failed: {e}")
        return GranolaProcessResponse(
            status="error",
            message=f"Reclassification failed: {str(e)}",
            processed=0,
            failed=0,
            skipped=0
        )


# ============ Calendar Indexer Endpoints ============


class CalendarSyncStatus(BaseModel):
    """Status of the calendar indexer."""
    status: str
    scheduler_running: bool
    last_sync: Optional[str] = None
    message: Optional[str] = None


class CalendarSyncResponse(BaseModel):
    """Response from calendar sync operation."""
    status: str
    events_indexed: int
    errors: list[str] = []
    elapsed_seconds: float
    last_sync: str


@router.get("/calendar/status", response_model=CalendarSyncStatus)
async def get_calendar_sync_status() -> CalendarSyncStatus:
    """
    Get status of the calendar indexer scheduler.

    Returns whether the scheduler is running and when the last sync occurred.
    """
    try:
        from api.services.calendar_indexer import get_calendar_indexer
        indexer = get_calendar_indexer()
        status = indexer.get_status()

        return CalendarSyncStatus(
            status="ok",
            scheduler_running=status["running"],
            last_sync=status["last_sync"],
            message="Calendar sync scheduler is running" if status["running"] else "Scheduler not running"
        )
    except Exception as e:
        logger.error(f"Failed to get calendar status: {e}")
        return CalendarSyncStatus(
            status="error",
            scheduler_running=False,
            message=str(e)
        )


@router.post("/calendar/sync", response_model=CalendarSyncResponse)
async def trigger_calendar_sync(days_past: int = 30, days_future: int = 30) -> CalendarSyncResponse:
    """
    Trigger an immediate calendar sync.

    Fetches events from the specified date range and indexes them into ChromaDB.

    Args:
        days_past: Number of days in the past to fetch (default: 30)
        days_future: Number of days in the future to fetch (default: 30)
    """
    try:
        from api.services.calendar_indexer import get_calendar_indexer
        indexer = get_calendar_indexer()
        result = indexer.sync(days_past=days_past, days_future=days_future)

        return CalendarSyncResponse(
            status=result["status"],
            events_indexed=result["events_indexed"],
            errors=result.get("errors", []),
            elapsed_seconds=result["elapsed_seconds"],
            last_sync=result["last_sync"]
        )
    except Exception as e:
        logger.error(f"Calendar sync failed: {e}")
        return CalendarSyncResponse(
            status="error",
            events_indexed=0,
            errors=[str(e)],
            elapsed_seconds=0,
            last_sync=""
        )


@router.post("/calendar/start")
async def start_calendar_scheduler(interval_hours: float = 24.0):
    """
    Start the calendar sync scheduler.

    Args:
        interval_hours: Hours between syncs (default: 24)
    """
    try:
        from api.services.calendar_indexer import get_calendar_indexer
        indexer = get_calendar_indexer()
        indexer.start_scheduler(interval_hours=interval_hours)
        return {"status": "started", "message": f"Calendar scheduler started ({interval_hours}h interval)"}
    except Exception as e:
        logger.error(f"Failed to start calendar scheduler: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/calendar/stop")
async def stop_calendar_scheduler():
    """Stop the calendar sync scheduler."""
    try:
        from api.services.calendar_indexer import get_calendar_indexer
        indexer = get_calendar_indexer()
        indexer.stop_scheduler()
        return {"status": "stopped", "message": "Calendar scheduler stopped"}
    except Exception as e:
        logger.error(f"Failed to stop calendar scheduler: {e}")
        return {"status": "error", "message": str(e)}
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
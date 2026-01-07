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

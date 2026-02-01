"""
Digest API endpoints.
"""
from datetime import date

from fastapi import APIRouter, Query

from api.services.weekly_digest import build_weekly_digest

router = APIRouter(prefix="/digest", tags=["digest"])


@router.get("/weekly")
async def get_weekly_digest(
    start: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    end: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
):
    """Return weekly digest data for the requested date range."""
    return build_weekly_digest(start=start, end=end)

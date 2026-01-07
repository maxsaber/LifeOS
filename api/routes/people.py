"""
People API endpoints for LifeOS.

Provides access to aggregated people from all sources.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.services.people_aggregator import get_people_aggregator, PersonRecord
from api.services.gmail import get_gmail_service
from api.services.calendar import get_calendar_service
from api.services.google_auth import GoogleAccount

router = APIRouter(prefix="/api/people", tags=["people"])


class PersonResponse(BaseModel):
    """Response model for a person."""
    canonical_name: str
    email: Optional[str] = None
    company: Optional[str] = None
    position: Optional[str] = None
    sources: list[str]
    meeting_count: int = 0
    email_count: int = 0
    mention_count: int = 0
    last_seen: Optional[str] = None
    category: str = "unknown"


class SearchResponse(BaseModel):
    """Response for search endpoint."""
    people: list[PersonResponse]
    count: int
    query: str


class SyncResponse(BaseModel):
    """Response for sync endpoint."""
    status: str
    sources: dict[str, int]
    total_people: int


class StatisticsResponse(BaseModel):
    """Response for statistics endpoint."""
    total_people: int
    by_source: dict[str, int]


def _record_to_response(record: PersonRecord) -> PersonResponse:
    """Convert PersonRecord to API response."""
    return PersonResponse(
        canonical_name=record.canonical_name,
        email=record.email,
        company=record.company,
        position=record.position,
        sources=record.sources,
        meeting_count=record.meeting_count,
        email_count=record.email_count,
        mention_count=record.mention_count,
        last_seen=record.last_seen.isoformat() if record.last_seen else None,
        category=record.category,
    )


@router.get("/search", response_model=SearchResponse)
async def search_people(
    q: str = Query(..., description="Search query for name or email"),
):
    """Search for people by name or email."""
    aggregator = get_people_aggregator()
    results = aggregator.search(q)

    return SearchResponse(
        people=[_record_to_response(r) for r in results],
        count=len(results),
        query=q,
    )


@router.get("/person/{name}", response_model=PersonResponse)
async def get_person(name: str):
    """Get a specific person by name."""
    aggregator = get_people_aggregator()
    person = aggregator.get_person(name)

    if not person:
        raise HTTPException(status_code=404, detail=f"Person '{name}' not found")

    return _record_to_response(person)


@router.get("/statistics", response_model=StatisticsResponse)
async def get_statistics():
    """Get statistics about aggregated people."""
    aggregator = get_people_aggregator()
    stats = aggregator.get_statistics()

    return StatisticsResponse(
        total_people=stats['total_people'],
        by_source=stats['by_source'],
    )


@router.post("/sync", response_model=SyncResponse)
async def sync_all_sources():
    """
    Sync people from all sources.

    This triggers a full sync from:
    - LinkedIn connections CSV
    - Gmail contacts (last 2 years)
    - Calendar attendees (last year)
    """
    try:
        # Get services for sync
        gmail_service = None
        calendar_service = None

        try:
            gmail_service = get_gmail_service(GoogleAccount.PERSONAL)
        except Exception as e:
            pass  # Gmail not available

        try:
            calendar_service = get_calendar_service(GoogleAccount.PERSONAL)
        except Exception as e:
            pass  # Calendar not available

        aggregator = get_people_aggregator(
            linkedin_csv_path="./data/LinkedInConnections.csv",
            gmail_service=gmail_service,
            calendar_service=calendar_service,
        )

        results = aggregator.sync_all_sources()
        stats = aggregator.get_statistics()

        return SyncResponse(
            status="success",
            sources=results,
            total_people=stats['total_people'],
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {e}")


@router.get("/list", response_model=SearchResponse)
async def list_people(
    limit: int = Query(default=50, ge=1, le=500, description="Max results"),
    source: Optional[str] = Query(default=None, description="Filter by source"),
):
    """List all people, optionally filtered by source."""
    aggregator = get_people_aggregator()
    all_people = aggregator.get_all_people()

    # Filter by source if specified
    if source:
        all_people = [p for p in all_people if source in p.sources]

    # Sort by last_seen (most recent first), then by name
    all_people.sort(
        key=lambda p: (p.last_seen or datetime.min.replace(tzinfo=timezone.utc), p.canonical_name),
        reverse=True
    )

    # Limit results
    all_people = all_people[:limit]

    return SearchResponse(
        people=[_record_to_response(p) for p in all_people],
        count=len(all_people),
        query="*",
    )


# Import at bottom to avoid circular import
from datetime import datetime, timezone

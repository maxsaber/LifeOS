"""
People API endpoints for LifeOS.

Provides access to aggregated people from all sources.
Supports both v1 (PeopleAggregator) and v2 (EntityResolver) systems.
"""
from typing import Optional
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.services.people_aggregator import get_people_aggregator, PersonRecord
from api.services.gmail import get_gmail_service
from api.services.calendar import get_calendar_service
from api.services.google_auth import GoogleAccount

# v2 imports
try:
    from api.services.entity_resolver import get_entity_resolver
    from api.services.person_entity import get_person_entity_store
    from api.services.interaction_store import get_interaction_store
    HAS_V2_PEOPLE = True
except ImportError:
    HAS_V2_PEOPLE = False

logger = logging.getLogger(__name__)

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
    # v2 fields
    entity_id: Optional[str] = None
    linkedin_url: Optional[str] = None
    display_name: Optional[str] = None
    aliases: Optional[list[str]] = None


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


# ============================================================================
# v2 Entity Endpoints (requires People System v2)
# ============================================================================

class EntityResolveRequest(BaseModel):
    """Request for entity resolution."""
    name: Optional[str] = None
    email: Optional[str] = None
    context_path: Optional[str] = None
    create_if_missing: bool = False


class EntityResolveResponse(BaseModel):
    """Response from entity resolution."""
    found: bool
    is_new: bool = False
    confidence: float = 0.0
    match_type: str = ""
    entity: Optional[PersonResponse] = None


class InteractionResponse(BaseModel):
    """Response model for an interaction."""
    id: str
    person_id: str
    timestamp: str
    source_type: str
    title: str
    snippet: Optional[str] = None
    source_link: str = ""
    source_badge: str = ""


class InteractionsResponse(BaseModel):
    """Response for interactions list."""
    interactions: list[InteractionResponse]
    count: int
    formatted_history: str = ""


def _entity_to_response(entity) -> PersonResponse:
    """Convert PersonEntity to API response."""
    return PersonResponse(
        canonical_name=entity.canonical_name,
        email=entity.emails[0] if entity.emails else None,
        company=entity.company,
        position=entity.position,
        sources=entity.sources,
        meeting_count=entity.meeting_count,
        email_count=entity.email_count,
        mention_count=entity.mention_count,
        last_seen=entity.last_seen.isoformat() if entity.last_seen else None,
        category=entity.category,
        entity_id=entity.id,
        linkedin_url=entity.linkedin_url,
        display_name=entity.display_name,
        aliases=entity.aliases,
    )


@router.post("/v2/resolve", response_model=EntityResolveResponse)
async def resolve_entity(request: EntityResolveRequest) -> EntityResolveResponse:
    """
    **PRIMARY TOOL for finding someone's email, full name, and contact info from a nickname or partial name.**

    Use this FIRST when you need to:
    - Find someone's email address (e.g., "tay" → annetaylorwalker@gmail.com)
    - Get someone's full/canonical name (e.g., "tay" → "Taylor Walker, MD, MPH")
    - Look up contact details before searching Gmail, Calendar, or other sources

    Example: To find emails to/from "Tay", first call this with {"name": "tay"} to get their email,
    then use that email in gmail_search with "to:email" or "from:email".

    Returns the resolved entity with email, canonical_name, company, position, aliases, and LinkedIn URL.
    """
    if not HAS_V2_PEOPLE:
        raise HTTPException(status_code=501, detail="People System v2 not available")

    if not request.name and not request.email:
        raise HTTPException(status_code=400, detail="Must provide name or email")

    resolver = get_entity_resolver()
    result = resolver.resolve(
        name=request.name,
        email=request.email,
        context_path=request.context_path,
        create_if_missing=request.create_if_missing,
    )

    if not result:
        return EntityResolveResponse(found=False)

    return EntityResolveResponse(
        found=True,
        is_new=result.is_new,
        confidence=result.confidence,
        match_type=result.match_type,
        entity=_entity_to_response(result.entity),
    )


@router.get("/v2/entities", response_model=SearchResponse)
async def list_entities(
    limit: int = Query(default=50, ge=1, le=500, description="Max results"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
):
    """
    List all entities from the v2 entity store.

    This uses the new PersonEntity system instead of PeopleAggregator.
    """
    if not HAS_V2_PEOPLE:
        raise HTTPException(status_code=501, detail="People System v2 not available")

    store = get_person_entity_store()
    all_entities = store.get_all()

    # Filter by category if specified
    if category:
        all_entities = [e for e in all_entities if e.category == category]

    # Sort by last_seen (most recent first)
    all_entities.sort(
        key=lambda e: e.last_seen or datetime.min,
        reverse=True
    )

    # Limit results
    all_entities = all_entities[:limit]

    return SearchResponse(
        people=[_entity_to_response(e) for e in all_entities],
        count=len(all_entities),
        query="*",
    )


@router.get("/v2/entity/{entity_id}", response_model=PersonResponse)
async def get_entity(entity_id: str):
    """Get a specific entity by ID."""
    if not HAS_V2_PEOPLE:
        raise HTTPException(status_code=501, detail="People System v2 not available")

    store = get_person_entity_store()
    entity = store.get_by_id(entity_id)

    if not entity:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")

    return _entity_to_response(entity)


@router.get("/v2/entity/{entity_id}/interactions", response_model=InteractionsResponse)
async def get_entity_interactions(
    entity_id: str,
    days_back: int = Query(default=90, ge=1, le=365, description="Days to look back"),
    limit: int = Query(default=50, ge=1, le=200, description="Max interactions"),
):
    """
    Get interaction history for a specific entity.

    Returns a list of interactions (emails, meetings, note mentions) with
    links to the original sources.
    """
    if not HAS_V2_PEOPLE:
        raise HTTPException(status_code=501, detail="People System v2 not available")

    # Verify entity exists
    store = get_person_entity_store()
    entity = store.get_by_id(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")

    # Get interactions
    interaction_store = get_interaction_store()
    interactions = interaction_store.get_for_person(entity_id, days_back=days_back, limit=limit)
    formatted = interaction_store.format_interaction_history(entity_id, days_back=days_back, limit=limit)

    return InteractionsResponse(
        interactions=[
            InteractionResponse(
                id=i.id,
                person_id=i.person_id,
                timestamp=i.timestamp.isoformat(),
                source_type=i.source_type,
                title=i.title,
                snippet=i.snippet,
                source_link=i.source_link,
                source_badge=i.source_badge,
            )
            for i in interactions
        ],
        count=len(interactions),
        formatted_history=formatted,
    )


@router.get("/v2/statistics")
async def get_v2_statistics():
    """Get statistics from the v2 people system."""
    if not HAS_V2_PEOPLE:
        raise HTTPException(status_code=501, detail="People System v2 not available")

    entity_store = get_person_entity_store()
    interaction_store = get_interaction_store()

    entity_stats = entity_store.get_statistics()
    interaction_stats = interaction_store.get_statistics()

    return {
        "entities": entity_stats,
        "interactions": interaction_stats,
        "v2_enabled": True,
    }

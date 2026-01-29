"""
CRM API endpoints for LifeOS Personal CRM.

Provides comprehensive endpoints for managing people, relationships,
and entity linking workflows.
"""
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional, Union
import logging

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field

from api.services.person_entity import PersonEntity, get_person_entity_store
from api.services.interaction_store import get_interaction_store
from config.people_config import InteractionConfig
from api.services.source_entity import (
    SourceEntity,
    get_source_entity_store,
    LINK_STATUS_CONFIRMED,
    LINK_STATUS_REJECTED,
)
from api.services.pending_link import (
    PendingLink,
    get_pending_link_store,
    STATUS_PENDING,
)
from api.services.relationship import get_relationship_store
from api.services.relationship_metrics import (
    compute_strength_for_person,
    get_strength_breakdown,
    update_all_strengths,
)
from api.services.relationship_discovery import (
    run_full_discovery,
    get_suggested_connections,
    get_connection_overlap,
)
from api.services.person_facts import (
    PersonFact,
    get_person_fact_store,
    get_person_fact_extractor,
    FACT_CATEGORIES,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/crm", tags=["crm"])


# Response Models


class SourceEntityResponse(BaseModel):
    """Response model for a source entity."""
    id: str
    source_type: str
    source_id: Optional[str] = None
    observed_name: Optional[str] = None
    observed_email: Optional[str] = None
    observed_phone: Optional[str] = None
    link_confidence: float = 0.0
    link_status: str = "auto"
    observed_at: Optional[str] = None
    source_badge: str = ""


class PendingLinkResponse(BaseModel):
    """Response model for a pending link."""
    id: str
    source_entity_id: str
    proposed_canonical_id: str
    previous_canonical_id: Optional[str] = None
    reason: str
    reason_display: str
    confidence: float = 0.0
    status: str = "pending"
    created_at: Optional[str] = None
    # Include source entity details for UI
    source_entity: Optional[SourceEntityResponse] = None
    # Include proposed person name for UI
    proposed_person_name: Optional[str] = None


class RelationshipResponse(BaseModel):
    """Response model for a relationship."""
    id: str
    person_a_id: str
    person_b_id: str
    relationship_type: str
    shared_contexts: list[str] = []
    shared_events_count: int = 0
    shared_threads_count: int = 0
    first_seen_together: Optional[str] = None
    last_seen_together: Optional[str] = None
    # Include person names for UI
    person_a_name: Optional[str] = None
    person_b_name: Optional[str] = None


class PersonDetailResponse(BaseModel):
    """Extended person response with CRM data."""
    id: str
    canonical_name: str
    display_name: str
    emails: list[str] = []
    phone_numbers: list[str] = []
    company: Optional[str] = None
    position: Optional[str] = None
    linkedin_url: Optional[str] = None
    category: str = "unknown"
    vault_contexts: list[str] = []
    tags: list[str] = []
    notes: str = ""
    sources: list[str] = []
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    relationship_strength: float = 0.0
    source_entity_count: int = 0
    meeting_count: int = 0
    email_count: int = 0
    mention_count: int = 0
    # Related data
    source_entities: list[SourceEntityResponse] = []
    pending_links: list[PendingLinkResponse] = []
    relationships: list[RelationshipResponse] = []


class PersonListResponse(BaseModel):
    """Response for person list endpoint."""
    people: list[PersonDetailResponse]
    count: int
    total: int
    offset: int = 0
    has_more: bool = False


class TimelineItem(BaseModel):
    """Response model for a timeline item."""
    id: str
    timestamp: str
    source_type: str
    title: str
    snippet: Optional[str] = None
    source_link: str = ""
    source_badge: str = ""


class TimelineResponse(BaseModel):
    """Response for timeline endpoint."""
    items: list[TimelineItem]
    count: int
    has_more: bool = False


class AggregatedTimelineItem(BaseModel):
    """Response model for an aggregated timeline item (grouped by day + type)."""
    date: str  # ISO date (YYYY-MM-DD)
    source_type: str
    source_badge: str
    count: int
    preview: Optional[str] = None  # First item's title/subject
    items: list[TimelineItem] = []  # Individual items (populated when expanded)


class AggregatedDayGroup(BaseModel):
    """A day's worth of aggregated interactions."""
    date: str  # ISO date (YYYY-MM-DD)
    date_display: str  # Human-readable date (e.g., "Jan 28, 2026")
    total_count: int
    groups: list[AggregatedTimelineItem]


class AggregatedTimelineResponse(BaseModel):
    """Response for aggregated timeline endpoint."""
    days: list[AggregatedDayGroup]
    total_interactions: int
    date_range_start: Optional[str] = None
    date_range_end: Optional[str] = None


class ConnectionResponse(BaseModel):
    """Response model for a connection."""
    person_id: str
    name: str
    company: Optional[str] = None
    relationship_type: str
    shared_events_count: int = 0
    shared_threads_count: int = 0
    shared_contexts: list[str] = []
    relationship_strength: float = 0.0
    last_seen_together: Optional[str] = None


class ConnectionsResponse(BaseModel):
    """Response for connections endpoint."""
    connections: list[ConnectionResponse]
    count: int


class SuggestedConnectionResponse(BaseModel):
    """Response for a suggested connection."""
    person_id: str
    name: str
    company: Optional[str] = None
    score: float = 0.0
    shared_contexts: list[str] = []
    shared_sources: list[str] = []


class DiscoverResponse(BaseModel):
    """Response for discover endpoint."""
    suggestions: list[SuggestedConnectionResponse]
    count: int


class StatisticsResponse(BaseModel):
    """Response for CRM statistics."""
    total_people: int = 0
    by_category: dict[str, int] = {}
    by_source: dict[str, int] = {}
    total_source_entities: int = 0
    linked_entities: int = 0
    unlinked_entities: int = 0
    pending_links_count: int = 0
    total_relationships: int = 0


class NetworkNode(BaseModel):
    """A node in the network graph."""
    id: str
    name: str
    category: str = "unknown"
    strength: float = 0.0
    interaction_count: int = 0


class NetworkEdge(BaseModel):
    """An edge in the network graph."""
    source: str
    target: str
    weight: int = 0
    type: str = "inferred"


class NetworkGraphResponse(BaseModel):
    """Response for network graph endpoint."""
    nodes: list[NetworkNode]
    edges: list[NetworkEdge]


class PendingLinksResponse(BaseModel):
    """Response for pending links list."""
    links: list[PendingLinkResponse]
    count: int


class PersonFactResponse(BaseModel):
    """Response model for a person fact."""
    id: str
    person_id: str
    category: str
    key: str
    value: str
    confidence: float = 0.5
    source_interaction_id: Optional[str] = None
    extracted_at: Optional[str] = None
    confirmed_by_user: bool = False
    created_at: Optional[str] = None
    category_icon: str = ""


class PersonFactsResponse(BaseModel):
    """Response for person facts list."""
    facts: list[PersonFactResponse]
    count: int
    by_category: dict[str, list[PersonFactResponse]] = {}


class FactUpdateRequest(BaseModel):
    """Request for updating a fact."""
    value: Optional[str] = None
    confidence: Optional[float] = None
    category: Optional[str] = None
    key: Optional[str] = None


class FactExtractionResponse(BaseModel):
    """Response for fact extraction."""
    status: str
    extracted_count: int
    facts: list[PersonFactResponse] = []


class PersonUpdateRequest(BaseModel):
    """Request for updating a person."""
    notes: Optional[str] = None
    tags: Optional[list[str]] = None
    category: Optional[str] = None


class LinkConfirmRequest(BaseModel):
    """Request for confirming or rejecting a link."""
    create_new_person: bool = Field(
        default=False,
        description="If rejecting, create a new person from the source entity"
    )
    new_person_name: Optional[str] = Field(
        default=None,
        description="Name for the new person (required if create_new_person=True)"
    )


# Helper functions


def _source_entity_to_response(entity: SourceEntity) -> SourceEntityResponse:
    """Convert SourceEntity to API response."""
    return SourceEntityResponse(
        id=entity.id,
        source_type=entity.source_type,
        source_id=entity.source_id,
        observed_name=entity.observed_name,
        observed_email=entity.observed_email,
        observed_phone=entity.observed_phone,
        link_confidence=entity.link_confidence,
        link_status=entity.link_status,
        observed_at=entity.observed_at.isoformat() if entity.observed_at else None,
        source_badge=entity.source_badge,
    )


def _pending_link_to_response(
    link: PendingLink,
    source_entity: Optional[SourceEntity] = None,
    proposed_person: Optional[PersonEntity] = None,
) -> PendingLinkResponse:
    """Convert PendingLink to API response."""
    return PendingLinkResponse(
        id=link.id,
        source_entity_id=link.source_entity_id,
        proposed_canonical_id=link.proposed_canonical_id,
        previous_canonical_id=link.previous_canonical_id,
        reason=link.reason,
        reason_display=link.reason_display,
        confidence=link.confidence,
        status=link.status,
        created_at=link.created_at.isoformat() if link.created_at else None,
        source_entity=_source_entity_to_response(source_entity) if source_entity else None,
        proposed_person_name=proposed_person.canonical_name if proposed_person else None,
    )


def _relationship_to_response(
    rel,
    person_store,
) -> RelationshipResponse:
    """Convert Relationship to API response."""
    person_a = person_store.get_by_id(rel.person_a_id)
    person_b = person_store.get_by_id(rel.person_b_id)

    return RelationshipResponse(
        id=rel.id,
        person_a_id=rel.person_a_id,
        person_b_id=rel.person_b_id,
        relationship_type=rel.relationship_type,
        shared_contexts=rel.shared_contexts,
        shared_events_count=rel.shared_events_count,
        shared_threads_count=rel.shared_threads_count,
        first_seen_together=rel.first_seen_together.isoformat() if rel.first_seen_together else None,
        last_seen_together=rel.last_seen_together.isoformat() if rel.last_seen_together else None,
        person_a_name=person_a.canonical_name if person_a else None,
        person_b_name=person_b.canonical_name if person_b else None,
    )


def _person_to_detail_response(
    person: PersonEntity,
    include_related: bool = True,
) -> PersonDetailResponse:
    """Convert PersonEntity to detailed API response."""
    response = PersonDetailResponse(
        id=person.id,
        canonical_name=person.canonical_name,
        display_name=person.display_name,
        emails=person.emails,
        phone_numbers=person.phone_numbers,
        company=person.company,
        position=person.position,
        linkedin_url=person.linkedin_url,
        category=person.category,
        vault_contexts=person.vault_contexts,
        tags=person.tags,
        notes=person.notes,
        sources=person.sources,
        first_seen=person.first_seen.isoformat() if person.first_seen else None,
        last_seen=person.last_seen.isoformat() if person.last_seen else None,
        relationship_strength=person.relationship_strength,
        source_entity_count=person.source_entity_count,
        meeting_count=person.meeting_count,
        email_count=person.email_count,
        mention_count=person.mention_count,
    )

    if include_related:
        # Add source entities
        source_store = get_source_entity_store()
        source_entities = source_store.get_for_person(person.id)
        response.source_entities = [_source_entity_to_response(e) for e in source_entities]

        # Add pending links
        pending_store = get_pending_link_store()
        pending = pending_store.get_pending_for_person(person.id)
        response.pending_links = [
            _pending_link_to_response(link, source_store.get_by_id(link.source_entity_id), person)
            for link in pending
        ]

        # Add relationships
        rel_store = get_relationship_store()
        person_store = get_person_entity_store()
        relationships = rel_store.get_for_person(person.id, limit=20)
        response.relationships = [_relationship_to_response(r, person_store) for r in relationships]

    return response


# Endpoints


@router.get("/people", response_model=PersonListResponse)
async def list_people(
    q: Optional[str] = Query(default=None, description="Search query"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
    source: Optional[str] = Query(default=None, description="Filter by source"),
    has_pending: Optional[bool] = Query(default=None, description="Filter by pending links"),
    has_interactions: Optional[bool] = Query(default=None, description="Filter by interaction count > 0"),
    sort: str = Query(default="interactions", description="Sort field: interactions, last_seen, name, strength"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    limit: int = Query(default=50, ge=1, le=200, description="Max results"),
):
    """
    List people with filtering and sorting.

    Supports searching by name/email, filtering by category/source,
    and sorting by interactions, last_seen, name, or relationship strength.
    """
    person_store = get_person_entity_store()
    pending_store = get_pending_link_store()

    # Get all people
    people = person_store.get_all()

    # Apply search filter
    if q:
        q_lower = q.lower()
        people = [
            p for p in people
            if q_lower in p.canonical_name.lower()
            or any(q_lower in email.lower() for email in p.emails)
            or any(q_lower in alias.lower() for alias in p.aliases)
            or (p.company and q_lower in p.company.lower())
        ]

    # Apply category filter
    if category:
        people = [p for p in people if p.category == category]

    # Apply source filter
    if source:
        people = [p for p in people if source in p.sources]

    # Apply pending links filter
    if has_pending is not None:
        pending_person_ids = set()
        for link in pending_store.get_pending():
            pending_person_ids.add(link.proposed_canonical_id)

        if has_pending:
            people = [p for p in people if p.id in pending_person_ids]
        else:
            people = [p for p in people if p.id not in pending_person_ids]

    # Apply interactions filter
    if has_interactions is not None:
        if has_interactions:
            people = [
                p for p in people
                if (p.email_count or 0) + (p.meeting_count or 0) + (p.mention_count or 0) + getattr(p, 'message_count', 0) > 0
            ]
        else:
            people = [
                p for p in people
                if (p.email_count or 0) + (p.meeting_count or 0) + (p.mention_count or 0) + getattr(p, 'message_count', 0) == 0
            ]

    total = len(people)

    # Apply sorting
    if sort == "name":
        people.sort(key=lambda p: p.canonical_name.lower())
    elif sort == "strength":
        people.sort(key=lambda p: p.relationship_strength, reverse=True)
    elif sort == "interactions":
        # Sort by total interaction count (emails + meetings + mentions + messages)
        people.sort(
            key=lambda p: (p.email_count or 0) + (p.meeting_count or 0) + (p.mention_count or 0) + getattr(p, 'message_count', 0),
            reverse=True
        )
    else:  # last_seen
        people.sort(
            key=lambda p: p.last_seen or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True
        )

    # Apply pagination
    has_more = offset + limit < total
    people = people[offset:offset + limit]

    return PersonListResponse(
        people=[_person_to_detail_response(p, include_related=False) for p in people],
        count=len(people),
        total=total,
        offset=offset,
        has_more=has_more,
    )


@router.get("/people/{person_id}", response_model=PersonDetailResponse)
async def get_person(person_id: str):
    """
    Get detailed information about a person.

    Includes source entities, pending links, and relationships.
    """
    person_store = get_person_entity_store()
    person = person_store.get_by_id(person_id)

    if not person:
        raise HTTPException(status_code=404, detail=f"Person '{person_id}' not found")

    # Compute fresh relationship strength
    try:
        strength = compute_strength_for_person(person)
        person.relationship_strength = strength
    except Exception as e:
        logger.warning(f"Failed to compute relationship strength: {e}")

    return _person_to_detail_response(person, include_related=True)


@router.patch("/people/{person_id}", response_model=PersonDetailResponse)
async def update_person(person_id: str, request: PersonUpdateRequest):
    """
    Update a person's notes, tags, or category.
    """
    person_store = get_person_entity_store()
    person = person_store.get_by_id(person_id)

    if not person:
        raise HTTPException(status_code=404, detail=f"Person '{person_id}' not found")

    if request.notes is not None:
        person.notes = request.notes

    if request.tags is not None:
        person.tags = [t.strip().lower() for t in request.tags if t.strip()]

    if request.category is not None:
        person.category = request.category

    person_store.update(person)
    person_store.save()

    return _person_to_detail_response(person, include_related=True)


@router.get("/people/{person_id}/timeline", response_model=TimelineResponse)
async def get_person_timeline(
    person_id: str,
    source_type: Optional[str] = Query(default=None, description="Filter by source type"),
    days_back: int = Query(
        default=InteractionConfig.DEFAULT_WINDOW_DAYS,
        ge=1,
        le=InteractionConfig.MAX_WINDOW_DAYS,
        description="Days to look back (default 365, max 3650)"
    ),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    limit: int = Query(default=50, ge=1, le=200, description="Max results"),
):
    """
    Get chronological interaction history for a person.

    Returns emails, meetings, notes, and other interactions in timeline format.
    """
    person_store = get_person_entity_store()
    person = person_store.get_by_id(person_id)

    if not person:
        raise HTTPException(status_code=404, detail=f"Person '{person_id}' not found")

    interaction_store = get_interaction_store()
    interactions = interaction_store.get_for_person(
        person_id,
        days_back=days_back,
        limit=limit + offset + 1,  # Fetch one extra to check has_more
        source_type=source_type,
    )

    has_more = len(interactions) > offset + limit
    interactions = interactions[offset:offset + limit]

    return TimelineResponse(
        items=[
            TimelineItem(
                id=i.id,
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
        has_more=has_more,
    )


# Source type badges for aggregated timeline
SOURCE_BADGES = {
    "gmail": "📧",
    "calendar": "📅",
    "vault": "📝",
    "granola": "📝",
    "imessage": "💬",
    "whatsapp": "💬",
    "contacts": "📇",
    "phone": "📞",
}


@router.get("/people/{person_id}/timeline/aggregated", response_model=AggregatedTimelineResponse)
async def get_person_timeline_aggregated(
    person_id: str,
    source_type: Optional[str] = Query(default=None, description="Filter by source type"),
    days_back: int = Query(
        default=InteractionConfig.DEFAULT_WINDOW_DAYS,
        ge=1,
        le=InteractionConfig.MAX_WINDOW_DAYS,
        description="Days to look back (default 365, max 3650)"
    ),
    include_items: bool = Query(default=False, description="Include individual items in each group"),
    max_items_per_group: int = Query(default=10, ge=1, le=50, description="Max items per group when include_items=True"),
):
    """
    Get aggregated interaction history for a person, grouped by day and source type.

    Returns interactions aggregated by day, with counts and previews.
    Use include_items=True to get individual interactions within each group.

    Example response structure:
    ```
    {
      "days": [
        {
          "date": "2026-01-28",
          "date_display": "Jan 28, 2026",
          "total_count": 15,
          "groups": [
            {
              "source_type": "gmail",
              "source_badge": "📧",
              "count": 3,
              "preview": "Re: Project Update",
              "items": [...]  // Only if include_items=True
            },
            {
              "source_type": "imessage",
              "source_badge": "💬",
              "count": 12,
              "preview": "Sounds good!",
              "items": []
            }
          ]
        }
      ],
      "total_interactions": 150,
      "date_range_start": "2025-10-30",
      "date_range_end": "2026-01-28"
    }
    ```
    """
    person_store = get_person_entity_store()
    person = person_store.get_by_id(person_id)

    if not person:
        raise HTTPException(status_code=404, detail=f"Person '{person_id}' not found")

    interaction_store = get_interaction_store()

    # Fetch all interactions within the time range (no pagination for aggregation)
    # Limit to a reasonable amount to avoid performance issues
    interactions = interaction_store.get_for_person(
        person_id,
        days_back=days_back,
        limit=10000,  # High limit for aggregation
        source_type=source_type,
    )

    if not interactions:
        return AggregatedTimelineResponse(
            days=[],
            total_interactions=0,
            date_range_start=None,
            date_range_end=None,
        )

    # Group interactions by date and source_type
    # Structure: { date_str: { source_type: [interactions] } }
    day_groups: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

    for interaction in interactions:
        date_str = interaction.timestamp.strftime("%Y-%m-%d")
        day_groups[date_str][interaction.source_type].append(interaction)

    # Build response
    days = []
    for date_str in sorted(day_groups.keys(), reverse=True):
        source_groups = day_groups[date_str]

        groups = []
        day_total = 0

        # Sort by interaction count descending
        for source_type in sorted(source_groups.keys(), key=lambda st: -len(source_groups[st])):
            items_list = source_groups[source_type]
            count = len(items_list)
            day_total += count

            # Get preview from first item
            preview = items_list[0].title if items_list else None
            if preview and len(preview) > 50:
                preview = preview[:47] + "..."

            # Build items list if requested
            items = []
            if include_items:
                for item in items_list[:max_items_per_group]:
                    items.append(TimelineItem(
                        id=item.id,
                        timestamp=item.timestamp.isoformat(),
                        source_type=item.source_type,
                        title=item.title,
                        snippet=item.snippet,
                        source_link=item.source_link,
                        source_badge=item.source_badge,
                    ))

            groups.append(AggregatedTimelineItem(
                date=date_str,
                source_type=source_type,
                source_badge=SOURCE_BADGES.get(source_type, "📄"),
                count=count,
                preview=preview,
                items=items,
            ))

        # Parse date for display format
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        date_display = date_obj.strftime("%b %d, %Y")

        days.append(AggregatedDayGroup(
            date=date_str,
            date_display=date_display,
            total_count=day_total,
            groups=groups,
        ))

    # Get date range
    date_range_start = days[-1].date if days else None
    date_range_end = days[0].date if days else None

    return AggregatedTimelineResponse(
        days=days,
        total_interactions=len(interactions),
        date_range_start=date_range_start,
        date_range_end=date_range_end,
    )


@router.get("/people/{person_id}/connections", response_model=ConnectionsResponse)
async def get_person_connections(
    person_id: str,
    relationship_type: Optional[str] = Query(default=None, description="Filter by type"),
    limit: int = Query(default=50, ge=1, le=200, description="Max results"),
):
    """
    Get related people with relationship scores.
    """
    person_store = get_person_entity_store()
    person = person_store.get_by_id(person_id)

    if not person:
        raise HTTPException(status_code=404, detail=f"Person '{person_id}' not found")

    rel_store = get_relationship_store()
    relationships = rel_store.get_for_person(person_id, relationship_type=relationship_type, limit=limit)

    connections = []
    for rel in relationships:
        other_id = rel.other_person(person_id)
        if not other_id:
            continue

        other = person_store.get_by_id(other_id)
        if not other:
            continue

        connections.append(ConnectionResponse(
            person_id=other.id,
            name=other.canonical_name,
            company=other.company,
            relationship_type=rel.relationship_type,
            shared_events_count=rel.shared_events_count,
            shared_threads_count=rel.shared_threads_count,
            shared_contexts=rel.shared_contexts,
            relationship_strength=other.relationship_strength,
            last_seen_together=rel.last_seen_together.isoformat() if rel.last_seen_together else None,
        ))

    # Sort by total shared interactions
    connections.sort(
        key=lambda c: c.shared_events_count + c.shared_threads_count,
        reverse=True
    )

    return ConnectionsResponse(
        connections=connections,
        count=len(connections),
    )


@router.get("/people/{person_id}/strength", response_model=dict)
async def get_person_strength_breakdown(person_id: str):
    """
    Get detailed breakdown of relationship strength components.

    Useful for understanding why a person has a certain strength score.
    """
    person_store = get_person_entity_store()
    person = person_store.get_by_id(person_id)

    if not person:
        raise HTTPException(status_code=404, detail=f"Person '{person_id}' not found")

    return get_strength_breakdown(person)


# Person Facts Endpoints
# ======================


def _fact_to_response(fact: PersonFact) -> PersonFactResponse:
    """Convert PersonFact to API response."""
    return PersonFactResponse(
        id=fact.id,
        person_id=fact.person_id,
        category=fact.category,
        key=fact.key,
        value=fact.value,
        confidence=fact.confidence,
        source_interaction_id=fact.source_interaction_id,
        extracted_at=fact.extracted_at.isoformat() if fact.extracted_at else None,
        confirmed_by_user=fact.confirmed_by_user,
        created_at=fact.created_at.isoformat() if fact.created_at else None,
        category_icon=FACT_CATEGORIES.get(fact.category, ""),
    )


@router.get("/people/{person_id}/facts", response_model=PersonFactsResponse)
async def get_person_facts(person_id: str):
    """
    Get all facts about a person.

    Returns facts grouped by category for easy display.
    """
    person_store = get_person_entity_store()
    person = person_store.get_by_id(person_id)

    if not person:
        raise HTTPException(status_code=404, detail=f"Person '{person_id}' not found")

    fact_store = get_person_fact_store()
    facts = fact_store.get_for_person(person_id)

    # Convert to responses
    fact_responses = [_fact_to_response(f) for f in facts]

    # Group by category
    by_category: dict[str, list[PersonFactResponse]] = {}
    for fact_resp in fact_responses:
        if fact_resp.category not in by_category:
            by_category[fact_resp.category] = []
        by_category[fact_resp.category].append(fact_resp)

    return PersonFactsResponse(
        facts=fact_responses,
        count=len(fact_responses),
        by_category=by_category,
    )


@router.post("/people/{person_id}/facts/extract", response_model=FactExtractionResponse)
async def extract_person_facts(person_id: str):
    """
    Trigger fact extraction for a person.

    Analyzes recent interactions and extracts structured facts using LLM.
    """
    person_store = get_person_entity_store()
    person = person_store.get_by_id(person_id)

    if not person:
        raise HTTPException(status_code=404, detail=f"Person '{person_id}' not found")

    # Get interactions for the person
    interaction_store = get_interaction_store()
    interactions = interaction_store.get_for_person(
        person_id,
        days_back=365,  # Look back further for fact extraction
        limit=50,
    )

    if not interactions:
        return FactExtractionResponse(
            status="no_interactions",
            extracted_count=0,
            facts=[],
        )

    # Convert to dict format expected by extractor
    interaction_dicts = [
        {
            "id": i.id,
            "source_type": i.source_type,
            "title": i.title,
            "snippet": i.snippet,
            "timestamp": i.timestamp.isoformat() if i.timestamp else "",
        }
        for i in interactions
    ]

    # Extract facts
    try:
        extractor = get_person_fact_extractor()
        extracted_facts = extractor.extract_facts(
            person_id=person_id,
            person_name=person.canonical_name,
            interactions=interaction_dicts,
        )

        return FactExtractionResponse(
            status="completed",
            extracted_count=len(extracted_facts),
            facts=[_fact_to_response(f) for f in extracted_facts],
        )
    except Exception as e:
        logger.error(f"Fact extraction failed for {person_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Fact extraction failed: {str(e)}")


@router.put("/people/{person_id}/facts/{fact_id}", response_model=PersonFactResponse)
async def update_person_fact(person_id: str, fact_id: str, request: FactUpdateRequest):
    """
    Update a fact's value or metadata.
    """
    fact_store = get_person_fact_store()
    fact = fact_store.get_by_id(fact_id)

    if not fact:
        raise HTTPException(status_code=404, detail=f"Fact '{fact_id}' not found")

    if fact.person_id != person_id:
        raise HTTPException(status_code=400, detail="Fact does not belong to this person")

    # Update fields
    if request.value is not None:
        fact.value = request.value
    if request.confidence is not None:
        fact.confidence = max(0.0, min(1.0, request.confidence))
    if request.category is not None:
        if request.category not in FACT_CATEGORIES:
            raise HTTPException(status_code=400, detail=f"Invalid category: {request.category}")
        fact.category = request.category
    if request.key is not None:
        fact.key = request.key

    fact_store.update(fact)

    return _fact_to_response(fact)


@router.delete("/people/{person_id}/facts/{fact_id}")
async def delete_person_fact(person_id: str, fact_id: str):
    """
    Delete a fact.
    """
    fact_store = get_person_fact_store()
    fact = fact_store.get_by_id(fact_id)

    if not fact:
        raise HTTPException(status_code=404, detail=f"Fact '{fact_id}' not found")

    if fact.person_id != person_id:
        raise HTTPException(status_code=400, detail="Fact does not belong to this person")

    fact_store.delete(fact_id)

    return {"status": "deleted", "fact_id": fact_id}


@router.post("/people/{person_id}/facts/{fact_id}/confirm")
async def confirm_person_fact(person_id: str, fact_id: str):
    """
    Mark a fact as confirmed by user.

    Confirmed facts won't be overwritten by future extractions.
    """
    fact_store = get_person_fact_store()
    fact = fact_store.get_by_id(fact_id)

    if not fact:
        raise HTTPException(status_code=404, detail=f"Fact '{fact_id}' not found")

    if fact.person_id != person_id:
        raise HTTPException(status_code=400, detail="Fact does not belong to this person")

    fact_store.confirm(fact_id)

    return {"status": "confirmed", "fact_id": fact_id}


@router.get("/pending-links", response_model=PendingLinksResponse)
async def get_pending_links(
    limit: int = Query(default=100, ge=1, le=500, description="Max results"),
):
    """
    List pending entity links awaiting confirmation.
    """
    pending_store = get_pending_link_store()
    source_store = get_source_entity_store()
    person_store = get_person_entity_store()

    pending = pending_store.get_pending(limit=limit)

    links = []
    for link in pending:
        source_entity = source_store.get_by_id(link.source_entity_id)
        proposed_person = person_store.get_by_id(link.proposed_canonical_id)
        links.append(_pending_link_to_response(link, source_entity, proposed_person))

    return PendingLinksResponse(
        links=links,
        count=len(links),
    )


@router.post("/pending-links/{link_id}/confirm")
async def confirm_pending_link(link_id: str):
    """
    Confirm a pending link.

    Updates the source entity to link to the proposed canonical person.
    """
    pending_store = get_pending_link_store()
    source_store = get_source_entity_store()
    person_store = get_person_entity_store()

    link = pending_store.get_by_id(link_id)
    if not link:
        raise HTTPException(status_code=404, detail=f"Pending link '{link_id}' not found")

    if link.status != STATUS_PENDING:
        raise HTTPException(status_code=400, detail=f"Link is already {link.status}")

    # Update source entity
    source_store.link_to_person(
        link.source_entity_id,
        link.proposed_canonical_id,
        confidence=1.0,
        status=LINK_STATUS_CONFIRMED,
    )

    # Update person's source entity count
    person = person_store.get_by_id(link.proposed_canonical_id)
    if person:
        person.source_entity_count = source_store.count_for_person(link.proposed_canonical_id)
        person_store.update(person)
        person_store.save()

    # Mark link as confirmed
    pending_store.confirm(link_id)

    return {"status": "confirmed", "link_id": link_id}


@router.post("/pending-links/{link_id}/reject")
async def reject_pending_link(link_id: str, request: LinkConfirmRequest):
    """
    Reject a pending link.

    Optionally creates a new person from the source entity.
    """
    pending_store = get_pending_link_store()
    source_store = get_source_entity_store()
    person_store = get_person_entity_store()

    link = pending_store.get_by_id(link_id)
    if not link:
        raise HTTPException(status_code=404, detail=f"Pending link '{link_id}' not found")

    if link.status != STATUS_PENDING:
        raise HTTPException(status_code=400, detail=f"Link is already {link.status}")

    new_person_id = None

    if request.create_new_person:
        if not request.new_person_name:
            raise HTTPException(status_code=400, detail="new_person_name required when creating new person")

        source_entity = source_store.get_by_id(link.source_entity_id)
        if not source_entity:
            raise HTTPException(status_code=404, detail="Source entity not found")

        # Create new person from source entity
        new_person = PersonEntity(
            canonical_name=request.new_person_name,
            display_name=request.new_person_name,
            emails=[source_entity.observed_email] if source_entity.observed_email else [],
            phone_numbers=[source_entity.observed_phone] if source_entity.observed_phone else [],
            sources=[source_entity.source_type],
            first_seen=source_entity.observed_at,
            last_seen=source_entity.observed_at,
            source_entity_count=1,
        )
        person_store.add(new_person)
        person_store.save()

        # Link source entity to new person
        source_store.link_to_person(
            link.source_entity_id,
            new_person.id,
            confidence=1.0,
            status=LINK_STATUS_CONFIRMED,
        )

        new_person_id = new_person.id
    else:
        # Just mark source entity as rejected
        source_entity = source_store.get_by_id(link.source_entity_id)
        if source_entity:
            source_entity.link_status = LINK_STATUS_REJECTED
            source_store.update(source_entity)

    # Mark link as rejected
    pending_store.reject(link_id)

    return {
        "status": "rejected",
        "link_id": link_id,
        "new_person_id": new_person_id,
    }


@router.get("/discover", response_model=DiscoverResponse)
async def discover_connections(
    person_id: Optional[str] = Query(default=None, description="Person to find suggestions for"),
    limit: int = Query(default=10, ge=1, le=50, description="Max suggestions"),
):
    """
    Get suggested connections based on shared contexts.

    If person_id is provided, finds suggestions for that person.
    Otherwise, finds people with potential connections.
    """
    if person_id:
        suggestions = get_suggested_connections(person_id, limit=limit)
        return DiscoverResponse(
            suggestions=[
                SuggestedConnectionResponse(
                    person_id=s["person_id"],
                    name=s["name"],
                    company=s.get("company"),
                    score=s["score"],
                    shared_contexts=s["shared_contexts"],
                    shared_sources=s["shared_sources"],
                )
                for s in suggestions
            ],
            count=len(suggestions),
        )
    else:
        # Return people with highest source diversity but low relationship count
        person_store = get_person_entity_store()
        rel_store = get_relationship_store()

        people = person_store.get_all()

        # Score by source diversity / relationship count
        scored = []
        for person in people:
            rel_count = len(rel_store.get_for_person(person.id, limit=1))
            source_count = len(person.sources)
            if source_count > 1 and rel_count == 0:
                scored.append({
                    "person_id": person.id,
                    "name": person.canonical_name,
                    "company": person.company,
                    "score": source_count / 10.0,
                    "shared_contexts": person.vault_contexts[:3],
                    "shared_sources": person.sources[:3],
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        scored = scored[:limit]

        return DiscoverResponse(
            suggestions=[
                SuggestedConnectionResponse(**s) for s in scored
            ],
            count=len(scored),
        )


@router.post("/sources/import")
async def import_source_data(
    source_type: str = Query(..., description="Source type: whatsapp, signal"),
    file: UploadFile = File(...),
):
    """
    Import data from WhatsApp or Signal export files.

    Accepts .txt for WhatsApp and .json for Signal.
    """
    if source_type not in ("whatsapp", "signal"):
        raise HTTPException(status_code=400, detail="source_type must be 'whatsapp' or 'signal'")

    content = await file.read()

    # Decode content
    try:
        if isinstance(content, bytes):
            try:
                content_str = content.decode("utf-8")
            except UnicodeDecodeError:
                content_str = content.decode("latin-1")
        else:
            content_str = content
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to decode file: {e}")

    source_store = get_source_entity_store()

    if source_type == "whatsapp":
        from api.services.whatsapp_import import import_whatsapp_export
        stats = import_whatsapp_export(
            content_str,
            file.filename or "chat.txt",
            source_store,
        )
    else:  # signal
        from api.services.signal_import import import_signal_export
        stats = import_signal_export(content_str, source_store)

    return {
        "status": "completed",
        "source_type": source_type,
        "filename": file.filename,
        "stats": stats,
    }


@router.post("/sources/{source_type}/sync")
async def sync_source(source_type: str):
    """
    Trigger a sync for a specific data source.
    """
    valid_sources = {"gmail", "calendar", "slack", "contacts", "imessage", "linkedin", "vault"}
    if source_type not in valid_sources:
        raise HTTPException(status_code=400, detail=f"Invalid source type: {source_type}")

    # TODO: Implement actual sync triggers
    return {
        "status": "queued",
        "source_type": source_type,
        "message": "Sync queued for processing",
    }


@router.post("/relationships/discover")
async def trigger_relationship_discovery():
    """
    Trigger relationship discovery across all sources.

    Analyzes shared calendar events, email threads, and vault mentions
    to discover connections between people.
    """
    results = run_full_discovery()
    return {
        "status": "completed",
        "discovered": results,
    }


@router.post("/strengths/update")
async def update_relationship_strengths():
    """
    Update relationship strength scores for all people.
    """
    results = update_all_strengths()
    return {
        "status": "completed",
        "results": results,
    }


@router.get("/statistics", response_model=StatisticsResponse)
async def get_crm_statistics():
    """
    Get comprehensive CRM statistics.
    """
    person_store = get_person_entity_store()
    source_store = get_source_entity_store()
    pending_store = get_pending_link_store()
    rel_store = get_relationship_store()

    person_stats = person_store.get_statistics()
    source_stats = source_store.get_statistics()
    pending_stats = pending_store.get_statistics()
    rel_stats = rel_store.get_statistics()

    return StatisticsResponse(
        total_people=person_stats.get("total_entities", 0),
        by_category=person_stats.get("by_category", {}),
        by_source=person_stats.get("by_source", {}),
        total_source_entities=source_stats.get("total_entities", 0),
        linked_entities=source_stats.get("linked_entities", 0),
        unlinked_entities=source_stats.get("unlinked_entities", 0),
        pending_links_count=pending_stats.get("pending_count", 0),
        total_relationships=rel_stats.get("total_relationships", 0),
    )


@router.get("/network", response_model=NetworkGraphResponse)
async def get_network_graph(
    center_on: Optional[str] = Query(default=None, description="Person ID to center the graph on"),
    depth: int = Query(default=2, ge=1, le=4, description="Hops from center person"),
    min_strength: float = Query(default=0.0, ge=0.0, le=1.0, description="Minimum relationship strength"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
):
    """
    Get network graph data for D3.js visualization.

    Returns nodes (people) and edges (relationships) for rendering
    an interactive force-directed network graph.

    If center_on is provided, only returns people within 'depth' hops
    of the center person. Otherwise, returns all people and relationships.
    """
    person_store = get_person_entity_store()
    rel_store = get_relationship_store()

    # Build the graph
    nodes: list[NetworkNode] = []
    edges: list[NetworkEdge] = []
    node_ids: set[str] = set()

    if center_on:
        # BFS to find people within depth hops of center
        center_person = person_store.get_by_id(center_on)
        if not center_person:
            raise HTTPException(status_code=404, detail=f"Person '{center_on}' not found")

        # BFS traversal
        visited: set[str] = {center_on}
        current_level: set[str] = {center_on}

        for _ in range(depth):
            next_level: set[str] = set()
            for person_id in current_level:
                relationships = rel_store.get_for_person(person_id, limit=100)
                for rel in relationships:
                    other_id = rel.other_person(person_id)
                    if other_id and other_id not in visited:
                        next_level.add(other_id)
                        visited.add(other_id)
            current_level = next_level

        node_ids = visited
    else:
        # Get all people
        all_people = person_store.get_all()
        node_ids = {p.id for p in all_people}

    # Filter by category and strength, then build nodes
    for person_id in node_ids:
        person = person_store.get_by_id(person_id)
        if not person:
            continue

        # Apply filters
        if category and person.category != category:
            continue
        if person.relationship_strength < min_strength:
            continue

        interaction_count = person.meeting_count + person.email_count + person.mention_count

        nodes.append(NetworkNode(
            id=person.id,
            name=person.display_name or person.canonical_name,
            category=person.category,
            strength=person.relationship_strength,
            interaction_count=interaction_count,
        ))

    # Build a set of valid node IDs after filtering
    valid_node_ids = {n.id for n in nodes}

    # Get edges between valid nodes
    seen_edges: set[tuple[str, str]] = set()
    for node in nodes:
        relationships = rel_store.get_for_person(node.id, limit=100)
        for rel in relationships:
            other_id = rel.other_person(node.id)
            if other_id not in valid_node_ids:
                continue

            # Create consistent edge key (smaller ID first)
            edge_key = (min(node.id, other_id), max(node.id, other_id))
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)

            weight = rel.shared_events_count + rel.shared_threads_count

            edges.append(NetworkEdge(
                source=rel.person_a_id,
                target=rel.person_b_id,
                weight=weight,
                type=rel.relationship_type,
            ))

    return NetworkGraphResponse(nodes=nodes, edges=edges)


# Slack Integration Routes
# =======================

@router.get("/slack/status")
async def get_slack_status():
    """
    Get Slack integration status.

    Returns whether Slack OAuth is configured and if we have valid tokens.
    """
    from api.services.slack_integration import get_slack_client

    client = get_slack_client()
    workspaces = client.token_store.list_workspaces()

    return {
        "configured": client.is_configured(),
        "connected": len(workspaces) > 0,
        "workspaces": workspaces,
    }


@router.get("/slack/oauth/start")
async def start_slack_oauth(state: Optional[str] = None):
    """
    Start Slack OAuth flow.

    Returns the authorization URL to redirect the user to.
    """
    from api.services.slack_integration import get_slack_client

    client = get_slack_client()
    if not client.is_configured():
        raise HTTPException(
            status_code=400,
            detail="Slack OAuth not configured. Set SLACK_CLIENT_ID and SLACK_CLIENT_SECRET.",
        )

    return {"oauth_url": client.get_oauth_url(state)}


@router.get("/slack/callback")
async def slack_oauth_callback(code: str, state: Optional[str] = None):
    """
    Handle Slack OAuth callback.

    Exchanges the authorization code for access token.
    """
    from api.services.slack_integration import get_slack_client, SlackAPIError

    client = get_slack_client()

    try:
        result = client.exchange_code(code)
        team = result.get("team", {})
        return {
            "status": "connected",
            "workspace_id": team.get("id"),
            "workspace_name": team.get("name"),
            "message": f"Successfully connected to {team.get('name')}",
        }
    except SlackAPIError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/slack/sync")
async def sync_slack_users_endpoint(workspace_id: str = "default"):
    """
    Sync Slack users to the CRM.

    Creates SourceEntity records for all users in the workspace.
    """
    from api.services.slack_integration import (
        get_slack_client,
        sync_slack_users,
        SlackAPIError,
    )

    client = get_slack_client()
    if not client.is_connected(workspace_id):
        raise HTTPException(
            status_code=400,
            detail=f"Not connected to Slack workspace {workspace_id}. Complete OAuth first.",
        )

    source_store = get_source_entity_store()

    try:
        stats = sync_slack_users(client, source_store, workspace_id)
        return {
            "status": "completed",
            "workspace_id": workspace_id,
            "stats": stats,
        }
    except SlackAPIError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/slack/disconnect")
async def disconnect_slack(workspace_id: str = "default"):
    """
    Disconnect a Slack workspace.

    Removes the stored OAuth token.
    """
    from api.services.slack_integration import get_slack_client

    client = get_slack_client()
    client.token_store.remove_token(workspace_id)

    return {
        "status": "disconnected",
        "workspace_id": workspace_id,
    }


# Apple Contacts Integration Routes
# ==================================

@router.get("/contacts/status")
async def get_contacts_status():
    """
    Get Apple Contacts integration status.

    Returns availability and authorization status.
    """
    from api.services.apple_contacts import get_contacts_reader

    reader = get_contacts_reader()

    return {
        "available": reader.is_available,
        "authorization": reader.check_authorization() if reader.is_available else "not_available",
    }


@router.post("/contacts/sync")
async def sync_contacts_endpoint():
    """
    Sync Apple Contacts to the CRM.

    Creates SourceEntity records for all contacts.
    Requires macOS and Contacts permission.
    """
    from api.services.apple_contacts import get_contacts_reader, sync_apple_contacts

    reader = get_contacts_reader()
    if not reader.is_available:
        raise HTTPException(
            status_code=400,
            detail="Apple Contacts not available. Requires macOS and pyobjc-framework-Contacts.",
        )

    auth_status = reader.check_authorization()
    if auth_status != "authorized":
        raise HTTPException(
            status_code=403,
            detail=f"Contacts access not authorized: {auth_status}. Grant permission in System Preferences.",
        )

    source_store = get_source_entity_store()
    stats = sync_apple_contacts(source_store, reader)

    return {
        "status": "completed",
        "stats": stats,
    }


# Sync Health Monitoring Routes
# =============================


class SyncHealthResponse(BaseModel):
    """Response for a single sync source health."""
    source: str
    description: str
    last_sync: Optional[str] = None
    last_status: Optional[str] = None
    last_error: Optional[str] = None
    is_stale: bool = True
    hours_since_sync: Optional[float] = None
    expected_frequency: str = "daily"


class SyncHealthSummaryResponse(BaseModel):
    """Response for overall sync health."""
    total_sources: int
    healthy: int
    stale: int
    failed: int
    never_run: int
    stale_sources: list[str] = []
    failed_sources: list[str] = []
    never_run_sources: list[str] = []
    all_healthy: bool


class SyncErrorResponse(BaseModel):
    """Response for a sync error."""
    id: int
    source: str
    timestamp: str
    error_type: Optional[str] = None
    error_message: str
    context: Optional[str] = None


@router.get("/sync/health", response_model=list[SyncHealthResponse])
async def get_all_sync_health():
    """
    Get health status for all sync sources.

    Returns staleness, last sync time, and error status for each source.
    This endpoint is critical for monitoring that all data sources remain in sync.
    """
    from api.services.sync_health import get_all_sync_health as _get_all

    health_list = _get_all()

    return [
        SyncHealthResponse(
            source=h.source,
            description=h.description,
            last_sync=h.last_sync.isoformat() if h.last_sync else None,
            last_status=h.last_status.value if h.last_status else None,
            last_error=h.last_error,
            is_stale=h.is_stale,
            hours_since_sync=h.hours_since_sync,
            expected_frequency=h.expected_frequency,
        )
        for h in health_list
    ]


@router.get("/sync/health/summary", response_model=SyncHealthSummaryResponse)
async def get_sync_health_summary():
    """
    Get summary of sync health across all sources.

    Returns counts of healthy, stale, and failed sources.
    Use this for dashboard status indicators.
    """
    from api.services.sync_health import get_sync_summary

    summary = get_sync_summary()

    return SyncHealthSummaryResponse(**summary)


@router.get("/sync/health/{source}", response_model=SyncHealthResponse)
async def get_source_sync_health(source: str):
    """
    Get health status for a specific sync source.
    """
    from api.services.sync_health import get_sync_health as _get_health, SYNC_SOURCES

    if source not in SYNC_SOURCES:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown sync source: {source}. Valid sources: {list(SYNC_SOURCES.keys())}"
        )

    health = _get_health(source)

    return SyncHealthResponse(
        source=health.source,
        description=health.description,
        last_sync=health.last_sync.isoformat() if health.last_sync else None,
        last_status=health.last_status.value if health.last_status else None,
        last_error=health.last_error,
        is_stale=health.is_stale,
        hours_since_sync=health.hours_since_sync,
        expected_frequency=health.expected_frequency,
    )


@router.get("/sync/errors", response_model=list[SyncErrorResponse])
async def get_sync_errors(
    source: Optional[str] = Query(default=None, description="Filter by source"),
    limit: int = Query(default=50, ge=1, le=200, description="Max results"),
):
    """
    Get recent sync errors for debugging.

    Returns errors with timestamps, types, and context.
    """
    from api.services.sync_health import get_recent_errors

    errors = get_recent_errors(source=source, limit=limit)

    return [
        SyncErrorResponse(
            id=e["id"],
            source=e["source"],
            timestamp=e["timestamp"],
            error_type=e.get("error_type"),
            error_message=e["error_message"],
            context=e.get("context"),
        )
        for e in errors
    ]


@router.get("/sync/stale", response_model=list[SyncHealthResponse])
async def get_stale_syncs():
    """
    Get list of syncs that are stale (>24 hours old).

    Use this to identify which sources need attention.
    """
    from api.services.sync_health import get_stale_syncs as _get_stale

    stale = _get_stale()

    return [
        SyncHealthResponse(
            source=h.source,
            description=h.description,
            last_sync=h.last_sync.isoformat() if h.last_sync else None,
            last_status=h.last_status.value if h.last_status else None,
            last_error=h.last_error,
            is_stale=h.is_stale,
            hours_since_sync=h.hours_since_sync,
            expected_frequency=h.expected_frequency,
        )
        for h in stale
    ]


# Low-confidence Match Review Queue Routes
# ========================================


class ReviewQueueItem(BaseModel):
    """An item in the low-confidence match review queue."""
    id: str
    source_entity_id: str
    source_type: str
    observed_name: Optional[str] = None
    observed_email: Optional[str] = None
    observed_phone: Optional[str] = None
    proposed_person_id: str
    proposed_person_name: str
    confidence: float
    reason: str
    created_at: Optional[str] = None


class ReviewQueueResponse(BaseModel):
    """Response for review queue."""
    items: list[ReviewQueueItem]
    count: int
    total_pending: int


@router.get("/review-queue", response_model=ReviewQueueResponse)
async def get_review_queue(
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0, description="Minimum confidence"),
    max_confidence: float = Query(default=0.85, ge=0.0, le=1.0, description="Maximum confidence"),
    limit: int = Query(default=50, ge=1, le=200, description="Max results"),
):
    """
    Get low-confidence matches for review.

    Returns source entities linked with confidence below threshold,
    allowing user to quickly confirm or reject matches.

    Default shows matches with confidence < 0.85 (85%).
    """
    source_store = get_source_entity_store()
    person_store = get_person_entity_store()

    # Get low-confidence linked entities
    entities = source_store.get_low_confidence(
        min_confidence=min_confidence,
        max_confidence=max_confidence,
        limit=limit,
    )

    total = source_store.count_low_confidence(
        min_confidence=min_confidence,
        max_confidence=max_confidence,
    )

    items = []
    for entity in entities:
        if entity.canonical_person_id:
            person = person_store.get_by_id(entity.canonical_person_id)
            if person:
                items.append(ReviewQueueItem(
                    id=entity.id,
                    source_entity_id=entity.id,
                    source_type=entity.source_type,
                    observed_name=entity.observed_name,
                    observed_email=entity.observed_email,
                    observed_phone=entity.observed_phone,
                    proposed_person_id=entity.canonical_person_id,
                    proposed_person_name=person.canonical_name,
                    confidence=entity.link_confidence,
                    reason=entity.link_status,
                    created_at=entity.observed_at.isoformat() if entity.observed_at else None,
                ))

    return ReviewQueueResponse(
        items=items,
        count=len(items),
        total_pending=total,
    )


@router.post("/review-queue/{entity_id}/confirm")
async def confirm_review_item(entity_id: str):
    """
    Confirm a low-confidence match as correct.

    Updates the link confidence to 1.0 and status to confirmed.
    """
    source_store = get_source_entity_store()
    entity = source_store.get_by_id(entity_id)

    if not entity:
        raise HTTPException(status_code=404, detail=f"Source entity '{entity_id}' not found")

    if not entity.canonical_person_id:
        raise HTTPException(status_code=400, detail="Source entity is not linked to any person")

    # Update to confirmed status
    source_store.link_to_person(
        entity_id,
        entity.canonical_person_id,
        confidence=1.0,
        status=LINK_STATUS_CONFIRMED,
    )

    return {"status": "confirmed", "entity_id": entity_id}


@router.post("/review-queue/{entity_id}/reject")
async def reject_review_item(entity_id: str, request: LinkConfirmRequest):
    """
    Reject a low-confidence match.

    Optionally creates a new person from the source entity.
    """
    source_store = get_source_entity_store()
    person_store = get_person_entity_store()
    entity = source_store.get_by_id(entity_id)

    if not entity:
        raise HTTPException(status_code=404, detail=f"Source entity '{entity_id}' not found")

    new_person_id = None

    if request.create_new_person:
        if not request.new_person_name:
            name = entity.observed_name or entity.observed_email or "Unknown"
        else:
            name = request.new_person_name

        # Create new person
        new_person = PersonEntity(
            canonical_name=name,
            display_name=name,
            emails=[entity.observed_email] if entity.observed_email else [],
            phone_numbers=[entity.observed_phone] if entity.observed_phone else [],
            sources=[entity.source_type],
            first_seen=entity.observed_at,
            last_seen=entity.observed_at,
            source_entity_count=1,
        )
        person_store.add(new_person)
        person_store.save()

        # Link to new person
        source_store.link_to_person(
            entity_id,
            new_person.id,
            confidence=1.0,
            status=LINK_STATUS_CONFIRMED,
        )
        new_person_id = new_person.id
    else:
        # Mark as rejected
        entity.link_status = LINK_STATUS_REJECTED
        entity.canonical_person_id = None
        source_store.update(entity)

    return {
        "status": "rejected",
        "entity_id": entity_id,
        "new_person_id": new_person_id,
    }

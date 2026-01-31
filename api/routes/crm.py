"""
CRM API endpoints for LifeOS Personal CRM.

Provides comprehensive endpoints for managing people, relationships,
and entity linking workflows.
"""
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional, Union
import logging
import time

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field

from api.services.person_entity import PersonEntity, get_person_entity_store
from api.services.interaction_store import get_interaction_store
from config.people_config import InteractionConfig
from config.settings import settings
from api.services.source_entity import (
    SourceEntity,
    get_source_entity_store,
    LINK_STATUS_CONFIRMED,
    LINK_STATUS_REJECTED,
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

# Work email domain for category detection
WORK_EMAIL_DOMAIN = "movementlabs.com"

# Owner's person ID for "Me" page
MY_PERSON_ID = "3f41e143-719f-4dc9-a9f1-389b2db5b166"

# Family last names (case-insensitive matching)
FAMILY_LAST_NAMES = {"ramia"}

# Family members by exact name (case-insensitive)
FAMILY_EXACT_NAMES = {
    # Walker/Lyras/Haddad
    "taylor walker",
    "cissy",
    "ethan van drimmelen",
    "evie lyras",
    "jordan haddad",
    # Jones family
    "lucy jones",
    "grandparents jones",
    "bryce jones",
    "bill jones",
    "ryan a. jones",
    "ryan jones",
    "uncle dave",
    "aunt judi",
    "aunt kathleen",
    # Berry family
    "shane berry",
    "shane e. berry",
    "bryce berry",
    "jonas berry",
    "brian berry",
    # Prenger/Townsend family
    "kayla townsend",
    "amy prenger",
    "grammy",
    "jeremy prenger",
}

# Manual strength overrides (name -> strength 0-100)
STRENGTH_OVERRIDES = {
    "taylor walker": 100.0,
    "nathan ramia": 100.0,
}


def _get_strength_override(name: str) -> float | None:
    """Check if a person has a manual strength override."""
    if not name:
        return None
    return STRENGTH_OVERRIDES.get(name.lower().strip())


def _is_family_member(name: str) -> bool:
    """Check if a name matches family criteria."""
    if not name:
        return False
    name_lower = name.lower().strip()

    # Check exact name match
    if name_lower in FAMILY_EXACT_NAMES:
        return True

    # Check last name match
    name_parts = name_lower.split()
    if name_parts:
        last_name = name_parts[-1]
        if last_name in FAMILY_LAST_NAMES:
            return True

    return False


def compute_person_category(person: PersonEntity, source_entities: list = None) -> str:
    """
    Compute category with priority: self → family → work → personal.

    Rules (in order):
    1. Is the CRM owner (my_person_id) → self
    2. Has family last name or exact name match → family
    3. Has Slack or @movementlabs.com email → work
    4. Otherwise → personal
    """
    # 1. Check if this is "me" (the CRM owner)
    if person.id == settings.my_person_id:
        return "self"

    # 2. Check family membership (by name)
    if _is_family_member(person.canonical_name):
        return "family"
    # Also check display name and aliases
    if _is_family_member(person.display_name):
        return "family"
    for alias in person.aliases:
        if _is_family_member(alias):
            return "family"

    # 3. Check for work indicators
    # Check person's own emails first
    for email in person.emails:
        if email and WORK_EMAIL_DOMAIN in email.lower():
            return "work"

    # Check sources list for slack
    if "slack" in person.sources:
        return "work"

    # If no source entities provided, fetch them
    if source_entities is None:
        source_store = get_source_entity_store()
        source_entities = source_store.get_for_person(person.id, limit=500)

    for se in source_entities:
        if se.source_type == "slack":
            return "work"
        if se.observed_email and WORK_EMAIL_DOMAIN in se.observed_email.lower():
            return "work"
        if se.metadata and se.metadata.get("account") == "work":
            return "work"

    # 4. Default to personal
    return "personal"


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens, removing punctuation."""
    import re
    # Split on whitespace and punctuation, keep only alphanumeric
    return [t.lower() for t in re.split(r'[\s.,;:\-\'\"()]+', text) if t]


def _fuzzy_name_match(query: str, name: str) -> bool:
    """
    Check if query tokens match name tokens as prefixes.

    Examples:
    - "ryan jones" matches "Ryan A. Jones" (exact word matches)
    - "ry jo" matches "Ryan A. Jones" (prefix matches)
    - "jo ry" matches "Ryan A. Jones" (order doesn't matter)
    """
    if not query or not name:
        return False

    query_tokens = _tokenize(query)
    name_tokens = _tokenize(name)

    if not query_tokens:
        return False

    # Each query token must match the start of at least one name token
    for qt in query_tokens:
        if not any(nt.startswith(qt) for nt in name_tokens):
            return False
    return True


def _search_matches(query: str, person) -> bool:
    """Check if a person matches the search query."""
    q_lower = query.lower()

    # Try fuzzy name matching first
    if _fuzzy_name_match(query, person.canonical_name):
        return True
    if _fuzzy_name_match(query, person.display_name):
        return True
    for alias in person.aliases:
        if _fuzzy_name_match(query, alias):
            return True

    # Fall back to substring matching for emails and company
    if any(q_lower in email.lower() for email in person.emails):
        return True
    if person.company and q_lower in person.company.lower():
        return True

    return False


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
    message_count: int = 0  # iMessage/SMS count
    # Related data
    source_entities: list[SourceEntityResponse] = []
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
    shared_messages_count: int = 0      # iMessage/SMS
    shared_whatsapp_count: int = 0      # WhatsApp
    shared_slack_count: int = 0         # Slack DMs
    shared_phone_calls_count: int = 0   # Phone calls
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
    total_relationships: int = 0


class NetworkNode(BaseModel):
    """A node in the network graph."""
    id: str
    name: str
    category: str = "unknown"
    strength: float = 0.0
    interaction_count: int = 0
    degree: int = 1  # 0 = center, 1 = first-degree, 2 = second-degree, etc.


class NetworkEdge(BaseModel):
    """An edge in the network graph."""
    source: str
    target: str
    weight: int = 0
    type: str = "inferred"
    # Multi-source breakdown for filtering
    shared_events_count: int = 0       # Calendar events
    shared_threads_count: int = 0      # Email threads
    shared_messages_count: int = 0     # iMessage/SMS
    shared_whatsapp_count: int = 0     # WhatsApp
    shared_slack_count: int = 0        # Slack DMs
    shared_phone_calls_count: int = 0  # Phone calls
    is_linkedin_connection: bool = False


class NetworkGraphResponse(BaseModel):
    """Response for network graph endpoint."""
    nodes: list[NetworkNode]
    edges: list[NetworkEdge]


class PersonFactResponse(BaseModel):
    """Response model for a person fact."""
    id: str
    person_id: str
    category: str
    key: str
    value: str
    confidence: float = 0.5
    source_interaction_id: Optional[str] = None
    source_quote: Optional[str] = None  # Verbatim quote proving this fact
    source_link: Optional[str] = None  # Deep link to source (Gmail, Calendar, Obsidian)
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


class PersonMergeRequest(BaseModel):
    """Request for merging people."""
    primary_id: str = Field(..., description="ID of the person to keep (survivor)")
    secondary_ids: list[str] = Field(..., description="IDs of people to merge into primary")


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


class HidePersonRequest(BaseModel):
    """Request for hiding a person (soft delete)."""
    reason: str = Field(
        default="",
        description="Reason for hiding (e.g., 'fake marketing persona')"
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
    # Fetch source entities first for category computation
    source_store = get_source_entity_store()
    source_entities = source_store.get_for_person(person.id, limit=100) if include_related else None

    # Compute category dynamically based on source entities and email domains
    computed_category = compute_person_category(person, source_entities)

    # Check for manual strength override
    strength_override = _get_strength_override(person.canonical_name)
    computed_strength = strength_override if strength_override is not None else person.relationship_strength

    response = PersonDetailResponse(
        id=person.id,
        canonical_name=person.canonical_name,
        display_name=person.display_name,
        emails=person.emails,
        phone_numbers=person.phone_numbers,
        company=person.company,
        position=person.position,
        linkedin_url=person.linkedin_url,
        category=computed_category,
        vault_contexts=person.vault_contexts,
        tags=person.tags,
        notes=person.notes,
        sources=person.sources,
        first_seen=person.first_seen.isoformat() if person.first_seen else None,
        last_seen=person.last_seen.isoformat() if person.last_seen else None,
        relationship_strength=computed_strength,
        source_entity_count=person.source_entity_count,
        meeting_count=person.meeting_count,
        email_count=person.email_count,
        mention_count=person.mention_count,
        message_count=person.message_count,
    )

    if include_related:
        # Source entities already fetched for category computation
        response.source_entities = [_source_entity_to_response(e) for e in source_entities]

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
    has_interactions: Optional[bool] = Query(default=None, description="Filter by interaction count > 0"),
    min_interactions: int = Query(default=0, ge=0, description="Minimum total interactions (emails + meetings + mentions + messages)"),
    sort: str = Query(default="strength", description="Sort field: interactions, last_seen, name, strength"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    limit: int = Query(default=50, ge=1, le=10000, description="Max results (up to 10000 for Dunbar calculation)"),
):
    """
    List people with filtering and sorting.

    Supports searching by name/email, filtering by category/source,
    and sorting by interactions, last_seen, name, or relationship strength.
    """
    start_time = time.time()

    person_store = get_person_entity_store()

    # Get all people
    people = person_store.get_all()

    # Apply search filter (fuzzy token-based matching for names)
    if q:
        people = [p for p in people if _search_matches(q, p)]

    # Apply category filter (uses computed category based on work domain/slack)
    if category:
        people = [p for p in people if compute_person_category(p, []) == category]

    # Apply source filter
    if source:
        people = [p for p in people if source in p.sources]

    # Apply interactions filter (boolean)
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

    # Apply min_interactions filter (numeric threshold)
    if min_interactions > 0:
        people = [
            p for p in people
            if (p.email_count or 0) + (p.meeting_count or 0) + (p.mention_count or 0) + getattr(p, 'message_count', 0) >= min_interactions
        ]

    total = len(people)

    # Apply sorting
    if sort == "name":
        people.sort(key=lambda p: p.canonical_name.lower())
    elif sort == "strength":
        # Use strength override if available
        people.sort(key=lambda p: _get_strength_override(p.canonical_name) or p.relationship_strength, reverse=True)
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

    result = PersonListResponse(
        people=[
            _person_to_detail_response(p, include_related=False)
            for p in people
        ],
        count=len(people),
        total=total,
        offset=offset,
        has_more=has_more,
    )

    elapsed = (time.time() - start_time) * 1000
    logger.info(f"list_people(q={q}, category={category}, limit={limit}) took {elapsed:.1f}ms ({total} total, {len(people)} returned)")

    return result


@router.get("/people/{person_id}", response_model=PersonDetailResponse)
async def get_person(
    person_id: str,
    include_related: bool = Query(default=False, description="Include source entities and relationships"),
    refresh_strength: bool = Query(default=False, description="Recompute relationship strength (slower)"),
):
    """
    Get detailed information about a person.

    By default returns only person data for fast loading.
    Use include_related=true for source entities and relationships.
    Use refresh_strength=true to recompute relationship strength (slower).
    """
    start_time = time.time()

    person_store = get_person_entity_store()
    person = person_store.get_by_id(person_id)

    if not person:
        raise HTTPException(status_code=404, detail=f"Person '{person_id}' not found")

    # Only recompute relationship strength if explicitly requested
    # This is slow (~100-500ms) so skip by default
    if refresh_strength:
        try:
            strength = compute_strength_for_person(person)
            person.relationship_strength = strength
        except Exception as e:
            logger.warning(f"Failed to compute relationship strength: {e}")

    response = _person_to_detail_response(person, include_related=include_related)

    elapsed = (time.time() - start_time) * 1000
    logger.info(f"get_person({person_id}) took {elapsed:.1f}ms (include_related={include_related})")

    return response


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


class PersonMergeResponse(BaseModel):
    """Response for merge operation."""
    status: str
    primary_id: str
    merged_ids: list[str]
    stats: dict


@router.post("/people/merge", response_model=PersonMergeResponse)
async def merge_people(request: PersonMergeRequest):
    """
    Merge multiple people into a single record.

    The primary person survives, and all secondary people are merged into it.
    This operation:
    - Merges emails, phones, aliases from all secondaries into primary
    - Updates all interactions to point to primary
    - Updates all source entities to point to primary
    - Updates all facts to point to primary
    - Records the merge for durability (prevents re-creation of duplicates)
    - Deletes the secondary records

    The merge is durable - merged IDs are tracked so entity resolution
    won't recreate duplicates from future syncs.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from scripts.merge_people import merge_people as do_merge, load_merged_ids, save_merged_ids

    person_store = get_person_entity_store()
    source_store = get_source_entity_store()

    # Validate primary exists
    primary = person_store.get_by_id(request.primary_id)
    if not primary:
        raise HTTPException(status_code=404, detail=f"Primary person '{request.primary_id}' not found")

    # Validate all secondaries exist
    for sec_id in request.secondary_ids:
        secondary = person_store.get_by_id(sec_id)
        if not secondary:
            raise HTTPException(status_code=404, detail=f"Secondary person '{sec_id}' not found")
        if sec_id == request.primary_id:
            raise HTTPException(status_code=400, detail="Cannot merge a person into itself")

    # Perform merges
    total_stats = {
        'interactions_updated': 0,
        'source_entities_updated': 0,
        'facts_cleared': 0,
        'emails_merged': 0,
        'phones_merged': 0,
        'aliases_added': 0,
    }

    merged_ids = []
    for sec_id in request.secondary_ids:
        try:
            stats = do_merge(request.primary_id, sec_id, dry_run=False)
            merged_ids.append(sec_id)
            for key in total_stats:
                total_stats[key] += stats.get(key, 0)
        except Exception as e:
            logger.error(f"Failed to merge {sec_id} into {request.primary_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Merge failed for {sec_id}: {str(e)}")

    logger.info(f"Merged {len(merged_ids)} people into {request.primary_id}: {merged_ids}")

    return PersonMergeResponse(
        status="completed",
        primary_id=request.primary_id,
        merged_ids=merged_ids,
        stats=total_stats,
    )


# ============================================================================
# Split Helper Functions
# ============================================================================

def _recalculate_person_stats(person_id: str, int_conn, person_store) -> dict:
    """
    Recalculate person stats from the interactions table.

    Returns dict of updated stats for logging.
    """
    from datetime import datetime, timezone

    person = person_store.get_by_id(person_id)
    if not person:
        return {}

    # Query interaction counts by source_type
    cursor = int_conn.execute("""
        SELECT source_type, COUNT(*) as count
        FROM interactions
        WHERE person_id = ?
        GROUP BY source_type
    """, (person_id,))

    counts = {row[0]: row[1] for row in cursor.fetchall()}

    # Map source_types to person stats
    old_stats = {
        'email_count': person.email_count,
        'meeting_count': person.meeting_count,
        'message_count': person.message_count,
        'mention_count': person.mention_count,
    }

    person.email_count = counts.get('gmail', 0)
    person.meeting_count = counts.get('calendar', 0)
    person.message_count = (
        counts.get('imessage', 0) +
        counts.get('whatsapp', 0) +
        counts.get('phone', 0)
    )
    person.mention_count = counts.get('vault', 0) + counts.get('granola', 0)

    # Update first_seen/last_seen from interactions
    cursor = int_conn.execute("""
        SELECT MIN(timestamp), MAX(timestamp)
        FROM interactions
        WHERE person_id = ?
    """, (person_id,))
    row = cursor.fetchone()
    if row and row[0]:
        person.first_seen = datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc)
    if row and row[1]:
        person.last_seen = datetime.fromisoformat(row[1]).replace(tzinfo=timezone.utc)

    person_store.update(person)

    new_stats = {
        'email_count': person.email_count,
        'meeting_count': person.meeting_count,
        'message_count': person.message_count,
        'mention_count': person.mention_count,
    }

    return {'old': old_stats, 'new': new_stats}


def _recalculate_relationship_with_me(person_id: str, my_person_id: str, int_conn) -> dict:
    """
    Recalculate the relationship between person_id and my_person_id.

    Queries interactions to get accurate shared_* counts.
    Returns dict with relationship changes for logging.
    """
    from api.services.relationship import get_relationship_store, Relationship
    from datetime import datetime, timezone

    if not my_person_id or person_id == my_person_id:
        return {}

    rel_store = get_relationship_store()

    # Query interaction counts by source_type for this person
    cursor = int_conn.execute("""
        SELECT source_type, COUNT(*) as count
        FROM interactions
        WHERE person_id = ?
        GROUP BY source_type
    """, (person_id,))

    counts = {row[0]: row[1] for row in cursor.fetchall()}

    # Get timestamps
    cursor = int_conn.execute("""
        SELECT MIN(timestamp), MAX(timestamp)
        FROM interactions
        WHERE person_id = ?
    """, (person_id,))
    row = cursor.fetchone()
    first_seen = datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc) if row and row[0] else None
    last_seen = datetime.fromisoformat(row[1]).replace(tzinfo=timezone.utc) if row and row[1] else None

    # Calculate shared counts (interactions with this person = shared with me)
    shared_events = counts.get('calendar', 0)
    shared_threads = counts.get('gmail', 0)
    shared_messages = counts.get('imessage', 0)
    shared_whatsapp = counts.get('whatsapp', 0)
    shared_phone = counts.get('phone', 0)
    shared_slack = counts.get('slack', 0)

    total_interactions = sum(counts.values())

    # Get or create relationship
    existing = rel_store.get_between(my_person_id, person_id)

    if total_interactions == 0:
        # No interactions - delete relationship if exists
        if existing:
            rel_store.delete(existing.id)
            return {'action': 'deleted', 'person_id': person_id}
        return {'action': 'none', 'person_id': person_id}

    if existing:
        # Update existing relationship
        old_total = existing.total_shared_interactions

        existing.shared_events_count = shared_events
        existing.shared_threads_count = shared_threads
        existing.shared_messages_count = shared_messages
        existing.shared_whatsapp_count = shared_whatsapp
        existing.shared_phone_calls_count = shared_phone
        existing.shared_slack_count = shared_slack

        if first_seen and (not existing.first_seen_together or first_seen < existing.first_seen_together):
            existing.first_seen_together = first_seen
        if last_seen and (not existing.last_seen_together or last_seen > existing.last_seen_together):
            existing.last_seen_together = last_seen

        rel_store.update(existing)

        return {
            'action': 'updated',
            'person_id': person_id,
            'old_total': old_total,
            'new_total': existing.total_shared_interactions,
        }
    else:
        # Create new relationship
        # Normalize IDs (person_a_id < person_b_id)
        if my_person_id < person_id:
            person_a_id, person_b_id = my_person_id, person_id
        else:
            person_a_id, person_b_id = person_id, my_person_id

        new_rel = Relationship(
            person_a_id=person_a_id,
            person_b_id=person_b_id,
            shared_events_count=shared_events,
            shared_threads_count=shared_threads,
            shared_messages_count=shared_messages,
            shared_whatsapp_count=shared_whatsapp,
            shared_phone_calls_count=shared_phone,
            shared_slack_count=shared_slack,
            first_seen_together=first_seen,
            last_seen_together=last_seen,
        )
        rel_store.add(new_rel)

        return {
            'action': 'created',
            'person_id': person_id,
            'total': new_rel.total_shared_interactions,
        }


class PersonSplitRequest(BaseModel):
    """Request to split source entities from a person to another."""
    from_person_id: str
    to_person_id: Optional[str] = None  # None = create new person
    new_person_name: Optional[str] = None  # Required if to_person_id is None
    source_entity_ids: list[str]  # IDs of source entities to move
    create_overrides: bool = True  # Create link override rules for durability


class PersonSplitResponse(BaseModel):
    """Response for split operation."""
    status: str
    from_person_id: str
    to_person_id: str
    source_entities_moved: int
    interactions_moved: int
    overrides_created: int


class ContactSource(BaseModel):
    """An aggregated contact source - a unique identifier linked to a person.

    This represents a meaningful unit for entity splitting:
    - An email address (across gmail, calendar, etc.)
    - A phone number (across iMessage, WhatsApp, calls)
    - A Slack user ID
    - A LinkedIn profile
    """
    identifier: str  # email address, phone number, or ID
    identifier_type: str  # 'email', 'phone', 'slack_user', 'linkedin_profile'
    source_types: list[str]  # Where this identifier appears (gmail, calendar, slack, etc.)
    observation_count: int  # Number of individual observations
    source_entity_ids: list[str]  # IDs for split operation
    observed_names: list[str]  # Names seen with this identifier
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None


@router.get("/people/{person_id}/contact-sources")
async def get_person_contact_sources(person_id: str):
    """
    Get aggregated contact sources linked to a person.

    Unlike source-entities which returns individual observations,
    this returns unique contact identifiers (emails, phones, etc.)
    that can be meaningfully split to another person.

    For entity resolution, what matters is:
    - This email address is linked to Person A
    - This phone number is linked to Person A

    Not: "Message #12345 is linked to Person A"
    """
    import sqlite3
    from pathlib import Path
    from collections import defaultdict

    person_store = get_person_entity_store()
    person = person_store.get_by_id(person_id)

    if not person:
        raise HTTPException(status_code=404, detail=f"Person '{person_id}' not found")

    crm_db = Path(__file__).parent.parent.parent / "data" / "crm.db"
    conn = sqlite3.connect(crm_db)
    conn.row_factory = sqlite3.Row

    # Get all source entities for this person
    cursor = conn.execute("""
        SELECT id, source_type, source_id, observed_name, observed_email, observed_phone,
               observed_at
        FROM source_entities
        WHERE canonical_person_id = ?
    """, (person_id,))

    # Aggregate by unique identifier
    # Key: (identifier_type, identifier) -> list of source entity info
    aggregated: dict[tuple[str, str], dict] = {}

    for row in cursor:
        source_type = row['source_type']
        observed_email = row['observed_email']
        observed_phone = row['observed_phone']
        source_id = row['source_id']
        observed_name = row['observed_name']
        observed_at = row['observed_at']
        entity_id = row['id']

        # Determine the identifier based on source type
        # Email-based sources
        if observed_email:
            key = ('email', observed_email.lower())
        # Phone-based sources
        elif observed_phone:
            key = ('phone', observed_phone)
        # ID-based sources (Slack, LinkedIn)
        elif source_type == 'slack' and source_id:
            key = ('slack_user', source_id)
        elif source_type == 'linkedin' and source_id:
            key = ('linkedin_profile', source_id)
        elif source_type in ('vault', 'granola') and observed_name:
            # For vault/granola, group by name since there's no email/phone
            key = ('name_only', observed_name.lower())
        else:
            # Skip entities without meaningful identifiers
            continue

        if key not in aggregated:
            aggregated[key] = {
                'identifier': key[1],
                'identifier_type': key[0],
                'source_types': set(),
                'source_entity_ids': [],
                'observed_names': set(),
                'first_seen': observed_at,
                'last_seen': observed_at,
            }

        agg = aggregated[key]
        agg['source_types'].add(source_type)
        agg['source_entity_ids'].append(entity_id)
        if observed_name:
            agg['observed_names'].add(observed_name)

        # Update first/last seen
        if observed_at:
            if not agg['first_seen'] or observed_at < agg['first_seen']:
                agg['first_seen'] = observed_at
            if not agg['last_seen'] or observed_at > agg['last_seen']:
                agg['last_seen'] = observed_at

    conn.close()

    # Convert to response format
    contact_sources = []
    for key, agg in aggregated.items():
        contact_sources.append(ContactSource(
            identifier=agg['identifier'],
            identifier_type=agg['identifier_type'],
            source_types=sorted(agg['source_types']),
            observation_count=len(agg['source_entity_ids']),
            source_entity_ids=agg['source_entity_ids'],
            observed_names=sorted(agg['observed_names'])[:5],  # Limit to 5 names
            first_seen=agg['first_seen'],
            last_seen=agg['last_seen'],
        ))

    # Sort: emails first, then phones, then by observation count
    type_order = {'email': 0, 'phone': 1, 'slack_user': 2, 'linkedin_profile': 3, 'name_only': 4}
    contact_sources.sort(key=lambda cs: (
        type_order.get(cs.identifier_type, 99),
        -cs.observation_count
    ))

    # Summary counts
    total_observations = sum(cs.observation_count for cs in contact_sources)

    return {
        'person_id': person_id,
        'person_name': person.canonical_name,
        'contact_sources': [cs.model_dump() for cs in contact_sources],
        'total_contact_sources': len(contact_sources),
        'total_observations': total_observations,
    }


@router.get("/people/{person_id}/source-entities")
async def get_person_source_entities(
    person_id: str,
    limit: int = Query(default=500, ge=1, le=5000, description="Max source entities to return"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
):
    """
    Get source entities linked to a person with pagination.

    Used by the split UI to show what sources comprise a person record.
    Default limit is 500 to prevent performance issues with large records.
    """
    import sqlite3
    from pathlib import Path

    person_store = get_person_entity_store()
    person = person_store.get_by_id(person_id)

    if not person:
        raise HTTPException(status_code=404, detail=f"Person '{person_id}' not found")

    crm_db = Path(__file__).parent.parent.parent / "data" / "crm.db"
    conn = sqlite3.connect(crm_db)
    conn.row_factory = sqlite3.Row

    # Get total count first
    count_cursor = conn.execute("""
        SELECT COUNT(*) as cnt FROM source_entities WHERE canonical_person_id = ?
    """, (person_id,))
    total_count = count_cursor.fetchone()['cnt']

    cursor = conn.execute("""
        SELECT id, source_type, source_id, observed_name, observed_email, observed_phone,
               link_confidence, link_status, observed_at
        FROM source_entities
        WHERE canonical_person_id = ?
        ORDER BY source_type, observed_at DESC
        LIMIT ? OFFSET ?
    """, (person_id, limit, offset))

    source_entities = []
    for row in cursor:
        # Create a short display for source_id (for vault paths, show just the filename)
        source_id = row['source_id'] or ''
        if '/' in source_id:
            source_id_display = source_id.split('/')[-1]
            if len(source_id_display) > 50:
                source_id_display = source_id_display[:47] + '...'
        else:
            source_id_display = source_id[:50] if source_id else ''

        source_entities.append({
            'id': row['id'],
            'source_type': row['source_type'],
            'source_id': source_id,
            'source_id_display': source_id_display,
            'observed_name': row['observed_name'],
            'observed_email': row['observed_email'],
            'observed_phone': row['observed_phone'],
            'link_confidence': row['link_confidence'] or 0.0,
            'link_status': row['link_status'] or 'auto',
            'observed_at': row['observed_at'],
        })

    conn.close()

    # Group by source_type for easier UI display
    by_type = {}
    for se in source_entities:
        st = se['source_type']
        if st not in by_type:
            by_type[st] = []
        by_type[st].append(se)

    return {
        'person_id': person_id,
        'person_name': person.canonical_name,
        'total_count': total_count,
        'returned_count': len(source_entities),
        'offset': offset,
        'limit': limit,
        'has_more': offset + len(source_entities) < total_count,
        'source_entities': source_entities,
        'by_type': by_type,
    }


@router.post("/people/split", response_model=PersonSplitResponse)
async def split_person(request: PersonSplitRequest):
    """
    Split source entities from one person to another.

    This is the reverse of merge - it moves specific source entities
    (and their interactions) from one person to another.

    Use cases:
    - Fix incorrectly merged entities (e.g., two different "Hayley"s)
    - Separate a person into work/personal records

    The operation:
    - Moves specified source entities to the target person
    - Moves related interactions to the target person
    - Optionally creates link override rules to prevent future mis-linking
    - Updates source lists on both persons

    If to_person_id is None, a new person is created with new_person_name.
    """
    import sqlite3
    import uuid
    from pathlib import Path
    from datetime import datetime, timezone

    from api.services.link_override import get_link_override_store, LinkOverride

    person_store = get_person_entity_store()
    source_store = get_source_entity_store()

    # Validate from_person exists
    from_person = person_store.get_by_id(request.from_person_id)
    if not from_person:
        raise HTTPException(status_code=404, detail=f"From person '{request.from_person_id}' not found")

    # Get or create to_person
    if request.to_person_id:
        to_person = person_store.get_by_id(request.to_person_id)
        if not to_person:
            raise HTTPException(status_code=404, detail=f"To person '{request.to_person_id}' not found")
    else:
        if not request.new_person_name:
            raise HTTPException(status_code=400, detail="new_person_name required when to_person_id is not provided")

        to_person = PersonEntity(
            id=str(uuid.uuid4()),
            canonical_name=request.new_person_name,
            sources=[],
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )
        person_store.add(to_person)
        person_store.save()
        logger.info(f"Created new person for split: {to_person.canonical_name} ({to_person.id[:8]})")

    # Get source entity details for override creation
    crm_db = Path(__file__).parent.parent.parent / "data" / "crm.db"
    conn = sqlite3.connect(crm_db)
    conn.row_factory = sqlite3.Row

    placeholders = ','.join('?' * len(request.source_entity_ids))
    cursor = conn.execute(f"""
        SELECT id, source_type, source_id, observed_name, observed_email, observed_phone
        FROM source_entities
        WHERE id IN ({placeholders})
        AND canonical_person_id = ?
    """, request.source_entity_ids + [request.from_person_id])

    source_entity_details = [dict(row) for row in cursor]

    if len(source_entity_details) != len(request.source_entity_ids):
        found_ids = {se['id'] for se in source_entity_details}
        missing = set(request.source_entity_ids) - found_ids
        raise HTTPException(
            status_code=400,
            detail=f"Some source entities not found or not linked to from_person: {missing}"
        )

    # Move source entities
    cursor = conn.execute(f"""
        UPDATE source_entities
        SET canonical_person_id = ?, linked_at = ?, link_status = 'confirmed'
        WHERE id IN ({placeholders})
    """, [to_person.id, datetime.now(timezone.utc).isoformat()] + request.source_entity_ids)
    source_entities_moved = cursor.rowcount
    conn.commit()

    # Move interactions - get source_types from the source entities
    source_types = list({se['source_type'] for se in source_entity_details})
    source_ids = [se['source_id'] for se in source_entity_details if se['source_id']]

    interactions_moved = 0
    if source_ids:
        int_db = Path(__file__).parent.parent.parent / "data" / "interactions.db"
        int_conn = sqlite3.connect(int_db)

        id_placeholders = ','.join('?' * len(source_ids))
        cursor = int_conn.execute(f"""
            UPDATE interactions
            SET person_id = ?
            WHERE person_id = ?
            AND source_id IN ({id_placeholders})
        """, [to_person.id, request.from_person_id] + source_ids)
        interactions_moved = cursor.rowcount
        int_conn.commit()
        int_conn.close()

    # Update source lists on both persons
    cursor = conn.execute("""
        SELECT DISTINCT source_type FROM source_entities
        WHERE canonical_person_id = ?
    """, (from_person.id,))
    from_person.sources = [row[0] for row in cursor]

    cursor = conn.execute("""
        SELECT DISTINCT source_type FROM source_entities
        WHERE canonical_person_id = ?
    """, (to_person.id,))
    to_person.sources = [row[0] for row in cursor]

    # Update phone_numbers and emails based on remaining source entities
    # Get phones/emails that were moved
    moved_phones = {se.get('observed_phone') for se in source_entity_details if se.get('observed_phone')}
    moved_emails = {se.get('observed_email', '').lower() for se in source_entity_details if se.get('observed_email')}

    # Add moved phones/emails to to_person
    for phone in moved_phones:
        if phone and phone not in to_person.phone_numbers:
            to_person.phone_numbers.append(phone)
            if not to_person.phone_primary:
                to_person.phone_primary = phone
    for email in moved_emails:
        if email and not to_person.has_email(email):
            to_person.emails.append(email)

    # Remove phones from from_person that no longer have source entities
    cursor = conn.execute("""
        SELECT DISTINCT observed_phone FROM source_entities
        WHERE canonical_person_id = ? AND observed_phone IS NOT NULL
    """, (from_person.id,))
    remaining_phones = {row[0] for row in cursor}
    from_person.phone_numbers = [p for p in from_person.phone_numbers if p in remaining_phones]
    if from_person.phone_primary and from_person.phone_primary not in remaining_phones:
        from_person.phone_primary = from_person.phone_numbers[0] if from_person.phone_numbers else None

    # Remove emails from from_person that no longer have source entities
    cursor = conn.execute("""
        SELECT DISTINCT LOWER(observed_email) FROM source_entities
        WHERE canonical_person_id = ? AND observed_email IS NOT NULL
    """, (from_person.id,))
    remaining_emails = {row[0] for row in cursor}
    from_person.emails = [e for e in from_person.emails if e.lower() in remaining_emails]

    person_store.update(from_person)
    person_store.update(to_person)
    person_store.save()

    conn.close()

    # Create link overrides for durability
    overrides_created = 0
    if request.create_overrides:
        override_store = get_link_override_store()

        # Group by name pattern + source_type
        patterns = {}
        for se in source_entity_details:
            name = se.get('observed_name', '')
            source_type = se.get('source_type', '')
            source_id = se.get('source_id', '')

            if not name:
                continue

            key = (name.lower(), source_type)
            if key not in patterns:
                patterns[key] = {'name': name, 'source_type': source_type, 'contexts': set()}

            # Extract context patterns from source_id
            if source_type in ('vault', 'granola') and source_id:
                if 'Work/ML' in source_id:
                    patterns[key]['contexts'].add('Work/ML/')
                elif 'Work/' in source_id:
                    patterns[key]['contexts'].add('Work/')

        for (name_lower, source_type), pattern in patterns.items():
            if pattern['contexts']:
                for context in pattern['contexts']:
                    override = LinkOverride(
                        id=str(uuid.uuid4()),
                        name_pattern=pattern['name'],
                        source_type=source_type,
                        context_pattern=context,
                        preferred_person_id=to_person.id,
                        rejected_person_id=from_person.id,
                        reason=f"Split via UI from {from_person.canonical_name}",
                    )
                    override_store.add(override)
                    overrides_created += 1
            else:
                override = LinkOverride(
                    id=str(uuid.uuid4()),
                    name_pattern=pattern['name'],
                    source_type=source_type,
                    context_pattern=None,
                    preferred_person_id=to_person.id,
                    rejected_person_id=from_person.id,
                    reason=f"Split via UI from {from_person.canonical_name}",
                )
                override_store.add(override)
                overrides_created += 1

    # Recalculate stats and relationships for both persons
    # (Consistent with merge behavior - recalculate after moving data)
    logger.info("Recalculating stats and relationships...")

    int_db = Path(__file__).parent.parent.parent / "data" / "interactions.db"
    int_conn_stats = sqlite3.connect(int_db)

    # Recalculate stats for both persons
    from_stats = _recalculate_person_stats(from_person.id, int_conn_stats, person_store)
    to_stats = _recalculate_person_stats(to_person.id, int_conn_stats, person_store)

    if from_stats:
        logger.info(f"  {from_person.canonical_name} stats: {from_stats['old']} -> {from_stats['new']}")
    if to_stats:
        logger.info(f"  {to_person.canonical_name} stats: {to_stats['old']} -> {to_stats['new']}")

    # Recalculate relationships with my_person_id
    my_person_id = settings.my_person_id
    if my_person_id:
        from_rel = _recalculate_relationship_with_me(from_person.id, my_person_id, int_conn_stats)
        to_rel = _recalculate_relationship_with_me(to_person.id, my_person_id, int_conn_stats)

        if from_rel.get('action') != 'none':
            logger.info(f"  {from_person.canonical_name} relationship: {from_rel}")
        if to_rel.get('action') != 'none':
            logger.info(f"  {to_person.canonical_name} relationship: {to_rel}")

    int_conn_stats.close()

    # Recalculate relationship strength for both persons
    from api.services.relationship_metrics import compute_strength_for_person

    from_person_refreshed = person_store.get_by_id(from_person.id)
    to_person_refreshed = person_store.get_by_id(to_person.id)

    if from_person_refreshed:
        new_strength = compute_strength_for_person(from_person_refreshed)
        if new_strength != from_person_refreshed._relationship_strength:
            from_person_refreshed._relationship_strength = new_strength
            person_store.update(from_person_refreshed)
            logger.info(f"  {from_person.canonical_name} strength: {new_strength}")

    if to_person_refreshed:
        new_strength = compute_strength_for_person(to_person_refreshed)
        if new_strength != to_person_refreshed._relationship_strength:
            to_person_refreshed._relationship_strength = new_strength
            person_store.update(to_person_refreshed)
            logger.info(f"  {to_person.canonical_name} strength: {new_strength}")

    person_store.save()

    logger.info(
        f"Split {source_entities_moved} source entities from {from_person.canonical_name} "
        f"to {to_person.canonical_name}, {interactions_moved} interactions, "
        f"{overrides_created} overrides created"
    )

    return PersonSplitResponse(
        status="completed",
        from_person_id=request.from_person_id,
        to_person_id=to_person.id,
        source_entities_moved=source_entities_moved,
        interactions_moved=interactions_moved,
        overrides_created=overrides_created,
    )


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
    date: Optional[str] = Query(default=None, description="Filter to specific date (YYYY-MM-DD)"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    limit: int = Query(default=50, ge=1, le=2000, description="Max results"),
):
    """
    Get chronological interaction history for a person.

    Returns emails, meetings, notes, and other interactions in timeline format.
    """
    start_time = time.time()

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
        specific_date=date,
    )

    has_more = len(interactions) > offset + limit
    interactions = interactions[offset:offset + limit]

    elapsed = (time.time() - start_time) * 1000
    logger.info(f"timeline({person_id}) took {elapsed:.1f}ms ({len(interactions)} interactions, {days_back} days)")

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
        default=90,  # Default to 90 days for faster initial load
        ge=1,
        le=InteractionConfig.MAX_WINDOW_DAYS,
        description="Days to look back (default 90, max 3650)"
    ),
    include_items: bool = Query(default=False, description="Include individual items in each group"),
    max_items_per_group: int = Query(default=10, ge=1, le=50, description="Max items per group when include_items=True"),
):
    """
    Get aggregated interaction history for a person, grouped by day and source type.

    Returns interactions aggregated by day, with counts and previews.
    Use include_items=True to get individual interactions within each group.

    Performance notes:
    - Default days_back=90 for fast initial load (~100ms)
    - Use days_back=365 for full year view (may take 500ms+)
    - include_items=False is faster for initial rendering

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
    start_time = time.time()

    person_store = get_person_entity_store()
    person = person_store.get_by_id(person_id)

    if not person:
        raise HTTPException(status_code=404, detail=f"Person '{person_id}' not found")

    interaction_store = get_interaction_store()

    # Fetch interactions within the time range
    # Use high limit for aggregation - need to support heavy users like Taylor (60k+ interactions)
    # TODO: Optimize by doing aggregation in SQL instead of fetching all to Python
    interactions = interaction_store.get_for_person(
        person_id,
        days_back=days_back,
        limit=100000,  # High limit for aggregation
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

    elapsed = (time.time() - start_time) * 1000
    logger.info(f"timeline_aggregated({person_id}) took {elapsed:.1f}ms ({len(interactions)} interactions, {days_back} days)")

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
    start_time = time.time()

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
            shared_events_count=rel.shared_events_count or 0,
            shared_threads_count=rel.shared_threads_count or 0,
            shared_messages_count=rel.shared_messages_count or 0,
            shared_whatsapp_count=rel.shared_whatsapp_count or 0,
            shared_slack_count=rel.shared_slack_count or 0,
            shared_phone_calls_count=rel.shared_phone_calls_count or 0,
            shared_contexts=rel.shared_contexts,
            relationship_strength=other.relationship_strength,
            last_seen_together=rel.last_seen_together.isoformat() if rel.last_seen_together else None,
        ))

    # Sort by total shared interactions (all sources)
    connections.sort(
        key=lambda c: (
            c.shared_events_count +
            c.shared_threads_count +
            c.shared_messages_count +
            c.shared_whatsapp_count +
            c.shared_slack_count +
            c.shared_phone_calls_count
        ),
        reverse=True
    )

    elapsed = (time.time() - start_time) * 1000
    logger.info(f"connections({person_id}) took {elapsed:.1f}ms ({len(connections)} connections)")

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
        source_quote=fact.source_quote,
        source_link=fact.source_link,
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
    start_time = time.time()

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

    elapsed = (time.time() - start_time) * 1000
    logger.info(f"facts({person_id}) took {elapsed:.1f}ms ({len(fact_responses)} facts)")

    return PersonFactsResponse(
        facts=fact_responses,
        count=len(fact_responses),
        by_category=by_category,
    )


@router.post("/people/{person_id}/facts/extract", response_model=FactExtractionResponse)
async def extract_person_facts(person_id: str, model: Optional[str] = None):
    """
    Trigger fact extraction for a person.

    Analyzes ALL interactions using strategic sampling and extracts
    structured facts using LLM with strict evidence requirements.

    Args:
        person_id: The person's ID
        model: Claude model to use. Options:
            - "sonnet" or "claude-sonnet-4-5" (more accurate, ~$0.15/person)
            - "haiku" or "claude-haiku-4-5" (faster/cheaper, ~$0.01/person, default)

    For contacts with many interactions (e.g., 49K), the extractor
    strategically samples based on source type distribution.
    """
    # Translate simple model names to full names
    from api.services.person_facts import PersonFactExtractor
    if model == "sonnet":
        model = PersonFactExtractor.MODEL_SONNET
    elif model == "haiku":
        model = PersonFactExtractor.MODEL_HAIKU
    person_store = get_person_entity_store()
    person = person_store.get_by_id(person_id)

    if not person:
        raise HTTPException(status_code=404, detail=f"Person '{person_id}' not found")

    # Get ALL interactions for the person (extractor will sample strategically)
    interaction_store = get_interaction_store()
    interactions = interaction_store.get_for_person(
        person_id,
        days_back=3650,  # Look back 10 years for full history
        limit=100000,  # No practical limit - let extractor sample
    )

    if not interactions:
        return FactExtractionResponse(
            status="no_interactions",
            extracted_count=0,
            facts=[],
        )

    # Convert to dict format expected by extractor (include source_link)
    interaction_dicts = [
        {
            "id": i.id,
            "source_type": i.source_type,
            "title": i.title,
            "snippet": i.snippet,
            "timestamp": i.timestamp.isoformat() if i.timestamp else "",
            "source_link": i.source_link,
        }
        for i in interactions
    ]

    # Extract facts (use async version for proper event loop handling)
    try:
        extractor = get_person_fact_extractor()
        extracted_facts = await extractor.extract_facts_async(
            person_id=person_id,
            person_name=person.canonical_name,
            interactions=interaction_dicts,
            model=model,
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


@router.post("/people/{person_id}/hide")
async def hide_person(person_id: str, request: HidePersonRequest):
    """
    Hide a person (soft delete) and blocklist their identifiers.

    This marks the person as hidden and adds all their emails/phones to
    a blocklist to prevent sync from recreating them. Use this for:
    - Fake marketing personas from store emails
    - Spam/bot accounts
    - Duplicate people that shouldn't exist

    The person is not deleted, just hidden. Hidden people won't appear
    in search results or the people list.
    """
    person_store = get_person_entity_store()
    person = person_store.get_by_id(person_id)

    if not person:
        raise HTTPException(status_code=404, detail=f"Person '{person_id}' not found")

    # Check if already hidden
    if person.hidden:
        return {
            "status": "already_hidden",
            "person_id": person_id,
            "hidden_at": person.hidden_at.isoformat() if person.hidden_at else None,
        }

    # Hide the person
    hidden = person_store.hide_person(person_id, request.reason)

    return {
        "status": "hidden",
        "person_id": person_id,
        "name": hidden.canonical_name,
        "emails_blocked": len(hidden.emails),
        "phones_blocked": len(hidden.phone_numbers),
        "reason": request.reason,
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
    start_time = time.time()

    if person_id:
        suggestions = get_suggested_connections(person_id, limit=limit)

        elapsed = (time.time() - start_time) * 1000
        logger.info(f"discover({person_id}) took {elapsed:.1f}ms ({len(suggestions)} suggestions)")

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

        # Get all people with relationships in one query (avoid N+1)
        people_with_rels = rel_store.get_people_with_relationships()

        # Score by source diversity / relationship count
        scored = []
        for person in people:
            has_relationships = person.id in people_with_rels
            source_count = len(person.sources)
            if source_count > 1 and not has_relationships:
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

        elapsed = (time.time() - start_time) * 1000
        logger.info(f"discover() took {elapsed:.1f}ms ({len(scored)} suggestions)")

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
    Automatically recalculates relationship strengths after discovery.
    """
    results = run_full_discovery()

    # Automatically recalculate relationship strengths after discovery
    strength_results = update_all_strengths()
    results["strengths_updated"] = strength_results.get("updated", 0)

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
    start_time = time.time()

    person_store = get_person_entity_store()
    source_store = get_source_entity_store()
    rel_store = get_relationship_store()

    person_stats = person_store.get_statistics()
    source_stats = source_store.get_statistics()
    rel_stats = rel_store.get_statistics()

    elapsed = (time.time() - start_time) * 1000
    logger.info(f"statistics() took {elapsed:.1f}ms")

    return StatisticsResponse(
        total_people=person_stats.get("total_entities", 0),
        by_category=person_stats.get("by_category", {}),
        by_source=person_stats.get("by_source", {}),
        total_source_entities=source_stats.get("total_entities", 0),
        linked_entities=source_stats.get("linked_entities", 0),
        unlinked_entities=source_stats.get("unlinked_entities", 0),
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

    Each node includes a 'degree' field:
    - 0 = center person
    - 1 = first-degree connection (direct connection to center)
    - 2 = second-degree connection (connection of connection)
    - etc.
    """
    start_time = time.time()
    person_store = get_person_entity_store()
    rel_store = get_relationship_store()

    # Build the graph
    nodes: list[NetworkNode] = []
    edges: list[NetworkEdge] = []
    # Map person_id -> degree (distance from center)
    node_degrees: dict[str, int] = {}

    if center_on:
        # BFS to find people within depth hops of center, tracking degree
        center_person = person_store.get_by_id(center_on)
        if not center_person:
            raise HTTPException(status_code=404, detail=f"Person '{center_on}' not found")

        # Get the CRM owner's ID - exclude from 2nd+ degree traversal
        # since they're connected to everyone and would pollute the graph
        my_person_id = settings.my_person_id
        is_viewing_self = (center_on == my_person_id)

        # BFS traversal with degree tracking - use batch queries
        node_degrees[center_on] = 0  # Center is degree 0
        current_level: set[str] = {center_on}

        for current_depth in range(1, depth + 1):
            if not current_level:
                break
            # Batch query for all people at this level
            level_relationships = rel_store.get_for_people_batch(current_level)
            next_level: set[str] = set()
            for person_id in current_level:
                # Skip "me" as a bridge for 2nd+ degree when not viewing self
                # This prevents everyone appearing as 2nd-degree through me
                if not is_viewing_self and current_depth > 1 and person_id == my_person_id:
                    continue
                for rel in level_relationships.get(person_id, []):
                    other_id = rel.other_person(person_id)
                    if other_id and other_id not in node_degrees:
                        next_level.add(other_id)
                        node_degrees[other_id] = current_depth
            current_level = next_level
    else:
        # Get all people (no center, all are degree 1)
        all_people = person_store.get_all()
        node_degrees = {p.id: 1 for p in all_people}

    # Get all people in one pass (avoid N+1 lookups)
    all_people_dict = {p.id: p for p in person_store.get_all()}

    # Filter by category and strength, then build nodes
    for person_id, degree in node_degrees.items():
        person = all_people_dict.get(person_id)
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
            category=compute_person_category(person, []),
            strength=person.relationship_strength,
            interaction_count=interaction_count,
            degree=degree,
        ))

    # Build a set of valid node IDs after filtering
    valid_node_ids = {n.id for n in nodes}

    # Get all edges in one query instead of per-node queries
    all_relationships = rel_store.get_all_relationships()
    seen_edges: set[tuple[str, str]] = set()

    for rel in all_relationships:
        # Both people must be in valid nodes
        if rel.person_a_id not in valid_node_ids or rel.person_b_id not in valid_node_ids:
            continue

        # Create consistent edge key (smaller ID first)
        edge_key = (min(rel.person_a_id, rel.person_b_id), max(rel.person_a_id, rel.person_b_id))
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)

        edges.append(NetworkEdge(
            source=rel.person_a_id,
            target=rel.person_b_id,
            weight=rel.edge_weight,
            type=rel.relationship_type,
            shared_events_count=rel.shared_events_count or 0,
            shared_threads_count=rel.shared_threads_count or 0,
            shared_messages_count=rel.shared_messages_count or 0,
            shared_whatsapp_count=rel.shared_whatsapp_count or 0,
            shared_slack_count=rel.shared_slack_count or 0,
            shared_phone_calls_count=rel.shared_phone_calls_count or 0,
            is_linkedin_connection=rel.is_linkedin_connection,
        ))

    elapsed = (time.time() - start_time) * 1000
    logger.info(f"network_graph(center={center_on}, depth={depth}) took {elapsed:.1f}ms ({len(nodes)} nodes, {len(edges)} edges)")

    return NetworkGraphResponse(nodes=nodes, edges=edges)


class RelationshipDetailResponse(BaseModel):
    """Response model for relationship details between two people."""
    person_a_id: str
    person_a_name: str
    person_b_id: str
    person_b_name: str
    relationship_type: str
    shared_contexts: list[str] = []
    # Multi-source breakdown
    shared_events_count: int = 0      # Calendar events
    shared_threads_count: int = 0     # Email threads
    shared_messages_count: int = 0    # iMessage/SMS
    shared_whatsapp_count: int = 0    # WhatsApp
    shared_slack_count: int = 0       # Slack DMs
    shared_phone_calls_count: int = 0  # Phone calls
    is_linkedin_connection: bool = False
    # Computed totals
    total_interactions: int = 0
    first_seen_together: Optional[str] = None
    last_seen_together: Optional[str] = None
    weight: int = 0  # Same as network edge weight


@router.get("/relationship/{person_a_id}/{person_b_id}", response_model=RelationshipDetailResponse)
async def get_relationship_details(person_a_id: str, person_b_id: str):
    """
    Get detailed information about the relationship between two people.

    Returns shared contexts, interaction counts, and timing information.
    """
    try:
        relationship_store = get_relationship_store()
        person_store = get_person_entity_store()

        # Get relationship
        rel = relationship_store.get_between(person_a_id, person_b_id)

        # Get person names
        person_a = person_store.get_by_id(person_a_id)
        person_b = person_store.get_by_id(person_b_id)

        if not person_a or not person_b:
            raise HTTPException(status_code=404, detail="One or both people not found")

        # If no relationship exists, return empty/default values
        if not rel:
            return RelationshipDetailResponse(
                person_a_id=person_a_id,
                person_a_name=person_a.canonical_name,
                person_b_id=person_b_id,
                person_b_name=person_b.canonical_name,
                relationship_type="none",
                shared_contexts=[],
                shared_events_count=0,
                shared_threads_count=0,
                shared_messages_count=0,
                shared_whatsapp_count=0,
                shared_slack_count=0,
                shared_phone_calls_count=0,
                is_linkedin_connection=False,
                total_interactions=0,
                first_seen_together=None,
                last_seen_together=None,
                weight=0,
            )

        # Map names correctly based on normalized IDs
        name_map = {person_a_id: person_a.canonical_name, person_b_id: person_b.canonical_name}

        return RelationshipDetailResponse(
            person_a_id=rel.person_a_id,
            person_a_name=name_map.get(rel.person_a_id, "Unknown"),
            person_b_id=rel.person_b_id,
            person_b_name=name_map.get(rel.person_b_id, "Unknown"),
            relationship_type=rel.relationship_type or "inferred",
            shared_contexts=rel.shared_contexts or [],
            shared_events_count=rel.shared_events_count or 0,
            shared_threads_count=rel.shared_threads_count or 0,
            shared_messages_count=rel.shared_messages_count or 0,
            shared_whatsapp_count=rel.shared_whatsapp_count or 0,
            shared_slack_count=rel.shared_slack_count or 0,
            shared_phone_calls_count=rel.shared_phone_calls_count or 0,
            is_linkedin_connection=rel.is_linkedin_connection,
            total_interactions=rel.total_shared_interactions or 0,
            first_seen_together=rel.first_seen_together.isoformat() if rel.first_seen_together else None,
            last_seen_together=rel.last_seen_together.isoformat() if rel.last_seen_together else None,
            weight=rel.edge_weight,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error in get_relationship_details: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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


# =============================
# "Me" Page Routes
# =============================


class MeStatsResponse(BaseModel):
    """Aggregate statistics for the owner's dashboard."""
    total_people: int
    total_emails: int
    total_meetings: int
    total_messages: int


class DailyAggregate(BaseModel):
    """Aggregated interactions for a single day."""
    date: str
    total: int
    sources: dict[str, int]


class TopContact(BaseModel):
    """A top contact with interaction count."""
    person_id: str
    person_name: str
    count: int


class TrendPerson(BaseModel):
    """Person with trend data (recent vs previous period)."""
    person_id: str
    person_name: str
    recent_count: int
    previous_count: int


class NeglectedContact(BaseModel):
    """A contact that hasn't been reached out to recently."""
    person_id: str
    person_name: str
    days_since_contact: int
    typical_gap_days: int  # How often you normally contact them
    dunbar_circle: int


class MonthlyNetworkGrowth(BaseModel):
    """Network growth for a single month."""
    month: str  # "YYYY-MM"
    new_people: int
    cumulative_total: int


class MonthlyMessagingVolume(BaseModel):
    """Messaging volume by Dunbar circle for a single month."""
    month: str  # "YYYY-MM"
    total: int
    by_circle: dict[str, int]  # circle "0"-"4" -> count
    circle_percentages: dict[str, float]  # circle -> % of total


class HealthScorePoint(BaseModel):
    """Health score at a point in time."""
    date: str  # "YYYY-MM-DD"
    score: int  # 0-100


class MeInteractionsResponse(BaseModel):
    """Aggregated interaction data for the owner's dashboard."""
    # Daily aggregates for heatmap (date -> {total, sources})
    daily: list[DailyAggregate]
    # Breakdown totals
    by_source: dict[str, int]
    by_month: dict[str, int]  # "YYYY-MM" -> count
    by_circle: dict[str, int]  # circle number as string -> count
    # Top contacts (last 30 days)
    top_contacts: list[TopContact]
    # Relationship trends (2-week comparison)
    warming: list[TrendPerson]
    cooling: list[TrendPerson]
    total_count: int
    # New widgets
    relationship_health_score: int = 0  # 0-100
    health_score_history: list[HealthScorePoint] = []  # Longitudinal health scores
    neglected_contacts: list[NeglectedContact] = []
    network_growth: list[MonthlyNetworkGrowth] = []
    messaging_by_circle: list[MonthlyMessagingVolume] = []


@router.get("/me/stats", response_model=MeStatsResponse)
async def get_me_stats():
    """
    Get aggregate statistics for the owner's personal dashboard.

    Returns total counts across all people in the CRM.
    """
    person_store = get_person_entity_store()
    interaction_store = get_interaction_store()

    # Get all people
    all_people = person_store.get_all()
    total_people = len(all_people)

    # Aggregate stats from all people
    total_emails = sum(p.email_count for p in all_people)
    total_meetings = sum(p.meeting_count for p in all_people)
    total_messages = sum(p.message_count for p in all_people)

    return MeStatsResponse(
        total_people=total_people,
        total_emails=total_emails,
        total_meetings=total_meetings,
        total_messages=total_messages,
    )


@router.get("/me/interactions", response_model=MeInteractionsResponse)
async def get_me_interactions(
    days_back: int = Query(default=365, ge=1, le=1095, description="Days of history (up to 3 years)"),
    trend_period: str = Query(default="quarter", description="Trend comparison period: week, month, quarter, year"),
    health_period: str = Query(default="quarter", description="Health score history period: month, quarter, year"),
):
    """
    Get aggregated interaction data for the "Me" dashboard.

    Returns pre-aggregated data for heatmaps, charts, and trends.
    """
    from datetime import timedelta
    from collections import defaultdict

    interaction_store = get_interaction_store()
    person_store = get_person_entity_store()

    # Calculate date range
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days_back)

    # Build person lookup for names (excludes hidden people by default)
    person_lookup = {p.id: p for p in person_store.get_all()}

    # Get hidden person IDs to exclude from metrics
    hidden_person_ids = {
        p.id for p in person_store.get_all(include_hidden=True) if p.hidden
    }

    # Get all interactions in date range, excluding self and hidden people
    all_interactions_raw = interaction_store.get_all_in_range(
        start_date=start_date,
        end_date=end_date,
        exclude_person_ids=[MY_PERSON_ID] + list(hidden_person_ids),
    )

    # Filter to only include interactions with known (non-orphaned) person IDs
    all_interactions = [
        i for i in all_interactions_raw
        if i.person_id in person_lookup
    ]

    # Pre-compute Dunbar circles (simplified - by relationship strength ranking)
    sorted_people = sorted(
        person_store.get_all(),
        key=lambda p: p.relationship_strength or 0,
        reverse=True
    )
    circle_map = {}
    circle_sizes = [3, 5, 15, 50, 150, 500, 1500]  # Cumulative thresholds
    cumulative = 0
    current_circle = 0
    for i, person in enumerate(sorted_people):
        if person.id == MY_PERSON_ID:
            circle_map[person.id] = -1  # Self
            continue
        if current_circle < len(circle_sizes) and i >= circle_sizes[current_circle] + cumulative:
            cumulative = circle_sizes[current_circle]
            current_circle += 1
        circle_map[person.id] = current_circle

    # Aggregation structures
    daily_data = defaultdict(lambda: {"total": 0, "sources": defaultdict(int)})
    by_source = defaultdict(int)
    by_month = defaultdict(int)
    by_circle = defaultdict(int)
    person_counts_30d = defaultdict(int)
    person_counts_recent = defaultdict(int)
    person_counts_previous = defaultdict(int)

    # Date boundaries for trends based on period
    now = datetime.now(timezone.utc)
    period_days = {
        "week": 7,
        "month": 30,
        "quarter": 90,
        "year": 365,
    }
    trend_days = period_days.get(trend_period, 90)
    trend_recent_start = now - timedelta(days=trend_days)
    trend_previous_start = now - timedelta(days=trend_days * 2)
    thirty_days_ago = now - timedelta(days=30)

    total_count = 0

    for interaction in all_interactions:
        # Get date string
        if interaction.timestamp:
            if hasattr(interaction.timestamp, 'strftime'):
                ts = interaction.timestamp
                # Ensure timezone-aware for comparisons
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                date_str = ts.strftime('%Y-%m-%d')
                month_str = ts.strftime('%Y-%m')
            else:
                date_str = str(interaction.timestamp)[:10]
                month_str = date_str[:7]
                ts = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        else:
            continue

        source = (interaction.source_type or "unknown").lower()
        person_id = interaction.person_id
        circle = circle_map.get(person_id, 7)

        # Daily aggregates (exclude email from totals for heatmap)
        if source != 'gmail':
            daily_data[date_str]["total"] += 1
        daily_data[date_str]["sources"][source] += 1

        # Breakdown totals
        by_source[source] += 1
        by_month[month_str] += 1
        by_circle[str(circle)] += 1

        # Top contacts (last 30 days)
        if ts >= thirty_days_ago:
            person_counts_30d[person_id] += 1

        # Trend data (period-based comparison)
        if ts >= trend_recent_start:
            person_counts_recent[person_id] += 1
        elif ts >= trend_previous_start:
            person_counts_previous[person_id] += 1

        total_count += 1

    # Build daily aggregates list
    daily_list = [
        DailyAggregate(date=date, total=data["total"], sources=dict(data["sources"]))
        for date, data in sorted(daily_data.items())
    ]

    # Build top contacts (top 10 by count in last 30 days)
    top_contacts = []
    for person_id, count in sorted(person_counts_30d.items(), key=lambda x: -x[1])[:10]:
        person = person_lookup.get(person_id)
        top_contacts.append(TopContact(
            person_id=person_id,
            person_name=person.canonical_name if person else "Unknown",
            count=count,
        ))

    # Build trend data (warming and cooling)
    warming = []
    cooling = []
    all_person_ids = set(person_counts_recent.keys()) | set(person_counts_previous.keys())
    for person_id in all_person_ids:
        recent = person_counts_recent.get(person_id, 0)
        prev = person_counts_previous.get(person_id, 0)
        if recent == prev:
            continue
        person = person_lookup.get(person_id)
        trend_person = TrendPerson(
            person_id=person_id,
            person_name=person.canonical_name if person else "Unknown",
            recent_count=recent,
            previous_count=prev,
        )
        if recent > prev:
            warming.append(trend_person)
        else:
            cooling.append(trend_person)

    # Sort by magnitude of change
    warming.sort(key=lambda x: x.recent_count - x.previous_count, reverse=True)
    cooling.sort(key=lambda x: x.previous_count - x.recent_count, reverse=True)

    # ===== NEW WIDGETS =====

    # 1. Relationship Health Score (0-100)
    # Based on: recency of contacts, frequency, weighted by circle
    health_score = 0
    if person_lookup:
        score_components = []
        for person in person_lookup.values():
            if person.id == MY_PERSON_ID:
                continue
            circle = circle_map.get(person.id, 7)
            if circle > 4:  # Only count circles 0-4 for health
                continue
            # Weight by circle (closer = more important)
            circle_weight = {0: 5, 1: 4, 2: 3, 3: 2, 4: 1}.get(circle, 0)
            if circle_weight == 0:
                continue
            # Recency score (100 if contacted today, decays over 90 days)
            last_seen = person.last_seen
            if last_seen:
                if last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                days_ago = (now - last_seen).days
                recency_score = max(0, 100 - (days_ago * 100 / 90))
            else:
                recency_score = 0
            score_components.append(recency_score * circle_weight)
        if score_components:
            # Weighted average
            total_weight = sum({0: 5, 1: 4, 2: 3, 3: 2, 4: 1}.get(circle_map.get(p.id, 7), 0)
                              for p in person_lookup.values()
                              if p.id != MY_PERSON_ID and circle_map.get(p.id, 7) <= 4)
            if total_weight > 0:
                health_score = int(sum(score_components) / total_weight)

    # 2. Neglected Contacts
    # People in circles 0-3 who haven't been contacted in longer than their typical gap
    neglected = []
    person_interaction_dates = defaultdict(list)
    for interaction in all_interactions:
        if interaction.timestamp:
            ts = interaction.timestamp
            if hasattr(ts, 'tzinfo') and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            elif not hasattr(ts, 'tzinfo'):
                ts = datetime.fromisoformat(str(ts)[:10]).replace(tzinfo=timezone.utc)
            person_interaction_dates[interaction.person_id].append(ts)

    for person_id, dates in person_interaction_dates.items():
        person = person_lookup.get(person_id)
        if not person:
            continue
        circle = circle_map.get(person_id, 7)
        if circle > 3:  # Only alert for circles 0-3
            continue
        if len(dates) < 5:  # Need meaningful history to establish pattern
            continue
        dates_sorted = sorted(dates)
        # Calculate typical gap (median of gaps, excluding outliers)
        gaps = [(dates_sorted[i+1] - dates_sorted[i]).days for i in range(len(dates_sorted)-1)]
        if not gaps:
            continue
        # Use median of gaps
        gaps_sorted = sorted(gaps)
        typical_gap = gaps_sorted[len(gaps_sorted)//2]
        # Minimum based on circle - closer relationships have lower thresholds
        min_gap = {0: 3, 1: 5, 2: 7, 3: 14}.get(circle, 14)
        if typical_gap < min_gap:
            typical_gap = min_gap
        # Days since last contact
        last_contact = dates_sorted[-1]
        days_since = (now - last_contact).days
        # Alert if 1.5x typical gap has passed (was 2x, now more sensitive)
        if days_since > typical_gap * 1.5:
            neglected.append(NeglectedContact(
                person_id=person_id,
                person_name=person.canonical_name,
                days_since_contact=days_since,
                typical_gap_days=typical_gap,
                dunbar_circle=circle,
            ))
    # Sort by circle (closer first), then by how overdue they are
    neglected.sort(key=lambda x: (x.dunbar_circle, -(x.days_since_contact / x.typical_gap_days)))

    # 2b. Health Score History (longitudinal)
    # Calculate health score at different points in time
    health_score_history = []

    # Determine time points based on health_period
    # Each period shows exactly 2x that period (2 months, 2 quarters, 2 years)
    if health_period == "month":
        # 2 months back, weekly intervals (9 points: 0, 1, 2, ..., 8 weeks)
        total_days = 61  # ~2 months
        num_points = 9
        time_points = [now - timedelta(days=int(i * total_days / (num_points - 1))) for i in range(num_points)]
    elif health_period == "year":
        # 2 years back, bi-monthly intervals (13 points)
        total_days = 730  # 2 years
        num_points = 13
        time_points = [now - timedelta(days=int(i * total_days / (num_points - 1))) for i in range(num_points)]
    else:  # quarter (default)
        # 6 months back (2 quarters), bi-weekly intervals (13 points)
        total_days = 183  # ~6 months
        num_points = 13
        time_points = [now - timedelta(days=int(i * total_days / (num_points - 1))) for i in range(num_points)]

    time_points = sorted(time_points)  # oldest first

    # Pre-calculate total weight (doesn't change over time)
    total_weight = sum(
        {0: 5, 1: 4, 2: 3, 3: 2, 4: 1}.get(circle_map.get(p.id, 7), 0)
        for p in person_lookup.values()
        if p.id != MY_PERSON_ID and circle_map.get(p.id, 7) <= 4
    )

    for point_date in time_points:
        score_components = []
        for person in person_lookup.values():
            if person.id == MY_PERSON_ID:
                continue
            circle = circle_map.get(person.id, 7)
            if circle > 4:
                continue
            circle_weight = {0: 5, 1: 4, 2: 3, 3: 2, 4: 1}.get(circle, 0)
            if circle_weight == 0:
                continue

            # Find most recent interaction before point_date
            person_dates = person_interaction_dates.get(person.id, [])
            dates_before = [d for d in person_dates if d <= point_date]
            if dates_before:
                last_contact = max(dates_before)
                days_ago = (point_date - last_contact).days
                recency_score = max(0, 100 - (days_ago * 100 / 90))
            else:
                recency_score = 0
            score_components.append(recency_score * circle_weight)

        if total_weight > 0 and score_components:
            point_score = int(sum(score_components) / total_weight)
        else:
            point_score = 0

        health_score_history.append(HealthScorePoint(
            date=point_date.strftime('%Y-%m-%d'),
            score=point_score,
        ))

    # 3. Network Growth Timeline
    # Use FIRST INTERACTION date across ALL time (not limited by days_back query)
    # Require at least 3 interactions to filter out one-off contacts (spam, single emails)
    first_interaction_dates = interaction_store.get_first_interaction_dates(min_interactions=3)
    monthly_new_people = defaultdict(int)
    for person_id, first_dt in first_interaction_dates.items():
        if person_id == MY_PERSON_ID:
            continue
        if person_id in hidden_person_ids:
            continue
        if person_id not in person_lookup:
            continue  # Skip orphaned person IDs
        month_key = first_dt.strftime('%Y-%m')
        monthly_new_people[month_key] += 1

    # Build growth list (based on days_back)
    network_growth = []
    cumulative = 0
    # Get all months and sort
    all_months = sorted(monthly_new_people.keys())
    # For cumulative, need to count all people before the chart window too
    # Use days_back to determine the cutoff for charts (network growth, messaging)
    chart_months_cutoff = (now - timedelta(days=days_back)).strftime('%Y-%m')
    for month in all_months:
        cumulative += monthly_new_people[month]
        if month >= chart_months_cutoff:
            network_growth.append(MonthlyNetworkGrowth(
                month=month,
                new_people=monthly_new_people[month],
                cumulative_total=cumulative,
            ))

    # 4. Messaging Volume by Circle (iMessage + WhatsApp only)
    # Group by month, then by circle
    monthly_messaging = defaultdict(lambda: {"total": 0, "by_circle": defaultdict(int)})
    for interaction in all_interactions:
        source = (interaction.source_type or "").lower()
        if source not in ('imessage', 'whatsapp'):
            continue
        if interaction.timestamp:
            ts = interaction.timestamp
            if hasattr(ts, 'strftime'):
                month_key = ts.strftime('%Y-%m')
            else:
                month_key = str(ts)[:7]
        else:
            continue
        person_id = interaction.person_id
        circle = circle_map.get(person_id, 7)
        if circle > 4:  # Only track circles 0-4
            circle = 5  # Group 5+ as "outer"
        monthly_messaging[month_key]["total"] += 1
        monthly_messaging[month_key]["by_circle"][str(circle)] += 1

    # Build messaging list (based on days_back)
    messaging_by_circle = []
    for month in sorted(monthly_messaging.keys()):
        if month >= chart_months_cutoff:
            data = monthly_messaging[month]
            total = data["total"]
            by_circle = dict(data["by_circle"])
            # Calculate percentages
            percentages = {}
            for c, count in by_circle.items():
                percentages[c] = round(count / total * 100, 1) if total > 0 else 0
            messaging_by_circle.append(MonthlyMessagingVolume(
                month=month,
                total=total,
                by_circle=by_circle,
                circle_percentages=percentages,
            ))

    return MeInteractionsResponse(
        daily=daily_list,
        by_source=dict(by_source),
        by_month=dict(by_month),
        by_circle=dict(by_circle),
        top_contacts=top_contacts[:10],
        warming=warming[:10],
        cooling=cooling[:10],
        total_count=total_count,
        relationship_health_score=health_score,
        health_score_history=health_score_history,
        neglected_contacts=neglected[:10],
        network_growth=network_growth,
        messaging_by_circle=messaging_by_circle,
    )


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
    start_time = time.time()

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

    elapsed = (time.time() - start_time) * 1000
    logger.info(f"review_queue() took {elapsed:.1f}ms ({len(items)} items)")

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


# ============================================================================
# Data Health Endpoints
# ============================================================================


@router.get("/data-health")
async def get_data_health():
    """
    Get comprehensive data health statistics.

    Returns metrics on data coverage, sync status, and relationship discovery.
    """
    import sqlite3
    from pathlib import Path

    data_dir = Path(__file__).parent.parent.parent / "data"

    result = {
        "sources": {},
        "relationships": {},
        "people": {},
        "sync_recommendations": [],
    }

    # Interaction stats by source
    int_db = data_dir / "interactions.db"
    if int_db.exists():
        conn = sqlite3.connect(int_db)
        cursor = conn.execute("""
            SELECT source_type, COUNT(*) as total,
                   MIN(DATE(timestamp)) as earliest,
                   MAX(DATE(timestamp)) as latest
            FROM interactions
            GROUP BY source_type
        """)
        for row in cursor.fetchall():
            source_type, total, earliest, latest = row
            result["sources"][source_type] = {
                "total_interactions": total,
                "earliest": earliest,
                "latest": latest,
            }
        conn.close()

    # iMessage linking stats
    imessage_db = data_dir / "imessage.db"
    if imessage_db.exists():
        conn = sqlite3.connect(imessage_db)
        cursor = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN person_entity_id IS NOT NULL THEN 1 ELSE 0 END) as linked
            FROM messages
        """)
        row = cursor.fetchone()
        if row:
            total, linked = row
            result["sources"]["imessage_raw"] = {
                "total_messages": total,
                "linked_messages": linked or 0,
                "unlinked_messages": total - (linked or 0),
                "linked_pct": round((linked or 0) / total * 100, 1) if total > 0 else 0,
            }
        conn.close()

    # Relationship stats
    crm_db = data_dir / "crm.db"
    if crm_db.exists():
        conn = sqlite3.connect(crm_db)

        # Total relationships
        cursor = conn.execute("SELECT COUNT(*) FROM relationships")
        result["relationships"]["total"] = cursor.fetchone()[0]

        # By context
        cursor = conn.execute("""
            SELECT shared_contexts, COUNT(*) as cnt
            FROM relationships
            GROUP BY shared_contexts
            ORDER BY cnt DESC
            LIMIT 20
        """)
        result["relationships"]["by_context"] = [
            {"contexts": row[0], "count": row[1]}
            for row in cursor.fetchall()
        ]

        # Source entities
        cursor = conn.execute("""
            SELECT source_type, COUNT(*) as total,
                   SUM(CASE WHEN canonical_person_id IS NOT NULL THEN 1 ELSE 0 END) as linked
            FROM source_entities
            GROUP BY source_type
        """)
        result["source_entities"] = {}
        for row in cursor.fetchall():
            source_type, total, linked = row
            result["source_entities"][source_type] = {
                "total": total,
                "linked": linked or 0,
                "unlinked": total - (linked or 0),
            }

        conn.close()

    # People stats
    person_store = get_person_entity_store()
    all_people = person_store.get_all()
    result["people"]["total"] = len(all_people)
    result["people"]["with_interactions"] = sum(
        1 for p in all_people
        if (p.email_count or 0) + (p.meeting_count or 0) + (p.message_count or 0) > 0
    )

    # Sync recommendations
    imessage_data = result["sources"].get("imessage_raw", {})
    if imessage_data.get("linked_pct", 100) < 80:
        result["sync_recommendations"].append({
            "source": "imessage",
            "issue": f"Only {imessage_data.get('linked_pct')}% of messages linked",
            "action": "Run: uv run python scripts/link_imessage_entities.py --execute",
        })

    # Check for stale syncs
    for source, data in result["sources"].items():
        if source == "imessage_raw":
            continue
        latest = data.get("latest")
        if latest:
            from datetime import datetime, timedelta
            try:
                latest_date = datetime.strptime(latest, "%Y-%m-%d")
                days_old = (datetime.now() - latest_date).days
                if days_old > 7:
                    result["sync_recommendations"].append({
                        "source": source,
                        "issue": f"Last data is {days_old} days old",
                        "action": f"Run sync script for {source}",
                    })
            except ValueError:
                pass

    return result


@router.get("/data-health/summary")
async def get_data_health_summary():
    """Get a brief summary of data health for the UI header."""
    health = await get_data_health()

    return {
        "total_interactions": sum(
            s.get("total_interactions", 0)
            for s in health["sources"].values()
            if isinstance(s.get("total_interactions"), int)
        ),
        "total_relationships": health["relationships"].get("total", 0),
        "total_people": health["people"].get("total", 0),
        "issues": len(health.get("sync_recommendations", [])),
    }


# Link Override Management


class LinkOverrideResponse(BaseModel):
    """Response model for a link override rule."""
    id: str
    name_pattern: str
    source_type: Optional[str] = None
    context_pattern: Optional[str] = None
    preferred_person_id: str
    preferred_person_name: Optional[str] = None
    rejected_person_id: Optional[str] = None
    rejected_person_name: Optional[str] = None
    reason: Optional[str] = None
    created_at: Optional[str] = None


@router.get("/link-overrides")
async def get_link_overrides(person_id: Optional[str] = Query(default=None)):
    """
    Get all link override rules.

    Optionally filter by person_id to see overrides affecting a specific person.
    """
    from api.services.link_override import get_link_override_store

    override_store = get_link_override_store()
    person_store = get_person_entity_store()

    if person_id:
        overrides = override_store.get_for_person(person_id)
    else:
        overrides = override_store.get_all()

    results = []
    for o in overrides:
        preferred_name = None
        rejected_name = None

        preferred = person_store.get_by_id(o.preferred_person_id)
        if preferred:
            preferred_name = preferred.canonical_name

        if o.rejected_person_id:
            rejected = person_store.get_by_id(o.rejected_person_id)
            if rejected:
                rejected_name = rejected.canonical_name

        results.append(LinkOverrideResponse(
            id=o.id,
            name_pattern=o.name_pattern,
            source_type=o.source_type,
            context_pattern=o.context_pattern,
            preferred_person_id=o.preferred_person_id,
            preferred_person_name=preferred_name,
            rejected_person_id=o.rejected_person_id,
            rejected_person_name=rejected_name,
            reason=o.reason,
            created_at=o.created_at.isoformat() if o.created_at else None,
        ))

    return {"overrides": results, "count": len(results)}


@router.delete("/link-overrides/{override_id}")
async def delete_link_override(override_id: str):
    """Delete a link override rule."""
    from api.services.link_override import get_link_override_store

    override_store = get_link_override_store()
    deleted = override_store.delete(override_id)

    if not deleted:
        raise HTTPException(status_code=404, detail=f"Override '{override_id}' not found")

    return {"status": "deleted", "id": override_id}

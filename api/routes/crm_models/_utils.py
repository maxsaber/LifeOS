"""
Shared utility functions for CRM route modules.

Contains helper functions for person lookup, category computation,
search matching, and response conversion.
"""
import logging
import re
from typing import Optional

from api.services.person_entity import PersonEntity, get_person_entity_store
from api.services.source_entity import SourceEntity, get_source_entity_store
from api.services.relationship import get_relationship_store
from config.settings import settings
from config.relationship_weights import STRENGTH_OVERRIDES_BY_ID

from api.routes.crm_models.models import (
    SourceEntityResponse,
    RelationshipResponse,
    PersonDetailResponse,
)

logger = logging.getLogger(__name__)

# Work email domain for category detection
WORK_EMAIL_DOMAIN = "movementlabs.com"

# Owner's person ID for "Me" page
MY_PERSON_ID = "3f41e143-719f-4dc9-a9f1-389b2db5b166"

# Taylor Walker's ID (hardcoded for relationship page)
TAYLOR_WALKER_ID = "cb93e7bd-036c-4ef5-adb9-34a9147c4984"

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


def get_strength_override(person_id: str) -> float | None:
    """Check if a person has a manual strength override (by ID)."""
    if not person_id:
        return None
    return STRENGTH_OVERRIDES_BY_ID.get(person_id)


def is_family_member(name: str) -> bool:
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
    if is_family_member(person.canonical_name):
        return "family"
    # Also check display name and aliases
    if is_family_member(person.display_name):
        return "family"
    for alias in person.aliases:
        if is_family_member(alias):
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


def tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens, removing punctuation."""
    # Split on whitespace and punctuation, keep only alphanumeric
    # Include various apostrophe/quote variants: ' ' ' ` ʼ ʻ
    return [t.lower() for t in re.split(r'[\s.,;:\-\'\"()\u2018\u2019\u0027\u0060\u02BC\u02BB]+', text) if t]


def fuzzy_name_match(query: str, name: str) -> bool:
    """
    Check if query tokens match name tokens as prefixes.

    Examples:
    - "ryan jones" matches "Ryan A. Jones" (exact word matches)
    - "ry jo" matches "Ryan A. Jones" (prefix matches)
    - "jo ry" matches "Ryan A. Jones" (order doesn't matter)
    """
    if not query or not name:
        return False

    query_tokens = tokenize(query)
    name_tokens = tokenize(name)

    if not query_tokens:
        return False

    # Each query token must match the start of at least one name token
    for qt in query_tokens:
        if not any(nt.startswith(qt) for nt in name_tokens):
            return False
    return True


def search_matches(query: str, person) -> bool:
    """Check if a person matches the search query."""
    q_lower = query.lower()

    # Try fuzzy name matching first
    if fuzzy_name_match(query, person.canonical_name):
        return True
    if fuzzy_name_match(query, person.display_name):
        return True
    for alias in person.aliases:
        if fuzzy_name_match(query, alias):
            return True

    # Fall back to substring matching for emails and company
    if any(q_lower in email.lower() for email in person.emails):
        return True
    if person.company and q_lower in person.company.lower():
        return True

    return False


def source_entity_to_response(entity: SourceEntity) -> SourceEntityResponse:
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


def relationship_to_response(rel, person_store) -> RelationshipResponse:
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


def person_to_detail_response(
    person: PersonEntity,
    include_related: bool = True,
) -> PersonDetailResponse:
    """Convert PersonEntity to detailed API response."""
    # Fetch source entities first for category computation
    source_store = get_source_entity_store()
    source_entities = source_store.get_for_person(person.id, limit=100) if include_related else None

    # Compute category dynamically based on source entities and email domains
    computed_category = compute_person_category(person, source_entities)

    # Check for manual strength override (by ID)
    strength_override = get_strength_override(person.id)
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
        dunbar_circle=person.dunbar_circle,
    )

    if include_related:
        # Source entities already fetched for category computation
        response.source_entities = [source_entity_to_response(e) for e in source_entities]

        # Add relationships
        rel_store = get_relationship_store()
        person_store = get_person_entity_store()
        relationships = rel_store.get_for_person(person.id, limit=20)
        response.relationships = [relationship_to_response(r, person_store) for r in relationships]

    return response


# Aliases for backward compatibility with underscore-prefixed names
_get_strength_override = get_strength_override
_is_family_member = is_family_member
_tokenize = tokenize
_fuzzy_name_match = fuzzy_name_match
_search_matches = search_matches
_source_entity_to_response = source_entity_to_response
_relationship_to_response = relationship_to_response
_person_to_detail_response = person_to_detail_response

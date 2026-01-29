"""
Relationship Discovery - Discover connections between people.

Analyzes shared contexts to discover and score relationships:
- Shared calendar events (strong signal)
- Shared email threads (medium signal)
- Co-mentions in vault notes (medium signal)
- Shared Slack channels (weak signal)
"""
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from api.services.person_entity import PersonEntity, get_person_entity_store
from api.services.interaction_store import get_interaction_store
from api.services.relationship import (
    Relationship,
    get_relationship_store,
    TYPE_COWORKER,
    TYPE_INFERRED,
)

logger = logging.getLogger(__name__)

# Discovery window (days to look back)
DISCOVERY_WINDOW_DAYS = 180


def discover_from_calendar(
    days_back: int = DISCOVERY_WINDOW_DAYS,
    min_shared_events: int = 2,
) -> list[Relationship]:
    """
    Discover relationships from shared calendar events.

    People who attend the same meetings are likely connected.

    Args:
        days_back: Days to look back
        min_shared_events: Minimum shared events to create relationship

    Returns:
        List of discovered relationships
    """
    interaction_store = get_interaction_store()
    relationship_store = get_relationship_store()
    person_store = get_person_entity_store()

    # Get all calendar interactions in the window
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    # Group interactions by event (source_id)
    event_attendees: dict[str, list[str]] = defaultdict(list)

    # Iterate through all people and their calendar interactions
    for person in person_store.get_all():
        interactions = interaction_store.get_for_person(
            person.id,
            days_back=days_back,
            source_type="calendar",
        )
        for interaction in interactions:
            if interaction.source_id:
                event_attendees[interaction.source_id].append(person.id)

    # Find pairs of people who share events
    pair_events: dict[tuple[str, str], list[str]] = defaultdict(list)

    for event_id, attendees in event_attendees.items():
        # Skip single-attendee events
        if len(attendees) < 2:
            continue

        # Create pairs from attendees
        for i, person_a in enumerate(attendees):
            for person_b in attendees[i + 1:]:
                # Normalize pair order
                pair = (min(person_a, person_b), max(person_a, person_b))
                pair_events[pair].append(event_id)

    # Create/update relationships for pairs with enough shared events
    relationships = []
    for (person_a_id, person_b_id), events in pair_events.items():
        if len(events) >= min_shared_events:
            existing = relationship_store.get_between(person_a_id, person_b_id)

            if existing:
                # Update existing relationship
                existing.shared_events_count = len(events)
                existing.last_seen_together = datetime.now(timezone.utc)
                relationship_store.update(existing)
                relationships.append(existing)
            else:
                # Create new relationship
                rel = Relationship(
                    person_a_id=person_a_id,
                    person_b_id=person_b_id,
                    relationship_type=TYPE_COWORKER,
                    shared_events_count=len(events),
                    first_seen_together=datetime.now(timezone.utc),
                    last_seen_together=datetime.now(timezone.utc),
                    shared_contexts=["calendar"],
                )
                relationship_store.add(rel)
                relationships.append(rel)

    logger.info(f"Discovered {len(relationships)} relationships from calendar")
    return relationships


def discover_from_email_threads(
    days_back: int = DISCOVERY_WINDOW_DAYS,
    min_shared_threads: int = 3,
) -> list[Relationship]:
    """
    Discover relationships from shared email threads.

    People who are CC'd together or reply to same threads are likely connected.

    Args:
        days_back: Days to look back
        min_shared_threads: Minimum shared threads to create relationship

    Returns:
        List of discovered relationships
    """
    interaction_store = get_interaction_store()
    relationship_store = get_relationship_store()
    person_store = get_person_entity_store()

    # Group email interactions by thread (using source_id prefix as thread proxy)
    # In Gmail, thread IDs are often similar to message IDs
    thread_participants: dict[str, list[str]] = defaultdict(list)

    for person in person_store.get_all():
        interactions = interaction_store.get_for_person(
            person.id,
            days_back=days_back,
            source_type="gmail",
        )
        for interaction in interactions:
            if interaction.source_id:
                # Use source_id as thread identifier
                # (In practice, you'd want to use actual thread_id from Gmail)
                thread_participants[interaction.source_id].append(person.id)

    # Find pairs who share threads
    pair_threads: dict[tuple[str, str], list[str]] = defaultdict(list)

    for thread_id, participants in thread_participants.items():
        if len(participants) < 2:
            continue

        for i, person_a in enumerate(participants):
            for person_b in participants[i + 1:]:
                pair = (min(person_a, person_b), max(person_a, person_b))
                pair_threads[pair].append(thread_id)

    # Create/update relationships
    relationships = []
    for (person_a_id, person_b_id), threads in pair_threads.items():
        if len(threads) >= min_shared_threads:
            existing = relationship_store.get_between(person_a_id, person_b_id)

            if existing:
                existing.shared_threads_count = len(threads)
                existing.last_seen_together = datetime.now(timezone.utc)
                if "gmail" not in existing.shared_contexts:
                    existing.shared_contexts.append("gmail")
                relationship_store.update(existing)
                relationships.append(existing)
            else:
                rel = Relationship(
                    person_a_id=person_a_id,
                    person_b_id=person_b_id,
                    relationship_type=TYPE_COWORKER,
                    shared_threads_count=len(threads),
                    first_seen_together=datetime.now(timezone.utc),
                    last_seen_together=datetime.now(timezone.utc),
                    shared_contexts=["gmail"],
                )
                relationship_store.add(rel)
                relationships.append(rel)

    logger.info(f"Discovered {len(relationships)} relationships from email")
    return relationships


def discover_from_vault_comments(
    days_back: int = DISCOVERY_WINDOW_DAYS,
    min_co_mentions: int = 2,
) -> list[Relationship]:
    """
    Discover relationships from co-mentions in vault notes.

    People mentioned in the same notes are likely connected.

    Args:
        days_back: Days to look back
        min_co_mentions: Minimum co-mentions to create relationship

    Returns:
        List of discovered relationships
    """
    interaction_store = get_interaction_store()
    relationship_store = get_relationship_store()
    person_store = get_person_entity_store()

    # Group vault interactions by note (source_id = file path)
    note_mentions: dict[str, list[str]] = defaultdict(list)

    for person in person_store.get_all():
        interactions = interaction_store.get_for_person(
            person.id,
            days_back=days_back,
            source_type="vault",
        )
        for interaction in interactions:
            if interaction.source_id:
                note_mentions[interaction.source_id].append(person.id)

    # Find pairs who are mentioned together
    pair_notes: dict[tuple[str, str], list[str]] = defaultdict(list)

    for note_path, mentioned in note_mentions.items():
        if len(mentioned) < 2:
            continue

        for i, person_a in enumerate(mentioned):
            for person_b in mentioned[i + 1:]:
                pair = (min(person_a, person_b), max(person_a, person_b))
                pair_notes[pair].append(note_path)

    # Create/update relationships
    relationships = []
    for (person_a_id, person_b_id), notes in pair_notes.items():
        if len(notes) >= min_co_mentions:
            existing = relationship_store.get_between(person_a_id, person_b_id)

            if existing:
                existing.last_seen_together = datetime.now(timezone.utc)
                if "vault" not in existing.shared_contexts:
                    existing.shared_contexts.append("vault")
                relationship_store.update(existing)
                relationships.append(existing)
            else:
                rel = Relationship(
                    person_a_id=person_a_id,
                    person_b_id=person_b_id,
                    relationship_type=TYPE_INFERRED,
                    first_seen_together=datetime.now(timezone.utc),
                    last_seen_together=datetime.now(timezone.utc),
                    shared_contexts=["vault"],
                )
                relationship_store.add(rel)
                relationships.append(rel)

    logger.info(f"Discovered {len(relationships)} relationships from vault")
    return relationships


def run_full_discovery(days_back: int = DISCOVERY_WINDOW_DAYS) -> dict:
    """
    Run all discovery methods and return statistics.

    Args:
        days_back: Days to look back

    Returns:
        Statistics about discovered relationships
    """
    results = {
        "calendar": len(discover_from_calendar(days_back)),
        "email": len(discover_from_email_threads(days_back)),
        "vault": len(discover_from_vault_comments(days_back)),
    }

    total = sum(results.values())
    logger.info(f"Full discovery complete: {total} relationships found")

    return {
        "by_source": results,
        "total": total,
    }


def get_suggested_connections(
    person_id: str,
    limit: int = 10,
) -> list[dict]:
    """
    Get suggested connections for a person.

    Returns people who share contexts but don't have a direct relationship yet.

    Args:
        person_id: Person to find suggestions for
        limit: Maximum suggestions to return

    Returns:
        List of suggested connections with scores
    """
    person_store = get_person_entity_store()
    relationship_store = get_relationship_store()
    interaction_store = get_interaction_store()

    person = person_store.get_by_id(person_id)
    if not person:
        return []

    # Get existing connections
    existing_connections = set(relationship_store.get_connections(person_id))

    # Get person's vault contexts
    person_contexts = set(person.vault_contexts)

    # Find people with overlapping contexts
    suggestions = []
    for other in person_store.get_all():
        if other.id == person_id:
            continue
        if other.id in existing_connections:
            continue

        # Calculate overlap score
        other_contexts = set(other.vault_contexts)
        shared_contexts = person_contexts & other_contexts

        if not shared_contexts:
            continue

        # Score based on context overlap
        overlap_score = len(shared_contexts) / max(len(person_contexts), 1)

        # Boost if they share sources
        shared_sources = set(person.sources) & set(other.sources)
        source_boost = len(shared_sources) * 0.1

        total_score = min(1.0, overlap_score + source_boost)

        suggestions.append({
            "person_id": other.id,
            "name": other.canonical_name,
            "company": other.company,
            "score": round(total_score, 3),
            "shared_contexts": list(shared_contexts),
            "shared_sources": list(shared_sources),
        })

    # Sort by score descending
    suggestions.sort(key=lambda x: x["score"], reverse=True)

    return suggestions[:limit]


def get_connection_overlap(person_a_id: str, person_b_id: str) -> dict:
    """
    Get detailed overlap information between two people.

    Args:
        person_a_id: First person ID
        person_b_id: Second person ID

    Returns:
        Dict with overlap details
    """
    person_store = get_person_entity_store()
    relationship_store = get_relationship_store()
    interaction_store = get_interaction_store()

    person_a = person_store.get_by_id(person_a_id)
    person_b = person_store.get_by_id(person_b_id)

    if not person_a or not person_b:
        return {"error": "Person not found"}

    relationship = relationship_store.get_between(person_a_id, person_b_id)

    # Context overlap
    shared_contexts = set(person_a.vault_contexts) & set(person_b.vault_contexts)

    # Source overlap
    shared_sources = set(person_a.sources) & set(person_b.sources)

    return {
        "person_a": {
            "id": person_a.id,
            "name": person_a.canonical_name,
        },
        "person_b": {
            "id": person_b.id,
            "name": person_b.canonical_name,
        },
        "relationship": {
            "exists": relationship is not None,
            "type": relationship.relationship_type if relationship else None,
            "shared_events_count": relationship.shared_events_count if relationship else 0,
            "shared_threads_count": relationship.shared_threads_count if relationship else 0,
            "first_seen_together": relationship.first_seen_together.isoformat() if relationship and relationship.first_seen_together else None,
            "last_seen_together": relationship.last_seen_together.isoformat() if relationship and relationship.last_seen_together else None,
        },
        "shared_contexts": list(shared_contexts),
        "shared_sources": list(shared_sources),
    }

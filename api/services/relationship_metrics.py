"""
Relationship Metrics - Compute relationship strength scores.

Relationship strength is computed using the formula:
    strength = (recency × 0.3) + (frequency × 0.4) + (diversity × 0.3)

Where:
- recency: max(0, 1 - days_since_last/90)
- frequency: min(1, interactions_90d/20)
- diversity: unique_sources / total_sources
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from api.services.person_entity import PersonEntity, get_person_entity_store
from api.services.interaction_store import get_interaction_store
from api.services.source_entity import get_source_entity_store, SOURCE_TYPES

logger = logging.getLogger(__name__)

# Weights for relationship strength calculation
RECENCY_WEIGHT = 0.3
FREQUENCY_WEIGHT = 0.4
DIVERSITY_WEIGHT = 0.3

# Parameters
RECENCY_WINDOW_DAYS = 90  # Days after which recency score is 0
FREQUENCY_TARGET = 20  # Number of interactions in 90 days for max frequency score


def compute_recency_score(last_seen: Optional[datetime]) -> float:
    """
    Compute recency score (0.0-1.0).

    Score is 1.0 if last interaction was today, decreasing linearly
    to 0.0 at RECENCY_WINDOW_DAYS days ago.

    Args:
        last_seen: Last interaction timestamp

    Returns:
        Recency score between 0.0 and 1.0
    """
    if last_seen is None:
        return 0.0

    now = datetime.now(timezone.utc)

    # Ensure last_seen is timezone-aware
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)

    days_since = (now - last_seen).days

    if days_since < 0:
        # Future date (shouldn't happen, but handle gracefully)
        return 1.0

    return max(0.0, 1.0 - (days_since / RECENCY_WINDOW_DAYS))


def compute_frequency_score(interaction_count: int) -> float:
    """
    Compute frequency score (0.0-1.0).

    Score increases linearly from 0 to 1.0 as interactions approach
    FREQUENCY_TARGET in the 90-day window.

    Args:
        interaction_count: Number of interactions in the window

    Returns:
        Frequency score between 0.0 and 1.0
    """
    if interaction_count <= 0:
        return 0.0

    return min(1.0, interaction_count / FREQUENCY_TARGET)


def compute_diversity_score(sources: list[str]) -> float:
    """
    Compute diversity score (0.0-1.0).

    Score is the ratio of unique sources used to total possible sources.

    Args:
        sources: List of source types used for interactions

    Returns:
        Diversity score between 0.0 and 1.0
    """
    if not sources:
        return 0.0

    unique_sources = len(set(sources))
    total_sources = len(SOURCE_TYPES)

    return min(1.0, unique_sources / total_sources)


def compute_relationship_strength(
    last_seen: Optional[datetime],
    interaction_count: int,
    sources: list[str],
) -> float:
    """
    Compute overall relationship strength score.

    Uses the formula:
        strength = (recency × 0.3) + (frequency × 0.4) + (diversity × 0.3)

    Args:
        last_seen: Last interaction timestamp
        interaction_count: Number of interactions in 90-day window
        sources: List of source types used

    Returns:
        Relationship strength between 0.0 and 1.0
    """
    recency = compute_recency_score(last_seen)
    frequency = compute_frequency_score(interaction_count)
    diversity = compute_diversity_score(sources)

    strength = (
        recency * RECENCY_WEIGHT +
        frequency * FREQUENCY_WEIGHT +
        diversity * DIVERSITY_WEIGHT
    )

    return round(strength, 3)


def compute_strength_for_person(person: PersonEntity) -> float:
    """
    Compute relationship strength for a PersonEntity.

    Fetches interaction data from stores and computes the score.

    Args:
        person: PersonEntity to compute strength for

    Returns:
        Relationship strength between 0.0 and 1.0
    """
    interaction_store = get_interaction_store()

    # Get interactions in the window
    interactions = interaction_store.get_for_person(
        person.id,
        days_back=RECENCY_WINDOW_DAYS,
        limit=1000,  # High limit to get accurate count
    )

    # Get source types from interactions
    sources = list(set(i.source_type for i in interactions))

    # Also include sources from the person's source list
    sources.extend(person.sources)
    sources = list(set(sources))

    # Get interaction count
    interaction_count = len(interactions)

    # Compute and return strength
    return compute_relationship_strength(
        last_seen=person.last_seen,
        interaction_count=interaction_count,
        sources=sources,
    )


def update_strength_for_person(person_id: str) -> Optional[float]:
    """
    Compute and update relationship strength for a person.

    Updates the PersonEntity with the new strength score.

    Args:
        person_id: ID of the person to update

    Returns:
        New relationship strength, or None if person not found
    """
    store = get_person_entity_store()
    person = store.get_by_id(person_id)

    if not person:
        logger.warning(f"Person not found: {person_id}")
        return None

    strength = compute_strength_for_person(person)
    person.relationship_strength = strength
    store.update(person)

    logger.debug(f"Updated relationship strength for {person.canonical_name}: {strength}")
    return strength


def update_all_strengths() -> dict:
    """
    Update relationship strength for all people.

    Returns:
        Statistics about the update
    """
    store = get_person_entity_store()
    people = store.get_all()

    updated = 0
    failed = 0

    for person in people:
        try:
            strength = compute_strength_for_person(person)
            person.relationship_strength = strength
            store.update(person)
            updated += 1
        except Exception as e:
            logger.error(f"Failed to update strength for {person.id}: {e}")
            failed += 1

    # Save all updates
    store.save()

    logger.info(f"Updated relationship strength for {updated} people ({failed} failed)")
    return {
        "updated": updated,
        "failed": failed,
        "total": len(people),
    }


def get_strength_breakdown(person: PersonEntity) -> dict:
    """
    Get detailed breakdown of relationship strength components.

    Useful for debugging and displaying in UI.

    Args:
        person: PersonEntity to analyze

    Returns:
        Dict with component scores and details
    """
    interaction_store = get_interaction_store()

    interactions = interaction_store.get_for_person(
        person.id,
        days_back=RECENCY_WINDOW_DAYS,
        limit=1000,
    )

    sources = list(set(i.source_type for i in interactions))
    sources.extend(person.sources)
    sources = list(set(sources))

    interaction_count = len(interactions)

    recency_score = compute_recency_score(person.last_seen)
    frequency_score = compute_frequency_score(interaction_count)
    diversity_score = compute_diversity_score(sources)

    days_since_last = None
    if person.last_seen:
        now = datetime.now(timezone.utc)
        last_seen = person.last_seen
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        days_since_last = (now - last_seen).days

    return {
        "overall_strength": compute_relationship_strength(
            person.last_seen,
            interaction_count,
            sources,
        ),
        "recency": {
            "score": recency_score,
            "weight": RECENCY_WEIGHT,
            "weighted_score": recency_score * RECENCY_WEIGHT,
            "last_seen": person.last_seen.isoformat() if person.last_seen else None,
            "days_since_last": days_since_last,
        },
        "frequency": {
            "score": frequency_score,
            "weight": FREQUENCY_WEIGHT,
            "weighted_score": frequency_score * FREQUENCY_WEIGHT,
            "interaction_count": interaction_count,
            "target": FREQUENCY_TARGET,
        },
        "diversity": {
            "score": diversity_score,
            "weight": DIVERSITY_WEIGHT,
            "weighted_score": diversity_score * DIVERSITY_WEIGHT,
            "sources_used": sources,
            "total_sources": len(SOURCE_TYPES),
        },
    }

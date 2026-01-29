"""
Relationship Metrics - Compute relationship strength scores.

Relationship strength is computed using the formula:
    strength = (recency × RECENCY_WEIGHT) + (frequency × FREQUENCY_WEIGHT) + (diversity × DIVERSITY_WEIGHT)

Where:
- recency: max(0, 1 - days_since_last/RECENCY_WINDOW_DAYS)
- frequency: min(1, weighted_interactions/FREQUENCY_TARGET)
- diversity: unique_sources / total_sources

Interaction weights are applied per source_type (e.g., imessage=1.5, gmail=0.8).
See config/relationship_weights.py for all weights.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from api.services.person_entity import PersonEntity, get_person_entity_store
from api.services.interaction_store import get_interaction_store
from api.services.source_entity import get_source_entity_store, SOURCE_TYPES

# Import weights from centralized config
from config.relationship_weights import (
    RECENCY_WEIGHT,
    FREQUENCY_WEIGHT,
    DIVERSITY_WEIGHT,
    RECENCY_WINDOW_DAYS,
    FREQUENCY_TARGET,
    FREQUENCY_WINDOW_DAYS,
    get_interaction_weight,
    compute_weighted_interaction_count,
    INTERACTION_TYPE_WEIGHTS,
)

logger = logging.getLogger(__name__)


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


def compute_frequency_score(interaction_count: float) -> float:
    """
    Compute frequency score (0.0-1.0).

    Score increases linearly from 0 to 1.0 as interactions approach
    FREQUENCY_TARGET in the 90-day window.

    Args:
        interaction_count: Number of interactions (can be weighted, so float)

    Returns:
        Frequency score between 0.0 and 1.0
    """
    if interaction_count <= 0:
        return 0.0

    return min(1.0, interaction_count / FREQUENCY_TARGET)


def compute_weighted_frequency_score(interactions_by_type: dict[str, int]) -> float:
    """
    Compute frequency score with interaction type weighting.

    Different interaction types are weighted differently:
    - imessage/whatsapp: 1.5 (direct personal contact)
    - phone_call: 2.0 (high effort synchronous)
    - slack: 1.2 (work DM)
    - calendar: 1.0 (meetings)
    - gmail: 0.8 (often passive/CC)
    - vault: 0.7 (mentioned in notes)

    Args:
        interactions_by_type: Dict mapping source_type to count

    Returns:
        Frequency score between 0.0 and 1.0
    """
    weighted_count = compute_weighted_interaction_count(interactions_by_type)
    return compute_frequency_score(weighted_count)


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
    interaction_count: float,  # Changed to float to support weighted counts
    sources: list[str],
) -> float:
    """
    Compute overall relationship strength score.

    Uses the formula:
        strength = (recency × RECENCY_WEIGHT) + (frequency × FREQUENCY_WEIGHT) + (diversity × DIVERSITY_WEIGHT)

    Args:
        last_seen: Last interaction timestamp
        interaction_count: Number of interactions in window (weighted or raw)
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


def compute_relationship_strength_weighted(
    last_seen: Optional[datetime],
    interactions_by_type: dict[str, int],
    sources: list[str],
) -> float:
    """
    Compute relationship strength with interaction type weighting.

    This is the preferred method as it weights different interaction types.

    Args:
        last_seen: Last interaction timestamp
        interactions_by_type: Dict mapping source_type to count
        sources: List of source types used

    Returns:
        Relationship strength between 0.0 and 1.0
    """
    recency = compute_recency_score(last_seen)
    frequency = compute_weighted_frequency_score(interactions_by_type)
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

    Fetches interaction data from stores and computes the score
    using weighted interaction counts by type.

    Args:
        person: PersonEntity to compute strength for

    Returns:
        Relationship strength between 0.0 and 1.0
    """
    interaction_store = get_interaction_store()

    # Get interaction counts by type
    interactions_by_type = interaction_store.get_interaction_counts(
        person.id,
        days_back=FREQUENCY_WINDOW_DAYS,
    )

    # Get source types from interactions
    sources = list(interactions_by_type.keys())

    # Also include sources from the person's source list
    sources.extend(person.sources)
    sources = list(set(sources))

    # Compute and return strength using weighted method
    return compute_relationship_strength_weighted(
        last_seen=person.last_seen,
        interactions_by_type=interactions_by_type,
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

    # Get interaction counts by type for weighted calculation
    interactions_by_type = interaction_store.get_interaction_counts(
        person.id,
        days_back=FREQUENCY_WINDOW_DAYS,
    )

    sources = list(interactions_by_type.keys())
    sources.extend(person.sources)
    sources = list(set(sources))

    # Calculate raw and weighted counts
    raw_interaction_count = sum(interactions_by_type.values())
    weighted_interaction_count = compute_weighted_interaction_count(interactions_by_type)

    recency_score = compute_recency_score(person.last_seen)
    frequency_score = compute_weighted_frequency_score(interactions_by_type)
    diversity_score = compute_diversity_score(sources)

    days_since_last = None
    if person.last_seen:
        now = datetime.now(timezone.utc)
        last_seen = person.last_seen
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        days_since_last = (now - last_seen).days

    # Build weighted breakdown for each source type
    interaction_weights_detail = {}
    for source_type, count in interactions_by_type.items():
        weight = get_interaction_weight(source_type)
        interaction_weights_detail[source_type] = {
            "count": count,
            "weight": weight,
            "weighted_count": round(count * weight, 2),
        }

    return {
        "overall_strength": compute_relationship_strength_weighted(
            person.last_seen,
            interactions_by_type,
            sources,
        ),
        "recency": {
            "score": recency_score,
            "weight": RECENCY_WEIGHT,
            "weighted_score": round(recency_score * RECENCY_WEIGHT, 4),
            "last_seen": person.last_seen.isoformat() if person.last_seen else None,
            "days_since_last": days_since_last,
            "window_days": RECENCY_WINDOW_DAYS,
        },
        "frequency": {
            "score": frequency_score,
            "weight": FREQUENCY_WEIGHT,
            "weighted_score": round(frequency_score * FREQUENCY_WEIGHT, 4),
            "raw_interaction_count": raw_interaction_count,
            "weighted_interaction_count": round(weighted_interaction_count, 2),
            "target": FREQUENCY_TARGET,
            "interactions_by_type": interaction_weights_detail,
        },
        "diversity": {
            "score": diversity_score,
            "weight": DIVERSITY_WEIGHT,
            "weighted_score": round(diversity_score * DIVERSITY_WEIGHT, 4),
            "sources_used": sources,
            "total_sources": len(SOURCE_TYPES),
        },
    }

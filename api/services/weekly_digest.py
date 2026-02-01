"""
<<<<<<< HEAD
Weekly digest helpers for relationship follow-ups.

Determines which people are slipping or need a reach-out based on
configurable thresholds.
"""
from typing import Iterable

from config.relationship_weights import (
    RECENT_INTERACTION_DAYS,
    SLIPPING_DAYS,
    REACHOUT_DAYS,
)
from api.services.person_entity import get_person_entity_store
from api.services.relationship_summary import RelationshipSummary, get_relationship_summary


def determine_contact_status(days_since_contact: int) -> str:
    """
    Classify contact status based on days since last interaction.

    Returns one of: recent, steady, slipping, reachout.
    """
    if days_since_contact <= RECENT_INTERACTION_DAYS:
        return "recent"
    if days_since_contact >= REACHOUT_DAYS:
        return "reachout"
    if days_since_contact >= SLIPPING_DAYS:
        return "slipping"
    return "steady"


def split_people_by_status(
    summaries: Iterable[RelationshipSummary],
) -> dict[str, list[RelationshipSummary]]:
    """
    Split people into slipping and reach-out buckets based on thresholds.
    """
    results: dict[str, list[RelationshipSummary]] = {
        "slipping": [],
        "reachout": [],
    }
    for summary in summaries:
        status = determine_contact_status(summary.days_since_contact)
        if status == "slipping":
            results["slipping"].append(summary)
        elif status == "reachout":
            results["reachout"].append(summary)
    return results


def get_weekly_digest_candidates() -> dict[str, list[RelationshipSummary]]:
    """
    Build slipping and reach-out lists for the weekly digest.
    """
    person_store = get_person_entity_store()
    summaries: list[RelationshipSummary] = []

    for person in person_store.get_all():
        summary = get_relationship_summary(person.id)
        if summary:
            summaries.append(summary)

    return split_people_by_status(summaries)
=======
Weekly digest service.

Builds digest sections from PersonEntity + interaction data.
"""
from datetime import datetime, timezone
from typing import Optional

from api.services.interaction_store import get_interaction_store
from api.services.person_entity import PersonEntity, get_person_entity_store
from api.services.relationship_metrics import compute_strength_for_person

# Classification thresholds
STRONG_RELATIONSHIP_THRESHOLD = 60.0
MODERATE_RELATIONSHIP_THRESHOLD = 35.0
SLIPPING_DAYS = 21
SUGGESTED_REACHOUT_DAYS = 45
DEFAULT_TOP_N = 10


def build_weekly_digest(
    start_dt: datetime,
    end_dt: datetime,
    top_n: int = DEFAULT_TOP_N,
) -> dict:
    """
    Build weekly digest sections for a date window.

    Args:
        start_dt: Start of window (inclusive)
        end_dt: End of window (inclusive)
        top_n: Max items per section

    Returns:
        Dict with digest sections and counts.
    """
    start_dt = _ensure_aware(start_dt)
    end_dt = _ensure_aware(end_dt)

    if end_dt < start_dt:
        raise ValueError("end_dt must be greater than or equal to start_dt")

    interaction_store = get_interaction_store()
    person_store = get_person_entity_store()
    people = [person for person in person_store.get_all() if not person.hidden]

    interactions = interaction_store.get_all_in_range(start_dt, end_dt)

    window_stats: dict[str, dict] = {}
    for interaction in interactions:
        entry = window_stats.setdefault(
            interaction.person_id,
            {
                "count": 0,
                "last_interaction": None,
                "sources": {},
            },
        )
        entry["count"] += 1
        entry["sources"][interaction.source_type] = (
            entry["sources"].get(interaction.source_type, 0) + 1
        )
        if entry["last_interaction"] is None or interaction.timestamp > entry["last_interaction"]:
            entry["last_interaction"] = interaction.timestamp

    talked_to: list[dict] = []
    slipping: list[dict] = []
    suggested: list[dict] = []

    for person in people:
        stats = window_stats.get(person.id)
        relationship_strength = compute_strength_for_person(person)
        last_seen = _get_last_seen(person, interaction_store)
        days_since_last = _days_since(last_seen, end_dt)

        if stats:
            talked_to.append(
                _build_item(
                    person,
                    relationship_strength,
                    last_seen,
                    days_since_last,
                    stats,
                    reasons=[
                        f"{stats['count']} interactions between {start_dt.date()} and {end_dt.date()}"
                    ],
                )
            )
            continue

        if days_since_last is None:
            continue

        if relationship_strength >= STRONG_RELATIONSHIP_THRESHOLD and days_since_last >= SLIPPING_DAYS:
            slipping.append(
                _build_item(
                    person,
                    relationship_strength,
                    last_seen,
                    days_since_last,
                    None,
                    reasons=[
                        f"Strong relationship (strength {relationship_strength:.1f})",
                        f"Last interaction {days_since_last} days ago",
                    ],
                )
            )
            continue

        if relationship_strength >= MODERATE_RELATIONSHIP_THRESHOLD and days_since_last >= SUGGESTED_REACHOUT_DAYS:
            suggested.append(
                _build_item(
                    person,
                    relationship_strength,
                    last_seen,
                    days_since_last,
                    None,
                    reasons=[
                        f"Moderate relationship (strength {relationship_strength:.1f})",
                        f"No contact in {days_since_last} days",
                    ],
                )
            )

    talked_to.sort(key=lambda item: (item["interaction_count"], item["last_interaction"] or ""), reverse=True)
    slipping.sort(key=lambda item: (item["relationship_strength"], item["days_since_last"] or 0), reverse=True)
    suggested.sort(key=lambda item: (item["relationship_strength"], item["days_since_last"] or 0), reverse=True)

    window_days = max((end_dt.date() - start_dt.date()).days + 1, 1)

    return {
        "window": {
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "days": window_days,
        },
        "summary": {
            "total_people": len(people),
            "people_with_interactions": len(window_stats),
            "interaction_count": len(interactions),
        },
        "talked_to": {
            "count": len(talked_to),
            "items": talked_to[:top_n],
        },
        "slipping": {
            "count": len(slipping),
            "items": slipping[:top_n],
        },
        "suggested_reachouts": {
            "count": len(suggested),
            "items": suggested[:top_n],
        },
    }


def _build_item(
    person: PersonEntity,
    relationship_strength: float,
    last_seen: Optional[datetime],
    days_since_last: Optional[int],
    stats: Optional[dict],
    reasons: list[str],
) -> dict:
    return {
        "person_id": person.id,
        "name": person.display_name or person.canonical_name,
        "company": person.company,
        "relationship_strength": relationship_strength,
        "last_interaction": last_seen.isoformat() if last_seen else None,
        "days_since_last": days_since_last,
        "interaction_count": stats["count"] if stats else 0,
        "interaction_sources": stats["sources"] if stats else {},
        "reasons": reasons,
    }


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _get_last_seen(person: PersonEntity, interaction_store) -> Optional[datetime]:
    if person.last_seen:
        return _ensure_aware(person.last_seen)
    last = interaction_store.get_last_interaction(person.id)
    return _ensure_aware(last.timestamp) if last else None


def _days_since(last_seen: Optional[datetime], reference: datetime) -> Optional[int]:
    if not last_seen:
        return None
    last_seen = _ensure_aware(last_seen)
    reference = _ensure_aware(reference)
    return max((reference - last_seen).days, 0)
>>>>>>> fe61eca (Add weekly digest service)

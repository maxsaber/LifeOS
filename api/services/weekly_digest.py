"""
Weekly digest service.

Builds digest sections from PersonEntity + interaction data.
"""
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional

from api.services.interaction_store import get_interaction_store
from api.services.person_entity import get_person_entity_store
from api.services.relationship_summary import RelationshipSummary, get_relationship_summary
from config.relationship_weights import (
    RECENT_INTERACTION_DAYS,
    SLIPPING_DAYS,
    REACHOUT_DAYS,
)


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


def build_weekly_digest(
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> dict[str, list[dict]]:
    """
    Build weekly digest response for the UI.

    Args:
        start: Start date (YYYY-MM-DD). Defaults to last 7 days.
        end: End date (YYYY-MM-DD). Defaults to today.

    Returns:
        Structured response with minimal person details.
    """
    if end is None:
        end = datetime.now(timezone.utc).date()
    if start is None:
        start = end - timedelta(days=7)

    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end, time.max, tzinfo=timezone.utc)

    candidates = get_weekly_digest_candidates()
    interaction_store = get_interaction_store()
    digest_people: list[dict] = []

    for reason, summaries in candidates.items():
        for summary in summaries:
            counts = interaction_store.get_interaction_counts_between(
                summary.person_id,
                start_dt,
                end_dt,
            )
            digest_people.append(
                {
                    "person_id": summary.person_id,
                    "name": summary.person_name,
                    "last_seen": summary.last_interaction.isoformat()
                    if summary.last_interaction
                    else None,
                    "counts": counts,
                    "reason": reason,
                }
            )

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "people": digest_people,
    }

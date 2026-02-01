"""
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

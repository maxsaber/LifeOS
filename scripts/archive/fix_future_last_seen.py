#!/usr/bin/env python3
"""
One-time script to fix PersonEntities with future last_seen dates.

These were caused by calendar events scheduled in the future being used
to set last_seen. This script recalculates last_seen from actual past
interactions.

Usage:
    uv run python scripts/fix_future_last_seen.py          # Dry run
    uv run python scripts/fix_future_last_seen.py --execute  # Apply fixes
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import sqlite3
import logging
from datetime import datetime, timezone

from api.services.person_entity import get_person_entity_store
from api.services.interaction_store import get_interaction_db_path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def get_last_interaction_date(person_id: str, now: datetime) -> datetime | None:
    """Get the most recent interaction date for a person (excluding future dates)."""
    int_db = get_interaction_db_path()
    conn = sqlite3.connect(int_db)
    try:
        cursor = conn.execute(
            """
            SELECT MAX(timestamp) FROM interactions
            WHERE person_id = ? AND timestamp <= ?
            """,
            (person_id, now.isoformat()),
        )
        row = cursor.fetchone()
        if row and row[0]:
            dt = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        return None
    finally:
        conn.close()


def fix_future_last_seen(dry_run: bool = True) -> dict:
    """Find and fix PersonEntities with future last_seen dates."""
    now = datetime.now(timezone.utc)
    store = get_person_entity_store()

    stats = {
        'total_checked': 0,
        'future_found': 0,
        'fixed': 0,
        'no_past_interactions': 0,
    }

    people_to_fix = []

    # Find people with future last_seen
    for person in store.get_all():
        stats['total_checked'] += 1

        if person.last_seen and person.last_seen > now:
            days_in_future = (person.last_seen - now).days
            stats['future_found'] += 1

            # Get the correct last_seen from interactions
            correct_last_seen = get_last_interaction_date(person.id, now)

            people_to_fix.append({
                'person': person,
                'old_last_seen': person.last_seen,
                'new_last_seen': correct_last_seen,
                'days_in_future': days_in_future,
            })

            logger.info(
                f"  {person.canonical_name}: last_seen={person.last_seen.date()} "
                f"({days_in_future} days in future) -> "
                f"{correct_last_seen.date() if correct_last_seen else 'None'}"
            )

    if not people_to_fix:
        logger.info("No people found with future last_seen dates.")
        return stats

    logger.info(f"\nFound {len(people_to_fix)} people with future last_seen dates.")

    if dry_run:
        logger.info("\nDRY RUN - no changes made. Use --execute to apply fixes.")
        return stats

    # Apply fixes
    for item in people_to_fix:
        person = item['person']
        new_last_seen = item['new_last_seen']

        if new_last_seen:
            person.last_seen = new_last_seen
            store.update(person)
            stats['fixed'] += 1
        else:
            # No past interactions - set to first_seen or None
            person.last_seen = person.first_seen
            store.update(person)
            stats['no_past_interactions'] += 1
            logger.warning(f"  {person.canonical_name}: No past interactions, set to first_seen")

    store.save()
    logger.info(f"\nFixed {stats['fixed']} people, {stats['no_past_interactions']} had no past interactions.")

    return stats


def main():
    parser = argparse.ArgumentParser(description='Fix PersonEntities with future last_seen dates')
    parser.add_argument('--execute', action='store_true', help='Actually apply fixes')
    args = parser.parse_args()

    logger.info("Scanning for people with future last_seen dates...\n")
    stats = fix_future_last_seen(dry_run=not args.execute)

    logger.info(f"\nSummary:")
    logger.info(f"  Total checked: {stats['total_checked']}")
    logger.info(f"  Future dates found: {stats['future_found']}")
    if not args.execute:
        logger.info(f"  Would fix: {stats['future_found']}")
    else:
        logger.info(f"  Fixed: {stats['fixed']}")
        logger.info(f"  No past interactions: {stats['no_past_interactions']}")


if __name__ == '__main__':
    main()

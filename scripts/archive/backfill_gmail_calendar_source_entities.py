#!/usr/bin/env python3
"""
One-time backfill script to create source entities for existing gmail/calendar interactions.

This script creates SourceEntity records for interactions that exist but don't have
corresponding source entities. It mirrors the logic in sync_gmail_calendar_interactions.py.

After running, move this script to scripts/archive/.
"""
import sqlite3
import logging
import argparse
from datetime import datetime, timezone

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.services.interaction_store import get_interaction_db_path
from api.services.source_entity import (
    get_source_entity_store,
    get_crm_db_path,
    create_gmail_source_entity,
    create_calendar_source_entity,
)
from api.services.person_entity import get_person_entity_store

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def backfill_gmail_source_entities(dry_run: bool = True) -> dict:
    """
    Create source entities for existing gmail interactions.

    Returns:
        Stats dict
    """
    stats = {
        'interactions_found': 0,
        'source_entities_created': 0,
        'already_exists': 0,
        'no_person': 0,
        'errors': 0,
    }

    interactions_db = get_interaction_db_path()
    crm_db = get_crm_db_path()

    int_conn = sqlite3.connect(interactions_db)
    crm_conn = sqlite3.connect(crm_db)
    source_entity_store = get_source_entity_store()
    person_store = get_person_entity_store()

    # Get existing gmail source entities to avoid duplicates
    existing_source_ids = set()
    cursor = crm_conn.execute(
        "SELECT source_id FROM source_entities WHERE source_type = 'gmail'"
    )
    for row in cursor.fetchall():
        existing_source_ids.add(row[0])
    logger.info(f"Found {len(existing_source_ids)} existing gmail source entities")

    # Get all gmail interactions
    cursor = int_conn.execute("""
        SELECT source_id, person_id, timestamp, title
        FROM interactions
        WHERE source_type = 'gmail'
    """)

    interactions = cursor.fetchall()
    stats['interactions_found'] = len(interactions)
    logger.info(f"Found {len(interactions)} gmail interactions to process")

    for source_id, person_id, timestamp, title in interactions:
        if not source_id:
            stats['errors'] += 1
            continue

        # Check if source entity already exists
        if source_id in existing_source_ids:
            stats['already_exists'] += 1
            continue

        # Get person to find their email
        person = person_store.get_by_id(person_id)
        if not person:
            stats['no_person'] += 1
            continue

        # Use person's primary email if available
        email = person.emails[0] if person.emails else None
        name = person.canonical_name

        try:
            timestamp_dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        except:
            timestamp_dt = datetime.now(timezone.utc)

        if not dry_run:
            source_entity = create_gmail_source_entity(
                message_id=source_id,
                sender_email=email or f"unknown-{person_id[:8]}@unknown",
                sender_name=name,
                observed_at=timestamp_dt,
                metadata={"subject": title[:100] if title else None, "backfilled": True},
            )
            source_entity.canonical_person_id = person_id
            source_entity.link_confidence = 1.0  # Direct from interaction
            source_entity.linked_at = datetime.now(timezone.utc)
            source_entity_store.add_or_update(source_entity)

        stats['source_entities_created'] += 1
        existing_source_ids.add(source_id)  # Track to avoid duplicates within run

    int_conn.close()
    crm_conn.close()

    return stats


def backfill_calendar_source_entities(dry_run: bool = True) -> dict:
    """
    Create source entities for existing calendar interactions.

    Returns:
        Stats dict
    """
    stats = {
        'interactions_found': 0,
        'source_entities_created': 0,
        'already_exists': 0,
        'no_person': 0,
        'errors': 0,
    }

    interactions_db = get_interaction_db_path()
    crm_db = get_crm_db_path()

    int_conn = sqlite3.connect(interactions_db)
    crm_conn = sqlite3.connect(crm_db)
    source_entity_store = get_source_entity_store()
    person_store = get_person_entity_store()

    # Get existing calendar source entities to avoid duplicates
    existing_source_ids = set()
    cursor = crm_conn.execute(
        "SELECT source_id FROM source_entities WHERE source_type = 'calendar'"
    )
    for row in cursor.fetchall():
        existing_source_ids.add(row[0])
    logger.info(f"Found {len(existing_source_ids)} existing calendar source entities")

    # Get all calendar interactions
    cursor = int_conn.execute("""
        SELECT source_id, person_id, timestamp, title
        FROM interactions
        WHERE source_type = 'calendar'
    """)

    interactions = cursor.fetchall()
    stats['interactions_found'] = len(interactions)
    logger.info(f"Found {len(interactions)} calendar interactions to process")

    for source_id, person_id, timestamp, title in interactions:
        if not source_id:
            stats['errors'] += 1
            continue

        # Check if source entity already exists
        if source_id in existing_source_ids:
            stats['already_exists'] += 1
            continue

        # Get person to find their email
        person = person_store.get_by_id(person_id)
        if not person:
            stats['no_person'] += 1
            continue

        # Use person's primary email if available
        email = person.emails[0] if person.emails else None
        name = person.canonical_name

        # Parse event_id from source_id (format: event_id:attendee_email)
        parts = source_id.split(':', 1)
        event_id = parts[0] if parts else source_id

        try:
            timestamp_dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        except:
            timestamp_dt = datetime.now(timezone.utc)

        if not dry_run:
            source_entity = create_calendar_source_entity(
                event_id=event_id,
                attendee_email=email or f"unknown-{person_id[:8]}@unknown",
                attendee_name=name,
                observed_at=timestamp_dt,
                metadata={"event_title": title[:100] if title else None, "backfilled": True},
            )
            source_entity.canonical_person_id = person_id
            source_entity.link_confidence = 1.0  # Direct from interaction
            source_entity.linked_at = datetime.now(timezone.utc)
            source_entity_store.add_or_update(source_entity)

        stats['source_entities_created'] += 1
        existing_source_ids.add(source_id)  # Track to avoid duplicates within run

    int_conn.close()
    crm_conn.close()

    return stats


def main():
    parser = argparse.ArgumentParser(description='Backfill gmail/calendar source entities')
    parser.add_argument('--execute', action='store_true', help='Actually apply changes')
    parser.add_argument('--gmail-only', action='store_true', help='Only backfill gmail')
    parser.add_argument('--calendar-only', action='store_true', help='Only backfill calendar')
    args = parser.parse_args()

    dry_run = not args.execute

    if not args.calendar_only:
        logger.info("\n=== Backfilling Gmail Source Entities ===")
        stats = backfill_gmail_source_entities(dry_run=dry_run)
        logger.info(f"Gmail: found={stats['interactions_found']}, created={stats['source_entities_created']}, exists={stats['already_exists']}, no_person={stats['no_person']}, errors={stats['errors']}")

    if not args.gmail_only:
        logger.info("\n=== Backfilling Calendar Source Entities ===")
        stats = backfill_calendar_source_entities(dry_run=dry_run)
        logger.info(f"Calendar: found={stats['interactions_found']}, created={stats['source_entities_created']}, exists={stats['already_exists']}, no_person={stats['no_person']}, errors={stats['errors']}")

    if dry_run:
        logger.info("\nDRY RUN - no changes made. Use --execute to apply.")


if __name__ == '__main__':
    main()

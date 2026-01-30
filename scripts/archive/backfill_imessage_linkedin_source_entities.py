#!/usr/bin/env python3
"""
One-time backfill script to create source entities for existing iMessage and LinkedIn data.

After running, move this script to scripts/archive/.
"""
import sqlite3
import csv
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.services.person_entity import get_person_entity_store
from api.services.source_entity import (
    get_source_entity_store,
    get_crm_db_path,
    create_imessage_source_entity,
    create_linkedin_source_entity,
)

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def backfill_imessage_source_entities(dry_run: bool = True) -> dict:
    """
    Create source entities for existing iMessage handles.

    Uses the imessage.db to find unique handles linked to persons.
    """
    stats = {
        'handles_found': 0,
        'source_entities_created': 0,
        'already_exists': 0,
        'no_person': 0,
        'errors': 0,
    }

    imessage_db = Path(__file__).parent.parent / "data" / "imessage.db"
    if not imessage_db.exists():
        logger.warning(f"iMessage DB not found: {imessage_db}")
        return stats

    crm_db = get_crm_db_path()
    imessage_conn = sqlite3.connect(imessage_db)
    crm_conn = sqlite3.connect(crm_db)
    source_entity_store = get_source_entity_store()
    person_store = get_person_entity_store()

    # Get existing iMessage source entities
    existing_source_ids = set()
    cursor = crm_conn.execute(
        "SELECT source_id FROM source_entities WHERE source_type = 'imessage'"
    )
    for row in cursor.fetchall():
        existing_source_ids.add(row[0])
    logger.info(f"Found {len(existing_source_ids)} existing iMessage source entities")

    # Get unique handles with person_entity_id from imessage.db
    cursor = imessage_conn.execute("""
        SELECT DISTINCT handle_normalized, person_entity_id, service
        FROM messages
        WHERE person_entity_id IS NOT NULL AND handle_normalized IS NOT NULL
    """)

    handles = cursor.fetchall()
    stats['handles_found'] = len(handles)
    logger.info(f"Found {len(handles)} unique iMessage handles to process")

    for handle, person_id, service in handles:
        if not handle:
            continue

        # Check if already exists
        if handle in existing_source_ids:
            stats['already_exists'] += 1
            continue

        # Verify person exists
        person = person_store.get_by_id(person_id)
        if not person:
            stats['no_person'] += 1
            continue

        if not dry_run:
            source_entity = create_imessage_source_entity(
                handle=handle,
                display_name=person.canonical_name,
                observed_at=datetime.now(timezone.utc),
                metadata={"service": service, "backfilled": True},
            )
            source_entity.canonical_person_id = person_id
            source_entity.link_confidence = 1.0
            source_entity.linked_at = datetime.now(timezone.utc)
            source_entity_store.add_or_update(source_entity)

        stats['source_entities_created'] += 1
        existing_source_ids.add(handle)

    imessage_conn.close()
    crm_conn.close()

    return stats


def backfill_linkedin_source_entities(dry_run: bool = True) -> dict:
    """
    Create source entities for existing LinkedIn connections.

    Uses the LinkedIn CSV and matches to existing persons.
    """
    stats = {
        'connections_found': 0,
        'source_entities_created': 0,
        'already_exists': 0,
        'no_person': 0,
        'errors': 0,
    }

    csv_path = Path(__file__).parent.parent / "data" / "LinkedInConnections.csv"
    if not csv_path.exists():
        logger.warning(f"LinkedIn CSV not found: {csv_path}")
        return stats

    crm_db = get_crm_db_path()
    crm_conn = sqlite3.connect(crm_db)
    source_entity_store = get_source_entity_store()
    person_store = get_person_entity_store()

    # Get existing LinkedIn source entities
    existing_source_ids = set()
    cursor = crm_conn.execute(
        "SELECT source_id FROM source_entities WHERE source_type = 'linkedin'"
    )
    for row in cursor.fetchall():
        existing_source_ids.add(row[0])
    logger.info(f"Found {len(existing_source_ids)} existing LinkedIn source entities")

    # Build a lookup map from name to person
    name_to_person = {}
    for person in person_store.get_all():
        name_lower = person.canonical_name.lower()
        name_to_person[name_lower] = person
        # Also add aliases
        for alias in (person.aliases or []):
            name_to_person[alias.lower()] = person

    # Read LinkedIn CSV
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            connections = list(reader)
    except Exception as e:
        logger.error(f"Failed to read LinkedIn CSV: {e}")
        return stats

    stats['connections_found'] = len(connections)
    logger.info(f"Found {len(connections)} LinkedIn connections to process")

    for conn in connections:
        first_name = conn.get("First Name", "").strip()
        last_name = conn.get("Last Name", "").strip()
        linkedin_url = conn.get("URL", "").strip()

        if not linkedin_url:
            continue

        # Check if already exists
        if linkedin_url in existing_source_ids:
            stats['already_exists'] += 1
            continue

        # Try to find matching person
        full_name = f"{first_name} {last_name}".strip().lower()
        person = name_to_person.get(full_name)

        if not person:
            stats['no_person'] += 1
            continue

        # Parse connected date
        connected_on = conn.get("Connected On", "")
        try:
            connected_at = datetime.strptime(connected_on, "%d %b %Y") if connected_on else None
            if connected_at:
                connected_at = connected_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            connected_at = None

        if not dry_run:
            source_entity = create_linkedin_source_entity(
                profile_url=linkedin_url,
                name=f"{first_name} {last_name}".strip(),
                email=conn.get("Email Address"),
                observed_at=connected_at,
                metadata={
                    "company": conn.get("Company"),
                    "position": conn.get("Position"),
                    "backfilled": True,
                },
            )
            source_entity.canonical_person_id = person.id
            source_entity.link_confidence = 1.0
            source_entity.linked_at = datetime.now(timezone.utc)
            source_entity_store.add_or_update(source_entity)

        stats['source_entities_created'] += 1
        existing_source_ids.add(linkedin_url)

    crm_conn.close()

    return stats


def main():
    parser = argparse.ArgumentParser(description='Backfill iMessage/LinkedIn source entities')
    parser.add_argument('--execute', action='store_true', help='Actually apply changes')
    parser.add_argument('--imessage-only', action='store_true', help='Only backfill iMessage')
    parser.add_argument('--linkedin-only', action='store_true', help='Only backfill LinkedIn')
    args = parser.parse_args()

    dry_run = not args.execute

    if not args.linkedin_only:
        logger.info("\n=== Backfilling iMessage Source Entities ===")
        stats = backfill_imessage_source_entities(dry_run=dry_run)
        logger.info(f"iMessage: found={stats['handles_found']}, created={stats['source_entities_created']}, exists={stats['already_exists']}, no_person={stats['no_person']}")

    if not args.imessage_only:
        logger.info("\n=== Backfilling LinkedIn Source Entities ===")
        stats = backfill_linkedin_source_entities(dry_run=dry_run)
        logger.info(f"LinkedIn: found={stats['connections_found']}, created={stats['source_entities_created']}, exists={stats['already_exists']}, no_person={stats['no_person']}")

    if dry_run:
        logger.info("\nDRY RUN - no changes made. Use --execute to apply.")


if __name__ == '__main__':
    main()

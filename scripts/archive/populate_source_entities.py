#!/usr/bin/env python3
"""
Populate source_entities table from various data sources.

This script creates SourceEntity records from:
1. Interactions (gmail, calendar, vault, granola, imessage)
2. PersonEntity sources (phone_contacts, linkedin, etc.)

Part of Phase 1 of the CRM two-tier data model.
"""
import sqlite3
import json
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path

from api.services.person_entity import get_person_entity_store
from api.services.interaction_store import get_interaction_db_path
from api.services.source_entity import get_crm_db_path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def populate_source_entities(dry_run: bool = True) -> dict:
    """
    Populate source_entities table from various sources.

    Args:
        dry_run: If True, don't actually insert anything

    Returns:
        Stats dict
    """
    crm_db = get_crm_db_path()
    interactions_db = get_interaction_db_path()
    person_store = get_person_entity_store()

    stats = {
        'from_interactions': 0,
        'from_person_sources': 0,
        'already_exists': 0,
        'total_inserted': 0,
    }

    crm_conn = sqlite3.connect(crm_db)
    interactions_conn = sqlite3.connect(interactions_db)

    # Get existing source entities to avoid duplicates
    existing = set()
    cursor = crm_conn.execute("SELECT source_type, source_id FROM source_entities")
    for row in cursor.fetchall():
        existing.add((row[0], row[1]))
    logger.info(f"Found {len(existing)} existing source entities")

    batch = []
    batch_size = 500

    # 1. Create source entities from interactions
    logger.info("Processing interactions...")
    cursor = interactions_conn.execute("""
        SELECT DISTINCT person_id, source_type, source_id, title, timestamp
        FROM interactions
        WHERE source_id IS NOT NULL
    """)

    for row in cursor.fetchall():
        person_id, source_type, source_id, title, timestamp = row

        # Create unique key
        key = (source_type, source_id)
        if key in existing:
            stats['already_exists'] += 1
            continue
        existing.add(key)

        # Extract observed data from source_id where possible
        # Gmail/Calendar source_ids have format: "message_id:email@domain.com"
        observed_email = None
        observed_phone = None

        if source_type in ('gmail', 'calendar') and ':' in source_id:
            # Parse email from source_id
            parts = source_id.split(':', 1)
            if len(parts) == 2 and '@' in parts[1]:
                observed_email = parts[1].lower()

        # For Gmail without email in source_id, skip creating source entity
        # (these are low-confidence name-only matches we don't want)
        if source_type == 'gmail' and not observed_email:
            stats['skipped_no_email'] = stats.get('skipped_no_email', 0) + 1
            continue

        # Get person details for name (and fallback email/phone for non-gmail types)
        person = person_store.get_by_id(person_id)
        observed_name = person.canonical_name if person else None

        # For non-gmail/calendar types, get email/phone from person if not parsed
        if not observed_email and source_type not in ('gmail', 'calendar'):
            observed_email = person.primary_email if person else None
        if source_type not in ('gmail', 'calendar'):
            observed_phone = person.phone_primary if person else None

        # Parse timestamp
        try:
            observed_at = datetime.fromisoformat(timestamp) if timestamp else datetime.now(timezone.utc)
        except (ValueError, TypeError):
            observed_at = datetime.now(timezone.utc)

        # Create source entity record
        entity_id = str(uuid.uuid4())
        batch.append((
            entity_id,
            source_type,
            source_id,
            observed_name,
            observed_email,
            observed_phone,
            json.dumps({'title': title}),  # metadata
            person_id,  # canonical_person_id
            1.0,  # link_confidence (high since from existing interaction)
            'auto',  # link_status
            datetime.now(timezone.utc).isoformat(),  # linked_at
            observed_at.isoformat() if hasattr(observed_at, 'isoformat') else observed_at,  # observed_at
        ))
        stats['from_interactions'] += 1

        if len(batch) >= batch_size:
            if not dry_run:
                _insert_batch(crm_conn, batch)
            logger.info(f"Processed {stats['from_interactions']} from interactions")
            batch = []

    # Insert remaining from interactions
    if batch:
        if not dry_run:
            _insert_batch(crm_conn, batch)
        batch = []

    # 2. Create source entities from PersonEntity sources (phone_contacts, linkedin)
    logger.info("Processing person sources...")
    for person in person_store.get_all():
        for source in person.sources:
            if source in ('gmail', 'calendar', 'vault', 'granola', 'imessage'):
                continue  # Already covered by interactions

            # Create source entity for this source
            source_id = f"{source}_{person.id}"
            key = (source, source_id)
            if key in existing:
                stats['already_exists'] += 1
                continue
            existing.add(key)

            # Build metadata
            metadata = {}
            if source == 'linkedin' and person.linkedin_url:
                metadata['linkedin_url'] = person.linkedin_url
            if source == 'phone_contacts':
                metadata['phones'] = person.phone_numbers

            entity_id = str(uuid.uuid4())
            batch.append((
                entity_id,
                source,
                source_id,
                person.canonical_name,
                person.primary_email,
                person.phone_primary,
                json.dumps(metadata),
                person.id,
                1.0,
                'auto',
                datetime.now(timezone.utc).isoformat(),
                person.first_seen.isoformat() if person.first_seen else datetime.now(timezone.utc).isoformat(),
            ))
            stats['from_person_sources'] += 1

    # Insert remaining from person sources
    if batch:
        if not dry_run:
            _insert_batch(crm_conn, batch)

    if not dry_run:
        crm_conn.commit()

    stats['total_inserted'] = stats['from_interactions'] + stats['from_person_sources']

    interactions_conn.close()
    crm_conn.close()

    logger.info(f"\n=== Source Entity Population Summary ===")
    logger.info(f"From interactions: {stats['from_interactions']}")
    logger.info(f"From person sources: {stats['from_person_sources']}")
    logger.info(f"Already existed: {stats['already_exists']}")
    logger.info(f"Skipped (gmail without email): {stats.get('skipped_no_email', 0)}")
    logger.info(f"Total inserted: {stats['total_inserted']}")

    if dry_run:
        logger.info("\nDRY RUN - no changes made")

    return stats


def _insert_batch(conn: sqlite3.Connection, batch: list):
    """Insert a batch of source entities."""
    conn.executemany("""
        INSERT OR IGNORE INTO source_entities
        (id, source_type, source_id, observed_name, observed_email, observed_phone,
         metadata, canonical_person_id, link_confidence, link_status, linked_at, observed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, batch)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Populate source_entities table')
    parser.add_argument('--execute', action='store_true', help='Actually apply changes')
    args = parser.parse_args()

    populate_source_entities(dry_run=not args.execute)

#!/usr/bin/env python3
"""
Populate relationships table from various signals.

Since each interaction is linked to one person, we use different signals:
1. Same company → coworkers
2. High message counts → close relationships
3. Shared vault contexts → may know each other
"""
import sqlite3
import uuid
import logging
from collections import defaultdict
from datetime import datetime, timezone

from api.services.person_entity import get_person_entity_store
from api.services.source_entity import get_crm_db_path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def populate_relationships(dry_run: bool = True) -> dict:
    """
    Populate relationships table from various signals.

    Args:
        dry_run: If True, don't actually insert anything

    Returns:
        Stats dict
    """
    crm_db = get_crm_db_path()
    person_store = get_person_entity_store()

    stats = {
        'coworkers': 0,
        'vault_shared': 0,
        'already_exists': 0,
        'total_inserted': 0,
    }

    crm_conn = sqlite3.connect(crm_db)

    # Get existing relationships
    existing = set()
    cursor = crm_conn.execute("SELECT person_a_id, person_b_id FROM relationships")
    for row in cursor.fetchall():
        existing.add((row[0], row[1]))
        existing.add((row[1], row[0]))  # Both directions
    logger.info(f"Found {len(existing)//2} existing relationships")

    batch = []

    # 1. Discover coworkers (same company)
    logger.info("Discovering coworkers by company...")
    company_people: dict[str, list] = defaultdict(list)
    for person in person_store.get_all():
        if person.company:
            company_people[person.company.lower()].append(person)

    for company, people in company_people.items():
        if len(people) < 2:
            continue
        if len(people) > 50:  # Skip very large companies
            continue

        # Create relationships between people in same company
        for i, person_a in enumerate(people):
            for person_b in people[i + 1:]:
                pair = (min(person_a.id, person_b.id), max(person_a.id, person_b.id))
                if pair in existing:
                    stats['already_exists'] += 1
                    continue
                existing.add(pair)

                rel_id = str(uuid.uuid4())
                batch.append((
                    rel_id,
                    pair[0],
                    pair[1],
                    'coworker',
                    f'["{company}"]',  # shared_contexts
                    0,  # shared_events_count
                    0,  # shared_threads_count
                    datetime.now(timezone.utc).isoformat(),  # first_seen
                    datetime.now(timezone.utc).isoformat(),  # last_seen
                ))
                stats['coworkers'] += 1

    # 2. Discover relationships from shared vault contexts
    logger.info("Discovering relationships by vault context...")
    context_people: dict[str, list] = defaultdict(list)
    for person in person_store.get_all():
        for context in person.vault_contexts:
            if context:
                context_people[context].append(person)

    for context, people in context_people.items():
        if len(people) < 2:
            continue
        if len(people) > 20:  # Skip very broad contexts
            continue

        for i, person_a in enumerate(people):
            for person_b in people[i + 1:]:
                pair = (min(person_a.id, person_b.id), max(person_a.id, person_b.id))
                if pair in existing:
                    stats['already_exists'] += 1
                    continue
                existing.add(pair)

                rel_id = str(uuid.uuid4())
                batch.append((
                    rel_id,
                    pair[0],
                    pair[1],
                    'inferred',
                    f'["{context}"]',
                    0,
                    0,
                    datetime.now(timezone.utc).isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                ))
                stats['vault_shared'] += 1

    # Insert batch
    if batch and not dry_run:
        crm_conn.executemany("""
            INSERT OR IGNORE INTO relationships
            (id, person_a_id, person_b_id, relationship_type, shared_contexts,
             shared_events_count, shared_threads_count, first_seen_together, last_seen_together)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, batch)
        crm_conn.commit()

    stats['total_inserted'] = stats['coworkers'] + stats['vault_shared']

    crm_conn.close()

    logger.info(f"\n=== Relationship Population Summary ===")
    logger.info(f"Coworkers: {stats['coworkers']}")
    logger.info(f"Vault shared: {stats['vault_shared']}")
    logger.info(f"Already existed: {stats['already_exists']}")
    logger.info(f"Total inserted: {stats['total_inserted']}")

    if dry_run:
        logger.info("\nDRY RUN - no changes made")

    return stats


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Populate relationships table')
    parser.add_argument('--execute', action='store_true', help='Actually apply changes')
    args = parser.parse_args()

    populate_relationships(dry_run=not args.execute)

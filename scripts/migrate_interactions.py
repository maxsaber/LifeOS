#!/usr/bin/env python3
"""
Migrate orphaned interactions to current PersonEntity IDs.

This script fixes the data integrity issue where interactions reference
person_ids that no longer exist in the PersonEntityStore.

For each orphaned person_id:
1. Find representative interactions to extract names
2. Use EntityResolver to find matching current PersonEntity
3. Update all interactions with correct person_id
"""
import sqlite3
import logging
import re
from collections import defaultdict
from pathlib import Path

from api.services.person_entity import get_person_entity_store, PersonEntity
from api.services.entity_resolver import get_entity_resolver
from api.services.interaction_store import get_interaction_db_path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def extract_person_name_from_title(title: str) -> str | None:
    """
    Extract a person's name from an interaction title.

    Patterns:
    - "Meeting with John Smith" -> "John Smith"
    - "Call: Jane Doe" -> "Jane Doe"
    - "1:1 with Bob" -> "Bob"
    - "Personal - Taylor pre-therapy conversation" -> "Taylor"
    - Just a name like "Taylor" -> "Taylor"
    """
    if not title:
        return None

    # Common meeting title patterns
    patterns = [
        r"(?:Meeting|Call|1:1|1-on-1|sync|chat) (?:with|w/) (.+?)(?:\s*[-–]|\s*\d{8}|$)",
        r"^(?:Personal|Work)\s*[-–]\s*(.+?)\s+(?:pre-|meeting|call|chat|conversation)",
        r"^([A-Z][a-z]+(?: [A-Z][a-z]+)*)\s*[-–]",  # "Name - something"
        r"^([A-Z][a-z]+(?: [A-Z][a-z]+)*)$",  # Just a name
    ]

    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            # Filter out non-names
            if len(name) > 1 and not name.lower() in ['meeting', 'call', 'sync', 'chat', 'the']:
                return name

    # If title looks like just a name (1-3 capitalized words)
    words = title.split()
    if 1 <= len(words) <= 3 and all(w[0].isupper() for w in words if w):
        return title.strip()

    return None


def get_orphaned_person_ids(conn: sqlite3.Connection, entity_ids: set[str]) -> dict[str, list[dict]]:
    """
    Get all orphaned person_ids with their representative interactions.

    Returns:
        Dict mapping orphaned person_id to list of interaction samples
    """
    cursor = conn.execute("""
        SELECT person_id, title, source_type, timestamp
        FROM interactions
        ORDER BY person_id, timestamp DESC
    """)

    orphaned = defaultdict(list)
    for row in cursor.fetchall():
        person_id, title, source_type, timestamp = row
        if person_id not in entity_ids:
            orphaned[person_id].append({
                'title': title,
                'source_type': source_type,
                'timestamp': timestamp,
            })

    return dict(orphaned)


def find_matching_entity(
    interactions: list[dict],
    resolver,
    store,
) -> PersonEntity | None:
    """
    Find a matching PersonEntity for a set of interactions.

    Tries to extract a name from interaction titles and resolve it.
    """
    # Collect candidate names from titles
    candidate_names = []
    for interaction in interactions[:10]:  # Check first 10 interactions
        name = extract_person_name_from_title(interaction['title'])
        if name:
            candidate_names.append(name)

    if not candidate_names:
        return None

    # Try each candidate name
    for name in candidate_names:
        # First try exact match in store
        entity = store.get_by_name(name)
        if entity:
            return entity

        # Try resolution (without creating new)
        result = resolver.resolve(name=name, create_if_missing=False)
        if result and result.entity:
            return result.entity

    return None


def migrate_interactions(dry_run: bool = True) -> dict:
    """
    Main migration function.

    Args:
        dry_run: If True, don't actually modify the database

    Returns:
        Stats dict
    """
    store = get_person_entity_store()
    resolver = get_entity_resolver()
    db_path = get_interaction_db_path()

    conn = sqlite3.connect(db_path)

    # Get current entity IDs
    entity_ids = {e.id for e in store.get_all()}
    logger.info(f"Found {len(entity_ids)} PersonEntity records")

    # Find orphaned person_ids
    orphaned = get_orphaned_person_ids(conn, entity_ids)
    logger.info(f"Found {len(orphaned)} orphaned person_ids")

    stats = {
        'orphaned_person_ids': len(orphaned),
        'matched': 0,
        'unmatched': 0,
        'interactions_updated': 0,
        'interactions_skipped': 0,
        'mapping': {},  # old_id -> new_id
    }

    for old_person_id, interactions in orphaned.items():
        # Try to find matching entity
        entity = find_matching_entity(interactions, resolver, store)

        if entity:
            stats['matched'] += 1
            stats['mapping'][old_person_id] = entity.id

            sample_title = interactions[0]['title'] if interactions else 'N/A'
            logger.info(f"Matched '{sample_title}' ({len(interactions)} interactions) -> {entity.display_name}")

            if not dry_run:
                # Update all interactions with this person_id
                cursor = conn.execute(
                    "UPDATE interactions SET person_id = ? WHERE person_id = ?",
                    (entity.id, old_person_id)
                )
                stats['interactions_updated'] += cursor.rowcount
        else:
            stats['unmatched'] += 1
            sample_title = interactions[0]['title'] if interactions else 'N/A'
            logger.warning(f"No match for '{sample_title}' ({len(interactions)} interactions)")
            stats['interactions_skipped'] += len(interactions)

    if not dry_run:
        conn.commit()
        logger.info(f"Committed {stats['interactions_updated']} interaction updates")
    else:
        logger.info("DRY RUN - no changes made")

    conn.close()

    # Summary
    logger.info(f"\n=== Migration Summary ===")
    logger.info(f"Orphaned person_ids: {stats['orphaned_person_ids']}")
    logger.info(f"Matched to entities: {stats['matched']}")
    logger.info(f"Unmatched: {stats['unmatched']}")
    if not dry_run:
        logger.info(f"Interactions updated: {stats['interactions_updated']}")
    logger.info(f"Interactions skipped: {stats['interactions_skipped']}")

    return stats


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Migrate orphaned interactions to current PersonEntity IDs')
    parser.add_argument('--execute', action='store_true', help='Actually perform the migration (default is dry run)')
    args = parser.parse_args()

    migrate_interactions(dry_run=not args.execute)

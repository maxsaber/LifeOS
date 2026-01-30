#!/usr/bin/env python3
"""
Fix Entity Resolution - Remove incorrectly linked vault interactions.

This script removes vault/granola interactions where the linked person
is NOT actually mentioned in the note content.
"""
import os
import sqlite3
import logging
from pathlib import Path

from api.services.person_entity import get_person_entity_store
from api.services.interaction_store import get_interaction_db_path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def fix_entity_resolution(dry_run: bool = True) -> dict:
    """
    Remove vault interactions where person isn't mentioned in the file.

    Args:
        dry_run: If True, don't actually delete anything

    Returns:
        Stats dict
    """
    store = get_person_entity_store()
    db_path = get_interaction_db_path()
    conn = sqlite3.connect(db_path)

    stats = {
        'checked': 0,
        'valid': 0,
        'invalid_removed': 0,
        'file_not_found': 0,
    }

    # Get all vault/granola interactions
    cursor = conn.execute("""
        SELECT id, person_id, source_id, title FROM interactions
        WHERE source_type IN ('vault', 'granola')
        AND source_id LIKE '/Users/%'
    """)

    to_delete = []

    for row in cursor.fetchall():
        interaction_id, person_id, source_id, title = row
        stats['checked'] += 1

        # Check if file exists
        if not os.path.exists(source_id):
            stats['file_not_found'] += 1
            to_delete.append(interaction_id)
            continue

        # Get person
        person = store.get_by_id(person_id)
        if not person:
            to_delete.append(interaction_id)
            continue

        # Build names to search for
        names_to_find = [person.canonical_name]
        if person.display_name and person.display_name != person.canonical_name:
            names_to_find.append(person.display_name)
        names_to_find.extend(person.aliases)

        # Read file content
        try:
            content = Path(source_id).read_text(encoding='utf-8').lower()
        except Exception:
            to_delete.append(interaction_id)
            continue

        # Check if any name appears in content
        found = False
        for name in names_to_find:
            if name and len(name) > 2:  # Skip very short names
                if name.lower() in content:
                    found = True
                    break

        if found:
            stats['valid'] += 1
        else:
            to_delete.append(interaction_id)
            if stats['invalid_removed'] < 20:
                logger.info(f"Invalid: {person.canonical_name} not in {title}")

    logger.info(f"\nChecked {stats['checked']} vault interactions")
    logger.info(f"Valid: {stats['valid']}")
    logger.info(f"To remove: {len(to_delete)}")

    if not dry_run and to_delete:
        # Delete in batches
        batch_size = 100
        for i in range(0, len(to_delete), batch_size):
            batch = to_delete[i:i+batch_size]
            placeholders = ','.join('?' * len(batch))
            conn.execute(f"DELETE FROM interactions WHERE id IN ({placeholders})", batch)

        conn.commit()
        stats['invalid_removed'] = len(to_delete)
        logger.info(f"Removed {len(to_delete)} invalid interactions")

    conn.close()

    if dry_run:
        logger.info("\nDRY RUN - no changes made")

    return stats


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Fix entity resolution')
    parser.add_argument('--execute', action='store_true', help='Actually apply changes')
    args = parser.parse_args()

    fix_entity_resolution(dry_run=not args.execute)

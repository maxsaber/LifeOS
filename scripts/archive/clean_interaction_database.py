#!/usr/bin/env python3
"""
Clean Interaction Database - Remove polluted/invalid data.

This script removes:
1. Test data (entries pointing to /tmp or /var/folders)
2. Entries pointing to non-existent files
3. Entries with orphaned person_ids

Run with --execute to apply changes, otherwise dry-run.
"""
import os
import sqlite3
import logging

from api.services.person_entity import get_person_entity_store
from api.services.interaction_store import get_interaction_db_path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def clean_database(dry_run: bool = True) -> dict:
    """
    Clean the interaction database.

    Args:
        dry_run: If True, don't actually delete anything

    Returns:
        Stats dict
    """
    db_path = get_interaction_db_path()
    conn = sqlite3.connect(db_path)

    stats = {
        'temp_data_removed': 0,
        'missing_files_removed': 0,
        'orphaned_person_ids_removed': 0,
        'total_before': 0,
        'total_after': 0,
    }

    # Get initial count
    cursor = conn.execute("SELECT COUNT(*) FROM interactions")
    stats['total_before'] = cursor.fetchone()[0]
    logger.info(f"Total interactions before: {stats['total_before']}")

    # 1. Remove test data (temp directories)
    cursor = conn.execute("""
        SELECT COUNT(*) FROM interactions
        WHERE source_id LIKE '/private/var/folders%'
           OR source_id LIKE '/tmp%'
           OR source_id LIKE '/var/%'
    """)
    temp_count = cursor.fetchone()[0]
    logger.info(f"Found {temp_count} test data entries to remove")

    if not dry_run and temp_count > 0:
        conn.execute("""
            DELETE FROM interactions
            WHERE source_id LIKE '/private/var/folders%'
               OR source_id LIKE '/tmp%'
               OR source_id LIKE '/var/%'
        """)
        stats['temp_data_removed'] = temp_count

    # 2. Remove entries pointing to non-existent files
    cursor = conn.execute("""
        SELECT id, source_id FROM interactions
        WHERE source_type IN ('vault', 'granola')
        AND source_id LIKE '/%'
    """)

    missing_file_ids = []
    for row in cursor.fetchall():
        interaction_id, source_id = row
        if not os.path.exists(source_id):
            missing_file_ids.append(interaction_id)

    logger.info(f"Found {len(missing_file_ids)} entries pointing to non-existent files")

    if not dry_run and missing_file_ids:
        placeholders = ','.join('?' * len(missing_file_ids))
        conn.execute(f"DELETE FROM interactions WHERE id IN ({placeholders})", missing_file_ids)
        stats['missing_files_removed'] = len(missing_file_ids)

    # 3. Remove entries with orphaned person_ids
    store = get_person_entity_store()
    entity_ids = {e.id for e in store.get_all()}

    cursor = conn.execute("SELECT DISTINCT person_id FROM interactions")
    interaction_person_ids = {row[0] for row in cursor.fetchall()}

    orphaned = interaction_person_ids - entity_ids
    logger.info(f"Found {len(orphaned)} orphaned person_ids")

    if not dry_run and orphaned:
        for orphan_id in orphaned:
            conn.execute("DELETE FROM interactions WHERE person_id = ?", (orphan_id,))
        stats['orphaned_person_ids_removed'] = len(orphaned)

    if not dry_run:
        conn.commit()
        logger.info("Changes committed")

    # Get final count
    cursor = conn.execute("SELECT COUNT(*) FROM interactions")
    stats['total_after'] = cursor.fetchone()[0]

    conn.close()

    logger.info(f"\n=== Cleanup Summary ===")
    logger.info(f"Test data removed: {stats['temp_data_removed']}")
    logger.info(f"Missing files removed: {stats['missing_files_removed']}")
    logger.info(f"Orphaned person_ids removed: {stats['orphaned_person_ids_removed']}")
    logger.info(f"Total before: {stats['total_before']}")
    logger.info(f"Total after: {stats['total_after']}")

    if dry_run:
        logger.info("\nDRY RUN - no changes made")

    return stats


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Clean interaction database')
    parser.add_argument('--execute', action='store_true', help='Actually apply changes')
    args = parser.parse_args()

    clean_database(dry_run=not args.execute)

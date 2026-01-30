#!/usr/bin/env python3
"""
Fix Taylor data integrity issue.

This script:
1. Merges duplicate PersonEntity records (Tay and Taylor Walker, MD, MPH)
2. Re-links orphaned interactions to the correct PersonEntity
"""
import sqlite3
import logging

from api.services.person_entity import get_person_entity_store
from api.services.interaction_store import get_interaction_db_path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def fix_taylor_data(dry_run: bool = True):
    """Fix Taylor data integrity."""
    store = get_person_entity_store()
    db_path = get_interaction_db_path()

    # Known IDs
    TAY_ID = "968f6f57-a8c4-43dc-8e5b-3983fdf4ad2c"  # Tay (phone_contacts)
    TAYLOR_WALKER_ID = "cb93e7bd-036c-4ef5-adb9-34a9147c4984"  # Taylor Walker (linkedin)
    ORPHANED_TAYLOR_ID = "cd43c8da-9a37-4d73-9c9e-f2c59a519697"  # Orphaned interactions

    # Get existing entities
    tay = store.get_by_id(TAY_ID)
    taylor_walker = store.get_by_id(TAYLOR_WALKER_ID)

    if not tay:
        logger.error(f"Tay entity not found: {TAY_ID}")
        return

    if not taylor_walker:
        logger.error(f"Taylor Walker entity not found: {TAYLOR_WALKER_ID}")
        return

    logger.info(f"Found Tay: {tay.canonical_name} (sources: {tay.sources})")
    logger.info(f"Found Taylor Walker: {taylor_walker.canonical_name} (sources: {taylor_walker.sources})")

    # Step 1: Merge Tay into Taylor Walker (keep Taylor Walker as canonical)
    logger.info("\n=== Step 1: Merging duplicate PersonEntity records ===")

    # Merge data from Tay into Taylor Walker
    merged = taylor_walker.merge(tay)

    # Update canonical name to be more recognizable
    merged.canonical_name = "Taylor Walker"
    merged.display_name = "Taylor Walker"

    # Add Tay as an alias
    if "Tay" not in merged.aliases:
        merged.aliases.append("Tay")
    if "Anne Taylor Walker" not in merged.aliases:
        merged.aliases.append("Anne Taylor Walker")

    logger.info(f"Merged entity: {merged.canonical_name}")
    logger.info(f"  Emails: {merged.emails}")
    logger.info(f"  Phones: {merged.phone_numbers}")
    logger.info(f"  Sources: {merged.sources}")
    logger.info(f"  Aliases: {merged.aliases}")

    if not dry_run:
        # Update Taylor Walker with merged data
        store.update(merged)
        # Delete Tay (duplicate)
        store.delete(TAY_ID)
        store.save()
        logger.info("Merged and saved PersonEntity changes")

    # Step 2: Re-link interactions
    logger.info("\n=== Step 2: Re-linking orphaned interactions ===")

    conn = sqlite3.connect(db_path)

    # Check current state
    cursor = conn.execute(
        "SELECT COUNT(*) FROM interactions WHERE person_id = ?",
        (ORPHANED_TAYLOR_ID,)
    )
    orphaned_count = cursor.fetchone()[0]
    logger.info(f"Orphaned Taylor interactions: {orphaned_count}")

    cursor = conn.execute(
        "SELECT COUNT(*) FROM interactions WHERE person_id = ?",
        (TAYLOR_WALKER_ID,)
    )
    existing_count = cursor.fetchone()[0]
    logger.info(f"Existing Taylor Walker interactions: {existing_count}")

    cursor = conn.execute(
        "SELECT COUNT(*) FROM interactions WHERE person_id = ?",
        (TAY_ID,)
    )
    tay_count = cursor.fetchone()[0]
    logger.info(f"Tay interactions: {tay_count}")

    if not dry_run:
        # Re-link orphaned interactions to Taylor Walker
        cursor = conn.execute(
            "UPDATE interactions SET person_id = ? WHERE person_id = ?",
            (TAYLOR_WALKER_ID, ORPHANED_TAYLOR_ID)
        )
        logger.info(f"Re-linked {cursor.rowcount} orphaned interactions to Taylor Walker")

        # Re-link Tay interactions to Taylor Walker (if any)
        cursor = conn.execute(
            "UPDATE interactions SET person_id = ? WHERE person_id = ?",
            (TAYLOR_WALKER_ID, TAY_ID)
        )
        logger.info(f"Re-linked {cursor.rowcount} Tay interactions to Taylor Walker")

        conn.commit()

    # Verify final state
    cursor = conn.execute(
        "SELECT COUNT(*) FROM interactions WHERE person_id = ?",
        (TAYLOR_WALKER_ID,)
    )
    final_count = cursor.fetchone()[0]
    logger.info(f"\nFinal Taylor Walker interaction count: {final_count}")

    conn.close()

    # Step 3: Update PersonEntity stats
    if not dry_run:
        logger.info("\n=== Step 3: Updating PersonEntity stats ===")
        conn = sqlite3.connect(db_path)

        # Count interactions by type
        cursor = conn.execute("""
            SELECT source_type, COUNT(*)
            FROM interactions
            WHERE person_id = ?
            GROUP BY source_type
        """, (TAYLOR_WALKER_ID,))

        stats = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()

        taylor = store.get_by_id(TAYLOR_WALKER_ID)
        if taylor:
            taylor.email_count = stats.get('gmail', 0)
            taylor.meeting_count = stats.get('calendar', 0)
            taylor.mention_count = stats.get('vault', 0) + stats.get('granola', 0)
            store.update(taylor)
            store.save()

            logger.info(f"Updated Taylor stats:")
            logger.info(f"  email_count: {taylor.email_count}")
            logger.info(f"  meeting_count: {taylor.meeting_count}")
            logger.info(f"  mention_count: {taylor.mention_count}")

    if dry_run:
        logger.info("\n=== DRY RUN - no changes made ===")
    else:
        logger.info("\n=== Changes applied successfully ===")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Fix Taylor data integrity')
    parser.add_argument('--execute', action='store_true', help='Actually apply changes')
    args = parser.parse_args()

    fix_taylor_data(dry_run=not args.execute)

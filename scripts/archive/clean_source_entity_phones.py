#!/usr/bin/env python3
"""
Clean up incorrectly propagated phone numbers from source entities.

This script fixes data corruption where phone numbers were incorrectly
assigned to source entities that shouldn't have them:

1. Vault source entities - should only have observed_name, never phone
2. Gmail source entities - should have observed_email, not observed_phone

After cleaning, the script re-runs entity resolution for affected entities
using the enhanced resolver that weighs relationship strength.

Usage:
    python scripts/clean_source_entity_phones.py --dry-run    # Preview changes
    python scripts/clean_source_entity_phones.py --execute    # Apply changes
"""
import argparse
import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_crm_db_path() -> Path:
    """Get path to CRM database."""
    return Path(__file__).parent.parent / "data" / "crm.db"


def analyze_corruption(conn: sqlite3.Connection) -> dict:
    """Analyze the scope of phone number corruption."""
    stats = {}

    # Vault entities with phones
    cursor = conn.execute("""
        SELECT COUNT(*) FROM source_entities
        WHERE source_type = 'vault' AND observed_phone IS NOT NULL
    """)
    stats['vault_with_phone'] = cursor.fetchone()[0]

    # Gmail entities with phone but no email
    cursor = conn.execute("""
        SELECT COUNT(*) FROM source_entities
        WHERE source_type = 'gmail'
        AND observed_phone IS NOT NULL
        AND observed_email IS NULL
    """)
    stats['gmail_phone_no_email'] = cursor.fetchone()[0]

    # Gmail entities with email (correct)
    cursor = conn.execute("""
        SELECT COUNT(*) FROM source_entities
        WHERE source_type = 'gmail' AND observed_email IS NOT NULL
    """)
    stats['gmail_with_email'] = cursor.fetchone()[0]

    # Distribution of phones in corrupted records
    cursor = conn.execute("""
        SELECT observed_phone, COUNT(*) as cnt
        FROM source_entities
        WHERE source_type IN ('vault', 'gmail')
        AND observed_phone IS NOT NULL
        AND (source_type = 'vault' OR observed_email IS NULL)
        GROUP BY observed_phone
        ORDER BY cnt DESC
        LIMIT 10
    """)
    stats['top_corrupted_phones'] = cursor.fetchall()

    return stats


def clean_vault_phones(conn: sqlite3.Connection, dry_run: bool) -> int:
    """Clear observed_phone from vault source entities."""
    if dry_run:
        cursor = conn.execute("""
            SELECT id, observed_name, observed_phone
            FROM source_entities
            WHERE source_type = 'vault' AND observed_phone IS NOT NULL
        """)
        affected = cursor.fetchall()
        logger.info(f"Would clear phone from {len(affected)} vault entities")
        for row in affected[:5]:
            logger.info(f"  - {row[1]} (phone: {row[2]})")
        if len(affected) > 5:
            logger.info(f"  ... and {len(affected) - 5} more")
        return len(affected)

    cursor = conn.execute("""
        UPDATE source_entities
        SET observed_phone = NULL
        WHERE source_type = 'vault' AND observed_phone IS NOT NULL
    """)
    affected = cursor.rowcount
    logger.info(f"Cleared phone from {affected} vault entities")
    return affected


def clean_gmail_phones(conn: sqlite3.Connection, dry_run: bool) -> int:
    """Clear observed_phone from gmail entities that have phone but no email."""
    if dry_run:
        cursor = conn.execute("""
            SELECT id, observed_name, observed_phone
            FROM source_entities
            WHERE source_type = 'gmail'
            AND observed_phone IS NOT NULL
            AND observed_email IS NULL
        """)
        affected = cursor.fetchall()
        logger.info(f"Would clear phone from {len(affected)} gmail entities (no email)")
        for row in affected[:5]:
            logger.info(f"  - {row[1]} (phone: {row[2]})")
        if len(affected) > 5:
            logger.info(f"  ... and {len(affected) - 5} more")
        return len(affected)

    cursor = conn.execute("""
        UPDATE source_entities
        SET observed_phone = NULL
        WHERE source_type = 'gmail'
        AND observed_phone IS NOT NULL
        AND observed_email IS NULL
    """)
    affected = cursor.rowcount
    logger.info(f"Cleared phone from {affected} gmail entities")
    return affected


def get_affected_person_ids(conn: sqlite3.Connection) -> set[str]:
    """Get person IDs that have affected source entities."""
    cursor = conn.execute("""
        SELECT DISTINCT canonical_person_id
        FROM source_entities
        WHERE source_type IN ('vault', 'gmail')
        AND observed_phone IS NOT NULL
        AND (source_type = 'vault' OR observed_email IS NULL)
        AND canonical_person_id IS NOT NULL
    """)
    return {row[0] for row in cursor.fetchall()}


def rerun_entity_resolution(conn: sqlite3.Connection, dry_run: bool) -> dict:
    """
    Re-run entity resolution for source entities that now only have names.

    After clearing phones, these entities need to be re-resolved using
    the enhanced name-based resolution that considers relationship strength.
    """
    from api.services.entity_resolver import get_entity_resolver
    from api.services.source_entity import LINK_STATUS_AUTO

    resolver = get_entity_resolver()

    # Get entities that now only have observed_name (no email, no phone)
    cursor = conn.execute("""
        SELECT id, source_type, observed_name, canonical_person_id, source_id
        FROM source_entities
        WHERE observed_name IS NOT NULL
        AND observed_email IS NULL
        AND observed_phone IS NULL
        AND source_type IN ('vault', 'gmail')
    """)

    name_only_entities = cursor.fetchall()
    logger.info(f"Found {len(name_only_entities)} name-only entities to re-resolve")

    stats = {
        'total': len(name_only_entities),
        'resolved_same': 0,
        'resolved_different': 0,
        'resolved_new': 0,
        'unresolved': 0,
    }

    changes = []  # Track changes for applying later

    for entity_id, source_type, observed_name, current_person_id, source_id in name_only_entities:
        if not observed_name:
            continue

        # Get context path for vault entities
        context_path = source_id if source_type == 'vault' else None

        # Resolve using enhanced resolver
        result = resolver.resolve(
            name=observed_name,
            context_path=context_path,
            create_if_missing=False,  # Don't create new entities during cleanup
        )

        if result and result.entity:
            new_person_id = result.entity.id
            if new_person_id == current_person_id:
                stats['resolved_same'] += 1
            else:
                stats['resolved_different'] += 1
                changes.append((entity_id, new_person_id, result.confidence))
                if not dry_run:
                    logger.debug(
                        f"Re-linking '{observed_name}' from {current_person_id[:8]}... "
                        f"to {new_person_id[:8]}... ({result.entity.canonical_name})"
                    )
        else:
            stats['unresolved'] += 1

    if not dry_run and changes:
        # Apply changes
        for entity_id, new_person_id, confidence in changes:
            conn.execute("""
                UPDATE source_entities
                SET canonical_person_id = ?,
                    link_confidence = ?,
                    link_status = ?,
                    linked_at = ?
                WHERE id = ?
            """, (
                new_person_id,
                confidence,
                LINK_STATUS_AUTO,
                datetime.now(timezone.utc).isoformat(),
                entity_id,
            ))
        logger.info(f"Applied {len(changes)} entity re-linkings")
    elif dry_run and changes:
        logger.info(f"Would re-link {len(changes)} entities to different persons")
        for entity_id, new_person_id, confidence in changes[:10]:
            cursor = conn.execute(
                "SELECT observed_name FROM source_entities WHERE id = ?",
                (entity_id,)
            )
            name = cursor.fetchone()[0]
            logger.info(f"  - '{name}' -> new person {new_person_id[:8]}...")
        if len(changes) > 10:
            logger.info(f"  ... and {len(changes) - 10} more")

    return stats


def update_person_phone_numbers(conn: sqlite3.Connection, dry_run: bool) -> int:
    """
    Update PersonEntity phone_numbers to match their remaining source entities.

    After cleaning, some persons may have stale phone numbers in their
    PersonEntity record that no longer have source entities.
    """
    from api.services.person_entity import get_person_entity_store

    store = get_person_entity_store()
    updated = 0

    for person in store.get_all():
        # Get phones still linked via source entities
        cursor = conn.execute("""
            SELECT DISTINCT observed_phone
            FROM source_entities
            WHERE canonical_person_id = ?
            AND observed_phone IS NOT NULL
        """, (person.id,))
        actual_phones = {row[0] for row in cursor.fetchall()}

        current_phones = set(person.phone_numbers)

        if actual_phones != current_phones:
            if dry_run:
                logger.info(
                    f"Would update {person.canonical_name}: "
                    f"phones {list(current_phones)} -> {list(actual_phones)}"
                )
            else:
                person.phone_numbers = list(actual_phones)
                person.phone_primary = person.phone_numbers[0] if person.phone_numbers else None
                store.update(person)
            updated += 1

    if not dry_run and updated > 0:
        store.save()
        logger.info(f"Updated phone_numbers for {updated} persons")

    return updated


def main():
    parser = argparse.ArgumentParser(
        description="Clean up incorrectly propagated phone numbers from source entities"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help="Preview changes without applying them"
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help="Apply changes to the database"
    )
    parser.add_argument(
        '--skip-resolution',
        action='store_true',
        help="Skip re-running entity resolution (just clean phones)"
    )

    args = parser.parse_args()

    if not args.dry_run and not args.execute:
        parser.error("Must specify either --dry-run or --execute")

    dry_run = args.dry_run

    db_path = get_crm_db_path()
    logger.info(f"Using database: {db_path}")

    conn = sqlite3.connect(db_path)

    try:
        # Analyze current state
        logger.info("=" * 60)
        logger.info("ANALYZING DATA CORRUPTION")
        logger.info("=" * 60)

        stats = analyze_corruption(conn)
        logger.info(f"Vault entities with phone (should be 0): {stats['vault_with_phone']}")
        logger.info(f"Gmail entities with phone but no email: {stats['gmail_phone_no_email']}")
        logger.info(f"Gmail entities with email (correct): {stats['gmail_with_email']}")

        if stats['top_corrupted_phones']:
            logger.info("Top corrupted phone numbers:")
            for phone, count in stats['top_corrupted_phones']:
                logger.info(f"  {phone}: {count} entities")

        # Get affected person IDs before cleaning
        affected_persons = get_affected_person_ids(conn)
        logger.info(f"Affected person IDs: {len(affected_persons)}")

        # Clean vault phones
        logger.info("")
        logger.info("=" * 60)
        logger.info("STEP 1: CLEAN VAULT PHONE NUMBERS")
        logger.info("=" * 60)
        vault_cleaned = clean_vault_phones(conn, dry_run)

        # Clean gmail phones
        logger.info("")
        logger.info("=" * 60)
        logger.info("STEP 2: CLEAN GMAIL PHONE NUMBERS")
        logger.info("=" * 60)
        gmail_cleaned = clean_gmail_phones(conn, dry_run)

        if not dry_run:
            conn.commit()

        # Re-run entity resolution
        if not args.skip_resolution:
            logger.info("")
            logger.info("=" * 60)
            logger.info("STEP 3: RE-RUN ENTITY RESOLUTION")
            logger.info("=" * 60)
            resolution_stats = rerun_entity_resolution(conn, dry_run)
            logger.info(f"Resolution stats: {resolution_stats}")

            if not dry_run:
                conn.commit()

        # Update person phone_numbers
        logger.info("")
        logger.info("=" * 60)
        logger.info("STEP 4: UPDATE PERSON PHONE NUMBERS")
        logger.info("=" * 60)
        persons_updated = update_person_phone_numbers(conn, dry_run)

        # Summary
        logger.info("")
        logger.info("=" * 60)
        logger.info("SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Vault entities cleaned: {vault_cleaned}")
        logger.info(f"Gmail entities cleaned: {gmail_cleaned}")
        logger.info(f"Persons phone_numbers updated: {persons_updated}")

        if dry_run:
            logger.info("")
            logger.info("DRY RUN - no changes applied. Use --execute to apply.")
        else:
            logger.info("")
            logger.info("Changes applied successfully.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()

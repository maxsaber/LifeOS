#!/usr/bin/env python3
"""
Sync iMessage data to the interactions database.

This script reads linked messages from imessage.db and creates
Interaction records so they appear in person timelines.
"""
import sqlite3
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from api.services.interaction_store import get_interaction_db_path
from api.services.person_entity import get_person_entity_store

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def get_imessage_db_path() -> str:
    """Get path to iMessage export database."""
    return str(Path(__file__).parent.parent / "data" / "imessage.db")


def sync_imessage_interactions(dry_run: bool = True, limit: int = None) -> dict:
    """
    Sync iMessage data to interactions database.

    Args:
        dry_run: If True, don't actually insert anything
        limit: Max messages to process (for testing)

    Returns:
        Stats dict
    """
    imessage_db = get_imessage_db_path()
    interactions_db = get_interaction_db_path()
    person_store = get_person_entity_store()

    stats = {
        'messages_checked': 0,
        'already_exists': 0,
        'person_not_found': 0,
        'inserted': 0,
        'errors': 0,
    }

    # Connect to both databases
    imessage_conn = sqlite3.connect(imessage_db)
    interactions_conn = sqlite3.connect(interactions_db)

    # Get existing iMessage interactions to avoid duplicates
    existing = set()
    cursor = interactions_conn.execute(
        "SELECT source_id FROM interactions WHERE source_type = 'imessage'"
    )
    for row in cursor.fetchall():
        existing.add(row[0])

    logger.info(f"Found {len(existing)} existing iMessage interactions")

    # Get linked messages from iMessage database
    query = """
        SELECT rowid, text, timestamp, is_from_me, handle, handle_normalized,
               service, person_entity_id
        FROM messages
        WHERE person_entity_id IS NOT NULL
        ORDER BY timestamp DESC
    """
    if limit:
        query += f" LIMIT {limit}"

    cursor = imessage_conn.execute(query)

    batch = []
    batch_size = 500

    for row in cursor.fetchall():
        rowid, text, timestamp, is_from_me, handle, handle_normalized, service, person_id = row
        stats['messages_checked'] += 1

        # Create unique source_id from rowid
        source_id = f"imessage_{rowid}"

        # Skip if already exists
        if source_id in existing:
            stats['already_exists'] += 1
            continue

        # Verify person still exists
        person = person_store.get_by_id(person_id)
        if not person:
            stats['person_not_found'] += 1
            continue

        # Parse timestamp
        try:
            ts = datetime.fromisoformat(timestamp)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            stats['errors'] += 1
            continue

        # Create title from message text
        text_preview = (text or "").strip()
        if len(text_preview) > 100:
            text_preview = text_preview[:97] + "..."
        if not text_preview:
            text_preview = "[No text content]"

        # Direction indicator
        direction = "→" if is_from_me else "←"
        title = f"{direction} {text_preview}"

        # Create interaction record
        interaction_id = str(uuid.uuid4())
        batch.append((
            interaction_id,
            person_id,
            ts.isoformat(),
            'imessage',
            title,
            text[:200] if text else None,  # snippet
            '',  # source_link (no web link for iMessage)
            source_id,
            datetime.now(timezone.utc).isoformat(),
        ))

        # Insert in batches
        if len(batch) >= batch_size:
            if not dry_run:
                _insert_batch(interactions_conn, batch)
            stats['inserted'] += len(batch)
            logger.info(f"Processed {stats['messages_checked']} messages, inserted {stats['inserted']}")
            batch = []

    # Insert remaining
    if batch:
        if not dry_run:
            _insert_batch(interactions_conn, batch)
        stats['inserted'] += len(batch)

    if not dry_run:
        interactions_conn.commit()

    imessage_conn.close()
    interactions_conn.close()

    logger.info(f"\n=== iMessage Sync Summary ===")
    logger.info(f"Messages checked: {stats['messages_checked']}")
    logger.info(f"Already exists: {stats['already_exists']}")
    logger.info(f"Person not found: {stats['person_not_found']}")
    logger.info(f"Inserted: {stats['inserted']}")
    logger.info(f"Errors: {stats['errors']}")

    if dry_run:
        logger.info("\nDRY RUN - no changes made")

    return stats


def _insert_batch(conn: sqlite3.Connection, batch: list):
    """Insert a batch of interactions."""
    conn.executemany("""
        INSERT INTO interactions (id, person_id, timestamp, source_type, title, snippet, source_link, source_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, batch)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Sync iMessage to interactions')
    parser.add_argument('--execute', action='store_true', help='Actually apply changes')
    parser.add_argument('--limit', type=int, help='Limit number of messages (for testing)')
    args = parser.parse_args()

    sync_imessage_interactions(dry_run=not args.execute, limit=args.limit)

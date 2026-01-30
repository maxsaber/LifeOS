#!/usr/bin/env python3
"""
Clean up iMessage data quality issues in interactions database.

Fixes:
1. Removes garbled binary plist messages (NSArchiver serialization artifacts)
2. Strips reaction prefix markers (+V, +v, +?, etc.) from message text
3. Updates both snippet and title fields
"""
import sqlite3
import re
import logging
import argparse
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def get_interactions_db_path() -> str:
    """Get path to interactions database."""
    return str(Path(__file__).parent.parent / "data" / "interactions.db")


def cleanup_imessage_data(dry_run: bool = True) -> dict:
    """
    Clean up iMessage data quality issues.

    Args:
        dry_run: If True, don't actually modify data

    Returns:
        Stats dict
    """
    db_path = get_interactions_db_path()
    conn = sqlite3.connect(db_path)

    stats = {
        'binary_plist_deleted': 0,
        'file_transfer_deleted': 0,
        'empty_prefix_deleted': 0,
        'prefixes_stripped': 0,
        'url_artifacts_cleaned': 0,
        'total_examined': 0,
    }

    # Pattern for binary plist garbage - contains NSArchiver serialization markers
    binary_plist_pattern = r'classnameX.*classes.*NS(Value|Object|Array|Dictionary)'

    # Pattern for file transfer GUIDs
    file_transfer_pattern = r'__kIMFileTransferGUIDAttributeName'

    # Pattern for reaction prefixes: +V, +v, +?, etc. plus any symbol prefixes
    # Catches any single character after + at start (including space)
    prefix_pattern = r'^\+.(.+)$'

    # Pattern for URL encoding artifacts: Ghttps://...WHttpURL/ or 9https://...WHttpURL/
    # Also handles truncated URLs like ttps:// (missing h) and various suffixes
    url_artifact_pattern = r'^.?(h?ttps?://[^\s]+?)WHttpURL[./]?$'

    # 1. Delete binary plist garbage messages
    logger.info("Finding binary plist garbage messages...")
    cursor = conn.execute("""
        SELECT id, snippet FROM interactions
        WHERE source_type = 'imessage'
        AND (snippet LIKE '%classnameX%' OR snippet LIKE '%NSValue%' OR snippet LIKE '%NSObject%')
    """)

    binary_ids = []
    for row in cursor.fetchall():
        id_, snippet = row
        if snippet and re.search(binary_plist_pattern, snippet):
            binary_ids.append(id_)
            stats['binary_plist_deleted'] += 1

    logger.info(f"Found {len(binary_ids)} binary plist garbage messages")

    if binary_ids and not dry_run:
        # Delete in batches
        for i in range(0, len(binary_ids), 500):
            batch = binary_ids[i:i+500]
            placeholders = ','.join('?' * len(batch))
            conn.execute(f"DELETE FROM interactions WHERE id IN ({placeholders})", batch)
        conn.commit()
        logger.info(f"Deleted {len(binary_ids)} binary plist messages")

    # 2. Delete file transfer GUID messages
    logger.info("Finding file transfer GUID messages...")
    cursor = conn.execute("""
        SELECT id FROM interactions
        WHERE source_type = 'imessage'
        AND snippet LIKE '%__kIMFileTransferGUIDAttributeName%'
    """)

    file_transfer_ids = [row[0] for row in cursor.fetchall()]
    stats['file_transfer_deleted'] = len(file_transfer_ids)

    logger.info(f"Found {len(file_transfer_ids)} file transfer GUID messages")

    if file_transfer_ids and not dry_run:
        for i in range(0, len(file_transfer_ids), 500):
            batch = file_transfer_ids[i:i+500]
            placeholders = ','.join('?' * len(batch))
            conn.execute(f"DELETE FROM interactions WHERE id IN ({placeholders})", batch)
        conn.commit()
        logger.info(f"Deleted {len(file_transfer_ids)} file transfer messages")

    # 3. Delete empty prefix-only messages (just +X with no content)
    logger.info("Finding empty prefix-only messages...")
    cursor = conn.execute("""
        SELECT id FROM interactions
        WHERE source_type = 'imessage'
        AND snippet LIKE '+%'
        AND LENGTH(snippet) <= 2
    """)

    empty_prefix_ids = [row[0] for row in cursor.fetchall()]
    stats['empty_prefix_deleted'] = len(empty_prefix_ids)

    logger.info(f"Found {len(empty_prefix_ids)} empty prefix-only messages")

    if empty_prefix_ids and not dry_run:
        placeholders = ','.join('?' * len(empty_prefix_ids))
        conn.execute(f"DELETE FROM interactions WHERE id IN ({placeholders})", empty_prefix_ids)
        conn.commit()
        logger.info(f"Deleted {len(empty_prefix_ids)} empty prefix messages")

    # 4. Strip reaction prefixes from remaining messages (including symbol prefixes)
    logger.info("Finding messages with reaction prefixes...")
    # Use LIKE with + prefix to find candidates, then filter with regex
    cursor = conn.execute("""
        SELECT id, title, snippet FROM interactions
        WHERE source_type = 'imessage'
        AND (snippet LIKE '+%' OR title LIKE '%+%')
    """)

    updates = []
    for row in cursor.fetchall():
        id_, title, snippet = row
        stats['total_examined'] += 1

        new_snippet = snippet
        new_title = title
        needs_update = False

        # Strip prefix from snippet
        if snippet:
            match = re.match(prefix_pattern, snippet, re.DOTALL)
            if match:
                new_snippet = match.group(1)
                needs_update = True

        # Strip prefix from title (format is "→ +VMessage" or "← +VMessage")
        if title:
            # Match direction arrow followed by prefix (any char after +)
            title_match = re.match(r'^([←→]\s*)\+.(.+)$', title, re.DOTALL)
            if title_match:
                new_title = title_match.group(1) + title_match.group(2)
                needs_update = True

        if needs_update:
            updates.append((new_title, new_snippet, id_))
            stats['prefixes_stripped'] += 1

    logger.info(f"Found {stats['prefixes_stripped']} messages with prefixes to strip")

    if updates and not dry_run:
        conn.executemany(
            "UPDATE interactions SET title = ?, snippet = ? WHERE id = ?",
            updates
        )
        conn.commit()
        logger.info(f"Updated {len(updates)} messages")

    # 5. Clean URL encoding artifacts (Ghttps://...WHttpURL/)
    logger.info("Finding messages with URL encoding artifacts...")
    cursor = conn.execute("""
        SELECT id, title, snippet FROM interactions
        WHERE source_type = 'imessage'
        AND snippet LIKE '%WHttpURL%'
    """)

    url_updates = []
    for row in cursor.fetchall():
        id_, title, snippet = row
        new_snippet = snippet
        new_title = title
        needs_update = False

        # Clean URL artifacts from snippet
        if snippet:
            match = re.match(url_artifact_pattern, snippet)
            if match:
                new_snippet = match.group(1)  # Extract just the URL
                needs_update = True

        # Clean URL artifacts from title
        if title:
            title_match = re.match(r'^([←→]\s*).?(h?ttps?://[^\s]+?)WHttpURL[./]?$', title)
            if title_match:
                new_title = title_match.group(1) + title_match.group(2)
                needs_update = True

        if needs_update:
            url_updates.append((new_title, new_snippet, id_))
            stats['url_artifacts_cleaned'] += 1

    logger.info(f"Found {stats['url_artifacts_cleaned']} messages with URL artifacts to clean")

    if url_updates and not dry_run:
        conn.executemany(
            "UPDATE interactions SET title = ?, snippet = ? WHERE id = ?",
            url_updates
        )
        conn.commit()
        logger.info(f"Cleaned {len(url_updates)} URL artifact messages")

    conn.close()

    # Summary
    logger.info(f"\n=== iMessage Cleanup Summary ===")
    logger.info(f"Binary plist messages deleted: {stats['binary_plist_deleted']}")
    logger.info(f"File transfer messages deleted: {stats['file_transfer_deleted']}")
    logger.info(f"Empty prefix messages deleted: {stats['empty_prefix_deleted']}")
    logger.info(f"Reaction prefixes stripped: {stats['prefixes_stripped']}")
    logger.info(f"URL artifacts cleaned: {stats['url_artifacts_cleaned']}")
    total_cleaned = (stats['binary_plist_deleted'] + stats['file_transfer_deleted'] +
                     stats['empty_prefix_deleted'] + stats['prefixes_stripped'] + stats['url_artifacts_cleaned'])
    logger.info(f"Total messages cleaned: {total_cleaned}")

    if dry_run:
        logger.info("\nDRY RUN - no changes made. Use --execute to apply.")

    return stats


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Clean up iMessage data quality issues')
    parser.add_argument('--execute', action='store_true', help='Actually apply changes')
    args = parser.parse_args()

    cleanup_imessage_data(dry_run=not args.execute)

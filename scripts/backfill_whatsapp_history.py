#!/usr/bin/env python3
"""
Backfill WhatsApp history for groups with known members.

This script identifies groups where we know some members from messages,
then uses wacli to backfill more history to discover additional members.
"""
import sys
from pathlib import Path
import subprocess

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3
import argparse
import logging
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

WACLI_DB_PATH = Path.home() / ".wacli" / "wacli.db"
CRM_DB_PATH = Path(__file__).parent.parent / "data" / "crm.db"


def get_phone_to_person_mapping() -> dict[str, str]:
    """Get mapping of phone numbers to person IDs from source_entities."""
    conn = sqlite3.connect(CRM_DB_PATH)
    cursor = conn.execute("""
        SELECT DISTINCT observed_phone, canonical_person_id
        FROM source_entities
        WHERE observed_phone IS NOT NULL
        AND observed_phone != ''
        AND canonical_person_id IS NOT NULL
    """)

    mapping = {}
    for row in cursor:
        phone = row[0]
        person_id = row[1]
        normalized = phone.replace('+', '').lstrip('1')
        mapping[normalized] = person_id
        if not phone.startswith('+1'):
            mapping['1' + normalized] = person_id

    conn.close()
    return mapping


def get_groups_needing_backfill() -> list[dict]:
    """Find groups that have known members but might be missing others."""
    if not WACLI_DB_PATH.exists():
        logger.error(f"wacli.db not found at {WACLI_DB_PATH}")
        return []

    conn = sqlite3.connect(WACLI_DB_PATH)
    phone_to_person = get_phone_to_person_mapping()

    # Get message counts and unique senders per group
    cursor = conn.execute("""
        SELECT g.jid, g.name,
               COUNT(DISTINCT m.rowid) as message_count,
               COUNT(DISTINCT m.sender_jid) as sender_count
        FROM groups g
        LEFT JOIN messages m ON g.jid = m.chat_jid
        WHERE g.jid LIKE '%@g.us'
        GROUP BY g.jid
        ORDER BY message_count ASC
    """)

    groups_to_backfill = []
    for row in cursor:
        jid, name, msg_count, sender_count = row

        # Get known members in this group
        members_cursor = conn.execute("""
            SELECT DISTINCT sender_jid, sender_name
            FROM messages
            WHERE chat_jid = ?
            AND sender_jid IS NOT NULL
            AND sender_jid NOT LIKE '%@g.us'
        """, (jid,))

        known_members = []
        unknown_members = []
        for member_row in members_cursor:
            sender_jid, sender_name = member_row
            phone = sender_jid.split('@')[0] if '@' in sender_jid else sender_jid

            is_known = False
            for fmt in [phone, phone.lstrip('1'), '1' + phone.lstrip('1')]:
                if fmt in phone_to_person:
                    is_known = True
                    break

            if is_known:
                known_members.append(sender_name or phone)
            else:
                unknown_members.append(sender_name or phone)

        # Groups with at least 1 known member and few messages are candidates
        if known_members and msg_count < 50:
            groups_to_backfill.append({
                'jid': jid,
                'name': name or jid,
                'message_count': msg_count,
                'known_members': known_members,
                'unknown_members': unknown_members,
            })

    conn.close()
    return groups_to_backfill


def backfill_group(jid: str, dry_run: bool = True) -> bool:
    """Run wacli history backfill for a specific group."""
    if dry_run:
        logger.info(f"  Would run: wacli history backfill {jid}")
        return True

    try:
        result = subprocess.run(
            ['wacli', 'history', 'backfill', jid],
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode == 0:
            logger.info(f"  Backfill successful for {jid}")
            return True
        else:
            logger.error(f"  Backfill failed: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        logger.error(f"  Backfill timed out for {jid}")
        return False
    except Exception as e:
        logger.error(f"  Backfill error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Backfill WhatsApp history for groups with known members'
    )
    parser.add_argument('--execute', action='store_true',
                       help='Actually run wacli backfill (default: dry run)')
    parser.add_argument('--limit', type=int, default=10,
                       help='Max number of groups to backfill (default: 10)')
    parser.add_argument('--group', type=str,
                       help='Specific group JID to backfill')
    args = parser.parse_args()

    if args.group:
        logger.info(f"Backfilling specific group: {args.group}")
        backfill_group(args.group, dry_run=not args.execute)
        return

    groups = get_groups_needing_backfill()

    if not groups:
        logger.info("No groups found that need backfill")
        return

    logger.info(f"\n=== Groups needing history backfill ===")
    logger.info(f"Found {len(groups)} groups with known members but limited history\n")

    for i, group in enumerate(groups[:args.limit]):
        logger.info(f"{i+1}. {group['name']}")
        logger.info(f"   Messages: {group['message_count']}")
        logger.info(f"   Known members: {', '.join(group['known_members'])}")
        if group['unknown_members']:
            logger.info(f"   Unknown members: {', '.join(group['unknown_members'])}")

        backfill_group(group['jid'], dry_run=not args.execute)
        logger.info("")

    if not args.execute:
        logger.info("DRY RUN - use --execute to actually run wacli backfill")
        logger.info("\nTo backfill all groups, run:")
        logger.info("  uv run python scripts/backfill_whatsapp_history.py --execute")
        logger.info("\nAfter backfill, re-run relationship discovery:")
        logger.info("  uv run python scripts/discover_whatsapp_relationships.py --execute")


if __name__ == '__main__':
    main()

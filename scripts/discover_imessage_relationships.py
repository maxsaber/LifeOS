#!/usr/bin/env python3
"""
Discover relationships from iMessage group chats.

Reads the macOS Messages database to find group chat participants
and creates relationships between people who share group chats.
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3
import argparse
import logging
from collections import defaultdict
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

MESSAGES_DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"
CRM_DB_PATH = Path(__file__).parent.parent / "data" / "crm.db"


def normalize_phone(phone: str) -> str:
    """Normalize phone number for matching."""
    if not phone:
        return ""
    # Remove all non-digit characters
    digits = ''.join(c for c in phone if c.isdigit())
    # Remove leading 1 for US numbers
    if len(digits) == 11 and digits.startswith('1'):
        digits = digits[1:]
    return digits


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
        normalized = normalize_phone(phone)
        if normalized:
            mapping[normalized] = person_id

    conn.close()
    return mapping


def get_email_to_person_mapping() -> dict[str, str]:
    """Get mapping of emails to person IDs from source_entities."""
    conn = sqlite3.connect(CRM_DB_PATH)
    cursor = conn.execute("""
        SELECT DISTINCT observed_email, canonical_person_id
        FROM source_entities
        WHERE observed_email IS NOT NULL
        AND observed_email != ''
        AND canonical_person_id IS NOT NULL
    """)

    mapping = {}
    for row in cursor:
        email = row[0].lower()
        person_id = row[1]
        mapping[email] = person_id

    conn.close()
    return mapping


def get_group_chats() -> list[dict]:
    """Get group chats with their participants from Messages.app database."""
    if not MESSAGES_DB_PATH.exists():
        logger.error(f"Messages database not found at {MESSAGES_DB_PATH}")
        return []

    conn = sqlite3.connect(str(MESSAGES_DB_PATH))
    conn.row_factory = sqlite3.Row

    # Get group chats with 2+ participants
    query = """
        SELECT
            c.ROWID as chat_id,
            c.display_name,
            c.chat_identifier,
            h.id as handle_id
        FROM chat c
        JOIN chat_handle_join chj ON c.ROWID = chj.chat_id
        JOIN handle h ON chj.handle_id = h.ROWID
        WHERE c.ROWID IN (
            SELECT chat_id
            FROM chat_handle_join
            GROUP BY chat_id
            HAVING COUNT(*) >= 2
        )
        ORDER BY c.ROWID
    """

    cursor = conn.execute(query)

    # Group by chat
    chats = defaultdict(lambda: {'name': None, 'participants': []})
    for row in cursor:
        chat_id = row['chat_id']
        if not chats[chat_id]['name']:
            chats[chat_id]['name'] = row['display_name'] or row['chat_identifier']
        chats[chat_id]['participants'].append(row['handle_id'])

    conn.close()

    return [
        {'id': cid, 'name': data['name'], 'participants': data['participants']}
        for cid, data in chats.items()
    ]


def discover_relationships(dry_run: bool = True) -> dict:
    """
    Discover relationships from iMessage group chat membership.

    Returns:
        Statistics about discovered relationships
    """
    from api.services.relationship import (
        Relationship,
        get_relationship_store,
        TYPE_INFERRED,
    )
    from api.services.person_entity import get_person_entity_store

    phone_to_person = get_phone_to_person_mapping()
    email_to_person = get_email_to_person_mapping()
    chats = get_group_chats()

    logger.info(f"Found {len(phone_to_person)} phone-to-person mappings")
    logger.info(f"Found {len(email_to_person)} email-to-person mappings")
    logger.info(f"Found {len(chats)} iMessage group chats")

    relationship_store = get_relationship_store()
    person_store = get_person_entity_store()

    stats = {
        'chats_with_multiple_known': 0,
        'relationships_created': 0,
        'relationships_updated': 0,
        'unknown_handles': set(),
    }

    # For each group chat, find known members and create relationships
    for chat in chats:
        # Map participants to person IDs
        known_members = []
        for handle in chat['participants']:
            person_id = None

            # Try as phone number
            normalized_phone = normalize_phone(handle)
            if normalized_phone in phone_to_person:
                person_id = phone_to_person[normalized_phone]
            # Try as email
            elif '@' in handle and handle.lower() in email_to_person:
                person_id = email_to_person[handle.lower()]

            if person_id:
                person = person_store.get_by_id(person_id)
                if person:
                    known_members.append((person_id, person.canonical_name))
            else:
                stats['unknown_handles'].add(handle)

        # Skip chats with fewer than 2 known members
        if len(known_members) < 2:
            continue

        stats['chats_with_multiple_known'] += 1
        chat_name = chat['name'] or f"Chat {chat['id']}"
        logger.info(f"Chat '{chat_name}' has {len(known_members)} known members: {[m[1] for m in known_members]}")

        # Generate all pairs
        for i in range(len(known_members)):
            for j in range(i + 1, len(known_members)):
                person_a_id, name_a = known_members[i]
                person_b_id, name_b = known_members[j]

                # Normalize pair order
                if person_a_id > person_b_id:
                    person_a_id, person_b_id = person_b_id, person_a_id
                    name_a, name_b = name_b, name_a

                existing = relationship_store.get_between(person_a_id, person_b_id)

                if existing:
                    if "imessage" not in existing.shared_contexts:
                        existing.shared_contexts.append("imessage")
                        existing.last_seen_together = datetime.now(timezone.utc)
                        if not dry_run:
                            relationship_store.update(existing)
                        stats['relationships_updated'] += 1
                        logger.debug(f"  Updated: {name_a} <-> {name_b}")
                else:
                    if not dry_run:
                        rel = Relationship(
                            person_a_id=person_a_id,
                            person_b_id=person_b_id,
                            relationship_type=TYPE_INFERRED,
                            first_seen_together=datetime.now(timezone.utc),
                            last_seen_together=datetime.now(timezone.utc),
                            shared_contexts=["imessage"],
                        )
                        relationship_store.add(rel)
                    stats['relationships_created'] += 1
                    logger.info(f"  Created: {name_a} <-> {name_b}")

    # Summary
    logger.info(f"\n=== iMessage Relationship Discovery Summary ===")
    logger.info(f"Chats with 2+ known members: {stats['chats_with_multiple_known']}")
    logger.info(f"Relationships created: {stats['relationships_created']}")
    logger.info(f"Relationships updated: {stats['relationships_updated']}")
    logger.info(f"Unknown handles: {len(stats['unknown_handles'])}")

    if stats['unknown_handles'] and len(stats['unknown_handles']) <= 20:
        logger.info(f"Sample unknown handles: {sorted(list(stats['unknown_handles']))[:10]}")

    if dry_run:
        logger.info("\nDRY RUN - no changes made. Use --execute to apply.")

    # Convert set to list for JSON serialization
    stats['unknown_handles'] = list(stats['unknown_handles'])
    return stats


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Discover relationships from iMessage groups')
    parser.add_argument('--execute', action='store_true', help='Actually create relationships')
    args = parser.parse_args()

    discover_relationships(dry_run=not args.execute)

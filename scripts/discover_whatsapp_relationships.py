#!/usr/bin/env python3
"""
Discover relationships from WhatsApp group membership.

Reads the wacli database directly to find all group members and creates
relationships between people who share groups.
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
        # Normalize phone number (remove + and leading 1 for US numbers)
        normalized = phone.replace('+', '').lstrip('1')
        mapping[normalized] = person_id
        # Also store with leading 1
        if not phone.startswith('+1'):
            mapping['1' + normalized] = person_id

    conn.close()
    return mapping


def get_group_members_from_messages() -> dict[str, set[tuple[str, str]]]:
    """Get group members from message senders in wacli.db."""
    if not WACLI_DB_PATH.exists():
        logger.warning(f"wacli.db not found at {WACLI_DB_PATH}")
        return {}

    conn = sqlite3.connect(WACLI_DB_PATH)

    # Get all distinct senders per group from messages
    cursor = conn.execute("""
        SELECT DISTINCT chat_jid, sender_name, sender_jid
        FROM messages
        WHERE chat_jid LIKE '%@g.us'
        AND sender_jid IS NOT NULL
        AND sender_jid NOT LIKE '%@g.us'
        AND sender_name IS NOT NULL
        AND sender_name != ''
        AND sender_name != 'me'
    """)

    groups: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for row in cursor:
        group_jid = row[0]
        sender_name = row[1]
        sender_jid = row[2]
        # Extract phone from JID (e.g., 12023295961@s.whatsapp.net -> 12023295961)
        phone = sender_jid.split('@')[0] if '@' in sender_jid else sender_jid
        groups[group_jid].add((phone, sender_name))

    conn.close()
    return groups


def get_group_names() -> dict[str, str]:
    """Get group names from wacli.db."""
    if not WACLI_DB_PATH.exists():
        return {}

    conn = sqlite3.connect(WACLI_DB_PATH)
    cursor = conn.execute("SELECT jid, name FROM groups")
    names = {row[0]: row[1] for row in cursor}
    conn.close()
    return names


def discover_relationships(dry_run: bool = True) -> dict:
    """
    Discover relationships from WhatsApp group membership.

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
    groups = get_group_members_from_messages()
    group_names = get_group_names()

    logger.info(f"Found {len(phone_to_person)} phone-to-person mappings")
    logger.info(f"Found {len(groups)} WhatsApp groups with messages")

    relationship_store = get_relationship_store()
    person_store = get_person_entity_store()

    stats = {
        'groups_with_multiple_known': 0,
        'relationships_created': 0,
        'relationships_updated': 0,
        'unknown_phones': set(),
    }

    # For each group, find all known members and create relationships
    for group_jid, members in groups.items():
        # Map members to person IDs
        known_members = []
        for phone, name in members:
            # Try various phone formats
            person_id = None
            for fmt in [phone, phone.lstrip('1'), '1' + phone.lstrip('1')]:
                if fmt in phone_to_person:
                    person_id = phone_to_person[fmt]
                    break

            if person_id:
                person = person_store.get_by_id(person_id)
                if person:
                    known_members.append((person_id, person.canonical_name))
            else:
                stats['unknown_phones'].add(f"{name} ({phone})")

        # Skip groups with fewer than 2 known members
        if len(known_members) < 2:
            continue

        stats['groups_with_multiple_known'] += 1
        group_name = group_names.get(group_jid, group_jid)
        logger.info(f"Group '{group_name}' has {len(known_members)} known members: {[m[1] for m in known_members]}")

        # Generate all pairs (C(n,2) = n*(n-1)/2 pairs)
        pairs_to_create = []
        for i in range(len(known_members)):
            for j in range(i + 1, len(known_members)):
                person_a_id, name_a = known_members[i]
                person_b_id, name_b = known_members[j]
                pairs_to_create.append((person_a_id, name_a, person_b_id, name_b))

        logger.debug(f"  Will check {len(pairs_to_create)} pairs")

        # Create relationships between all pairs
        for person_a_id, name_a, person_b_id, name_b in pairs_to_create:
            # Normalize pair order
            if person_a_id > person_b_id:
                person_a_id, person_b_id = person_b_id, person_a_id
                name_a, name_b = name_b, name_a

            existing = relationship_store.get_between(person_a_id, person_b_id)

            if existing:
                if "whatsapp" not in existing.shared_contexts:
                    existing.shared_contexts.append("whatsapp")
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
                        shared_contexts=["whatsapp"],
                    )
                    relationship_store.add(rel)
                stats['relationships_created'] += 1
                logger.info(f"  Created: {name_a} <-> {name_b}")

    # Summary
    logger.info(f"\n=== WhatsApp Relationship Discovery Summary ===")
    logger.info(f"Groups with 2+ known members: {stats['groups_with_multiple_known']}")
    logger.info(f"Relationships created: {stats['relationships_created']}")
    logger.info(f"Relationships updated: {stats['relationships_updated']}")
    logger.info(f"Unknown phones: {len(stats['unknown_phones'])}")

    if stats['unknown_phones'] and len(stats['unknown_phones']) <= 20:
        logger.info(f"Unknown phones: {sorted(stats['unknown_phones'])}")

    if dry_run:
        logger.info("\nDRY RUN - no changes made. Use --execute to apply.")

    # Convert set to list for JSON serialization
    stats['unknown_phones'] = list(stats['unknown_phones'])
    return stats


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Discover relationships from WhatsApp groups')
    parser.add_argument('--execute', action='store_true', help='Actually create relationships')
    args = parser.parse_args()

    discover_relationships(dry_run=not args.execute)

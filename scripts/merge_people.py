#!/usr/bin/env python3
"""
Merge duplicate person records.

This script merges two PersonEntity records into one, updating all references
(interactions, source_entities, facts) to point to the surviving record.

The merge is durable - merged IDs are tracked so entity resolution won't
recreate duplicates from future syncs.

Usage:
    python scripts/merge_people.py --primary <id> --secondary <id> [--execute]
    python scripts/merge_people.py --list-duplicates
    python scripts/merge_people.py --search "name pattern"
"""
import sys
import json
import sqlite3
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.services.person_entity import get_person_entity_store
from api.services.interaction_store import get_interaction_db_path
from api.services.source_entity import get_crm_db_path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# File to track merged person IDs for durability
MERGED_IDS_FILE = Path(__file__).parent.parent / "data" / "merged_person_ids.json"


def load_merged_ids() -> dict:
    """Load the merged IDs mapping (secondary_id -> primary_id)."""
    if MERGED_IDS_FILE.exists():
        with open(MERGED_IDS_FILE) as f:
            return json.load(f)
    return {}


def save_merged_ids(merged_ids: dict):
    """Save the merged IDs mapping."""
    MERGED_IDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MERGED_IDS_FILE, 'w') as f:
        json.dump(merged_ids, f, indent=2)


def get_canonical_person_id(person_id: str) -> str:
    """
    Get the canonical (primary) person ID, following merge chain if needed.

    This is called by entity resolver to ensure we always use the primary ID.
    """
    merged_ids = load_merged_ids()

    # Follow the merge chain (in case of multiple merges)
    visited = set()
    while person_id in merged_ids and person_id not in visited:
        visited.add(person_id)
        person_id = merged_ids[person_id]

    return person_id


def search_people(pattern: str) -> list:
    """Search for people matching a pattern."""
    store = get_person_entity_store()
    people = store.get_all()

    pattern_lower = pattern.lower()
    matches = []

    for p in people:
        # Match against name, emails, phones
        if pattern_lower in p.canonical_name.lower():
            matches.append(p)
        elif any(pattern_lower in e.lower() for e in (p.emails or [])):
            matches.append(p)
        elif any(pattern_lower in ph for ph in (p.phone_numbers or [])):
            matches.append(p)

    return matches


def find_potential_duplicates() -> list:
    """Find potential duplicate person records."""
    store = get_person_entity_store()
    people = store.get_all()

    duplicates = []

    # Group by normalized name
    by_name = {}
    for p in people:
        # Normalize: lowercase, remove common suffixes
        name = p.canonical_name.lower().strip()
        for suffix in [' jr', ' sr', ' ii', ' iii']:
            name = name.replace(suffix, '')

        if name not in by_name:
            by_name[name] = []
        by_name[name].append(p)

    for name, group in by_name.items():
        if len(group) > 1:
            duplicates.append({
                'name': name,
                'people': group,
            })

    # Also check for shared emails/phones across different names
    by_email = {}
    by_phone = {}

    for p in people:
        for email in (p.emails or []):
            if email not in by_email:
                by_email[email] = []
            by_email[email].append(p)
        for phone in (p.phone_numbers or []):
            if phone not in by_phone:
                by_phone[phone] = []
            by_phone[phone].append(p)

    for email, group in by_email.items():
        if len(group) > 1:
            names = [p.canonical_name for p in group]
            if len(set(names)) > 1:  # Different names sharing email
                duplicates.append({
                    'reason': f'shared email: {email}',
                    'people': group,
                })

    for phone, group in by_phone.items():
        if len(group) > 1:
            names = [p.canonical_name for p in group]
            if len(set(names)) > 1:  # Different names sharing phone
                duplicates.append({
                    'reason': f'shared phone: {phone}',
                    'people': group,
                })

    return duplicates


def merge_people(primary_id: str, secondary_id: str, dry_run: bool = True) -> dict:
    """
    Merge secondary person into primary person.

    Args:
        primary_id: ID of the person to keep (survivor)
        secondary_id: ID of the person to merge and delete
        dry_run: If True, don't actually make changes

    Returns:
        Stats dict
    """
    stats = {
        'interactions_updated': 0,
        'source_entities_updated': 0,
        'facts_updated': 0,
        'emails_merged': 0,
        'phones_merged': 0,
        'aliases_added': 0,
    }

    store = get_person_entity_store()
    primary = store.get_by_id(primary_id)
    secondary = store.get_by_id(secondary_id)

    if not primary:
        raise ValueError(f"Primary person not found: {primary_id}")
    if not secondary:
        raise ValueError(f"Secondary person not found: {secondary_id}")

    logger.info(f"Merging: '{secondary.canonical_name}' -> '{primary.canonical_name}'")
    logger.info(f"  Primary ID: {primary_id}")
    logger.info(f"  Secondary ID: {secondary_id}")

    # 1. Merge identifying info into primary
    logger.info("\n1. Merging identifying info...")

    # Merge emails
    for email in (secondary.emails or []):
        if email and email not in (primary.emails or []):
            if primary.emails is None:
                primary.emails = []
            primary.emails.append(email)
            stats['emails_merged'] += 1
            logger.info(f"   + Email: {email}")

    # Merge phone numbers
    for phone in (secondary.phone_numbers or []):
        if phone and phone not in (primary.phone_numbers or []):
            if primary.phone_numbers is None:
                primary.phone_numbers = []
            primary.phone_numbers.append(phone)
            stats['phones_merged'] += 1
            logger.info(f"   + Phone: {phone}")

    # Add secondary's name as alias
    if secondary.canonical_name and secondary.canonical_name != primary.canonical_name:
        if primary.aliases is None:
            primary.aliases = []
        if secondary.canonical_name not in primary.aliases:
            primary.aliases.append(secondary.canonical_name)
            stats['aliases_added'] += 1
            logger.info(f"   + Alias: {secondary.canonical_name}")

    # Merge secondary's aliases
    for alias in (secondary.aliases or []):
        if alias and alias not in (primary.aliases or []):
            if primary.aliases is None:
                primary.aliases = []
            primary.aliases.append(alias)
            stats['aliases_added'] += 1
            logger.info(f"   + Alias: {alias}")

    # Merge sources
    for source in (secondary.sources or []):
        if source and source not in (primary.sources or []):
            if primary.sources is None:
                primary.sources = []
            primary.sources.append(source)

    # 2. Update interactions
    logger.info("\n2. Updating interactions...")
    interactions_db = get_interaction_db_path()
    int_conn = sqlite3.connect(interactions_db)

    cursor = int_conn.execute(
        "SELECT COUNT(*) FROM interactions WHERE person_id = ?",
        (secondary_id,)
    )
    count = cursor.fetchone()[0]
    stats['interactions_updated'] = count
    logger.info(f"   {count} interactions to update")

    if not dry_run and count > 0:
        int_conn.execute(
            "UPDATE interactions SET person_id = ? WHERE person_id = ?",
            (primary_id, secondary_id)
        )
        int_conn.commit()
    int_conn.close()

    # 3. Update source entities
    logger.info("\n3. Updating source entities...")
    crm_db = get_crm_db_path()
    crm_conn = sqlite3.connect(crm_db)

    cursor = crm_conn.execute(
        "SELECT COUNT(*) FROM source_entities WHERE canonical_person_id = ?",
        (secondary_id,)
    )
    count = cursor.fetchone()[0]
    stats['source_entities_updated'] = count
    logger.info(f"   {count} source entities to update")

    if not dry_run and count > 0:
        crm_conn.execute(
            "UPDATE source_entities SET canonical_person_id = ? WHERE canonical_person_id = ?",
            (primary_id, secondary_id)
        )
        crm_conn.commit()

    # 4. Update facts
    logger.info("\n4. Updating facts...")
    cursor = crm_conn.execute(
        "SELECT COUNT(*) FROM person_facts WHERE person_id = ?",
        (secondary_id,)
    )
    count = cursor.fetchone()[0]
    stats['facts_updated'] = count
    logger.info(f"   {count} facts to update")

    if not dry_run and count > 0:
        crm_conn.execute(
            "UPDATE person_facts SET person_id = ? WHERE person_id = ?",
            (primary_id, secondary_id)
        )
        crm_conn.commit()

    crm_conn.close()

    # 5. Merge relationships
    logger.info("\n5. Merging relationships...")
    stats['relationships_updated'] = 0
    stats['relationships_merged'] = 0
    stats['relationships_deleted'] = 0

    from api.services.relationship import get_relationship_store, Relationship
    rel_store = get_relationship_store()

    # Get all relationships involving the secondary person
    secondary_rels = rel_store.get_for_person(secondary_id)
    logger.info(f"   {len(secondary_rels)} relationships to process")

    for rel in secondary_rels:
        # Find the "other" person in this relationship
        other_id = rel.other_person(secondary_id)
        if not other_id:
            continue

        # Skip if other person is the primary (self-relationship after merge)
        if other_id == primary_id:
            # Delete this relationship - it would be a self-loop
            if not dry_run:
                rel_store.delete(rel.id)
            stats['relationships_deleted'] += 1
            logger.info(f"   - Deleted self-loop relationship")
            continue

        # Check if primary already has a relationship with the other person
        existing = rel_store.get_between(primary_id, other_id)

        if existing:
            # Merge relationship data into existing
            existing.shared_events_count = (existing.shared_events_count or 0) + (rel.shared_events_count or 0)
            existing.shared_threads_count = (existing.shared_threads_count or 0) + (rel.shared_threads_count or 0)
            existing.shared_messages_count = (existing.shared_messages_count or 0) + (rel.shared_messages_count or 0)
            existing.shared_whatsapp_count = (existing.shared_whatsapp_count or 0) + (rel.shared_whatsapp_count or 0)
            existing.shared_slack_count = (existing.shared_slack_count or 0) + (rel.shared_slack_count or 0)

            # Merge shared contexts
            for ctx in (rel.shared_contexts or []):
                if ctx not in (existing.shared_contexts or []):
                    if existing.shared_contexts is None:
                        existing.shared_contexts = []
                    existing.shared_contexts.append(ctx)

            # Update dates
            if rel.first_seen_together:
                if not existing.first_seen_together or rel.first_seen_together < existing.first_seen_together:
                    existing.first_seen_together = rel.first_seen_together
            if rel.last_seen_together:
                if not existing.last_seen_together or rel.last_seen_together > existing.last_seen_together:
                    existing.last_seen_together = rel.last_seen_together

            # LinkedIn connection - true if either was connected
            if rel.is_linkedin_connection:
                existing.is_linkedin_connection = True

            if not dry_run:
                rel_store.update(existing)
                rel_store.delete(rel.id)

            stats['relationships_merged'] += 1
            logger.info(f"   ~ Merged relationship with {other_id}")
        else:
            # Transfer relationship to primary - create new to trigger normalization
            new_rel = Relationship(
                person_a_id=primary_id if rel.person_a_id == secondary_id else rel.person_a_id,
                person_b_id=primary_id if rel.person_b_id == secondary_id else rel.person_b_id,
                relationship_type=rel.relationship_type,
                shared_contexts=rel.shared_contexts,
                shared_events_count=rel.shared_events_count,
                shared_threads_count=rel.shared_threads_count,
                shared_messages_count=rel.shared_messages_count,
                shared_whatsapp_count=rel.shared_whatsapp_count,
                shared_slack_count=rel.shared_slack_count,
                is_linkedin_connection=rel.is_linkedin_connection,
                first_seen_together=rel.first_seen_together,
                last_seen_together=rel.last_seen_together,
            )

            if not dry_run:
                rel_store.delete(rel.id)
                rel_store.add(new_rel)

            stats['relationships_updated'] += 1
            logger.info(f"   > Transferred relationship with {other_id}")

    # 6. Save merge mapping for durability
    logger.info("\n6. Recording merge for durability...")
    if not dry_run:
        merged_ids = load_merged_ids()
        merged_ids[secondary_id] = primary_id
        save_merged_ids(merged_ids)
        logger.info(f"   Recorded: {secondary_id} -> {primary_id}")

    # 7. Update primary stats and delete secondary
    logger.info("\n7. Updating stats and cleaning up...")
    if not dry_run:
        # Recalculate stats for primary
        primary.email_count = (primary.email_count or 0) + (secondary.email_count or 0)
        primary.meeting_count = (primary.meeting_count or 0) + (secondary.meeting_count or 0)
        primary.message_count = (primary.message_count or 0) + (secondary.message_count or 0)
        primary.mention_count = (primary.mention_count or 0) + (secondary.mention_count or 0)
        primary.source_entity_count = (primary.source_entity_count or 0) + (secondary.source_entity_count or 0)

        # Update last_seen to most recent
        if secondary.last_seen:
            if primary.last_seen is None or secondary.last_seen > primary.last_seen:
                primary.last_seen = secondary.last_seen

        # Update first_seen to earliest
        if secondary.first_seen:
            if primary.first_seen is None or secondary.first_seen < primary.first_seen:
                primary.first_seen = secondary.first_seen

        # Save primary
        store.update(primary)

        # Delete secondary
        store.delete(secondary_id)

        # Save store
        store.save()

        logger.info(f"   Deleted secondary record: {secondary.canonical_name}")

    # 8. Recalculate relationship strength for primary
    logger.info("\n8. Recalculating relationship strength...")
    if not dry_run:
        from api.services.relationship_metrics import compute_strength_for_person
        new_strength = compute_strength_for_person(primary)
        if new_strength != primary.relationship_strength:
            logger.info(f"   Strength: {primary.relationship_strength} -> {new_strength}")
            primary.relationship_strength = new_strength
            store.update(primary)
            store.save()
        else:
            logger.info(f"   Strength unchanged: {new_strength}")

    # Summary
    logger.info(f"\n=== Merge Summary ===")
    logger.info(f"Primary: {primary.canonical_name} ({primary_id})")
    logger.info(f"Secondary: {secondary.canonical_name} ({secondary_id})")
    logger.info(f"Interactions updated: {stats['interactions_updated']}")
    logger.info(f"Source entities updated: {stats['source_entities_updated']}")
    logger.info(f"Facts updated: {stats['facts_updated']}")
    logger.info(f"Relationships: {stats['relationships_updated']} transferred, {stats['relationships_merged']} merged, {stats['relationships_deleted']} deleted")
    logger.info(f"Emails merged: {stats['emails_merged']}")
    logger.info(f"Phones merged: {stats['phones_merged']}")
    logger.info(f"Aliases added: {stats['aliases_added']}")

    if dry_run:
        logger.info("\nDRY RUN - no changes made. Use --execute to apply.")

    return stats


def main():
    parser = argparse.ArgumentParser(description='Merge duplicate person records')
    parser.add_argument('--primary', help='ID of the person to keep')
    parser.add_argument('--secondary', help='ID of the person to merge into primary')
    parser.add_argument('--execute', action='store_true', help='Actually apply changes')
    parser.add_argument('--list-duplicates', action='store_true', help='List potential duplicates')
    parser.add_argument('--search', help='Search for people by name/email/phone')
    args = parser.parse_args()

    if args.list_duplicates:
        duplicates = find_potential_duplicates()
        print(f"\nFound {len(duplicates)} potential duplicate groups:\n")
        for i, dup in enumerate(duplicates, 1):
            reason = dup.get('name') or dup.get('reason')
            print(f"{i}. {reason}")
            for p in dup['people']:
                total = (p.email_count or 0) + (p.message_count or 0) + (p.meeting_count or 0)
                print(f"   - {p.canonical_name} (ID: {p.id[:8]}..., interactions: {total})")
            print()
        return

    if args.search:
        matches = search_people(args.search)
        print(f"\nFound {len(matches)} matches for '{args.search}':\n")
        for p in matches:
            total = (p.email_count or 0) + (p.message_count or 0) + (p.meeting_count or 0)
            print(f"  ID: {p.id}")
            print(f"  Name: {p.canonical_name}")
            print(f"  Emails: {p.emails}")
            print(f"  Phones: {p.phone_numbers}")
            print(f"  Aliases: {p.aliases}")
            print(f"  Interactions: {total} (email={p.email_count}, msg={p.message_count}, mtg={p.meeting_count})")
            print(f"  Strength: {p.relationship_strength}")
            print()
        return

    if not args.primary or not args.secondary:
        parser.print_help()
        print("\nExamples:")
        print("  python scripts/merge_people.py --search 'Yoni'")
        print("  python scripts/merge_people.py --list-duplicates")
        print("  python scripts/merge_people.py --primary abc123 --secondary def456")
        print("  python scripts/merge_people.py --primary abc123 --secondary def456 --execute")
        return

    merge_people(args.primary, args.secondary, dry_run=not args.execute)


if __name__ == '__main__':
    main()

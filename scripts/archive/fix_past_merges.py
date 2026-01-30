#!/usr/bin/env python3
"""
Fix relationships for past merges that didn't handle relationships.

This script reads merged_person_ids.json and for each past merge:
1. Finds any relationships still referencing the secondary (merged) ID
2. Transfers or merges them to the primary ID
3. Recalculates relationship strength

Usage:
    python scripts/fix_past_merges.py           # Dry run
    python scripts/fix_past_merges.py --execute # Apply fixes
"""
import sys
import json
import logging
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.services.relationship import get_relationship_store, Relationship
from api.services.person_entity import get_person_entity_store
from api.services.relationship_metrics import compute_strength_for_person

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

MERGED_IDS_FILE = Path(__file__).parent.parent / "data" / "merged_person_ids.json"


def fix_relationships_for_merge(secondary_id: str, primary_id: str, dry_run: bool = True) -> dict:
    """Fix relationships for a single past merge."""
    stats = {
        'relationships_transferred': 0,
        'relationships_merged': 0,
        'relationships_deleted': 0,
    }

    rel_store = get_relationship_store()
    person_store = get_person_entity_store()

    # Check if primary still exists
    primary = person_store.get_by_id(primary_id)
    if not primary:
        logger.warning(f"  Primary {primary_id[:8]}... no longer exists, skipping")
        return stats

    # Get relationships still referencing the secondary ID
    secondary_rels = rel_store.get_for_person(secondary_id)

    if not secondary_rels:
        logger.info(f"  No orphaned relationships found")
        return stats

    logger.info(f"  Found {len(secondary_rels)} orphaned relationships")

    for rel in secondary_rels:
        # Find the "other" person in this relationship
        other_id = rel.other_person(secondary_id)
        if not other_id:
            continue

        # Skip if other person is the primary (would be self-loop)
        if other_id == primary_id:
            if not dry_run:
                rel_store.delete(rel.id)
            stats['relationships_deleted'] += 1
            logger.info(f"    - Deleted self-loop")
            continue

        # Check if primary already has a relationship with this person
        existing = rel_store.get_between(primary_id, other_id)

        if existing:
            # Merge relationship data
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

            if rel.is_linkedin_connection:
                existing.is_linkedin_connection = True

            if not dry_run:
                rel_store.update(existing)
                rel_store.delete(rel.id)

            stats['relationships_merged'] += 1
            logger.info(f"    ~ Merged relationship with {other_id[:8]}...")
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

            stats['relationships_transferred'] += 1
            logger.info(f"    > Transferred relationship with {other_id[:8]}...")

    # Recalculate strength for primary
    if not dry_run and (stats['relationships_transferred'] > 0 or stats['relationships_merged'] > 0):
        new_strength = compute_strength_for_person(primary)
        if new_strength != primary.relationship_strength:
            logger.info(f"    Strength updated: {primary.relationship_strength} -> {new_strength}")
            primary.relationship_strength = new_strength
            person_store.update(primary)
            person_store.save()

    return stats


def main():
    parser = argparse.ArgumentParser(description='Fix relationships for past merges')
    parser.add_argument('--execute', action='store_true', help='Actually apply fixes')
    args = parser.parse_args()

    dry_run = not args.execute

    if not MERGED_IDS_FILE.exists():
        logger.info("No merged IDs file found - nothing to fix")
        return

    with open(MERGED_IDS_FILE) as f:
        merged_ids = json.load(f)

    if not merged_ids:
        logger.info("No past merges found - nothing to fix")
        return

    logger.info(f"Checking {len(merged_ids)} past merges for orphaned relationships...")
    if dry_run:
        logger.info("DRY RUN - no changes will be made\n")

    total_stats = {
        'relationships_transferred': 0,
        'relationships_merged': 0,
        'relationships_deleted': 0,
        'merges_with_issues': 0,
    }

    person_store = get_person_entity_store()

    for secondary_id, primary_id in merged_ids.items():
        primary = person_store.get_by_id(primary_id)
        primary_name = primary.canonical_name if primary else "DELETED"
        logger.info(f"\nMerge: {secondary_id[:8]}... -> {primary_name} ({primary_id[:8]}...)")

        stats = fix_relationships_for_merge(secondary_id, primary_id, dry_run)

        total_stats['relationships_transferred'] += stats['relationships_transferred']
        total_stats['relationships_merged'] += stats['relationships_merged']
        total_stats['relationships_deleted'] += stats['relationships_deleted']

        if sum(stats.values()) > 0:
            total_stats['merges_with_issues'] += 1

    logger.info(f"\n=== Summary ===")
    logger.info(f"Past merges checked: {len(merged_ids)}")
    logger.info(f"Merges with orphaned relationships: {total_stats['merges_with_issues']}")
    logger.info(f"Relationships transferred: {total_stats['relationships_transferred']}")
    logger.info(f"Relationships merged: {total_stats['relationships_merged']}")
    logger.info(f"Relationships deleted (self-loops): {total_stats['relationships_deleted']}")

    if dry_run:
        logger.info("\nDRY RUN - use --execute to apply fixes")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Migration script for LifeOS Personal CRM.

Migrates existing data to the new two-tier CRM model:
1. Converts PersonEntity records to CanonicalPerson format (adds new fields)
2. Creates SourceEntity records from existing interactions
3. Links source entities to canonical persons
4. Calculates initial relationship strengths
5. Discovers relationships from shared contexts

Usage:
    python scripts/migrate_to_crm.py [--dry-run] [--backup]

Options:
    --dry-run   Show what would be done without making changes
    --backup    Create backup of data files before migration

WARNING - ID DURABILITY:
========================
This script PRESERVES existing PersonEntity IDs. It does NOT recreate entities
from scratch. Person IDs are critical because they are:
- Referenced throughout the system (relationships, interactions, source entities)
- Hardcoded in config/settings.py (my_person_id for the CRM owner)
- Used in merged_person_ids.json to track person merges

If you need to rebuild from scratch (AVOID if possible):
- All person IDs will change, breaking relationships and hardcoded references
- You MUST update my_person_id in settings after finding your new ID
- All merge history will be lost

Prefer incremental syncs and edits over full rebuilds whenever possible.
"""
import argparse
import json
import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from api.services.person_entity import get_person_entity_store, PersonEntity
from api.services.interaction_store import get_interaction_store
from api.services.source_entity import (
    get_source_entity_store,
    SourceEntity,
    LINK_STATUS_AUTO,
)
from api.services.relationship import get_relationship_store
from api.services.relationship_metrics import update_all_strengths
from api.services.relationship_discovery import run_full_discovery

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def backup_data_files():
    """Create timestamped backups of data files."""
    data_dir = PROJECT_ROOT / "data"
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    files_to_backup = [
        "people_entities.json",
        "interactions.db",
        "crm.db",  # May not exist yet
    ]

    backed_up = []
    for filename in files_to_backup:
        src = data_dir / filename
        if src.exists():
            dst = backup_dir / f"{filename}.{timestamp}"
            shutil.copy2(src, dst)
            backed_up.append(str(dst))
            logger.info(f"Backed up {filename} to {dst}")

    return backed_up


def migrate_person_entities(dry_run: bool = False):
    """
    Migrate PersonEntity records to include new CRM fields.

    Adds: tags, notes, source_entity_count, relationship_strength
    """
    logger.info("=== Migrating PersonEntity records ===")

    store = get_person_entity_store()
    people = store.get_all()
    logger.info(f"Found {len(people)} people to migrate")

    migrated = 0
    for person in people:
        # Initialize new fields if not present
        needs_update = False

        if not hasattr(person, 'tags') or person.tags is None:
            person.tags = []
            needs_update = True

        if not hasattr(person, 'notes') or person.notes is None:
            person.notes = ""
            needs_update = True

        if not hasattr(person, 'source_entity_count') or person.source_entity_count is None:
            person.source_entity_count = 0
            needs_update = True

        if needs_update:
            if not dry_run:
                store.update(person)
            migrated += 1

    if not dry_run:
        store.save()

    logger.info(f"Migrated {migrated} people (dry_run={dry_run})")
    return {"migrated": migrated, "total": len(people)}


def create_source_entities_from_interactions(dry_run: bool = False):
    """
    Create SourceEntity records from existing interactions.

    Groups interactions by person + source_type to create source entities.
    """
    logger.info("=== Creating SourceEntity records from interactions ===")

    interaction_store = get_interaction_store()
    source_store = get_source_entity_store()
    person_store = get_person_entity_store()

    # Get all people
    people = person_store.get_all()
    logger.info(f"Processing interactions for {len(people)} people")

    created = 0
    linked = 0

    for person in people:
        # Get all interactions for this person
        interactions = interaction_store.get_for_person(
            person.id,
            days_back=365 * 5,  # All history
            limit=10000,
        )

        # Group by source_type + source_id
        seen_sources = set()
        for interaction in interactions:
            # Create unique key for this source
            source_key = f"{interaction.source_type}:{interaction.source_id}"
            if source_key in seen_sources:
                continue
            seen_sources.add(source_key)

            # Check if source entity already exists
            existing = source_store.get_by_source(
                interaction.source_type,
                interaction.source_id
            )
            if existing:
                # Already linked?
                if existing.canonical_person_id != person.id:
                    if not dry_run:
                        source_store.link_to_person(
                            existing.id,
                            person.id,
                            confidence=1.0,
                            status=LINK_STATUS_AUTO,
                        )
                    linked += 1
                continue

            # Create new source entity
            source_entity = SourceEntity(
                source_type=interaction.source_type,
                source_id=interaction.source_id,
                observed_name=person.canonical_name,
                observed_email=person.primary_email,
                observed_at=interaction.timestamp,
                canonical_person_id=person.id,
                link_confidence=1.0,
                link_status=LINK_STATUS_AUTO,
                linked_at=datetime.now(timezone.utc),
            )

            if not dry_run:
                source_store.add(source_entity)
            created += 1

        # Update person's source_entity_count
        if not dry_run and len(seen_sources) > 0:
            person.source_entity_count = source_store.count_for_person(person.id)
            person_store.update(person)

    if not dry_run:
        person_store.save()

    logger.info(f"Created {created} source entities, linked {linked} (dry_run={dry_run})")
    return {"created": created, "linked": linked}


def calculate_relationship_strengths(dry_run: bool = False):
    """Calculate relationship strength scores for all people."""
    logger.info("=== Calculating relationship strengths ===")

    if dry_run:
        logger.info("Skipping (dry_run=True)")
        return {"updated": 0}

    results = update_all_strengths()
    logger.info(f"Updated {results['updated']} people, {results['failed']} failed")
    return results


def discover_relationships(dry_run: bool = False):
    """Discover relationships from shared contexts."""
    logger.info("=== Discovering relationships ===")

    if dry_run:
        logger.info("Skipping (dry_run=True)")
        return {"total": 0}

    results = run_full_discovery()
    logger.info(f"Discovered {results['total']} relationships")
    return results


def print_statistics():
    """Print current data statistics."""
    logger.info("=== Current Statistics ===")

    person_store = get_person_entity_store()
    interaction_store = get_interaction_store()

    person_stats = person_store.get_statistics()
    logger.info(f"People: {person_stats['total_entities']}")
    logger.info(f"  By category: {person_stats['by_category']}")
    logger.info(f"  By source: {person_stats['by_source']}")

    interaction_stats = interaction_store.get_statistics()
    logger.info(f"Interactions: {interaction_stats['total_interactions']}")
    logger.info(f"  By source: {interaction_stats['by_source']}")

    # CRM stats (may not exist yet)
    try:
        source_store = get_source_entity_store()
        source_stats = source_store.get_statistics()
        logger.info(f"Source Entities: {source_stats['total_entities']}")
        logger.info(f"  Linked: {source_stats['linked_entities']}")
        logger.info(f"  Unlinked: {source_stats['unlinked_entities']}")
    except Exception:
        logger.info("Source Entities: (not yet created)")

    try:
        rel_store = get_relationship_store()
        rel_stats = rel_store.get_statistics()
        logger.info(f"Relationships: {rel_stats['total_relationships']}")
    except Exception:
        logger.info("Relationships: (not yet created)")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate LifeOS data to new CRM model"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Create backup of data files before migration"
    )
    parser.add_argument(
        "--stats-only",
        action="store_true",
        help="Only show current statistics, don't migrate"
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("LifeOS CRM Migration")
    logger.info("=" * 60)

    if args.stats_only:
        print_statistics()
        return

    if args.dry_run:
        logger.info("DRY RUN MODE - no changes will be made")

    if args.backup and not args.dry_run:
        logger.info("")
        logger.info("Creating backups...")
        backed_up = backup_data_files()
        logger.info(f"Created {len(backed_up)} backups")

    logger.info("")
    print_statistics()

    logger.info("")
    logger.info("Starting migration...")
    logger.info("")

    # Step 1: Migrate PersonEntity records
    person_results = migrate_person_entities(dry_run=args.dry_run)

    # Step 2: Create SourceEntity records from interactions
    logger.info("")
    source_results = create_source_entities_from_interactions(dry_run=args.dry_run)

    # Step 3: Calculate relationship strengths
    logger.info("")
    strength_results = calculate_relationship_strengths(dry_run=args.dry_run)

    # Step 4: Discover relationships
    logger.info("")
    discovery_results = discover_relationships(dry_run=args.dry_run)

    # Final statistics
    logger.info("")
    logger.info("=" * 60)
    logger.info("Migration Complete!")
    logger.info("=" * 60)
    logger.info("")
    print_statistics()

    logger.info("")
    logger.info("Summary:")
    logger.info(f"  People migrated: {person_results['migrated']}")
    logger.info(f"  Source entities created: {source_results['created']}")
    logger.info(f"  Source entities linked: {source_results['linked']}")
    logger.info(f"  Relationship strengths updated: {strength_results.get('updated', 0)}")
    logger.info(f"  Relationships discovered: {discovery_results.get('total', 0)}")


if __name__ == "__main__":
    main()

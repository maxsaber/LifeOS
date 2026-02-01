#!/usr/bin/env python3
"""
Sync commitments for top contacts.

Extracts commitments/promises from conversations using Claude and stores
them for tracking in the CRM.

Usage:
    python scripts/sync_commitments.py [--execute] [--top N] [--days N]

Options:
    --execute   Actually run the sync (required)
    --top N     Only process top N contacts by interaction count (default: 50)
    --days N    Days of interactions to analyze (default: 30)
"""
import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.services.commitments import get_commitment_store, get_commitment_extractor
from api.services.person_entity import get_person_entity_store
from api.services.interaction_store import get_interaction_store

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Message-based sources where commitments are most likely
MESSAGE_SOURCES = {"imessage", "whatsapp", "slack", "gmail"}


def get_top_contacts(limit: int = 50) -> list:
    """
    Get top contacts by total interaction count.

    Returns list of (person_id, person_name, interaction_count) tuples.
    """
    person_store = get_person_entity_store()
    people = person_store.get_all()

    # Calculate total interactions for each person
    scored = []
    for p in people:
        total = (
            (p.email_count or 0) +
            (p.meeting_count or 0) +
            (p.mention_count or 0) +
            getattr(p, 'message_count', 0)
        )
        if total > 0:
            scored.append((p.id, p.canonical_name, total))

    # Sort by interaction count descending
    scored.sort(key=lambda x: x[2], reverse=True)

    return scored[:limit]


def sync_commitments(
    top: int = 50,
    days: int = 30,
    dry_run: bool = True,
) -> dict:
    """
    Sync commitments for top contacts.

    Args:
        top: Number of top contacts to process
        days: Days of interactions to analyze
        dry_run: If True, don't actually extract

    Returns:
        Dict with sync statistics
    """
    stats = {
        "contacts_processed": 0,
        "interactions_analyzed": 0,
        "commitments_extracted": 0,
        "overdue_marked": 0,
        "errors": 0,
        "skipped": 0,
    }

    commitment_store = get_commitment_store()

    # First, mark any overdue commitments as expired
    if not dry_run:
        overdue_count = commitment_store.mark_overdue_expired()
        stats["overdue_marked"] = overdue_count
        if overdue_count > 0:
            logger.info(f"Marked {overdue_count} overdue commitments as expired")

    # Get top contacts
    contacts = get_top_contacts(limit=top)
    logger.info(f"Found {len(contacts)} top contacts to process")

    if dry_run:
        for person_id, name, count in contacts[:10]:
            logger.info(f"  Would process: {name} ({count} interactions)")
        if len(contacts) > 10:
            logger.info(f"  ... and {len(contacts) - 10} more")
        return stats

    interaction_store = get_interaction_store()
    extractor = get_commitment_extractor()

    for person_id, name, total_count in contacts:
        try:
            # Get recent message-based interactions
            interactions = interaction_store.get_for_person(
                person_id,
                days_back=days,
                limit=150,  # Cap per person
            )

            # Filter to message sources
            interactions = [i for i in interactions if i.source_type in MESSAGE_SOURCES]

            if not interactions:
                logger.debug(f"No message interactions for {name}")
                stats["skipped"] += 1
                continue

            # Convert to dict format
            interaction_dicts = [
                {
                    "id": i.id,
                    "source_type": i.source_type,
                    "title": i.title,
                    "snippet": i.snippet,
                    "timestamp": i.timestamp.isoformat() if i.timestamp else "",
                    "source_link": i.source_link,
                }
                for i in interactions
            ]

            # Extract commitments
            result = extractor.extract_for_person(
                person_id=person_id,
                person_name=name,
                interactions=interaction_dicts,
            )

            stats["contacts_processed"] += 1
            stats["interactions_analyzed"] += len(interaction_dicts)
            stats["commitments_extracted"] += result.get("extracted", 0)
            stats["errors"] += result.get("errors", 0)

            if result.get("extracted", 0) > 0:
                logger.info(
                    f"Processed {name}: {result.get('extracted', 0)} commitments from "
                    f"{len(interaction_dicts)} interactions"
                )

        except Exception as e:
            logger.error(f"Failed to process {name}: {e}")
            stats["errors"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description='Sync commitments')
    parser.add_argument('--execute', action='store_true', help='Actually run the sync')
    parser.add_argument('--top', type=int, default=50, help='Process top N contacts')
    parser.add_argument('--days', type=int, default=30, help='Days of interactions to analyze')
    args = parser.parse_args()

    if not args.execute:
        logger.info("DRY RUN - use --execute to actually sync")

    stats = sync_commitments(
        top=args.top,
        days=args.days,
        dry_run=not args.execute,
    )

    logger.info("\n=== Commitment Sync Summary ===")
    logger.info(f"Contacts processed: {stats['contacts_processed']}")
    logger.info(f"Interactions analyzed: {stats['interactions_analyzed']}")
    logger.info(f"Commitments extracted: {stats['commitments_extracted']}")
    logger.info(f"Overdue marked expired: {stats['overdue_marked']}")
    logger.info(f"Skipped: {stats['skipped']}")
    logger.info(f"Errors: {stats['errors']}")


if __name__ == '__main__':
    main()

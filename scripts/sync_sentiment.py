#!/usr/bin/env python3
"""
Sync sentiment scores for top contacts.

Analyzes the emotional tone of interactions using Claude and stores
sentiment data for trend analysis in the CRM.

Usage:
    python scripts/sync_sentiment.py [--execute] [--top N] [--days N] [--force]

Options:
    --execute   Actually run the sync (required)
    --top N     Only process top N contacts by interaction count (default: 50)
    --days N    Days of interactions to analyze (default: 7)
    --force     Re-extract sentiment even if already exists
"""
import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.services.sentiment import get_sentiment_store, get_sentiment_extractor
from api.services.person_entity import get_person_entity_store
from api.services.interaction_store import get_interaction_store

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


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


def sync_sentiment(
    top: int = 50,
    days: int = 7,
    force: bool = False,
    dry_run: bool = True,
) -> dict:
    """
    Sync sentiment for top contacts.

    Args:
        top: Number of top contacts to process
        days: Days of interactions to analyze
        force: Re-extract even if sentiment exists
        dry_run: If True, don't actually extract

    Returns:
        Dict with sync statistics
    """
    stats = {
        "contacts_processed": 0,
        "interactions_analyzed": 0,
        "sentiments_extracted": 0,
        "errors": 0,
        "skipped": 0,
    }

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
    extractor = get_sentiment_extractor()

    for person_id, name, total_count in contacts:
        try:
            # Get recent interactions
            interactions = interaction_store.get_for_person(
                person_id,
                days_back=days,
                limit=100,  # Cap per person
            )

            if not interactions:
                logger.debug(f"No recent interactions for {name}")
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
                }
                for i in interactions
            ]

            # Extract sentiment
            result = extractor.extract_for_person(
                person_id=person_id,
                person_name=name,
                interactions=interaction_dicts,
                force=force,
            )

            stats["contacts_processed"] += 1
            stats["interactions_analyzed"] += len(interaction_dicts)
            stats["sentiments_extracted"] += result.get("extracted", 0)
            stats["errors"] += result.get("errors", 0)

            logger.info(
                f"Processed {name}: {result.get('extracted', 0)} sentiments from "
                f"{len(interaction_dicts)} interactions"
            )

        except Exception as e:
            logger.error(f"Failed to process {name}: {e}")
            stats["errors"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description='Sync sentiment scores')
    parser.add_argument('--execute', action='store_true', help='Actually run the sync')
    parser.add_argument('--top', type=int, default=50, help='Process top N contacts')
    parser.add_argument('--days', type=int, default=7, help='Days of interactions to analyze')
    parser.add_argument('--force', action='store_true', help='Re-extract existing sentiment')
    args = parser.parse_args()

    if not args.execute:
        logger.info("DRY RUN - use --execute to actually sync")

    stats = sync_sentiment(
        top=args.top,
        days=args.days,
        force=args.force,
        dry_run=not args.execute,
    )

    logger.info("\n=== Sentiment Sync Summary ===")
    logger.info(f"Contacts processed: {stats['contacts_processed']}")
    logger.info(f"Interactions analyzed: {stats['interactions_analyzed']}")
    logger.info(f"Sentiments extracted: {stats['sentiments_extracted']}")
    logger.info(f"Skipped: {stats['skipped']}")
    logger.info(f"Errors: {stats['errors']}")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Batch extract Quick Facts for top contacts.

Pre-populates facts for top 50 people by relationship strength,
skipping those who already have facts extracted.
"""
import argparse
import logging
import time
from typing import Optional

from api.services.person_entity import get_person_entity_store
from api.services.person_facts import get_person_fact_store, get_person_fact_extractor
from api.services.interaction_store import get_interaction_store
from api.services.relationship_metrics import compute_strength_for_person

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def get_top_people_by_strength(limit: int = 50) -> list:
    """
    Get top people by relationship strength with 1+ interactions.

    Returns:
        List of PersonEntity objects sorted by strength descending
    """
    person_store = get_person_entity_store()
    all_people = person_store.get_all()

    # Filter to people with interactions
    people_with_interactions = []
    for person in all_people:
        total_interactions = (
            (person.email_count or 0) +
            (person.meeting_count or 0) +
            (person.mention_count or 0) +
            getattr(person, 'message_count', 0)
        )
        if total_interactions > 0:
            # Compute fresh relationship strength
            try:
                strength = compute_strength_for_person(person)
                person.relationship_strength = strength
            except Exception as e:
                logger.warning(f"Failed to compute strength for {person.canonical_name}: {e}")
                person.relationship_strength = 0.0

            people_with_interactions.append(person)

    # Sort by strength descending
    people_with_interactions.sort(key=lambda p: p.relationship_strength, reverse=True)

    return people_with_interactions[:limit]


def extract_facts_for_person(person, interaction_store, fact_extractor) -> int:
    """
    Extract facts for a single person.

    Returns:
        Number of facts extracted
    """
    # Get ALL interactions for the person
    interactions = interaction_store.get_for_person(
        person.id,
        days_back=3650,  # Look back 10 years
        limit=100000,  # No practical limit
    )

    if not interactions:
        logger.info(f"  No interactions found for {person.canonical_name}")
        return 0

    # Convert to dict format expected by extractor
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

    # Extract facts
    extracted_facts = fact_extractor.extract_facts(
        person_id=person.id,
        person_name=person.canonical_name,
        interactions=interaction_dicts,
    )

    return len(extracted_facts)


def batch_extract_facts(
    limit: int = 50,
    skip_existing: bool = True,
    dry_run: bool = False,
    delay_seconds: float = 1.0,
) -> dict:
    """
    Batch extract facts for top contacts.

    Args:
        limit: Number of top people to process
        skip_existing: Skip people who already have facts
        dry_run: If True, don't actually extract (just report what would be done)
        delay_seconds: Delay between API calls to avoid rate limiting

    Returns:
        Stats dict
    """
    fact_store = get_person_fact_store()
    fact_extractor = get_person_fact_extractor()
    interaction_store = get_interaction_store()

    stats = {
        'people_processed': 0,
        'people_skipped': 0,
        'total_facts_extracted': 0,
        'errors': 0,
    }

    logger.info(f"Getting top {limit} people by relationship strength...")
    top_people = get_top_people_by_strength(limit)
    logger.info(f"Found {len(top_people)} people with interactions")

    for i, person in enumerate(top_people, 1):
        # Check if person already has facts
        existing_facts = fact_store.get_for_person(person.id)

        if skip_existing and existing_facts:
            logger.info(f"[{i}/{len(top_people)}] Skipping {person.canonical_name} (already has {len(existing_facts)} facts)")
            stats['people_skipped'] += 1
            continue

        logger.info(f"[{i}/{len(top_people)}] Extracting facts for {person.canonical_name} (strength: {person.relationship_strength:.2f})...")

        if dry_run:
            logger.info(f"  [DRY RUN] Would extract facts")
            stats['people_processed'] += 1
            continue

        try:
            facts_count = extract_facts_for_person(person, interaction_store, fact_extractor)
            logger.info(f"  Done ({facts_count} facts)")
            stats['people_processed'] += 1
            stats['total_facts_extracted'] += facts_count

            # Rate limiting delay
            if delay_seconds > 0 and i < len(top_people):
                time.sleep(delay_seconds)

        except Exception as e:
            logger.error(f"  Error: {e}")
            stats['errors'] += 1

    # Summary
    logger.info("")
    logger.info("=== Batch Extract Summary ===")
    logger.info(f"People processed: {stats['people_processed']}")
    logger.info(f"People skipped (existing facts): {stats['people_skipped']}")
    logger.info(f"Total facts extracted: {stats['total_facts_extracted']}")
    logger.info(f"Errors: {stats['errors']}")

    if dry_run:
        logger.info("[DRY RUN - no actual extraction performed]")

    return stats


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Batch extract Quick Facts for top contacts'
    )
    parser.add_argument(
        '--limit', '-n',
        type=int,
        default=50,
        help='Number of top people to process (default: 50)'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Re-extract facts even for people who already have them'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without actually extracting'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=1.0,
        help='Delay between API calls in seconds (default: 1.0)'
    )

    args = parser.parse_args()

    batch_extract_facts(
        limit=args.limit,
        skip_existing=not args.force,
        dry_run=args.dry_run,
        delay_seconds=args.delay,
    )

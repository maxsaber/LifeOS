#!/usr/bin/env python3
"""
Sync PersonEntity stats from interaction database.

This script updates:
- email_count: number of gmail interactions
- meeting_count: number of calendar interactions
- mention_count: number of vault/granola interactions
- message_count: number of imessage + whatsapp interactions
- last_seen: most recent interaction timestamp
"""
import sqlite3
import logging
from datetime import datetime, timezone

from api.services.person_entity import get_person_entity_store
from api.services.interaction_store import get_interaction_db_path
from api.services.source_entity import get_source_entity_store

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def sync_person_stats(dry_run: bool = True) -> dict:
    """
    Sync PersonEntity stats from interaction database.

    Args:
        dry_run: If True, don't actually modify the database

    Returns:
        Stats dict
    """
    store = get_person_entity_store()
    source_store = get_source_entity_store()
    db_path = get_interaction_db_path()

    conn = sqlite3.connect(db_path)

    # Get counts by person and source type
    cursor = conn.execute("""
        SELECT person_id, source_type, COUNT(*) as cnt, MAX(timestamp) as last_ts
        FROM interactions
        GROUP BY person_id, source_type
    """)

    # Build stats per person
    person_stats: dict[str, dict] = {}
    for row in cursor.fetchall():
        person_id, source_type, count, last_ts = row
        if person_id not in person_stats:
            person_stats[person_id] = {
                'gmail': 0,
                'calendar': 0,
                'vault': 0,
                'granola': 0,
                'imessage': 0,
                'whatsapp': 0,
                'last_ts': None,
            }
        person_stats[person_id][source_type] = count
        if last_ts:
            ts = datetime.fromisoformat(last_ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if person_stats[person_id]['last_ts'] is None or ts > person_stats[person_id]['last_ts']:
                person_stats[person_id]['last_ts'] = ts

    conn.close()

    stats = {
        'people_updated': 0,
        'people_not_found': 0,
        'total_interactions_counted': 0,
    }

    # Update people who have interactions
    for person_id, counts in person_stats.items():
        entity = store.get_by_id(person_id)
        if not entity:
            stats['people_not_found'] += 1
            continue

        email_count = counts['gmail']
        meeting_count = counts['calendar']
        mention_count = counts['vault'] + counts['granola']
        message_count = counts['imessage'] + counts['whatsapp']
        total = email_count + meeting_count + mention_count + message_count
        stats['total_interactions_counted'] += total

        # Get source entity count
        source_entity_count = source_store.count_for_person(person_id)

        # Check if update needed
        needs_update = (
            entity.email_count != email_count or
            entity.meeting_count != meeting_count or
            entity.mention_count != mention_count or
            entity.message_count != message_count or
            entity.source_entity_count != source_entity_count
        )

        if needs_update:
            if not dry_run:
                entity.email_count = email_count
                entity.meeting_count = meeting_count
                entity.mention_count = mention_count
                entity.message_count = message_count
                entity.source_entity_count = source_entity_count
                if counts['last_ts'] and (entity.last_seen is None or counts['last_ts'] > entity.last_seen):
                    entity.last_seen = counts['last_ts']
                store.update(entity)
            stats['people_updated'] += 1

            if stats['people_updated'] <= 20:
                logger.info(f"Updated {entity.canonical_name}: email={email_count}, meeting={meeting_count}, mention={mention_count}, message={message_count}, sources={source_entity_count}")

    # Update people who have no interactions (or update source_entity_count for those not in person_stats)
    for entity in store.get_all():
        if entity.id in person_stats:
            continue  # Already handled above

        source_entity_count = source_store.count_for_person(entity.id)
        needs_update = (
            entity.email_count > 0 or
            entity.meeting_count > 0 or
            entity.mention_count > 0 or
            entity.message_count > 0 or
            entity.source_entity_count != source_entity_count
        )

        if needs_update:
            if not dry_run:
                entity.email_count = 0
                entity.meeting_count = 0
                entity.mention_count = 0
                entity.message_count = 0
                entity.source_entity_count = source_entity_count
                store.update(entity)
            stats['people_updated'] += 1
            if stats['people_updated'] <= 30:
                logger.info(f"Updated {entity.canonical_name}: no interactions, sources={source_entity_count}")

    if not dry_run:
        store.save()

    logger.info(f"\n=== Sync Summary ===")
    logger.info(f"People updated: {stats['people_updated']}")
    logger.info(f"People not found: {stats['people_not_found']}")
    logger.info(f"Total interactions: {stats['total_interactions_counted']}")

    if dry_run:
        logger.info("DRY RUN - no changes made")

    return stats


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Sync PersonEntity stats from interactions')
    parser.add_argument('--execute', action='store_true', help='Actually apply changes')
    args = parser.parse_args()

    sync_person_stats(dry_run=not args.execute)

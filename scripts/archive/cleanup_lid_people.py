#!/usr/bin/env python3
"""
One-time cleanup script to remove PersonEntities created from WhatsApp @lid messages.

These entities have phone-number-like display names (e.g., "+1∙∙∙∙∙∙∙∙90") because
WhatsApp linked device IDs (@lid) are not real phone numbers and couldn't be resolved
to actual contacts.

This script:
1. Identifies PersonEntities with phone-number display names from WhatsApp
2. Deletes their associated interactions from interactions.db
3. Removes the PersonEntities from people_entities.json

Run with --execute to actually make changes (default is dry run).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import re
import sqlite3
import argparse
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
PEOPLE_FILE = DATA_DIR / "people_entities.json"
INTERACTIONS_DB = DATA_DIR / "interactions.db"
MERGED_IDS_FILE = DATA_DIR / "merged_person_ids.json"


def find_bad_people() -> list[dict]:
    """Find PersonEntities with phone-number-like display names from WhatsApp."""
    with open(PEOPLE_FILE) as f:
        data = json.load(f)

    # Load merged mappings to skip merged people
    merged_from = set()
    if MERGED_IDS_FILE.exists():
        with open(MERGED_IDS_FILE) as f:
            merged_mappings = json.load(f)
            merged_from = set(merged_mappings.keys())

    # Pattern for phone-number-like names
    phone_pattern = re.compile(r'^[\+\d\s\-\(\)∙\.]+$')

    bad_people = []
    for p in data:
        if 'whatsapp' in p.get('sources', []):
            name = p.get('display_name', '')
            pid = p['id']
            # Check if name looks like a phone number and not merged
            if phone_pattern.match(name) and len(name) >= 5 and pid not in merged_from:
                bad_people.append({
                    'id': pid,
                    'display_name': name,
                    'message_count': p.get('message_count', 0),
                })

    return bad_people


def cleanup_lid_people(dry_run: bool = True) -> dict:
    """Remove bad PersonEntities and their interactions."""
    stats = {
        'people_found': 0,
        'people_deleted': 0,
        'interactions_deleted': 0,
    }

    bad_people = find_bad_people()
    stats['people_found'] = len(bad_people)

    if not bad_people:
        logger.info("No bad people found to clean up")
        return stats

    bad_ids = [p['id'] for p in bad_people]

    logger.info(f"Found {len(bad_people)} PersonEntities with phone-number names:")
    for p in sorted(bad_people, key=lambda x: -x['message_count'])[:10]:
        logger.info(f"  {p['display_name']} ({p['message_count']} msgs)")
    if len(bad_people) > 10:
        logger.info(f"  ... and {len(bad_people) - 10} more")

    # Delete interactions
    conn = sqlite3.connect(INTERACTIONS_DB)
    cursor = conn.cursor()

    placeholders = ','.join('?' * len(bad_ids))
    cursor.execute(f"SELECT COUNT(*) FROM interactions WHERE person_id IN ({placeholders})", bad_ids)
    interaction_count = cursor.fetchone()[0]
    logger.info(f"Found {interaction_count} interactions to delete")

    if not dry_run:
        cursor.execute(f"DELETE FROM interactions WHERE person_id IN ({placeholders})", bad_ids)
        conn.commit()
        stats['interactions_deleted'] = cursor.rowcount
        logger.info(f"Deleted {stats['interactions_deleted']} interactions")

    conn.close()

    # Remove PersonEntities from JSON
    if not dry_run:
        with open(PEOPLE_FILE) as f:
            data = json.load(f)

        original_count = len(data)
        data = [p for p in data if p['id'] not in bad_ids]
        stats['people_deleted'] = original_count - len(data)

        # Backup before writing
        backup_path = PEOPLE_FILE.with_suffix(f'.json.backup.{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        with open(backup_path, 'w') as f:
            json.dump([p for p in json.load(open(PEOPLE_FILE))], f)
        logger.info(f"Created backup at {backup_path}")

        with open(PEOPLE_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Removed {stats['people_deleted']} PersonEntities from {PEOPLE_FILE.name}")

    return stats


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Clean up PersonEntities created from WhatsApp @lid messages')
    parser.add_argument('--execute', action='store_true', help='Actually delete (default is dry run)')
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("Cleanup WhatsApp @lid PersonEntities")
    logger.info("=" * 50)

    stats = cleanup_lid_people(dry_run=not args.execute)

    logger.info("")
    logger.info("=== Summary ===")
    logger.info(f"People found: {stats['people_found']}")
    logger.info(f"People deleted: {stats['people_deleted']}")
    logger.info(f"Interactions deleted: {stats['interactions_deleted']}")

    if not args.execute:
        logger.info("")
        logger.info("DRY RUN - no changes made. Run with --execute to apply.")

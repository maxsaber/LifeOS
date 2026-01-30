#!/usr/bin/env python3
"""
Fix Gmail interactions where sent emails have person_id = myself.

For emails I sent, the person_id should be the recipient, not myself.
This script re-resolves these emails to correctly assign them.
"""
import sqlite3
import logging
from datetime import datetime, timezone

from api.services.gmail import GmailService
from api.services.google_auth import GoogleAccount
from api.services.entity_resolver import get_entity_resolver
from api.services.interaction_store import get_interaction_db_path
from config.settings import settings

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def fix_sent_emails(dry_run: bool = True, account_type: GoogleAccount = None) -> dict:
    """
    Fix emails where person_id is incorrectly set to myself.

    For sent emails, re-resolve to find the recipient.
    """
    my_person_id = settings.my_person_id
    if not my_person_id:
        logger.error("MY_PERSON_ID not configured")
        return {"error": "MY_PERSON_ID not set"}

    logger.info(f"my_person_id: {my_person_id}")

    stats = {
        'total': 0,
        'fixed': 0,
        'deleted': 0,  # Couldn't find recipient
        'errors': 0,
    }

    db_path = get_interaction_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    resolver = get_entity_resolver()

    # Get all gmail interactions where person_id = myself
    cursor = conn.execute('''
        SELECT id, source_id, title FROM interactions
        WHERE source_type = 'gmail' AND person_id = ?
    ''', (my_person_id,))

    to_fix = cursor.fetchall()
    stats['total'] = len(to_fix)
    logger.info(f"Found {len(to_fix)} emails assigned to myself (likely sent)")

    if not to_fix:
        return stats

    # Initialize Gmail services for both accounts
    gmail_personal = GmailService(account_type=GoogleAccount.PERSONAL)
    gmail_work = GmailService(account_type=GoogleAccount.WORK)

    updates = []
    deletes = []

    for i, row in enumerate(to_fix):
        interaction_id = row['id']
        message_id = row['source_id']

        if not message_id:
            deletes.append(interaction_id)
            stats['deleted'] += 1
            continue

        try:
            # Try to fetch from personal first, then work
            email = None
            for gmail in [gmail_personal, gmail_work]:
                try:
                    email = gmail.get_message(message_id, include_body=False)
                    if email:
                        break
                except Exception:
                    pass

            if not email:
                # Couldn't fetch email - maybe deleted
                deletes.append(interaction_id)
                stats['deleted'] += 1
                continue

            # Parse recipient from To field
            if not email.to:
                deletes.append(interaction_id)
                stats['deleted'] += 1
                continue

            # Parse first recipient
            to_field = email.to.split(',')[0].strip()
            if '<' in to_field:
                recipient_email = to_field.split('<')[1].rstrip('>')
                recipient_name = to_field.split('<')[0].strip().strip('"')
            else:
                recipient_email = to_field
                recipient_name = None

            # Resolve recipient
            result = resolver.resolve(
                name=recipient_name,
                email=recipient_email,
                create_if_missing=True,
            )

            if not result or not result.entity or result.entity.id == my_person_id:
                # Still resolves to myself - delete
                deletes.append(interaction_id)
                stats['deleted'] += 1
                continue

            new_person_id = result.entity.id
            updates.append((new_person_id, interaction_id))
            stats['fixed'] += 1

        except Exception as e:
            logger.warning(f"Error processing {message_id}: {e}")
            stats['errors'] += 1

        if (i + 1) % 100 == 0:
            logger.info(f"Processed {i + 1}/{len(to_fix)} emails (fixed: {stats['fixed']}, deleted: {stats['deleted']})")

    # Apply changes
    if not dry_run:
        if updates:
            conn.executemany(
                "UPDATE interactions SET person_id = ? WHERE id = ?",
                updates
            )
            logger.info(f"Updated {len(updates)} interactions")

        if deletes:
            placeholders = ','.join('?' * len(deletes))
            conn.execute(
                f"DELETE FROM interactions WHERE id IN ({placeholders})",
                deletes
            )
            logger.info(f"Deleted {len(deletes)} interactions")

        conn.commit()
    else:
        logger.info("DRY RUN - no changes made")

    conn.close()
    return stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fix Gmail sent emails person_id")
    parser.add_argument("--apply", action="store_true", help="Actually apply changes")
    args = parser.parse_args()

    stats = fix_sent_emails(dry_run=not args.apply)
    print(f"\nResults: {stats}")

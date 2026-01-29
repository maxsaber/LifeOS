#!/usr/bin/env python3
"""
Sync Gmail and Calendar interactions to the interactions database.

Creates Interaction records for:
- Emails (both sent and received)
- Calendar events (for each attendee)

Syncs from both personal and work Google accounts.
"""
import sqlite3
import uuid
import logging
import argparse
from datetime import datetime, timedelta, timezone

from api.services.gmail import GmailService
from api.services.calendar import CalendarService
from api.services.google_auth import GoogleAccount
from api.services.entity_resolver import get_entity_resolver
from api.services.interaction_store import get_interaction_db_path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def sync_gmail_interactions(
    account_type: GoogleAccount,
    days_back: int = 365,
    dry_run: bool = True,
    batch_size: int = 100,
) -> dict:
    """
    Sync Gmail interactions for an account.

    Args:
        account_type: Which Google account to use
        days_back: How many days back to sync
        dry_run: If True, don't actually insert

    Returns:
        Stats dict
    """
    stats = {
        'fetched': 0,
        'inserted': 0,
        'already_exists': 0,
        'no_person': 0,
        'errors': 0,
    }

    db_path = get_interaction_db_path()
    conn = sqlite3.connect(db_path)
    resolver = get_entity_resolver()

    # Get existing interactions to avoid duplicates
    existing = set()
    cursor = conn.execute(
        "SELECT source_id FROM interactions WHERE source_type = 'gmail'"
    )
    for row in cursor.fetchall():
        if row[0]:
            existing.add(row[0])
    logger.info(f"Found {len(existing)} existing gmail interactions")

    gmail = GmailService(account_type=account_type)
    after_date = datetime.now(timezone.utc) - timedelta(days=days_back)

    # Fetch emails in batches using search
    # Gmail API limits to 500 results per query, so we paginate
    try:
        logger.info(f"Fetching emails from {account_type.value} account (last {days_back} days)...")

        # Search for all emails after the date
        result = gmail.service.users().messages().list(
            userId="me",
            q=f"after:{after_date.strftime('%Y/%m/%d')}",
            maxResults=500,
        ).execute()

        messages = result.get("messages", [])
        next_page_token = result.get("nextPageToken")

        while next_page_token:
            result = gmail.service.users().messages().list(
                userId="me",
                q=f"after:{after_date.strftime('%Y/%m/%d')}",
                maxResults=500,
                pageToken=next_page_token,
            ).execute()
            messages.extend(result.get("messages", []))
            next_page_token = result.get("nextPageToken")

            if len(messages) % 1000 == 0:
                logger.info(f"  Fetched {len(messages)} message IDs...")

        logger.info(f"Found {len(messages)} total messages")
        stats['fetched'] = len(messages)

        batch = []
        processed = 0

        for msg_data in messages:
            message_id = msg_data["id"]

            # Skip if already exists
            if message_id in existing:
                stats['already_exists'] += 1
                continue

            try:
                # Fetch message details (metadata only for speed)
                email = gmail.get_message(message_id, include_body=False)
                if not email:
                    stats['errors'] += 1
                    continue

                # Resolve sender to PersonEntity
                result = resolver.resolve(
                    name=email.sender_name if email.sender_name != email.sender else None,
                    email=email.sender,
                    create_if_missing=True,
                )

                if not result or not result.entity:
                    stats['no_person'] += 1
                    continue

                person_id = result.entity.id

                # Create interaction
                interaction_id = str(uuid.uuid4())
                timestamp = email.date.isoformat()
                source_link = f"https://mail.google.com/mail/u/0/#inbox/{message_id}"

                batch.append((
                    interaction_id,
                    person_id,
                    timestamp,
                    'gmail',
                    email.subject or "(No Subject)",
                    email.snippet[:200] if email.snippet else None,
                    source_link,
                    message_id,
                    datetime.now(timezone.utc).isoformat(),
                ))

                if len(batch) >= batch_size:
                    if not dry_run:
                        _insert_batch(conn, batch)
                    stats['inserted'] += len(batch)
                    batch = []

                processed += 1
                if processed % 500 == 0:
                    logger.info(f"  Processed {processed} emails...")

            except Exception as e:
                logger.warning(f"Error processing email {message_id}: {e}")
                stats['errors'] += 1

        # Insert remaining
        if batch:
            if not dry_run:
                _insert_batch(conn, batch)
            stats['inserted'] += len(batch)

        if not dry_run:
            conn.commit()

    except Exception as e:
        logger.error(f"Failed to sync Gmail: {e}")
        stats['errors'] += 1

    conn.close()
    return stats


def sync_calendar_interactions(
    account_type: GoogleAccount,
    days_back: int = 365,
    dry_run: bool = True,
) -> dict:
    """
    Sync Calendar interactions for an account.

    Creates one interaction per attendee per event.

    Args:
        account_type: Which Google account to use
        days_back: How many days back to sync
        dry_run: If True, don't actually insert

    Returns:
        Stats dict
    """
    stats = {
        'events_fetched': 0,
        'interactions_inserted': 0,
        'already_exists': 0,
        'no_person': 0,
        'errors': 0,
    }

    db_path = get_interaction_db_path()
    conn = sqlite3.connect(db_path)
    resolver = get_entity_resolver()

    # Get existing interactions to avoid duplicates
    existing = set()
    cursor = conn.execute(
        "SELECT source_id FROM interactions WHERE source_type = 'calendar'"
    )
    for row in cursor.fetchall():
        if row[0]:
            existing.add(row[0])
    logger.info(f"Found {len(existing)} existing calendar interactions")

    calendar = CalendarService(account_type=account_type)
    start_date = datetime.now(timezone.utc) - timedelta(days=days_back)
    end_date = datetime.now(timezone.utc) + timedelta(days=30)  # Include upcoming

    try:
        logger.info(f"Fetching calendar events from {account_type.value} account...")
        events = calendar.get_events_in_range(
            start_date=start_date,
            end_date=end_date,
            max_results=2500,
        )
        logger.info(f"Found {len(events)} events")
        stats['events_fetched'] = len(events)

        batch = []

        for event in events:
            # Process each attendee
            attendees = event.attendees if event.attendees else []

            # Also try to parse attendees from title (Task 3: parse meeting titles)
            title_attendees = _parse_attendees_from_title(event.title)
            for ta in title_attendees:
                if ta not in attendees:
                    attendees.append(ta)

            if not attendees:
                # No attendees - skip
                continue

            for attendee in attendees:
                # Create unique source_id per event+attendee
                source_id = f"{event.event_id}:{attendee}"

                if source_id in existing:
                    stats['already_exists'] += 1
                    continue

                # Parse attendee (could be "Name <email>" or just email)
                attendee_name = None
                attendee_email = None
                if "<" in attendee and ">" in attendee:
                    import re
                    match = re.match(r'^([^<]+)<([^>]+)>$', attendee.strip())
                    if match:
                        attendee_name = match.group(1).strip()
                        attendee_email = match.group(2).strip()
                elif "@" in attendee:
                    attendee_email = attendee
                else:
                    attendee_name = attendee

                # Resolve to PersonEntity
                result = resolver.resolve(
                    name=attendee_name,
                    email=attendee_email,
                    create_if_missing=True,
                )

                if not result or not result.entity:
                    stats['no_person'] += 1
                    continue

                person_id = result.entity.id

                # Create interaction
                interaction_id = str(uuid.uuid4())
                timestamp = event.start_time.isoformat()
                source_link = event.html_link or ""

                batch.append((
                    interaction_id,
                    person_id,
                    timestamp,
                    'calendar',
                    event.title,
                    event.description[:200] if event.description else None,
                    source_link,
                    source_id,
                    datetime.now(timezone.utc).isoformat(),
                ))
                stats['interactions_inserted'] += 1

        # Insert batch
        if batch and not dry_run:
            _insert_batch(conn, batch)
            conn.commit()

    except Exception as e:
        logger.error(f"Failed to sync Calendar: {e}")
        import traceback
        traceback.print_exc()
        stats['errors'] += 1

    conn.close()
    return stats


def _parse_attendees_from_title(title: str) -> list[str]:
    """
    Parse attendee names from meeting titles.

    Handles patterns like:
    - "1:1 with John Smith"
    - "Sync: Nathan/Taylor"
    - "Meeting with Sarah Chen"
    - "Nathan <> Rushi"

    Args:
        title: Meeting title

    Returns:
        List of extracted names
    """
    import re

    names = []
    title_lower = title.lower()

    # Pattern: "1:1 with <name>"
    match = re.search(r'1:1\s+with\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', title, re.IGNORECASE)
    if match:
        names.append(match.group(1))

    # Pattern: "Meeting with <name>"
    match = re.search(r'meeting\s+with\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', title, re.IGNORECASE)
    if match:
        names.append(match.group(1))

    # Pattern: "Sync: Name1/Name2" or "Sync: Name1 / Name2"
    match = re.search(r'sync[:\s]+([A-Z][a-z]+)\s*/\s*([A-Z][a-z]+)', title, re.IGNORECASE)
    if match:
        names.append(match.group(1))
        names.append(match.group(2))

    # Pattern: "Name1 <> Name2" or "Name1 <-> Name2"
    match = re.search(r'([A-Z][a-z]+)\s*<-?>\s*([A-Z][a-z]+)', title)
    if match:
        names.append(match.group(1))
        names.append(match.group(2))

    # Pattern: "Call with <name>"
    match = re.search(r'call\s+with\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', title, re.IGNORECASE)
    if match:
        names.append(match.group(1))

    # Pattern: "Intro: Name1 <> Name2"
    match = re.search(r'intro[:\s]+([A-Z][a-z]+)\s*(?:<-?>|/|&)\s*([A-Z][a-z]+)', title, re.IGNORECASE)
    if match:
        names.append(match.group(1))
        names.append(match.group(2))

    return list(set(names))


def _insert_batch(conn: sqlite3.Connection, batch: list):
    """Insert a batch of interactions."""
    conn.executemany("""
        INSERT OR IGNORE INTO interactions
        (id, person_id, timestamp, source_type, title, snippet, source_link, source_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, batch)


def main():
    parser = argparse.ArgumentParser(description='Sync Gmail and Calendar to interactions')
    parser.add_argument('--execute', action='store_true', help='Actually apply changes')
    parser.add_argument('--days', type=int, default=365, help='Days back to sync')
    parser.add_argument('--gmail-only', action='store_true', help='Only sync Gmail')
    parser.add_argument('--calendar-only', action='store_true', help='Only sync Calendar')
    parser.add_argument('--personal-only', action='store_true', help='Only sync personal account')
    parser.add_argument('--work-only', action='store_true', help='Only sync work account')
    args = parser.parse_args()

    dry_run = not args.execute

    accounts = []
    if args.personal_only:
        accounts = [GoogleAccount.PERSONAL]
    elif args.work_only:
        accounts = [GoogleAccount.WORK]
    else:
        accounts = [GoogleAccount.PERSONAL, GoogleAccount.WORK]

    all_stats = {}

    for account in accounts:
        if not args.calendar_only:
            logger.info(f"\n=== Syncing Gmail ({account.value}) ===")
            stats = sync_gmail_interactions(
                account_type=account,
                days_back=args.days,
                dry_run=dry_run,
            )
            all_stats[f'gmail_{account.value}'] = stats
            logger.info(f"Gmail {account.value}: fetched={stats['fetched']}, inserted={stats['inserted']}, exists={stats['already_exists']}, errors={stats['errors']}")

        if not args.gmail_only:
            logger.info(f"\n=== Syncing Calendar ({account.value}) ===")
            stats = sync_calendar_interactions(
                account_type=account,
                days_back=args.days,
                dry_run=dry_run,
            )
            all_stats[f'calendar_{account.value}'] = stats
            logger.info(f"Calendar {account.value}: events={stats['events_fetched']}, inserted={stats['interactions_inserted']}, exists={stats['already_exists']}, errors={stats['errors']}")

    if dry_run:
        logger.info("\nDRY RUN - no changes made. Use --execute to apply.")

    return all_stats


if __name__ == '__main__':
    main()

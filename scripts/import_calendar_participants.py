#!/usr/bin/env python3
"""
Import calendar participants as PersonEntity records.

Scans the interactions database for calendar participants and creates
PersonEntity records for any that don't already exist.
"""
import argparse
import logging
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from api.services.person_entity import PersonEntity, get_person_entity_store
from api.services.interaction_store import get_interaction_db_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def extract_name_from_email(email: str) -> str:
    """Extract a display name from an email address."""
    local_part = email.split("@")[0]
    # Handle common patterns like firstlast, first.last, first_last
    # Split on common delimiters
    parts = re.split(r"[._]", local_part)
    # Capitalize each part
    name_parts = [p.capitalize() for p in parts if p]
    return " ".join(name_parts)


def get_calendar_participants(domain_filter: str = None) -> dict[str, dict]:
    """
    Get all unique calendar participants from interactions.

    Returns:
        Dict mapping email/name to participant info
    """
    db_path = get_interaction_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Extract participant from source_id (format: event_id:participant)
    query = """
        SELECT
            substr(source_id, instr(source_id, ':') + 1) as participant,
            COUNT(*) as event_count,
            MIN(timestamp) as first_seen,
            MAX(timestamp) as last_seen
        FROM interactions
        WHERE source_type = 'calendar'
          AND source_id LIKE '%:%'
        GROUP BY participant
        ORDER BY event_count DESC
    """

    cursor = conn.execute(query)

    participants = {}
    for row in cursor:
        participant = row["participant"]

        # Skip empty or invalid
        if not participant or len(participant) < 2:
            continue

        # Apply domain filter if specified
        if domain_filter and domain_filter not in participant.lower():
            continue

        participants[participant] = {
            "participant": participant,
            "event_count": row["event_count"],
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen"],
            "is_email": "@" in participant,
        }

    conn.close()
    return participants


def main():
    parser = argparse.ArgumentParser(
        description="Import calendar participants as PersonEntity records"
    )
    parser.add_argument(
        "--domain",
        type=str,
        default=None,
        help="Filter to participants with this domain (e.g., 'movementlabs')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be imported without making changes",
    )
    parser.add_argument(
        "--min-events",
        type=int,
        default=1,
        help="Minimum calendar events to include (default: 1)",
    )
    args = parser.parse_args()

    logger.info("Scanning calendar participants...")

    # Get participants
    participants = get_calendar_participants(args.domain)
    logger.info(f"Found {len(participants)} unique participants")

    # Filter by minimum events
    participants = {
        k: v for k, v in participants.items()
        if v["event_count"] >= args.min_events
    }
    logger.info(f"After min_events filter: {len(participants)} participants")

    # Load person store
    store = get_person_entity_store()
    existing_count = len(store.get_all())
    logger.info(f"Existing people in store: {existing_count}")

    # Build lookup for existing emails
    existing_emails = set()
    existing_names = set()
    for person in store.get_all():
        for email in person.emails:
            existing_emails.add(email.lower())
        existing_names.add(person.canonical_name.lower())
        for alias in person.aliases:
            existing_names.add(alias.lower())

    # Find participants that need records
    to_create = []
    already_exists = 0

    for participant, info in participants.items():
        participant_lower = participant.lower()

        # Check if already exists
        if info["is_email"]:
            if participant_lower in existing_emails:
                already_exists += 1
                continue
        else:
            if participant_lower in existing_names:
                already_exists += 1
                continue

        to_create.append(info)

    logger.info(f"Already in store: {already_exists}")
    logger.info(f"Need to create: {len(to_create)}")

    if args.dry_run:
        logger.info("\n=== DRY RUN - Would create: ===")
        for info in to_create[:20]:
            p = info["participant"]
            name = extract_name_from_email(p) if info["is_email"] else p
            logger.info(f"  {name} ({p}) - {info['event_count']} events")
        if len(to_create) > 20:
            logger.info(f"  ... and {len(to_create) - 20} more")
        return

    # Create PersonEntity records
    created = 0
    for info in to_create:
        participant = info["participant"]
        is_email = info["is_email"]

        # Determine name and email
        if is_email:
            email = participant.lower()
            name = extract_name_from_email(email)
        else:
            email = None
            name = participant

        # Determine category from domain
        category = "unknown"
        company = None
        if is_email:
            domain = email.split("@")[1] if "@" in email else ""
            if "movementlabs" in domain:
                category = "work"
                company = "Movement Labs"
            elif domain in ("gmail.com", "yahoo.com", "hotmail.com", "icloud.com"):
                category = "personal"

        # Create entity
        entity = PersonEntity(
            canonical_name=name,
            display_name=name,
            emails=[email] if email else [],
            category=category,
            company=company,
            sources=["calendar"],
            first_seen=datetime.fromisoformat(info["first_seen"]) if info["first_seen"] else None,
            last_seen=datetime.fromisoformat(info["last_seen"]) if info["last_seen"] else None,
            meeting_count=info["event_count"],
        )

        store.add(entity)
        created += 1

        if created % 50 == 0:
            logger.info(f"Created {created}/{len(to_create)} records...")

    # Save
    store.save()

    logger.info(f"\n=== Import Complete ===")
    logger.info(f"Created: {created} new PersonEntity records")
    logger.info(f"Total in store: {len(store.get_all())}")


if __name__ == "__main__":
    main()

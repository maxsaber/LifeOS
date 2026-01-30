#!/usr/bin/env python3
"""
Auto-categorize people based on interaction patterns and heuristics.

Categories:
- family: Same last name as user, high interaction frequency
- work: Work email domains, frequent calendar meetings
- personal: High interaction frequency, not work-related
- unknown: Default for low/no interaction people
"""
import sys
import re
import logging
import argparse
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.services.person_entity import get_person_entity_store

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# User's last name for family detection
USER_LAST_NAME = "Ramia"

# Work email domains
WORK_DOMAINS = {
    "movementlabs.xyz",
    "movement.xyz",
    "movementnetwork.xyz",
}

# Personal email domains (not work indicators)
PERSONAL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "icloud.com",
    "me.com",
    "aol.com",
}


def extract_last_name(name: str) -> str:
    """Extract last name from full name."""
    if not name:
        return ""
    parts = name.strip().split()
    if len(parts) >= 2:
        return parts[-1]
    return ""


def get_email_domain(email: str) -> str:
    """Extract domain from email address."""
    if not email or "@" not in email:
        return ""
    return email.split("@")[-1].lower()


def categorize_person(person) -> tuple[str, str]:
    """
    Determine category for a person.

    Returns:
        Tuple of (category, reason)
    """
    # Extract relevant data
    name = person.canonical_name or ""
    last_name = extract_last_name(name)
    emails = person.emails or []
    email_domains = [get_email_domain(e) for e in emails]

    total_interactions = (
        person.email_count +
        person.meeting_count +
        person.message_count +
        person.mention_count
    )

    # 1. Check for family (same last name)
    if last_name and last_name.lower() == USER_LAST_NAME.lower():
        return "family", f"same last name ({last_name})"

    # 2. Check for work (work email domain or many meetings)
    has_work_email = any(d in WORK_DOMAINS for d in email_domains)
    has_many_meetings = person.meeting_count >= 5

    if has_work_email:
        return "work", f"work email domain"

    if has_many_meetings and not any(d in PERSONAL_DOMAINS for d in email_domains):
        return "work", f"frequent meetings ({person.meeting_count})"

    # 3. Check for personal (high message frequency)
    if person.message_count >= 100:
        return "personal", f"frequent messages ({person.message_count})"

    # 4. Check for personal (moderate interaction across multiple sources)
    if total_interactions >= 50 and len(person.sources) >= 2:
        return "personal", f"multi-source interactions ({total_interactions})"

    # 5. Default to unknown for low interaction people
    return "unknown", "insufficient interaction data"


def auto_categorize(dry_run: bool = True) -> dict:
    """
    Auto-categorize all people.

    Args:
        dry_run: If True, don't actually modify data

    Returns:
        Stats dict
    """
    store = get_person_entity_store()
    people = store.get_all()

    stats = {
        'total': len(people),
        'family': 0,
        'work': 0,
        'personal': 0,
        'unknown': 0,
        'changed': 0,
        'unchanged': 0,
    }

    changes = []

    for person in people:
        new_category, reason = categorize_person(person)
        old_category = person.category or "unknown"

        stats[new_category] += 1

        if old_category != new_category:
            changes.append((person.canonical_name, old_category, new_category, reason))
            stats['changed'] += 1

            if not dry_run:
                person.category = new_category
                store.update(person)
        else:
            stats['unchanged'] += 1

    if not dry_run:
        store.save()

    # Log changes
    logger.info(f"\n=== Category Changes ===")
    for name, old, new, reason in changes[:50]:  # Show first 50
        logger.info(f"  {name}: {old} → {new} ({reason})")

    if len(changes) > 50:
        logger.info(f"  ... and {len(changes) - 50} more changes")

    # Summary
    logger.info(f"\n=== Auto-Categorization Summary ===")
    logger.info(f"Total people: {stats['total']}")
    logger.info(f"Family: {stats['family']}")
    logger.info(f"Work: {stats['work']}")
    logger.info(f"Personal: {stats['personal']}")
    logger.info(f"Unknown: {stats['unknown']}")
    logger.info(f"Changed: {stats['changed']}")
    logger.info(f"Unchanged: {stats['unchanged']}")

    if dry_run:
        logger.info("\nDRY RUN - no changes made. Use --execute to apply.")

    return stats


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Auto-categorize people')
    parser.add_argument('--execute', action='store_true', help='Actually apply changes')
    args = parser.parse_args()

    auto_categorize(dry_run=not args.execute)

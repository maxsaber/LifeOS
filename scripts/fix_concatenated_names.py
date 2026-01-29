#!/usr/bin/env python3
"""
Fix concatenated names from calendar source.

The calendar sync creates person records with names like "Zoestein" instead of
"Zoe Stein" because it uses the email username as the display name.

This script:
1. Finds single-word names that look like concatenated first+last names
2. Splits them using a common first names dictionary
3. Updates the canonical_name to proper format

Usage:
    python scripts/fix_concatenated_names.py           # Dry run
    python scripts/fix_concatenated_names.py --execute # Apply changes
"""
import sys
import re
import logging
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.services.person_entity import get_person_entity_store

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Common first names for splitting (lowercase)
# This list covers most common US names
COMMON_FIRST_NAMES = {
    # Male names
    'aaron', 'adam', 'adrian', 'aidan', 'alan', 'albert', 'alex', 'alexander',
    'andrew', 'anthony', 'antonio', 'austin', 'benjamin', 'blake', 'bradley',
    'brandon', 'brian', 'bruce', 'bryce', 'caleb', 'cameron', 'carl', 'carlos',
    'casey', 'charles', 'chase', 'chris', 'christian', 'christopher', 'cody',
    'colin', 'connor', 'corey', 'craig', 'dan', 'daniel', 'david', 'dean',
    'dennis', 'derek', 'dominic', 'donald', 'douglas', 'drew', 'dustin',
    'dylan', 'edward', 'eli', 'elijah', 'eric', 'ethan', 'evan', 'frank',
    'gabriel', 'garrett', 'gary', 'george', 'grant', 'greg', 'gregory',
    'henry', 'hunter', 'ian', 'isaac', 'jack', 'jackson', 'jacob', 'jake',
    'james', 'jason', 'jay', 'jeff', 'jeffrey', 'jeremy', 'jesse', 'jim',
    'joe', 'joel', 'john', 'johnny', 'jon', 'jonathan', 'jordan', 'joseph',
    'josh', 'joshua', 'juan', 'justin', 'keith', 'ken', 'kenneth', 'kevin',
    'kyle', 'lance', 'larry', 'leo', 'logan', 'louis', 'lucas', 'luis',
    'luke', 'marcus', 'mark', 'martin', 'matt', 'matthew', 'max', 'michael',
    'mike', 'nathan', 'nicholas', 'nick', 'noah', 'oliver', 'oscar', 'owen',
    'patrick', 'paul', 'peter', 'philip', 'raymond', 'richard', 'rick',
    'robert', 'ron', 'ronald', 'ross', 'russell', 'ryan', 'sam', 'samuel',
    'scott', 'sean', 'sebastian', 'shane', 'shawn', 'simon', 'spencer',
    'stephen', 'steve', 'steven', 'taylor', 'thomas', 'tim', 'timothy',
    'todd', 'tom', 'tony', 'travis', 'trevor', 'troy', 'tyler', 'victor',
    'vincent', 'wesley', 'william', 'wyatt', 'zachary', 'zach',
    # Female names
    'abby', 'abigail', 'adriana', 'alexandra', 'alexis', 'alice', 'alicia',
    'allison', 'alyssa', 'amanda', 'amber', 'amy', 'ana', 'andrea', 'angela',
    'anna', 'annabelle', 'anne', 'annie', 'ariel', 'ashley', 'audrey',
    'bailey', 'barbara', 'becky', 'beth', 'bethany', 'brenda', 'brianna',
    'bridget', 'brita', 'brittany', 'brooke', 'caitlin', 'carmen', 'carol',
    'caroline', 'carolyn', 'casey', 'cassandra', 'catherine', 'chelsea',
    'cheryl', 'chloe', 'christina', 'christine', 'cindy', 'claire', 'clara',
    'claudia', 'colleen', 'courtney', 'crystal', 'cynthia', 'danielle',
    'deborah', 'denise', 'diana', 'diane', 'donna', 'dorothy', 'elena',
    'elizabeth', 'ella', 'ellen', 'emily', 'emma', 'erica', 'erin', 'eva',
    'faith', 'fiona', 'frances', 'gabrielle', 'grace', 'hailey', 'hannah',
    'heather', 'helen', 'holly', 'jackie', 'jacqueline', 'jamie', 'jane',
    'janet', 'janice', 'jasmine', 'jean', 'jenna', 'jennifer', 'jenny',
    'jessica', 'jill', 'joan', 'joanna', 'jocelyn', 'jordan', 'josephine',
    'joyce', 'judith', 'judy', 'julia', 'julie', 'karen', 'kate', 'katherine',
    'kathleen', 'kathryn', 'kathy', 'katie', 'kayla', 'kelly', 'kerry',
    'kim', 'kimberly', 'kristen', 'kristin', 'kristina', 'laura', 'lauren',
    'leah', 'leslie', 'lily', 'linda', 'lindsay', 'lisa', 'liz', 'lori',
    'lucy', 'lynn', 'madeline', 'madison', 'maggie', 'margaret', 'maria',
    'marie', 'marilyn', 'martha', 'mary', 'megan', 'melanie', 'melissa',
    'meredith', 'michelle', 'miranda', 'molly', 'monica', 'morgan', 'nancy',
    'natalie', 'natasha', 'nicole', 'nina', 'olivia', 'paige', 'pamela',
    'patricia', 'paula', 'rachel', 'rebecca', 'renee', 'riley', 'robin',
    'rose', 'ruby', 'ruth', 'samantha', 'sandra', 'sara', 'sarah', 'savannah',
    'shannon', 'sharon', 'sheila', 'shelby', 'sophia', 'stephanie', 'sue',
    'susan', 'sydney', 'tamara', 'tara', 'taylor', 'teresa', 'theresa',
    'tiffany', 'tracy', 'valerie', 'vanessa', 'veronica', 'victoria',
    'virginia', 'wendy', 'whitney', 'zoe', 'zoë',
    # Additional common names
    'asha', 'atlas', 'causten', 'content', 'simone', 'rossy', 'leonardo',
    'carly', 'jaylin', 'abby', 'brita', 'elena', 'colleen',
}


def split_concatenated_name(name: str) -> str | None:
    """
    Try to split a concatenated name like 'Zoestein' into 'Zoe Stein'.

    Returns the split name or None if can't be split.
    """
    if ' ' in name:
        return None  # Already has space

    if len(name) < 6:
        return None  # Too short to be concatenated

    # Skip if it looks like an email address
    if '@' in name or '.' in name:
        return None

    name_lower = name.lower()

    # Skip if the whole name is a common first name (e.g., "Danielle", "Jonathan")
    if name_lower in COMMON_FIRST_NAMES:
        return None

    # Try to find a first name at the start
    for first_name in sorted(COMMON_FIRST_NAMES, key=len, reverse=True):
        if name_lower.startswith(first_name) and len(name_lower) > len(first_name):
            rest = name[len(first_name):]
            rest_lower = rest.lower()

            # Skip if the rest is also a common first name (would create "Chris Tine" from "Christine")
            if rest_lower in COMMON_FIRST_NAMES:
                return None

            # Skip if the rest is too short (likely not a last name)
            if len(rest) < 4:
                return None

            # Skip if the rest starts with common name suffixes that aren't last names
            bad_suffixes = ['ine', 'ina', 'lyn', 'ley', 'thy', 'iel', 'ald', 'atha', 'beth']
            if any(rest_lower.startswith(s) for s in bad_suffixes):
                return None

            # Capitalize properly
            first = name[:len(first_name)].capitalize()
            last = rest.capitalize()
            return f"{first} {last}"

    return None


def find_concatenated_names(calendar_only: bool = True) -> list:
    """
    Find all person records with concatenated names.

    Args:
        calendar_only: If True, only look at calendar-sourced names with work emails
    """
    store = get_person_entity_store()
    people = store.get_all()

    candidates = []

    for person in people:
        name = person.canonical_name

        # Skip if already has space
        if ' ' in name:
            continue

        # Skip short names (likely single names)
        if len(name) < 6:
            continue

        # If calendar_only, filter to calendar source with work emails
        if calendar_only:
            if 'calendar' not in person.sources:
                continue
            # Check if has a work email that matches the concatenated pattern
            has_matching_work_email = any(
                email.endswith('@movementlabs.com') and
                name.lower() == email.split('@')[0].lower()
                for email in (person.emails or [])
            )
            if not has_matching_work_email:
                continue

        # Try to split
        split_name = split_concatenated_name(name)
        if split_name:
            candidates.append({
                'id': person.id,
                'old_name': name,
                'new_name': split_name,
                'sources': person.sources,
                'emails': person.emails,
            })

    return candidates


def fix_concatenated_names(dry_run: bool = True) -> dict:
    """
    Fix concatenated names.

    Args:
        dry_run: If True, don't actually make changes

    Returns:
        Stats dict
    """
    store = get_person_entity_store()
    candidates = find_concatenated_names()

    stats = {
        'total_found': len(candidates),
        'updated': 0,
        'skipped': 0,
    }

    logger.info(f"\nFound {len(candidates)} concatenated names to fix:\n")

    for c in candidates:
        logger.info(f"  {c['old_name']} -> {c['new_name']}  (sources: {c['sources']})")

        if not dry_run:
            person = store.get_by_id(c['id'])
            if person:
                # Add old name as alias
                if person.aliases is None:
                    person.aliases = []
                if c['old_name'] not in person.aliases:
                    person.aliases.append(c['old_name'])

                # Update canonical name
                person.canonical_name = c['new_name']
                person.display_name = c['new_name']

                store.update(person)
                stats['updated'] += 1
            else:
                stats['skipped'] += 1

    if not dry_run:
        store.save()
        logger.info(f"\nUpdated {stats['updated']} names")

    logger.info(f"\n=== Summary ===")
    logger.info(f"Total found: {stats['total_found']}")
    logger.info(f"Updated: {stats['updated']}")
    logger.info(f"Skipped: {stats['skipped']}")

    if dry_run:
        logger.info("\nDRY RUN - no changes made. Use --execute to apply.")

    return stats


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Fix concatenated names')
    parser.add_argument('--execute', action='store_true', help='Actually apply changes')
    args = parser.parse_args()

    fix_concatenated_names(dry_run=not args.execute)

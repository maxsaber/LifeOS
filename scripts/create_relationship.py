#!/usr/bin/env python3
"""
Manually create relationships between people.

Use this when you know people are connected but the data doesn't show it.
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def search_people(query: str) -> list[dict]:
    """Search for people by name."""
    from api.services.person_entity import get_person_entity_store

    store = get_person_entity_store()
    results = []

    query_lower = query.lower()
    for person in store.get_all():
        if query_lower in person.canonical_name.lower():
            results.append({
                'id': person.id,
                'name': person.canonical_name,
                'company': person.company,
            })

    return sorted(results, key=lambda x: x['name'])


def get_person_by_id(person_id: str) -> dict | None:
    """Get a person by ID."""
    from api.services.person_entity import get_person_entity_store

    store = get_person_entity_store()
    person = store.get_by_id(person_id)
    if person:
        return {
            'id': person.id,
            'name': person.canonical_name,
            'company': person.company,
        }
    return None


def create_relationship(
    person_a_id: str,
    person_b_id: str,
    relationship_type: str = 'friend',
    context: str = 'manual',
    dry_run: bool = True
) -> bool:
    """Create a relationship between two people."""
    from api.services.relationship import (
        Relationship,
        get_relationship_store,
    )

    # Normalize order
    if person_a_id > person_b_id:
        person_a_id, person_b_id = person_b_id, person_a_id

    store = get_relationship_store()

    # Check if relationship exists
    existing = store.get_between(person_a_id, person_b_id)
    if existing:
        logger.info(f"Relationship already exists (type: {existing.relationship_type})")
        if context not in existing.shared_contexts:
            existing.shared_contexts.append(context)
            if not dry_run:
                store.update(existing)
            logger.info(f"Added context '{context}' to existing relationship")
        return True

    if dry_run:
        logger.info("Would create new relationship (dry run)")
        return True

    rel = Relationship(
        person_a_id=person_a_id,
        person_b_id=person_b_id,
        relationship_type=relationship_type,
        first_seen_together=datetime.now(timezone.utc),
        last_seen_together=datetime.now(timezone.utc),
        shared_contexts=[context],
    )
    store.add(rel)
    logger.info("Created new relationship")
    return True


def interactive_mode():
    """Interactive mode for creating relationships."""
    print("\n=== Create Relationship ===\n")

    # Get first person
    query1 = input("Search for first person: ").strip()
    if not query1:
        print("Cancelled")
        return

    results1 = search_people(query1)
    if not results1:
        print(f"No people found matching '{query1}'")
        return

    print("\nMatching people:")
    for i, p in enumerate(results1[:10], 1):
        company = f" ({p['company']})" if p['company'] else ""
        print(f"  {i}. {p['name']}{company}")

    try:
        choice1 = int(input("\nSelect first person (number): ")) - 1
        person1 = results1[choice1]
    except (ValueError, IndexError):
        print("Invalid selection")
        return

    # Get second person
    query2 = input("\nSearch for second person: ").strip()
    if not query2:
        print("Cancelled")
        return

    results2 = search_people(query2)
    if not results2:
        print(f"No people found matching '{query2}'")
        return

    print("\nMatching people:")
    for i, p in enumerate(results2[:10], 1):
        company = f" ({p['company']})" if p['company'] else ""
        print(f"  {i}. {p['name']}{company}")

    try:
        choice2 = int(input("\nSelect second person (number): ")) - 1
        person2 = results2[choice2]
    except (ValueError, IndexError):
        print("Invalid selection")
        return

    # Get relationship type
    print("\nRelationship types:")
    print("  1. friend (default)")
    print("  2. family")
    print("  3. coworker")
    print("  4. acquaintance")

    rel_choice = input("\nSelect relationship type (1-4, default 1): ").strip()
    rel_types = {'1': 'friend', '2': 'family', '3': 'coworker', '4': 'acquaintance'}
    rel_type = rel_types.get(rel_choice, 'friend')

    # Confirm
    print(f"\n=== Creating relationship ===")
    print(f"  {person1['name']} <-> {person2['name']}")
    print(f"  Type: {rel_type}")

    confirm = input("\nCreate this relationship? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Cancelled")
        return

    create_relationship(
        person1['id'],
        person2['id'],
        relationship_type=rel_type,
        context='manual',
        dry_run=False
    )
    print("Done!")


def batch_create(names: list[str], relationship_type: str, dry_run: bool):
    """Create relationships between all pairs in a list of names."""
    from api.services.person_entity import get_person_entity_store

    store = get_person_entity_store()

    # Find all people
    people = []
    for name in names:
        results = search_people(name)
        if not results:
            logger.warning(f"No person found matching '{name}'")
            continue
        if len(results) > 1:
            logger.warning(f"Multiple matches for '{name}', using first: {results[0]['name']}")
        people.append(results[0])

    if len(people) < 2:
        logger.error("Need at least 2 people to create relationships")
        return

    logger.info(f"\nCreating relationships between {len(people)} people:")
    for p in people:
        logger.info(f"  - {p['name']}")

    # Create all pairs
    created = 0
    for i in range(len(people)):
        for j in range(i + 1, len(people)):
            p1, p2 = people[i], people[j]
            logger.info(f"\n{p1['name']} <-> {p2['name']}")
            if create_relationship(
                p1['id'], p2['id'],
                relationship_type=relationship_type,
                context='manual',
                dry_run=dry_run
            ):
                created += 1

    logger.info(f"\n=== Summary ===")
    logger.info(f"Relationships processed: {created}")
    if dry_run:
        logger.info("DRY RUN - use --execute to actually create")


def main():
    parser = argparse.ArgumentParser(
        description='Manually create relationships between people'
    )
    parser.add_argument('--person1', type=str, help='First person name/ID')
    parser.add_argument('--person2', type=str, help='Second person name/ID')
    parser.add_argument('--type', type=str, default='friend',
                       choices=['friend', 'family', 'coworker', 'acquaintance'],
                       help='Relationship type (default: friend)')
    parser.add_argument('--batch', type=str, nargs='+',
                       help='Create relationships between all listed people')
    parser.add_argument('--execute', action='store_true',
                       help='Actually create relationships (default: dry run)')
    parser.add_argument('--interactive', '-i', action='store_true',
                       help='Interactive mode')
    args = parser.parse_args()

    if args.interactive:
        interactive_mode()
        return

    if args.batch:
        batch_create(args.batch, args.type, dry_run=not args.execute)
        return

    if args.person1 and args.person2:
        # Search for both people
        results1 = search_people(args.person1)
        results2 = search_people(args.person2)

        if not results1:
            logger.error(f"No person found matching '{args.person1}'")
            return
        if not results2:
            logger.error(f"No person found matching '{args.person2}'")
            return

        person1 = results1[0]
        person2 = results2[0]

        logger.info(f"Creating relationship:")
        logger.info(f"  {person1['name']} <-> {person2['name']}")
        logger.info(f"  Type: {args.type}")

        create_relationship(
            person1['id'],
            person2['id'],
            relationship_type=args.type,
            context='manual',
            dry_run=not args.execute
        )
        return

    # No arguments - show help
    parser.print_help()
    print("\nExamples:")
    print("  # Interactive mode")
    print("  uv run python scripts/create_relationship.py -i")
    print("")
    print("  # Create single relationship")
    print("  uv run python scripts/create_relationship.py --person1 'Taylor Walker' --person2 'Alix Haber' --execute")
    print("")
    print("  # Create relationships between a group")
    print("  uv run python scripts/create_relationship.py --batch 'Taylor Walker' 'Alix Haber' 'Heather Williams' 'Emily Durfee' --execute")


if __name__ == '__main__':
    main()

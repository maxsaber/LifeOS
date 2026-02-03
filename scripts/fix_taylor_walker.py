#!/usr/bin/env python3
"""
Fix Taylor Walker's entity by removing Mary Katherine Palmer's LinkedIn data.

This was incorrectly merged due to the old token_set_ratio algorithm
being too permissive (56% character similarity).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.services.person_entity import PersonEntityStore

def main():
    store = PersonEntityStore()

    # Find Taylor Walker
    taylor = store.get_by_name("Taylor Walker")

    if not taylor:
        print("ERROR: Could not find Taylor Walker in entity store")
        return 1

    print(f"Found Taylor Walker (ID: {taylor.id})")
    print(f"  canonical_name: {taylor.canonical_name}")
    print(f"  linkedin_url: {taylor.linkedin_url}")
    print(f"  company: {taylor.company}")
    print(f"  position: {taylor.position}")
    print()

    # Check if there's bad data to fix
    if taylor.linkedin_url and "mary-katherine-palmer" in taylor.linkedin_url.lower():
        print("Found incorrect LinkedIn URL (Mary Katherine Palmer's)")
        taylor.linkedin_url = None
        taylor.company = None  # Also clear company since it came from same source
        taylor.position = None  # Also clear position

        # Update the entity
        store.update(taylor)
        store.save()

        print("\nFixed! Cleared linkedin_url, company, and position fields.")

        # Verify the fix
        taylor_after = store.get_by_name("Taylor Walker")
        print(f"\nAfter fix:")
        print(f"  linkedin_url: {taylor_after.linkedin_url}")
        print(f"  company: {taylor_after.company}")
        print(f"  position: {taylor_after.position}")
    elif taylor.linkedin_url:
        print(f"LinkedIn URL doesn't contain 'mary-katherine-palmer': {taylor.linkedin_url}")
        print("No changes made.")
    else:
        print("No LinkedIn URL set. Nothing to fix.")

    return 0

if __name__ == "__main__":
    sys.exit(main())

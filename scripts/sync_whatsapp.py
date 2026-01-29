#!/usr/bin/env python3
"""
Sync WhatsApp data to LifeOS CRM via wacli.

Requires wacli to be installed and authenticated:
  brew install steipete/tap/wacli
  wacli auth

Syncs:
1. WhatsApp contacts as SourceEntities (with phone numbers and names)
2. Group memberships (for relationship discovery)
"""
import subprocess
import json
import uuid
import sqlite3
import logging
import argparse
import re
from datetime import datetime, timezone
from pathlib import Path

from api.services.entity_resolver import get_entity_resolver
from api.services.interaction_store import get_interaction_db_path
from api.services.source_entity import (
    get_source_entity_store,
    SourceEntity,
    LINK_STATUS_AUTO,
)
from api.services.person_entity import get_person_entity_store

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def normalize_phone(phone: str) -> str:
    """Normalize phone number to E.164 format."""
    if not phone:
        return ""
    # Remove all non-digit characters
    digits = re.sub(r'\D', '', phone)

    # Handle US numbers
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits.startswith('1'):
        return f"+{digits}"
    elif len(digits) > 10:
        return f"+{digits}"
    return ""


def run_wacli(args: list, timeout: int = 300) -> dict | list | None:
    """
    Run wacli command and return JSON output.

    Args:
        args: Command arguments (without 'wacli' prefix)
        timeout: Timeout in seconds

    Returns:
        Parsed JSON output or None on error
    """
    cmd = ["wacli", "--json"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            if "no store found" in result.stderr.lower() or "not authenticated" in result.stderr.lower():
                logger.error("wacli not authenticated. Run 'wacli auth' first.")
                return None
            logger.error(f"wacli error: {result.stderr}")
            return None

        if not result.stdout.strip():
            return []

        parsed = json.loads(result.stdout)
        # wacli wraps responses in {"success": true, "data": [...], "error": null}
        if isinstance(parsed, dict) and "data" in parsed:
            return parsed["data"] if parsed["data"] is not None else []
        return parsed
    except subprocess.TimeoutExpired:
        logger.error(f"wacli command timed out: {' '.join(cmd)}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse wacli output: {e}")
        return None
    except FileNotFoundError:
        logger.error("wacli not found. Install with: brew install steipete/tap/wacli")
        return None


def check_wacli_auth() -> bool:
    """Check if wacli is authenticated."""
    result = run_wacli(["chats", "list", "--limit", "1"])
    return result is not None


def sync_whatsapp(dry_run: bool = True) -> dict:
    """
    Sync WhatsApp contacts to CRM.

    Args:
        dry_run: If True, don't actually insert

    Returns:
        Stats dict
    """
    stats = {
        'contacts_read': 0,
        'source_entities_created': 0,
        'source_entities_updated': 0,
        'persons_linked': 0,
        'persons_created': 0,
        'persons_updated': 0,
        'skipped': 0,
        'errors': 0,
    }

    # Check authentication
    if not check_wacli_auth():
        stats['error'] = "wacli not authenticated"
        return stats

    source_store = get_source_entity_store()
    person_store = get_person_entity_store()
    resolver = get_entity_resolver()

    # Get all WhatsApp contacts
    logger.info("Fetching WhatsApp contacts...")

    # Search with "." pattern and high limit to get all contacts
    contacts = run_wacli(["contacts", "search", ".", "--limit", "10000"])
    if contacts is None:
        stats['error'] = "Failed to fetch contacts"
        return stats

    stats['contacts_read'] = len(contacts)
    logger.info(f"Found {len(contacts)} contacts")

    for contact in contacts:
        try:
            jid = contact.get("JID", "")
            phone_raw = contact.get("Phone", "")
            name = contact.get("Name", "").strip()
            alias = contact.get("Alias", "").strip()

            # Skip contacts without valid phone
            phone = normalize_phone(phone_raw)
            if not phone:
                stats['skipped'] += 1
                continue

            # Skip contacts without meaningful name
            display_name = name or alias
            if not display_name or display_name == phone_raw:
                stats['skipped'] += 1
                continue

            # Create unique source_id
            source_id = f"whatsapp_{jid}"

            # Check for existing source entity
            existing_source = source_store.get_by_source('whatsapp', source_id)

            source_entity = SourceEntity(
                source_type='whatsapp',
                source_id=source_id,
                observed_name=display_name,
                observed_phone=phone,
                metadata={
                    'jid': jid,
                    'alias': alias,
                    'raw_phone': phone_raw,
                },
                observed_at=datetime.now(timezone.utc),
            )

            if existing_source:
                if not dry_run:
                    existing_source.observed_name = source_entity.observed_name
                    existing_source.observed_phone = source_entity.observed_phone
                    existing_source.metadata = source_entity.metadata
                    existing_source.observed_at = datetime.now(timezone.utc)
                    source_store.update(existing_source)
                stats['source_entities_updated'] += 1
                source_entity = existing_source
            else:
                if not dry_run:
                    source_entity = source_store.add(source_entity)
                stats['source_entities_created'] += 1

            # Resolve to PersonEntity
            result = resolver.resolve(
                name=display_name,
                phone=phone,
                create_if_missing=True,
            )

            if result and result.entity:
                person = result.entity
                person_updated = False

                # Link source entity to person
                if not existing_source or existing_source.canonical_person_id != person.id:
                    if not dry_run:
                        source_store.link_to_person(
                            source_entity.id,
                            person.id,
                            confidence=0.95,  # High confidence for phone match
                            status=LINK_STATUS_AUTO,
                        )
                    stats['persons_linked'] += 1

                # Add phone to person if not present
                if phone and phone not in person.phone_numbers:
                    person.phone_numbers.append(phone)
                    if not person.phone_primary:
                        person.phone_primary = phone
                    person_updated = True

                # Add source
                if 'whatsapp' not in person.sources:
                    person.sources.append('whatsapp')
                    person_updated = True

                # Update source_entity_count
                if not dry_run:
                    new_count = source_store.count_for_person(person.id)
                    if person.source_entity_count != new_count:
                        person.source_entity_count = new_count
                        person_updated = True

                if person_updated:
                    if not dry_run:
                        person_store.update(person)
                    stats['persons_updated'] += 1

                if result.is_new:
                    stats['persons_created'] += 1

        except Exception as e:
            logger.error(f"Error processing contact: {e}")
            stats['errors'] += 1

    # Save person store
    if not dry_run:
        person_store.save()

    # Log summary
    logger.info(f"\n=== WhatsApp Sync Summary ===")
    logger.info(f"Contacts read: {stats['contacts_read']}")
    logger.info(f"Source entities created: {stats['source_entities_created']}")
    logger.info(f"Source entities updated: {stats['source_entities_updated']}")
    logger.info(f"Persons linked: {stats['persons_linked']}")
    logger.info(f"Persons created: {stats['persons_created']}")
    logger.info(f"Persons updated: {stats['persons_updated']}")
    logger.info(f"Skipped: {stats['skipped']}")
    logger.info(f"Errors: {stats['errors']}")

    if dry_run:
        logger.info("\nDRY RUN - no changes made")

    return stats


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Sync WhatsApp contacts to CRM via wacli')
    parser.add_argument('--execute', action='store_true', help='Actually apply changes')
    args = parser.parse_args()

    sync_whatsapp(dry_run=not args.execute)

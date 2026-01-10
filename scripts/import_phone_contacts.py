#!/usr/bin/env python3
"""
Import phone contacts from CSV to enhance PersonEntity records.

Reads a CSV export of phone contacts (from iPhone/Google Contacts) and:
1. Normalizes all phone numbers to E.164 format
2. Resolves contacts to existing PersonEntity records by email or name
3. Adds phone numbers to matched entities
4. Creates new entities for unmatched contacts
5. Generates an import report

Usage:
    python scripts/import_phone_contacts.py [--dry-run] [--verbose] [--csv-path PATH]

Options:
    --dry-run     Preview import without saving changes
    --verbose     Show detailed progress for each contact
    --csv-path    Path to contacts CSV (default: ./data/phonecontacts20260109.csv)
"""
import argparse
import csv
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.services.person_entity import PersonEntity, get_person_entity_store
from api.services.entity_resolver import get_entity_resolver, EntityResolver
from api.services.phone_utils import normalize_phone, is_valid_phone

# Optional: progress bar support
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# CSV field mappings
CSV_FIELDS = {
    "first_name": "First Name",
    "last_name": "Last Name",
    "display_name": "Display Name",
    "nickname": "Nickname",
    "email1": "E-mail Address",
    "email2": "E-mail Address 2",
    "email3": "E-mail Address 3",
    "home_phone": "Home Phone",
    "business_phone": "Business Phone",
    "home_fax": "Home Fax",
    "business_fax": "Business Fax",
    "pager": "Pager",
    "mobile_phone": "Mobile Phone",
    "organization": "Organization",
    "notes": "Notes",
}


@dataclass
class ContactRecord:
    """Parsed contact from CSV."""
    display_name: str
    first_name: str
    last_name: str
    nickname: str
    emails: list[str]
    phones: list[str]  # E.164 normalized
    phone_primary: Optional[str]  # Mobile preferred
    organization: Optional[str]
    notes: Optional[str]

    @classmethod
    def from_csv_row(cls, row: dict) -> Optional["ContactRecord"]:
        """Parse a CSV row into a ContactRecord."""
        # Get name components
        first_name = row.get(CSV_FIELDS["first_name"], "").strip()
        last_name = row.get(CSV_FIELDS["last_name"], "").strip()
        display_name = row.get(CSV_FIELDS["display_name"], "").strip()
        nickname = row.get(CSV_FIELDS["nickname"], "").strip()

        # Derive display name if not present
        if not display_name:
            display_name = f"{first_name} {last_name}".strip()

        # Skip if no name at all
        if not display_name:
            return None

        # Collect emails (non-empty)
        emails = []
        for email_field in ["email1", "email2", "email3"]:
            email = row.get(CSV_FIELDS[email_field], "").strip().lower()
            if email and "@" in email:
                emails.append(email)

        # Collect and normalize phones
        # Priority: mobile > business > home
        phones = []
        phone_primary = None
        phone_fields = [
            ("mobile_phone", True),   # Primary candidate
            ("business_phone", True),  # Secondary primary candidate
            ("home_phone", False),
            ("home_fax", False),
            ("business_fax", False),
            ("pager", False),
        ]

        for field_key, is_primary_candidate in phone_fields:
            raw_phone = row.get(CSV_FIELDS[field_key], "").strip()
            if raw_phone:
                normalized = normalize_phone(raw_phone)
                if normalized and normalized not in phones:
                    phones.append(normalized)
                    if is_primary_candidate and not phone_primary:
                        phone_primary = normalized

        # Organization and notes
        organization = row.get(CSV_FIELDS["organization"], "").strip() or None
        notes = row.get(CSV_FIELDS["notes"], "").strip() or None

        return cls(
            display_name=display_name,
            first_name=first_name,
            last_name=last_name,
            nickname=nickname,
            emails=emails,
            phones=phones,
            phone_primary=phone_primary,
            organization=organization,
            notes=notes,
        )


@dataclass
class ImportReport:
    """Report of the import operation."""
    total_contacts: int = 0
    skipped_no_phone: int = 0
    matched_by_email: int = 0
    matched_by_name: int = 0
    new_entities_created: int = 0
    phones_added: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dict for JSON."""
        return {
            "summary": {
                "total_contacts": self.total_contacts,
                "skipped_no_phone": self.skipped_no_phone,
                "matched_by_email": self.matched_by_email,
                "matched_by_name": self.matched_by_name,
                "new_entities_created": self.new_entities_created,
                "phones_added": self.phones_added,
                "errors_count": len(self.errors),
            },
            "errors": self.errors,
        }


def load_contacts(csv_path: Path) -> list[ContactRecord]:
    """
    Load contacts from CSV file.

    Args:
        csv_path: Path to the CSV file

    Returns:
        List of ContactRecord objects
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    contacts = []

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            contact = ContactRecord.from_csv_row(row)
            if contact:
                contacts.append(contact)

    return contacts


def import_contacts(
    contacts: list[ContactRecord],
    resolver: EntityResolver,
    verbose: bool = False,
    dry_run: bool = False,
) -> ImportReport:
    """
    Import contacts into the people entity system.

    Args:
        contacts: List of ContactRecord objects
        resolver: EntityResolver for matching
        verbose: Whether to log each contact
        dry_run: Whether to skip saving

    Returns:
        ImportReport with statistics
    """
    report = ImportReport(total_contacts=len(contacts))
    store = resolver.store

    # Create iterator with optional progress bar
    if HAS_TQDM and not verbose:
        iterator = tqdm(contacts, desc="Importing contacts", unit="contact")
    else:
        iterator = contacts
        if not HAS_TQDM:
            print(f"Processing {len(contacts)} contacts...")

    for contact in iterator:
        try:
            # Skip contacts without any phone numbers
            if not contact.phones:
                report.skipped_no_phone += 1
                if verbose:
                    logger.info(f"Skipped (no phone): {contact.display_name}")
                continue

            # Try to match by email first
            matched_entity: Optional[PersonEntity] = None
            match_type = ""

            for email in contact.emails:
                entity = resolver.resolve_by_email(email)
                if entity:
                    matched_entity = entity
                    match_type = "email"
                    report.matched_by_email += 1
                    break

            # Try name matching if no email match
            if not matched_entity:
                result = resolver.resolve_by_name(
                    contact.display_name,
                    create_if_missing=False
                )
                if result:
                    matched_entity = result.entity
                    match_type = "name"
                    report.matched_by_name += 1

            # Handle matched or create new
            if matched_entity:
                # Add phones to existing entity
                phones_added_count = 0
                for phone in contact.phones:
                    if matched_entity.add_phone(phone):
                        phones_added_count += 1

                # Set primary if not already set
                if not matched_entity.phone_primary and contact.phone_primary:
                    matched_entity.phone_primary = contact.phone_primary

                # Add organization if missing
                if not matched_entity.company and contact.organization:
                    matched_entity.company = contact.organization

                # Add to sources
                if "phone_contacts" not in matched_entity.sources:
                    matched_entity.sources.append("phone_contacts")

                if phones_added_count > 0:
                    report.phones_added += phones_added_count
                    if not dry_run:
                        store.update(matched_entity)

                if verbose:
                    logger.info(
                        f"Matched ({match_type}): {contact.display_name} -> "
                        f"{matched_entity.canonical_name} (+{phones_added_count} phones)"
                    )

            else:
                # Create new entity
                report.new_entities_created += 1
                report.phones_added += len(contact.phones)

                new_entity = PersonEntity(
                    canonical_name=contact.display_name,
                    display_name=contact.display_name,
                    emails=contact.emails,
                    phone_numbers=contact.phones,
                    phone_primary=contact.phone_primary,
                    company=contact.organization,
                    aliases=[contact.nickname] if contact.nickname else [],
                    category="personal",  # Phone contacts are typically personal
                    sources=["phone_contacts"],
                    first_seen=datetime.now(timezone.utc),
                    last_seen=datetime.now(timezone.utc),
                )

                if not dry_run:
                    store.add(new_entity)

                if verbose:
                    logger.info(f"Created new: {contact.display_name} ({len(contact.phones)} phones)")

        except Exception as e:
            error_msg = f"Error processing '{contact.display_name}': {str(e)}"
            report.errors.append(error_msg)
            logger.error(error_msg)

    # Save store if not dry run
    if not dry_run:
        store.save()

    return report


def print_report(report: ImportReport, dry_run: bool = False) -> None:
    """Print formatted import report to console."""
    mode = "[DRY RUN] " if dry_run else ""

    print(f"\n{'=' * 60}")
    print(f"{mode}PHONE CONTACTS IMPORT REPORT")
    print('=' * 60)

    print(f"\nSummary:")
    print(f"  Total contacts processed:   {report.total_contacts}")
    print(f"  Skipped (no phone):         {report.skipped_no_phone}")
    print(f"  Matched by email:           {report.matched_by_email}")
    print(f"  Matched by name:            {report.matched_by_name}")
    print(f"  New entities created:       {report.new_entities_created}")
    print(f"  Phone numbers added:        {report.phones_added}")
    print(f"  Errors:                     {len(report.errors)}")

    if report.errors:
        print(f"\nErrors:")
        for error in report.errors[:5]:
            print(f"  - {error}")
        if len(report.errors) > 5:
            print(f"  ... and {len(report.errors) - 5} more errors")

    print('=' * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Import phone contacts into people entities"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview import without saving changes"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed progress for each contact"
    )
    parser.add_argument(
        "--csv-path",
        type=str,
        default="./data/phonecontacts20260109.csv",
        help="Path to contacts CSV file"
    )

    args = parser.parse_args()

    csv_path = Path(args.csv_path)

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    print("\nPhone Contacts Import")
    print("=" * 60)

    if args.dry_run:
        print("[DRY RUN MODE - No changes will be saved]")

    # Load contacts
    print(f"\nLoading contacts from: {csv_path}")
    try:
        contacts = load_contacts(csv_path)
        print(f"Loaded {len(contacts)} contacts")
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR loading contacts: {e}")
        sys.exit(1)

    # Show some stats
    contacts_with_phone = sum(1 for c in contacts if c.phones)
    contacts_with_email = sum(1 for c in contacts if c.emails)
    print(f"  - With phone numbers: {contacts_with_phone}")
    print(f"  - With email addresses: {contacts_with_email}")

    # Get resolver
    print("\nInitializing entity resolver...")
    resolver = get_entity_resolver()
    store = resolver.store
    print(f"Existing entities: {store.count()}")

    # Import contacts
    print("\nImporting contacts...")
    report = import_contacts(
        contacts,
        resolver,
        verbose=args.verbose,
        dry_run=args.dry_run
    )

    # Print report
    print_report(report, dry_run=args.dry_run)

    if not args.dry_run:
        print(f"\nEntity store now has {store.count()} entities")
        stats = store.get_statistics()
        print(f"  - Phones indexed: {stats['total_phones_indexed']}")
        print("\nImport complete!")
    else:
        print("\n[DRY RUN] No changes saved. Run without --dry-run to apply.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Migrate People v1 (PersonRecord) to v2 (PersonEntity).

Migrates data from the v1 people system to v2:
- Loads data from data/people_aggregated.json (~1,900 records)
- Converts using PersonEntity.from_person_record()
- Detects duplicates using EntityResolver fuzzy matching
- Infers vault_contexts from related_notes paths
- Generates detailed migration report

Usage:
    python scripts/migrate_people_v1_to_v2.py [--dry-run] [--verbose]

Options:
    --dry-run     Preview migration without saving changes
    --verbose     Show detailed progress for each record
"""
import argparse
import json
import logging
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.services.people_aggregator import PersonRecord
from api.services.person_entity import PersonEntity, PersonEntityStore
from config.people_config import COMPANY_NORMALIZATION

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


# Vault context patterns for inference from related_notes paths
VAULT_CONTEXT_PATTERNS: list[tuple[str, str]] = [
    # Work contexts
    ("Work/ML/", "Work/ML/"),
    ("Work/", "Work/"),

    # Personal archived contexts
    ("Personal/zArchive/Murm/", "Personal/zArchive/Murm/"),
    ("Personal/zArchive/BlueLabs/", "Personal/zArchive/BlueLabs/"),
    ("Personal/zArchive/Deck/", "Personal/zArchive/Deck/"),
    ("Personal/zArchive/Rise/", "Personal/zArchive/Rise/"),

    # General personal contexts
    ("Personal/Relationship/", "Personal/Relationship/"),
    ("Personal/Malea/", "Personal/Malea/"),
    ("Personal/", "Personal/"),
]


@dataclass
class MergeRecord:
    """Records details of a merge operation."""
    original_name: str
    merged_with_name: str
    match_score: float
    match_type: str


@dataclass
class MigrationReport:
    """Comprehensive migration report."""
    total_records: int = 0
    new_entities_created: int = 0
    merges_performed: int = 0
    skipped_records: int = 0
    errors: list[str] = field(default_factory=list)
    merges: list[MergeRecord] = field(default_factory=list)
    entities_by_category: dict[str, int] = field(default_factory=dict)
    entities_by_source: dict[str, int] = field(default_factory=dict)
    vault_contexts_inferred: int = 0

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            "summary": {
                "total_records": self.total_records,
                "new_entities_created": self.new_entities_created,
                "merges_performed": self.merges_performed,
                "skipped_records": self.skipped_records,
                "errors_count": len(self.errors),
                "vault_contexts_inferred": self.vault_contexts_inferred,
            },
            "entities_by_category": self.entities_by_category,
            "entities_by_source": self.entities_by_source,
            "merges": [
                {
                    "original_name": m.original_name,
                    "merged_with_name": m.merged_with_name,
                    "match_score": m.match_score,
                    "match_type": m.match_type,
                }
                for m in self.merges
            ],
            "errors": self.errors,
        }


def infer_vault_contexts(related_notes: list[str]) -> list[str]:
    """
    Infer vault contexts from related_notes paths.

    Args:
        related_notes: List of file paths from the v1 record

    Returns:
        Deduplicated list of vault context paths
    """
    contexts = set()

    for note_path in related_notes:
        # Normalize path separators
        path_str = str(note_path).replace("\\", "/")

        # Check each pattern
        for pattern, context in VAULT_CONTEXT_PATTERNS:
            if pattern in path_str:
                contexts.add(context)
                break  # Use most specific match

    return sorted(list(contexts))


def infer_vault_contexts_from_company(company: Optional[str]) -> list[str]:
    """
    Infer vault contexts from company name using COMPANY_NORMALIZATION.

    Args:
        company: Company name from the v1 record

    Returns:
        List of vault context paths
    """
    if not company:
        return []

    company_info = COMPANY_NORMALIZATION.get(company, {})
    return company_info.get("vault_contexts", [])


class MigrationResolver:
    """
    Simplified resolver for migration that uses in-memory matching.

    Does not use the full EntityResolver to avoid side effects during migration.
    Instead, builds an in-memory index for duplicate detection.
    """

    def __init__(self):
        """Initialize the migration resolver."""
        self._entities: dict[str, PersonEntity] = {}  # id -> entity
        self._email_index: dict[str, str] = {}  # email.lower() -> entity id
        self._name_index: dict[str, str] = {}  # name.lower() -> entity id

        # Optional: import rapidfuzz for fuzzy matching
        try:
            from rapidfuzz import fuzz
            self._fuzz = fuzz
        except ImportError:
            self._fuzz = None
            logger.warning("rapidfuzz not installed - fuzzy matching disabled")

    def add_entity(self, entity: PersonEntity) -> None:
        """Add entity to indices."""
        self._entities[entity.id] = entity

        # Index emails
        for email in entity.emails:
            self._email_index[email.lower()] = entity.id

        # Index names
        if entity.canonical_name:
            self._name_index[entity.canonical_name.lower()] = entity.id
        for alias in entity.aliases:
            if alias:
                self._name_index[alias.lower()] = entity.id

    def find_by_email(self, email: str) -> Optional[PersonEntity]:
        """Find entity by exact email match."""
        if not email:
            return None
        entity_id = self._email_index.get(email.lower())
        return self._entities.get(entity_id) if entity_id else None

    def find_by_name_exact(self, name: str) -> Optional[PersonEntity]:
        """Find entity by exact name match."""
        if not name:
            return None
        entity_id = self._name_index.get(name.lower())
        return self._entities.get(entity_id) if entity_id else None

    def find_by_name_fuzzy(
        self,
        name: str,
        threshold: float = 92.0
    ) -> Optional[tuple[PersonEntity, float]]:
        """
        Find entity by fuzzy name match.

        Uses stricter matching to avoid false positives:
        - High threshold (92%) for overall similarity
        - Also checks first name similarity to avoid "Peter Williams" <-> "Heather Williams"

        Args:
            name: Name to search for
            threshold: Minimum similarity score (0-100)

        Returns:
            Tuple of (entity, score) if found above threshold, else None
        """
        if not name or not self._fuzz:
            return None

        name_lower = name.lower()
        name_parts = name_lower.split()
        best_match: Optional[tuple[PersonEntity, float]] = None

        for entity in self._entities.values():
            entity_name_lower = entity.canonical_name.lower()
            entity_parts = entity_name_lower.split()

            # Check overall similarity
            score = self._fuzz.token_set_ratio(name_lower, entity_name_lower)
            if score >= threshold:
                # Additional check: first names should also be similar
                # This prevents "Peter Williams" matching "Heather Williams"
                if name_parts and entity_parts:
                    first_name_score = self._fuzz.ratio(name_parts[0], entity_parts[0])
                    if first_name_score < 80:
                        # First names too different, skip this match
                        continue

                if best_match is None or score > best_match[1]:
                    best_match = (entity, score)

            # Check aliases
            for alias in entity.aliases:
                alias_lower = alias.lower()
                alias_score = self._fuzz.token_set_ratio(name_lower, alias_lower)
                if alias_score >= threshold:
                    # First name check for aliases too
                    alias_parts = alias_lower.split()
                    if name_parts and alias_parts:
                        first_name_score = self._fuzz.ratio(name_parts[0], alias_parts[0])
                        if first_name_score < 80:
                            continue

                    if best_match is None or alias_score > best_match[1]:
                        best_match = (entity, alias_score)

        return best_match

    def get_all(self) -> list[PersonEntity]:
        """Get all entities."""
        return list(self._entities.values())

    def count(self) -> int:
        """Get entity count."""
        return len(self._entities)


def load_v1_data(v1_path: Path) -> list[PersonRecord]:
    """
    Load v1 data from people_aggregated.json.

    Args:
        v1_path: Path to the v1 data file

    Returns:
        List of PersonRecord objects
    """
    if not v1_path.exists():
        raise FileNotFoundError(f"V1 data file not found: {v1_path}")

    with open(v1_path, "r") as f:
        data = json.load(f)

    records = []
    for item in data:
        try:
            record = PersonRecord.from_dict(item)
            records.append(record)
        except Exception as e:
            logger.error(f"Failed to parse record: {e}")

    return records


def backup_file(file_path: Path, backup_dir: Optional[Path] = None) -> Path:
    """
    Create a timestamped backup of a file.

    Args:
        file_path: Path to file to backup
        backup_dir: Directory for backup (default: same as file)

    Returns:
        Path to backup file
    """
    if not file_path.exists():
        return file_path

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = backup_dir or file_path.parent
    backup_dir.mkdir(parents=True, exist_ok=True)

    backup_path = backup_dir / f"{file_path.stem}_backup_{timestamp}{file_path.suffix}"
    shutil.copy2(file_path, backup_path)

    return backup_path


def migrate_records(
    records: list[PersonRecord],
    resolver: MigrationResolver,
    verbose: bool = False,
    fuzzy_threshold: float = 92.0,
) -> tuple[list[PersonEntity], MigrationReport]:
    """
    Migrate v1 records to v2 entities with duplicate detection.

    Args:
        records: List of v1 PersonRecord objects
        resolver: MigrationResolver for duplicate detection
        verbose: Whether to log each record
        fuzzy_threshold: Minimum similarity score for fuzzy matching (0-100)

    Returns:
        Tuple of (list of new entities, migration report)
    """
    report = MigrationReport(total_records=len(records))

    # Create iterator with optional progress bar
    if HAS_TQDM:
        iterator = tqdm(records, desc="Migrating records", unit="record")
    else:
        iterator = records
        print(f"Processing {len(records)} records...")

    for record in iterator:
        try:
            # Convert to v2 entity
            entity = PersonEntity.from_person_record(record)

            # Infer vault contexts from related notes
            related_notes_contexts = infer_vault_contexts(record.related_notes)
            company_contexts = infer_vault_contexts_from_company(record.company)

            # Combine contexts (deduplicated)
            all_contexts = set(related_notes_contexts + company_contexts)
            if all_contexts:
                entity.vault_contexts = sorted(list(all_contexts))
                report.vault_contexts_inferred += 1

            # Check for duplicates
            existing_entity: Optional[PersonEntity] = None
            match_type = ""
            match_score = 0.0

            # 1. Check email match (exact)
            if entity.primary_email:
                existing_entity = resolver.find_by_email(entity.primary_email)
                if existing_entity:
                    match_type = "email_exact"
                    match_score = 100.0

            # 2. Check exact name match
            if not existing_entity:
                existing_entity = resolver.find_by_name_exact(entity.canonical_name)
                if existing_entity:
                    match_type = "name_exact"
                    match_score = 100.0

            # 3. Check fuzzy name match
            if not existing_entity:
                fuzzy_result = resolver.find_by_name_fuzzy(
                    entity.canonical_name,
                    threshold=fuzzy_threshold
                )
                if fuzzy_result:
                    existing_entity, match_score = fuzzy_result
                    match_type = "name_fuzzy"

            # Handle duplicate or add new
            if existing_entity and match_score >= fuzzy_threshold:
                # Merge into existing entity
                merged_entity = existing_entity.merge(entity)

                # Update in resolver
                resolver._entities[merged_entity.id] = merged_entity

                report.merges_performed += 1
                report.merges.append(MergeRecord(
                    original_name=record.canonical_name,
                    merged_with_name=existing_entity.canonical_name,
                    match_score=match_score,
                    match_type=match_type,
                ))

                if verbose:
                    logger.info(
                        f"Merged '{record.canonical_name}' with "
                        f"'{existing_entity.canonical_name}' ({match_type}: {match_score:.1f})"
                    )
            else:
                # Add as new entity
                resolver.add_entity(entity)
                report.new_entities_created += 1

                if verbose:
                    logger.info(f"Created new entity: {record.canonical_name}")

            # Track category
            category = entity.category or "unknown"
            report.entities_by_category[category] = (
                report.entities_by_category.get(category, 0) + 1
            )

            # Track sources
            for source in record.sources:
                report.entities_by_source[source] = (
                    report.entities_by_source.get(source, 0) + 1
                )

        except Exception as e:
            error_msg = f"Error processing '{record.canonical_name}': {str(e)}"
            report.errors.append(error_msg)
            logger.error(error_msg)

    # Return deduplicated entities
    return resolver.get_all(), report


def save_entities(entities: list[PersonEntity], output_path: Path) -> None:
    """
    Save entities to v2 storage format.

    Args:
        entities: List of PersonEntity objects
        output_path: Path to output file
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = [entity.to_dict() for entity in entities]

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)


def print_report(report: MigrationReport, dry_run: bool = False) -> None:
    """Print formatted migration report to console."""
    mode = "[DRY RUN] " if dry_run else ""

    print(f"\n{'=' * 60}")
    print(f"{mode}MIGRATION REPORT")
    print('=' * 60)

    print(f"\n{'Summary':}")
    print(f"  Total v1 records processed: {report.total_records}")
    print(f"  New v2 entities created:    {report.new_entities_created}")
    print(f"  Merges performed:           {report.merges_performed}")
    print(f"  Vault contexts inferred:    {report.vault_contexts_inferred}")
    print(f"  Errors:                     {len(report.errors)}")

    print(f"\n{'Entities by Category:'}")
    for category, count in sorted(report.entities_by_category.items()):
        print(f"  {category}: {count}")

    print(f"\n{'Records by Source:'}")
    for source, count in sorted(report.entities_by_source.items()):
        print(f"  {source}: {count}")

    if report.merges:
        print(f"\n{'Merges Performed:'}")
        # Show first 10 merges
        for merge in report.merges[:10]:
            print(f"  '{merge.original_name}' -> '{merge.merged_with_name}'")
            print(f"    ({merge.match_type}: {merge.match_score:.1f})")
        if len(report.merges) > 10:
            print(f"  ... and {len(report.merges) - 10} more merges")

    if report.errors:
        print(f"\n{'Errors:'}")
        for error in report.errors[:5]:
            print(f"  - {error}")
        if len(report.errors) > 5:
            print(f"  ... and {len(report.errors) - 5} more errors")

    print('=' * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Migrate People v1 to v2"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview migration without saving changes"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed progress for each record"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=92.0,
        help="Fuzzy match threshold for duplicate detection (default: 92.0)"
    )
    parser.add_argument(
        "--v1-path",
        type=str,
        default="./data/people_aggregated.json",
        help="Path to v1 data file (default: ./data/people_aggregated.json)"
    )
    parser.add_argument(
        "--v2-path",
        type=str,
        default="./data/people_entities.json",
        help="Path to v2 output file (default: ./data/people_entities.json)"
    )
    parser.add_argument(
        "--report-path",
        type=str,
        default="./data/migration_report.json",
        help="Path to save migration report (default: ./data/migration_report.json)"
    )

    args = parser.parse_args()

    v1_path = Path(args.v1_path)
    v2_path = Path(args.v2_path)
    report_path = Path(args.report_path)

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    print("\nPeople v1 -> v2 Migration")
    print("=" * 60)

    if args.dry_run:
        print("[DRY RUN MODE - No changes will be saved]")

    # Load v1 data
    print(f"\nLoading v1 data from: {v1_path}")
    try:
        records = load_v1_data(v1_path)
        print(f"Loaded {len(records)} records")
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR loading v1 data: {e}")
        sys.exit(1)

    # Create backup of v1 data (even in dry-run, for safety)
    if not args.dry_run:
        print(f"\nBacking up v1 data...")
        backup_path = backup_file(v1_path)
        if backup_path != v1_path:
            print(f"Backup created: {backup_path}")

    # Initialize resolver
    resolver = MigrationResolver()

    # Migrate records
    print(f"\nMigrating records...")
    entities, report = migrate_records(
        records,
        resolver,
        verbose=args.verbose,
        fuzzy_threshold=args.threshold
    )

    # Print report
    print_report(report, dry_run=args.dry_run)

    # Save results
    if not args.dry_run:
        print(f"\nSaving {len(entities)} entities to: {v2_path}")
        save_entities(entities, v2_path)

        print(f"Saving migration report to: {report_path}")
        with open(report_path, "w") as f:
            json.dump(report.to_dict(), f, indent=2)

        print("\nMigration complete!")
    else:
        print("\n[DRY RUN] No changes saved. Run without --dry-run to apply.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
PersonEntity - Enhanced person model for LifeOS People System v2.

Key changes from PersonRecord:
- Email is primary identifier (emails is a list, not single optional string)
- Supports multiple emails per person
- Includes vault_contexts for context-aware resolution
- Includes confidence_score for merge quality tracking
- Includes display_name for disambiguation (e.g., "Sarah (Movement)")
"""
import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from api.services.people_aggregator import PersonRecord

logger = logging.getLogger(__name__)


def _make_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime is timezone-aware (UTC if naive)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class PersonEntity:
    """
    Enhanced person record with email-anchored identity.

    Primary identifier: emails list (email is most reliable cross-source anchor)
    Secondary: canonical_name + aliases for fuzzy matching
    """

    # Identity
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    canonical_name: str = ""
    display_name: str = ""  # For disambiguation: "Sarah Chen (Movement)"

    # Email anchors (PRIMARY identifier)
    emails: list[str] = field(default_factory=list)

    # Professional info
    company: Optional[str] = None
    position: Optional[str] = None
    linkedin_url: Optional[str] = None

    # Context
    category: str = "unknown"  # work, personal, family
    vault_contexts: list[str] = field(default_factory=list)  # ["Work/ML/", "Personal/"]

    # Source tracking
    sources: list[str] = field(default_factory=list)  # linkedin, gmail, calendar, vault, granola

    # Timestamps
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None

    # Aggregated stats
    meeting_count: int = 0
    email_count: int = 0
    mention_count: int = 0
    message_count: int = 0  # iMessage/SMS count

    # Related content
    related_notes: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)

    # Phone numbers (E.164 format: +1XXXXXXXXXX)
    phone_numbers: list[str] = field(default_factory=list)
    phone_primary: Optional[str] = None  # Preferred phone (mobile > business > home)

    # Resolution metadata
    confidence_score: float = 1.0  # 0.0-1.0, how confident we are in merges

    # CRM fields
    tags: list[str] = field(default_factory=list)  # User-defined tags
    notes: str = ""  # User notes about the person
    source_entity_count: int = 0  # Count of linked SourceEntity records

    # Relationship strength (computed, not stored - see relationship_metrics.py)
    # Formula: (recency × 0.3) + (frequency × 0.4) + (diversity × 0.3)
    _relationship_strength: Optional[float] = field(default=None, repr=False)

    def __post_init__(self):
        """Set display_name to canonical_name if not specified."""
        if not self.display_name and self.canonical_name:
            self.display_name = self.canonical_name

    @property
    def primary_email(self) -> Optional[str]:
        """Get the primary (first) email address."""
        return self.emails[0] if self.emails else None

    @property
    def relationship_strength(self) -> float:
        """
        Get computed relationship strength (0.0-1.0).

        If not computed yet, returns 0.0. Use relationship_metrics.py
        to compute and cache this value.
        """
        return self._relationship_strength if self._relationship_strength is not None else 0.0

    @relationship_strength.setter
    def relationship_strength(self, value: float) -> None:
        """Set relationship strength."""
        self._relationship_strength = max(0.0, min(1.0, value))

    def add_tag(self, tag: str) -> bool:
        """Add a tag if not already present."""
        if not tag:
            return False
        tag = tag.strip().lower()
        if tag not in self.tags:
            self.tags.append(tag)
            return True
        return False

    def remove_tag(self, tag: str) -> bool:
        """Remove a tag if present."""
        tag = tag.strip().lower()
        if tag in self.tags:
            self.tags.remove(tag)
            return True
        return False

    def has_email(self, email: str) -> bool:
        """Check if this person has a specific email (case-insensitive)."""
        email_lower = email.lower()
        return any(e.lower() == email_lower for e in self.emails)

    def add_email(self, email: str) -> bool:
        """
        Add an email if not already present (case-insensitive check).

        Returns:
            True if email was added, False if already exists
        """
        if not email:
            return False
        if not self.has_email(email):
            self.emails.append(email.lower())
            return True
        return False

    def has_phone(self, phone: str) -> bool:
        """Check if this person has a specific phone number."""
        return phone in self.phone_numbers

    def add_phone(self, phone: str) -> bool:
        """
        Add a phone number if not already present.

        Args:
            phone: E.164 format phone number (+1XXXXXXXXXX)

        Returns:
            True if phone was added, False if already exists
        """
        if not phone:
            return False
        if not self.has_phone(phone):
            self.phone_numbers.append(phone)
            # Set as primary if first phone number
            if not self.phone_primary:
                self.phone_primary = phone
            return True
        return False

    def merge(self, other: "PersonEntity") -> "PersonEntity":
        """
        Merge another entity into this one.

        Follows same logic as PersonRecord.merge() but enhanced for new fields.
        """
        # Combine emails (unique, case-insensitive)
        emails = list(self.emails)
        for email in other.emails:
            if not any(e.lower() == email.lower() for e in emails):
                emails.append(email.lower())

        # Combine sources
        sources = list(set(self.sources + other.sources))

        # Combine vault contexts
        vault_contexts = list(set(self.vault_contexts + other.vault_contexts))

        # Take earliest first_seen (use _make_aware for safe comparison)
        first_seen = self.first_seen
        if other.first_seen:
            if first_seen is None or _make_aware(other.first_seen) < _make_aware(first_seen):
                first_seen = other.first_seen

        # Take latest last_seen (use _make_aware for safe comparison)
        last_seen = self.last_seen
        if other.last_seen:
            if last_seen is None or _make_aware(other.last_seen) > _make_aware(last_seen):
                last_seen = other.last_seen

        # Sum counts
        meeting_count = self.meeting_count + other.meeting_count
        email_count = self.email_count + other.email_count
        mention_count = self.mention_count + other.mention_count
        message_count = self.message_count + other.message_count

        # Combine related notes
        related_notes = list(set(self.related_notes + other.related_notes))

        # Combine aliases
        aliases = list(set(self.aliases + other.aliases))

        # Combine phone numbers (unique)
        phone_numbers = list(self.phone_numbers)
        for phone in other.phone_numbers:
            if phone not in phone_numbers:
                phone_numbers.append(phone)

        # Phone primary: prefer self, then other
        phone_primary = self.phone_primary or other.phone_primary

        # Take first non-None values for single fields
        company = self.company or other.company
        position = self.position or other.position
        linkedin_url = self.linkedin_url or other.linkedin_url

        # Category: prefer non-unknown
        category = self.category if self.category != "unknown" else other.category

        # Confidence: average of both, slightly reduced for merge uncertainty
        confidence_score = (self.confidence_score + other.confidence_score) / 2 * 0.95

        # Combine tags (unique)
        tags = list(set(self.tags + other.tags))

        # Notes: concatenate if both have content
        notes = self.notes
        if other.notes and other.notes != self.notes:
            if notes:
                notes = f"{notes}\n\n---\n\n{other.notes}"
            else:
                notes = other.notes

        # Source entity count: sum
        source_entity_count = self.source_entity_count + other.source_entity_count

        return PersonEntity(
            id=self.id,  # Keep original ID
            canonical_name=self.canonical_name,
            display_name=self.display_name,
            emails=emails,
            company=company,
            position=position,
            linkedin_url=linkedin_url,
            category=category,
            vault_contexts=vault_contexts,
            sources=sources,
            first_seen=first_seen,
            last_seen=last_seen,
            meeting_count=meeting_count,
            email_count=email_count,
            mention_count=mention_count,
            message_count=message_count,
            related_notes=related_notes,
            aliases=aliases,
            phone_numbers=phone_numbers,
            phone_primary=phone_primary,
            confidence_score=confidence_score,
            tags=tags,
            notes=notes,
            source_entity_count=source_entity_count,
        )

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        data = asdict(self)
        # Convert datetime to ISO format strings
        if self.first_seen:
            data["first_seen"] = self.first_seen.isoformat()
        if self.last_seen:
            data["last_seen"] = self.last_seen.isoformat()
        # Remove private fields (they start with _)
        data.pop("_relationship_strength", None)
        # Add computed relationship_strength if available
        if self._relationship_strength is not None:
            data["relationship_strength"] = self._relationship_strength
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "PersonEntity":
        """Create PersonEntity from dict."""
        # Parse datetime strings and ensure timezone-aware
        if data.get("first_seen") and isinstance(data["first_seen"], str):
            dt = datetime.fromisoformat(data["first_seen"])
            data["first_seen"] = _make_aware(dt)
        if data.get("last_seen") and isinstance(data["last_seen"], str):
            dt = datetime.fromisoformat(data["last_seen"])
            data["last_seen"] = _make_aware(dt)
        # Handle relationship_strength -> _relationship_strength
        if "relationship_strength" in data:
            data["_relationship_strength"] = data.pop("relationship_strength")
        # Handle legacy data without new fields
        data.setdefault("tags", [])
        data.setdefault("notes", "")
        data.setdefault("source_entity_count", 0)
        data.setdefault("message_count", 0)
        return cls(**data)

    @classmethod
    def from_person_record(cls, record: "PersonRecord") -> "PersonEntity":
        """
        Migrate a PersonRecord to PersonEntity.

        This is the primary migration path from the v1 system.
        """
        # Convert single email to list
        emails = [record.email.lower()] if record.email else []

        return cls(
            id=str(uuid.uuid4()),
            canonical_name=record.canonical_name,
            display_name=record.canonical_name,
            emails=emails,
            company=record.company,
            position=record.position,
            linkedin_url=record.linkedin_url,
            category=record.category,
            vault_contexts=[],  # Will be populated during re-indexing
            sources=record.sources,
            first_seen=record.first_seen,
            last_seen=record.last_seen,
            meeting_count=record.meeting_count,
            email_count=record.email_count,
            mention_count=record.mention_count,
            related_notes=record.related_notes,
            aliases=record.aliases,
            confidence_score=1.0,  # Full confidence for migrated records
        )

    def to_person_record(self) -> "PersonRecord":
        """
        Convert back to PersonRecord for backward compatibility.

        Note: Some data may be lost (multiple emails → single email, vault_contexts, confidence_score)
        """
        # Import here to avoid circular import
        from api.services.people_aggregator import PersonRecord

        return PersonRecord(
            canonical_name=self.canonical_name,
            email=self.primary_email,
            sources=self.sources,
            first_seen=self.first_seen,
            last_seen=self.last_seen,
            company=self.company,
            position=self.position,
            linkedin_url=self.linkedin_url,
            meeting_count=self.meeting_count,
            email_count=self.email_count,
            mention_count=self.mention_count,
            related_notes=self.related_notes,
            aliases=self.aliases,
            category=self.category,
        )


class PersonEntityStore:
    """
    Storage layer for PersonEntity objects.

    Provides CRUD operations and persistence to JSON file.
    """

    # Path to merged IDs file (secondary_id -> primary_id mapping)
    MERGED_IDS_PATH = Path(__file__).parent.parent.parent / "data" / "merged_person_ids.json"

    def __init__(self, storage_path: str = "./data/people_entities.json"):
        """
        Initialize the entity store.

        Args:
            storage_path: Path to JSON file for persistence
        """
        self.storage_path = Path(storage_path)
        self._entities: dict[str, PersonEntity] = {}  # Keyed by entity ID
        self._email_index: dict[str, str] = {}  # email.lower() → entity ID
        self._name_index: dict[str, str] = {}  # canonical_name.lower() → entity ID
        self._phone_index: dict[str, str] = {}  # E.164 phone → entity ID
        self._merged_ids: dict[str, str] = {}  # secondary_id -> primary_id
        self._load()
        self._load_merged_ids()

    def _load_merged_ids(self) -> None:
        """Load the merged IDs mapping for durability."""
        if self.MERGED_IDS_PATH.exists():
            try:
                with open(self.MERGED_IDS_PATH) as f:
                    self._merged_ids = json.load(f)
                if self._merged_ids:
                    logger.info(f"Loaded {len(self._merged_ids)} merged ID mappings")
            except Exception as e:
                logger.warning(f"Failed to load merged IDs: {e}")

    def get_canonical_id(self, person_id: str) -> str:
        """
        Get the canonical (primary) person ID, following merge chain if needed.

        This ensures that if a person was merged into another, we always
        return the surviving primary ID.
        """
        visited = set()
        while person_id in self._merged_ids and person_id not in visited:
            visited.add(person_id)
            person_id = self._merged_ids[person_id]
        return person_id

    def _load(self) -> None:
        """Load entities from disk."""
        if not self.storage_path.exists():
            logger.info(f"No existing entity store at {self.storage_path}")
            return

        try:
            with open(self.storage_path, "r") as f:
                data = json.load(f)

            for entity_data in data:
                entity = PersonEntity.from_dict(entity_data)
                self._entities[entity.id] = entity
                self._index_entity(entity)

            logger.info(f"Loaded {len(self._entities)} entities from {self.storage_path}")
        except Exception as e:
            logger.error(f"Failed to load entity store: {e}")

    def _index_entity(self, entity: PersonEntity) -> None:
        """Add entity to lookup indices."""
        # Email index
        for email in entity.emails:
            self._email_index[email.lower()] = entity.id

        # Name index
        if entity.canonical_name:
            self._name_index[entity.canonical_name.lower()] = entity.id

        # Alias index (also add to name index)
        for alias in entity.aliases:
            if alias:
                self._name_index[alias.lower()] = entity.id

        # Phone index
        for phone in entity.phone_numbers:
            if phone:
                self._phone_index[phone] = entity.id

    def _remove_from_indices(self, entity: PersonEntity) -> None:
        """Remove entity from lookup indices."""
        for email in entity.emails:
            self._email_index.pop(email.lower(), None)

        if entity.canonical_name:
            self._name_index.pop(entity.canonical_name.lower(), None)

        for alias in entity.aliases:
            if alias:
                self._name_index.pop(alias.lower(), None)

        for phone in entity.phone_numbers:
            if phone:
                self._phone_index.pop(phone, None)

    def save(self) -> None:
        """Persist entities to disk."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        data = [entity.to_dict() for entity in self._entities.values()]

        with open(self.storage_path, "w") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Saved {len(data)} entities to {self.storage_path}")

    def add(self, entity: PersonEntity) -> PersonEntity:
        """
        Add a new entity to the store.

        Args:
            entity: PersonEntity to add

        Returns:
            The added entity (a copy is stored internally)
        """
        # Store a copy to avoid reference issues
        stored = PersonEntity.from_dict(entity.to_dict())
        self._entities[stored.id] = stored
        self._index_entity(stored)
        return stored

    def update(self, entity: PersonEntity) -> PersonEntity:
        """
        Update an existing entity.

        Args:
            entity: PersonEntity with updated data

        Returns:
            The updated entity (a copy is stored internally)
        """
        # Get the OLD stored entity (not the passed-in one which may have been modified)
        old_entity = self._entities.get(entity.id)
        if old_entity:
            self._remove_from_indices(old_entity)

        # Store a copy to avoid reference issues
        stored = PersonEntity.from_dict(entity.to_dict())
        self._entities[stored.id] = stored
        self._index_entity(stored)
        return stored

    def delete(self, entity_id: str) -> bool:
        """
        Delete an entity by ID.

        Args:
            entity_id: ID of entity to delete

        Returns:
            True if deleted, False if not found
        """
        entity = self._entities.pop(entity_id, None)
        if entity:
            self._remove_from_indices(entity)
            return True
        return False

    def get_by_id(self, entity_id: str) -> Optional[PersonEntity]:
        """
        Get entity by ID, following merge chain if needed.

        If this ID was merged into another person, returns the surviving
        primary person instead.
        """
        # Follow merge chain to get canonical ID
        canonical_id = self.get_canonical_id(entity_id)
        return self._entities.get(canonical_id)

    def get_by_email(self, email: str) -> Optional[PersonEntity]:
        """Get entity by email address (case-insensitive), following merge chain."""
        entity_id = self._email_index.get(email.lower())
        if entity_id:
            return self.get_by_id(entity_id)  # Uses canonical ID
        return None

    def get_by_phone(self, phone: str) -> Optional[PersonEntity]:
        """Get entity by phone number (E.164 format), following merge chain."""
        entity_id = self._phone_index.get(phone)
        if entity_id:
            return self.get_by_id(entity_id)  # Uses canonical ID
        return None

    def get_by_name(self, name: str) -> Optional[PersonEntity]:
        """Get entity by canonical name or alias (case-insensitive), following merge chain."""
        entity_id = self._name_index.get(name.lower())
        if entity_id:
            return self.get_by_id(entity_id)  # Uses canonical ID
        return None

    def reload_merged_ids(self) -> None:
        """Reload merged IDs mapping from disk (call after a merge operation)."""
        self._load_merged_ids()

    def search(self, query: str, limit: int = 20) -> list[PersonEntity]:
        """
        Search entities by name, email, or alias.

        Args:
            query: Search string
            limit: Maximum results to return

        Returns:
            List of matching entities
        """
        query_lower = query.lower()
        results = []

        for entity in self._entities.values():
            # Check canonical name
            if query_lower in entity.canonical_name.lower():
                results.append(entity)
                continue

            # Check display name
            if query_lower in entity.display_name.lower():
                results.append(entity)
                continue

            # Check emails
            if any(query_lower in email.lower() for email in entity.emails):
                results.append(entity)
                continue

            # Check aliases
            if any(query_lower in alias.lower() for alias in entity.aliases):
                results.append(entity)
                continue

            if len(results) >= limit:
                break

        # Sort by last_seen (most recent first), then by name
        results.sort(
            key=lambda e: (e.last_seen or datetime.min, e.canonical_name),
            reverse=True,
        )

        return results[:limit]

    def get_all(self) -> list[PersonEntity]:
        """Get all entities."""
        return list(self._entities.values())

    def count(self) -> int:
        """Get total number of entities."""
        return len(self._entities)

    def get_statistics(self) -> dict:
        """Get aggregate statistics about stored entities."""
        by_source: dict[str, int] = {}
        by_category: dict[str, int] = {}

        for entity in self._entities.values():
            for source in entity.sources:
                by_source[source] = by_source.get(source, 0) + 1
            by_category[entity.category] = by_category.get(entity.category, 0) + 1

        return {
            "total_entities": len(self._entities),
            "by_source": by_source,
            "by_category": by_category,
            "total_emails_indexed": len(self._email_index),
            "total_names_indexed": len(self._name_index),
            "total_phones_indexed": len(self._phone_index),
        }


# Singleton instance
_entity_store: Optional[PersonEntityStore] = None


def get_person_entity_store(
    storage_path: str = "./data/people_entities.json",
) -> PersonEntityStore:
    """
    Get or create the singleton PersonEntityStore.

    Args:
        storage_path: Path to JSON file for persistence

    Returns:
        PersonEntityStore instance
    """
    global _entity_store
    if _entity_store is None:
        _entity_store = PersonEntityStore(storage_path)
    return _entity_store

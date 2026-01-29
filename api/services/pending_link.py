"""
PendingLink - Workflow for confirming entity-to-person links.

When the entity resolver proposes a link between a SourceEntity and a
CanonicalPerson, it creates a PendingLink for user confirmation if the
confidence is below a threshold or if it's a new person creation.
"""
import sqlite3
import json
import uuid
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

from api.services.source_entity import get_crm_db_path, LINK_STATUS_CONFIRMED, LINK_STATUS_REJECTED

logger = logging.getLogger(__name__)


def _make_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime is timezone-aware (UTC if naive)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# Link reasons
REASON_NEW_ENTITY = "new_entity"  # Creating a new canonical person
REASON_EMAIL_MATCH = "email_match"  # Matched by email
REASON_PHONE_MATCH = "phone_match"  # Matched by phone
REASON_NAME_MATCH = "name_match"  # Matched by fuzzy name
REASON_CONTEXT_MATCH = "context_match"  # Matched by context (vault folder, etc.)

# Pending link status
STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_REJECTED = "rejected"


@dataclass
class PendingLink:
    """
    A proposed link between a SourceEntity and a CanonicalPerson.

    Created when the entity resolver has low confidence or when
    creating a new person that the user should confirm.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_entity_id: str = ""

    # Previous link (for re-linking scenarios)
    previous_canonical_id: Optional[str] = None

    # Proposed link
    proposed_canonical_id: str = ""

    # Why this link was proposed
    reason: str = REASON_NAME_MATCH
    confidence: float = 0.0

    # Status
    status: str = STATUS_PENDING  # pending, confirmed, rejected

    # Resolution
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None  # "user" or "auto"

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        data = asdict(self)
        if self.resolved_at:
            data["resolved_at"] = self.resolved_at.isoformat()
        if self.created_at:
            data["created_at"] = self.created_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "PendingLink":
        """Create PendingLink from dict."""
        if data.get("resolved_at") and isinstance(data["resolved_at"], str):
            data["resolved_at"] = _make_aware(datetime.fromisoformat(data["resolved_at"]))
        if data.get("created_at") and isinstance(data["created_at"], str):
            data["created_at"] = _make_aware(datetime.fromisoformat(data["created_at"]))
        return cls(**data)

    @classmethod
    def from_row(cls, row: tuple) -> "PendingLink":
        """Create PendingLink from SQLite row."""
        # Row order: id, source_entity_id, previous_canonical_id, proposed_canonical_id,
        #            reason, confidence, status, resolved_at, resolved_by, created_at
        resolved_at = datetime.fromisoformat(row[7]) if row[7] else None
        created_at = datetime.fromisoformat(row[9]) if row[9] else datetime.now(timezone.utc)

        return cls(
            id=row[0],
            source_entity_id=row[1],
            previous_canonical_id=row[2],
            proposed_canonical_id=row[3],
            reason=row[4] or REASON_NAME_MATCH,
            confidence=row[5] or 0.0,
            status=row[6] or STATUS_PENDING,
            resolved_at=_make_aware(resolved_at),
            resolved_by=row[8],
            created_at=_make_aware(created_at),
        )

    @property
    def is_pending(self) -> bool:
        """Check if this link is still pending."""
        return self.status == STATUS_PENDING

    @property
    def is_resolved(self) -> bool:
        """Check if this link has been resolved."""
        return self.status in (STATUS_CONFIRMED, STATUS_REJECTED)

    @property
    def reason_display(self) -> str:
        """Get human-readable reason."""
        reasons = {
            REASON_NEW_ENTITY: "New person",
            REASON_EMAIL_MATCH: "Email match",
            REASON_PHONE_MATCH: "Phone match",
            REASON_NAME_MATCH: "Name match",
            REASON_CONTEXT_MATCH: "Context match",
        }
        return reasons.get(self.reason, self.reason)


class PendingLinkStore:
    """
    SQLite-backed storage for PendingLink records.

    Provides workflow operations for confirming/rejecting links.
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the pending link store.

        Args:
            db_path: Path to SQLite database (default from settings)
        """
        self.db_path = db_path or get_crm_db_path()
        self._init_db()

    def _init_db(self):
        """Create database tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_links (
                    id TEXT PRIMARY KEY,
                    source_entity_id TEXT NOT NULL,
                    previous_canonical_id TEXT,
                    proposed_canonical_id TEXT NOT NULL,
                    reason TEXT,
                    confidence REAL,
                    status TEXT DEFAULT 'pending',
                    resolved_at TIMESTAMP,
                    resolved_by TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Index for finding pending links by source entity
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_pending_links_source
                ON pending_links(source_entity_id)
            """)

            # Index for finding pending links by status
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_pending_links_status
                ON pending_links(status)
            """)

            # Index for finding pending links by proposed person
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_pending_links_proposed
                ON pending_links(proposed_canonical_id)
            """)

            conn.commit()
            logger.info(f"Initialized pending links database at {self.db_path}")
        finally:
            conn.close()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        return sqlite3.connect(self.db_path)

    def add(self, link: PendingLink) -> PendingLink:
        """
        Add a new pending link.

        Args:
            link: PendingLink to add

        Returns:
            The added link
        """
        conn = self._get_connection()
        try:
            conn.execute("""
                INSERT INTO pending_links
                (id, source_entity_id, previous_canonical_id, proposed_canonical_id,
                 reason, confidence, status, resolved_at, resolved_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                link.id,
                link.source_entity_id,
                link.previous_canonical_id,
                link.proposed_canonical_id,
                link.reason,
                link.confidence,
                link.status,
                link.resolved_at.isoformat() if link.resolved_at else None,
                link.resolved_by,
                link.created_at.isoformat(),
            ))
            conn.commit()
            return link
        finally:
            conn.close()

    def get_by_id(self, link_id: str) -> Optional[PendingLink]:
        """Get pending link by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM pending_links WHERE id = ?",
                (link_id,)
            )
            row = cursor.fetchone()
            if row:
                return PendingLink.from_row(row)
            return None
        finally:
            conn.close()

    def get_for_source_entity(self, source_entity_id: str) -> list[PendingLink]:
        """Get all pending links for a source entity."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                SELECT * FROM pending_links
                WHERE source_entity_id = ?
                ORDER BY created_at DESC
            """, (source_entity_id,))
            return [PendingLink.from_row(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_pending(self, limit: int = 100) -> list[PendingLink]:
        """Get all pending (unresolved) links."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                SELECT * FROM pending_links
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT ?
            """, (limit,))
            return [PendingLink.from_row(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_pending_for_person(self, canonical_person_id: str) -> list[PendingLink]:
        """Get pending links proposing to link to a specific person."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                SELECT * FROM pending_links
                WHERE proposed_canonical_id = ? AND status = 'pending'
                ORDER BY created_at ASC
            """, (canonical_person_id,))
            return [PendingLink.from_row(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def confirm(
        self,
        link_id: str,
        resolved_by: str = "user",
    ) -> Optional[PendingLink]:
        """
        Confirm a pending link.

        This updates the pending link status and should be followed by
        updating the source entity's link.

        Args:
            link_id: Pending link ID
            resolved_by: Who resolved it ("user" or "auto")

        Returns:
            The updated link, or None if not found
        """
        link = self.get_by_id(link_id)
        if not link:
            return None

        conn = self._get_connection()
        try:
            now = datetime.now(timezone.utc)
            conn.execute("""
                UPDATE pending_links SET
                    status = 'confirmed',
                    resolved_at = ?,
                    resolved_by = ?
                WHERE id = ?
            """, (now.isoformat(), resolved_by, link_id))
            conn.commit()

            link.status = STATUS_CONFIRMED
            link.resolved_at = now
            link.resolved_by = resolved_by
            return link
        finally:
            conn.close()

    def reject(
        self,
        link_id: str,
        resolved_by: str = "user",
    ) -> Optional[PendingLink]:
        """
        Reject a pending link.

        Args:
            link_id: Pending link ID
            resolved_by: Who resolved it

        Returns:
            The updated link, or None if not found
        """
        link = self.get_by_id(link_id)
        if not link:
            return None

        conn = self._get_connection()
        try:
            now = datetime.now(timezone.utc)
            conn.execute("""
                UPDATE pending_links SET
                    status = 'rejected',
                    resolved_at = ?,
                    resolved_by = ?
                WHERE id = ?
            """, (now.isoformat(), resolved_by, link_id))
            conn.commit()

            link.status = STATUS_REJECTED
            link.resolved_at = now
            link.resolved_by = resolved_by
            return link
        finally:
            conn.close()

    def delete(self, link_id: str) -> bool:
        """Delete a pending link."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM pending_links WHERE id = ?",
                (link_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_for_source_entity(self, source_entity_id: str) -> int:
        """Delete all pending links for a source entity."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM pending_links WHERE source_entity_id = ?",
                (source_entity_id,)
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def count_pending(self) -> int:
        """Get count of pending links."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM pending_links WHERE status = 'pending'"
            )
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def get_statistics(self) -> dict:
        """Get aggregate statistics about pending links."""
        conn = self._get_connection()
        try:
            total = conn.execute("SELECT COUNT(*) FROM pending_links").fetchone()[0]

            by_status = {}
            cursor = conn.execute("""
                SELECT status, COUNT(*) as count
                FROM pending_links
                GROUP BY status
            """)
            for row in cursor.fetchall():
                by_status[row[0]] = row[1]

            by_reason = {}
            cursor = conn.execute("""
                SELECT reason, COUNT(*) as count
                FROM pending_links
                WHERE status = 'pending'
                GROUP BY reason
            """)
            for row in cursor.fetchall():
                by_reason[row[0]] = row[1]

            return {
                "total_links": total,
                "pending_count": by_status.get("pending", 0),
                "confirmed_count": by_status.get("confirmed", 0),
                "rejected_count": by_status.get("rejected", 0),
                "by_reason": by_reason,
            }
        finally:
            conn.close()


# Singleton instance
_pending_link_store: Optional[PendingLinkStore] = None


def get_pending_link_store(db_path: Optional[str] = None) -> PendingLinkStore:
    """
    Get or create the singleton PendingLinkStore.

    Args:
        db_path: Path to SQLite database

    Returns:
        PendingLinkStore instance
    """
    global _pending_link_store
    if _pending_link_store is None:
        _pending_link_store = PendingLinkStore(db_path)
    return _pending_link_store


def create_pending_link(
    source_entity_id: str,
    proposed_canonical_id: str,
    reason: str = REASON_NAME_MATCH,
    confidence: float = 0.0,
    previous_canonical_id: Optional[str] = None,
) -> PendingLink:
    """
    Create a new pending link.

    Args:
        source_entity_id: Source entity ID
        proposed_canonical_id: Proposed canonical person ID
        reason: Why this link was proposed
        confidence: Link confidence (0.0-1.0)
        previous_canonical_id: Previous link (for re-linking)

    Returns:
        New PendingLink
    """
    return PendingLink(
        source_entity_id=source_entity_id,
        proposed_canonical_id=proposed_canonical_id,
        reason=reason,
        confidence=confidence,
        previous_canonical_id=previous_canonical_id,
    )

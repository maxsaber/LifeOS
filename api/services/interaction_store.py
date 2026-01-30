"""
Interaction Store for LifeOS People System v2.

Stores lightweight interaction records with links to sources.
Each interaction represents a single touchpoint (email, meeting, note mention).
"""
import sqlite3
import json
import uuid
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from config.settings import settings
from config.people_config import InteractionConfig

logger = logging.getLogger(__name__)


def _make_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime is timezone-aware (UTC if naive)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def get_interaction_db_path() -> str:
    """Get the path to the interactions database."""
    db_dir = Path(settings.chroma_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)
    return str(db_dir / "interactions.db")


@dataclass
class Interaction:
    """
    A single interaction with a person.

    Stores metadata and links to source content, NOT the full content itself.
    """

    id: str
    person_id: str  # FK to PersonEntity.id
    timestamp: datetime
    source_type: str  # "gmail", "calendar", "vault", "granola"

    # Metadata (not full content)
    title: str  # Email subject, meeting title, note filename
    snippet: Optional[str] = None  # First N chars for preview

    # Links to actual content
    source_link: str = ""  # Gmail URL, obsidian:// link, calendar URL
    source_id: Optional[str] = None  # Gmail message ID, calendar event ID, file path

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        data["created_at"] = self.created_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Interaction":
        """Create Interaction from dict."""
        if isinstance(data.get("timestamp"), str):
            dt = datetime.fromisoformat(data["timestamp"])
            data["timestamp"] = _make_aware(dt)
        if isinstance(data.get("created_at"), str):
            dt = datetime.fromisoformat(data["created_at"])
            data["created_at"] = _make_aware(dt)
        return cls(**data)

    @classmethod
    def from_row(cls, row: tuple) -> "Interaction":
        """Create Interaction from SQLite row."""
        # Parse and normalize timestamps to be timezone-aware
        timestamp = datetime.fromisoformat(row[2]) if row[2] else datetime.now(timezone.utc)
        timestamp = _make_aware(timestamp)
        created_at = datetime.fromisoformat(row[8]) if row[8] else datetime.now(timezone.utc)
        created_at = _make_aware(created_at)

        return cls(
            id=row[0],
            person_id=row[1],
            timestamp=timestamp,
            source_type=row[3],
            title=row[4],
            snippet=row[5],
            source_link=row[6] or "",
            source_id=row[7],
            created_at=created_at,
        )

    @property
    def source_badge(self) -> str:
        """Get emoji badge for source type."""
        badges = {
            "gmail": "📧",
            "calendar": "📅",
            "vault": "📝",
            "granola": "📝",
            "imessage": "💬",
            "whatsapp": "💬",
            "contacts": "📇",
            "phone": "📞",
        }
        return badges.get(self.source_type, "📄")


def build_obsidian_link(file_path: str, vault_path: str = None) -> str:
    """
    Build an obsidian:// URI for a vault file.

    Args:
        file_path: Absolute or relative path to the file
        vault_path: Path to vault root (default from settings)

    Returns:
        obsidian:// URI
    """
    if vault_path is None:
        vault_path = str(settings.vault_path)

    # Get relative path from vault root
    path = Path(file_path)
    try:
        rel_path = path.relative_to(vault_path)
    except ValueError:
        rel_path = path

    # Build URI - obsidian://open?vault=VaultName&file=path/to/file
    vault_name = Path(vault_path).name
    file_param = quote(str(rel_path).replace(".md", ""), safe="")
    return f"obsidian://open?vault={quote(vault_name)}&file={file_param}"


def build_gmail_link(message_id: str) -> str:
    """
    Build a Gmail deep link for a message.

    Args:
        message_id: Gmail message ID

    Returns:
        Gmail web URL
    """
    return f"https://mail.google.com/mail/u/0/#inbox/{message_id}"


def build_calendar_link(event_id: str, calendar_id: str = "primary") -> str:
    """
    Build a Google Calendar link for an event.

    Args:
        event_id: Calendar event ID
        calendar_id: Calendar ID (default "primary")

    Returns:
        Google Calendar web URL
    """
    return f"https://calendar.google.com/calendar/event?eid={event_id}"


class InteractionStore:
    """
    SQLite-backed interaction storage.

    Manages interaction records with efficient queries by person and time range.
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize interaction store.

        Args:
            db_path: Path to SQLite database (default from settings)
        """
        self.db_path = db_path or get_interaction_db_path()
        self._init_db()

    def _init_db(self):
        """Create database tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS interactions (
                    id TEXT PRIMARY KEY,
                    person_id TEXT NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    source_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    snippet TEXT,
                    source_link TEXT,
                    source_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Index for efficient person + time queries
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_interactions_person_timestamp
                ON interactions(person_id, timestamp DESC)
            """
            )

            # Index for source deduplication
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_interactions_source
                ON interactions(source_type, source_id)
            """
            )

            # Index for time-based queries
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_interactions_timestamp
                ON interactions(timestamp DESC)
            """
            )

            conn.commit()
            logger.info(f"Initialized interaction database at {self.db_path}")
        finally:
            conn.close()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        return sqlite3.connect(self.db_path)

    def add(self, interaction: Interaction) -> Interaction:
        """
        Add a new interaction.

        Automatically follows merge chain - if the person_id was merged into
        another person, links to the surviving primary instead.

        Args:
            interaction: Interaction to add

        Returns:
            The added interaction
        """
        # Follow merge chain to get the canonical person ID
        from api.services.person_entity import get_person_entity_store
        person_store = get_person_entity_store()
        resolved_person_id = person_store.get_canonical_id(interaction.person_id)

        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO interactions
                (id, person_id, timestamp, source_type, title, snippet, source_link, source_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    interaction.id,
                    resolved_person_id,  # Use canonical ID
                    interaction.timestamp.isoformat(),
                    interaction.source_type,
                    interaction.title,
                    interaction.snippet,
                    interaction.source_link,
                    interaction.source_id,
                    interaction.created_at.isoformat(),
                ),
            )
            conn.commit()
            # Update the interaction object with the resolved ID
            interaction.person_id = resolved_person_id
            return interaction
        finally:
            conn.close()

    def add_if_not_exists(
        self, interaction: Interaction
    ) -> tuple[Interaction, bool]:
        """
        Add interaction if source_id doesn't already exist.

        Useful for avoiding duplicate imports.

        Args:
            interaction: Interaction to add

        Returns:
            Tuple of (interaction, was_added)
        """
        if interaction.source_id:
            existing = self.get_by_source(
                interaction.source_type, interaction.source_id
            )
            if existing:
                return existing, False

        return self.add(interaction), True

    def get_by_id(self, interaction_id: str) -> Optional[Interaction]:
        """Get interaction by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM interactions WHERE id = ?", (interaction_id,)
            )
            row = cursor.fetchone()
            if row:
                return Interaction.from_row(row)
            return None
        finally:
            conn.close()

    def get_by_source(
        self, source_type: str, source_id: str
    ) -> Optional[Interaction]:
        """Get interaction by source type and ID."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM interactions WHERE source_type = ? AND source_id = ?",
                (source_type, source_id),
            )
            row = cursor.fetchone()
            if row:
                return Interaction.from_row(row)
            return None
        finally:
            conn.close()

    def get_for_person(
        self,
        person_id: str,
        days_back: int = None,
        limit: int = None,
        source_type: Optional[str] = None,
        specific_date: Optional[str] = None,
    ) -> list[Interaction]:
        """
        Get interactions for a person.

        Args:
            person_id: PersonEntity ID
            days_back: Only return interactions from last N days (default from config)
            limit: Maximum interactions to return (default from config)
            source_type: Filter by source type (optional)
            specific_date: Filter to a specific date (YYYY-MM-DD format, optional)

        Returns:
            List of interactions, most recent first
        """
        if limit is None:
            limit = InteractionConfig.MAX_INTERACTIONS_PER_QUERY

        conn = self._get_connection()
        try:
            # Build query based on filters
            if specific_date:
                # Filter to a specific day
                date_start = f"{specific_date}T00:00:00"
                date_end = f"{specific_date}T23:59:59"
                if source_type:
                    cursor = conn.execute(
                        """
                        SELECT * FROM interactions
                        WHERE person_id = ? AND timestamp >= ? AND timestamp <= ? AND source_type = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """,
                        (person_id, date_start, date_end, source_type, limit),
                    )
                else:
                    cursor = conn.execute(
                        """
                        SELECT * FROM interactions
                        WHERE person_id = ? AND timestamp >= ? AND timestamp <= ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """,
                        (person_id, date_start, date_end, limit),
                    )
            else:
                # Use days_back cutoff
                if days_back is None:
                    days_back = InteractionConfig.DEFAULT_WINDOW_DAYS
                cutoff = datetime.now() - timedelta(days=days_back)
                if source_type:
                    cursor = conn.execute(
                        """
                        SELECT * FROM interactions
                        WHERE person_id = ? AND timestamp > ? AND source_type = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """,
                        (person_id, cutoff.isoformat(), source_type, limit),
                    )
                else:
                    cursor = conn.execute(
                        """
                        SELECT * FROM interactions
                        WHERE person_id = ? AND timestamp > ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """,
                        (person_id, cutoff.isoformat(), limit),
                    )

            return [Interaction.from_row(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_interaction_counts(
        self, person_id: str, days_back: int = None
    ) -> dict[str, int]:
        """
        Get count of interactions by source type for a person.

        Args:
            person_id: PersonEntity ID
            days_back: Only count interactions from last N days

        Returns:
            Dict mapping source_type to count
        """
        if days_back is None:
            days_back = InteractionConfig.DEFAULT_WINDOW_DAYS

        cutoff = datetime.now() - timedelta(days=days_back)

        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT source_type, COUNT(*) as count
                FROM interactions
                WHERE person_id = ? AND timestamp > ?
                GROUP BY source_type
            """,
                (person_id, cutoff.isoformat()),
            )

            return {row[0]: row[1] for row in cursor.fetchall()}
        finally:
            conn.close()

    def get_last_interaction(self, person_id: str) -> Optional[Interaction]:
        """Get the most recent interaction with a person."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT * FROM interactions
                WHERE person_id = ?
                ORDER BY timestamp DESC
                LIMIT 1
            """,
                (person_id,),
            )
            row = cursor.fetchone()
            if row:
                return Interaction.from_row(row)
            return None
        finally:
            conn.close()

    def delete(self, interaction_id: str) -> bool:
        """
        Delete an interaction by ID.

        Returns:
            True if deleted, False if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM interactions WHERE id = ?", (interaction_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_for_person(self, person_id: str) -> int:
        """
        Delete all interactions for a person.

        Returns:
            Number of interactions deleted
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM interactions WHERE person_id = ?", (person_id,)
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def count(self) -> int:
        """Get total number of interactions."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM interactions")
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def get_statistics(self) -> dict:
        """Get aggregate statistics about stored interactions."""
        conn = self._get_connection()
        try:
            # Total count
            total = conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]

            # By source type
            by_source = {}
            cursor = conn.execute(
                """
                SELECT source_type, COUNT(*) as count
                FROM interactions
                GROUP BY source_type
            """
            )
            for row in cursor.fetchall():
                by_source[row[0]] = row[1]

            # Unique people
            unique_people = conn.execute(
                "SELECT COUNT(DISTINCT person_id) FROM interactions"
            ).fetchone()[0]

            # Date range
            date_range = conn.execute(
                """
                SELECT MIN(timestamp), MAX(timestamp)
                FROM interactions
            """
            ).fetchone()

            return {
                "total_interactions": total,
                "by_source": by_source,
                "unique_people": unique_people,
                "earliest_interaction": date_range[0],
                "latest_interaction": date_range[1],
            }
        finally:
            conn.close()

    def format_interaction_history(
        self, person_id: str, days_back: int = None, limit: int = None
    ) -> str:
        """
        Format interaction history as markdown for briefings.

        Args:
            person_id: PersonEntity ID
            days_back: Days to look back
            limit: Maximum interactions

        Returns:
            Formatted markdown string
        """
        interactions = self.get_for_person(person_id, days_back, limit)
        counts = self.get_interaction_counts(person_id, days_back)
        last = self.get_last_interaction(person_id)

        if not interactions:
            return "_No interactions found in the specified time period._"

        # Build summary line
        total = sum(counts.values())
        count_parts = []
        if counts.get("gmail", 0):
            count_parts.append(f"📧 {counts['gmail']} emails")
        if counts.get("calendar", 0):
            count_parts.append(f"📅 {counts['calendar']} meetings")
        if counts.get("vault", 0) or counts.get("granola", 0):
            notes = counts.get("vault", 0) + counts.get("granola", 0)
            count_parts.append(f"📝 {notes} notes")

        last_str = ""
        if last:
            days_ago = (datetime.now(timezone.utc) - _make_aware(last.timestamp)).days
            if days_ago == 0:
                last_str = "today"
            elif days_ago == 1:
                last_str = "yesterday"
            else:
                last_str = f"{days_ago} days ago"

        lines = [
            f"**Summary:** {total} interactions | Last: {last_str}",
            " | ".join(count_parts),
            "",
            "### Recent Activity",
        ]

        # Add individual interactions
        for interaction in interactions[:20]:  # Cap at 20 for display
            date_str = interaction.timestamp.strftime("%b %d")
            badge = interaction.source_badge

            if interaction.source_link:
                if interaction.source_type in ("vault", "granola"):
                    lines.append(
                        f"- {badge} {date_str}: {interaction.title} — [[{interaction.title}]]"
                    )
                else:
                    lines.append(
                        f"- {badge} {date_str}: {interaction.title} — [View]({interaction.source_link})"
                    )
            else:
                lines.append(f"- {badge} {date_str}: {interaction.title}")

        return "\n".join(lines)


# Singleton instance
_interaction_store: Optional[InteractionStore] = None


def get_interaction_store(db_path: Optional[str] = None) -> InteractionStore:
    """
    Get or create the singleton InteractionStore.

    Args:
        db_path: Path to SQLite database

    Returns:
        InteractionStore instance
    """
    global _interaction_store
    if _interaction_store is None:
        _interaction_store = InteractionStore(db_path)
    return _interaction_store


# Factory functions for creating interactions from different sources


def create_gmail_interaction(
    person_id: str,
    message_id: str,
    subject: str,
    timestamp: datetime,
    snippet: Optional[str] = None,
) -> Interaction:
    """
    Create an interaction from a Gmail message.

    Args:
        person_id: PersonEntity ID
        message_id: Gmail message ID
        subject: Email subject line
        timestamp: Email date
        snippet: First part of email body

    Returns:
        Interaction ready to be stored
    """
    return Interaction(
        id=str(uuid.uuid4()),
        person_id=person_id,
        timestamp=timestamp,
        source_type="gmail",
        title=subject,
        snippet=snippet[:InteractionConfig.SNIPPET_LENGTH] if snippet else None,
        source_link=build_gmail_link(message_id),
        source_id=message_id,
    )


def create_calendar_interaction(
    person_id: str,
    event_id: str,
    title: str,
    timestamp: datetime,
    snippet: Optional[str] = None,
) -> Interaction:
    """
    Create an interaction from a Calendar event.

    Args:
        person_id: PersonEntity ID
        event_id: Calendar event ID
        title: Event title
        timestamp: Event start time
        snippet: Event description

    Returns:
        Interaction ready to be stored
    """
    return Interaction(
        id=str(uuid.uuid4()),
        person_id=person_id,
        timestamp=timestamp,
        source_type="calendar",
        title=title,
        snippet=snippet[:InteractionConfig.SNIPPET_LENGTH] if snippet else None,
        source_link=build_calendar_link(event_id),
        source_id=event_id,
    )


def create_vault_interaction(
    person_id: str,
    file_path: str,
    title: str,
    timestamp: datetime,
    snippet: Optional[str] = None,
    is_granola: bool = False,
) -> Interaction:
    """
    Create an interaction from a vault note.

    Args:
        person_id: PersonEntity ID
        file_path: Path to the note file
        title: Note title (usually filename without .md)
        timestamp: Note date (from frontmatter or filename)
        snippet: First part of note content
        is_granola: Whether this is a Granola meeting note

    Returns:
        Interaction ready to be stored
    """
    return Interaction(
        id=str(uuid.uuid4()),
        person_id=person_id,
        timestamp=timestamp,
        source_type="granola" if is_granola else "vault",
        title=title,
        snippet=snippet[:InteractionConfig.SNIPPET_LENGTH] if snippet else None,
        source_link=build_obsidian_link(file_path),
        source_id=file_path,
    )

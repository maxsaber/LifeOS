"""
Commitment Tracking Service for LifeOS CRM.

Extracts and tracks commitments/promises from conversations:
- Promises I made to others ("made_by_me")
- Promises others made to me ("made_to_me")

Supports tracking status: open, completed, expired, cancelled.
"""
import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Any

from config.settings import settings

logger = logging.getLogger(__name__)


def _make_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime is timezone-aware (UTC if naive)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def get_crm_db_path() -> str:
    """Get the path to the CRM database."""
    db_dir = Path(settings.chroma_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)
    return str(db_dir / "crm.db")


@dataclass
class Commitment:
    """
    A commitment/promise extracted from a conversation.

    Tracks both direction (who promised whom) and fulfillment status.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    person_id: str = ""  # The other person involved
    direction: str = "made_by_me"  # "made_by_me" or "made_to_me"
    description: str = ""  # What was promised
    due_date: Optional[datetime] = None  # If mentioned
    status: str = "open"  # "open", "completed", "expired", "cancelled"
    confidence: float = 0.5  # 0.0-1.0
    source_interaction_id: Optional[str] = None
    source_quote: Optional[str] = None  # Verbatim quote
    source_link: Optional[str] = None  # Deep link
    extracted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            "id": self.id,
            "person_id": self.person_id,
            "direction": self.direction,
            "description": self.description,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "status": self.status,
            "confidence": self.confidence,
            "source_interaction_id": self.source_interaction_id,
            "source_quote": self.source_quote,
            "source_link": self.source_link,
            "extracted_at": self.extracted_at.isoformat() if self.extracted_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Commitment":
        """Create Commitment from dict."""
        for field in ["due_date", "extracted_at", "completed_at", "created_at"]:
            if data.get(field) and isinstance(data[field], str):
                data[field] = _make_aware(datetime.fromisoformat(data[field]))
        return cls(**data)

    @classmethod
    def from_row(cls, row: tuple) -> "Commitment":
        """Create Commitment from SQLite row.

        Column order:
        0: id, 1: person_id, 2: direction, 3: description, 4: due_date,
        5: status, 6: confidence, 7: source_interaction_id, 8: source_quote,
        9: source_link, 10: extracted_at, 11: completed_at, 12: created_at
        """
        return cls(
            id=row[0],
            person_id=row[1],
            direction=row[2] or "made_by_me",
            description=row[3] or "",
            due_date=_make_aware(datetime.fromisoformat(row[4])) if row[4] else None,
            status=row[5] or "open",
            confidence=row[6] or 0.5,
            source_interaction_id=row[7],
            source_quote=row[8],
            source_link=row[9],
            extracted_at=_make_aware(datetime.fromisoformat(row[10])) if row[10] else datetime.now(timezone.utc),
            completed_at=_make_aware(datetime.fromisoformat(row[11])) if row[11] else None,
            created_at=_make_aware(datetime.fromisoformat(row[12])) if row[12] else datetime.now(timezone.utc),
        )

    @property
    def is_overdue(self) -> bool:
        """Check if commitment is past due date and still open."""
        if self.status != "open" or not self.due_date:
            return False
        return datetime.now(timezone.utc) > self.due_date

    @property
    def days_until_due(self) -> Optional[int]:
        """Days until due date (negative if overdue)."""
        if not self.due_date:
            return None
        delta = self.due_date - datetime.now(timezone.utc)
        return delta.days


class CommitmentStore:
    """
    SQLite-backed storage for commitments.

    Provides queries for open commitments, due dates, and status updates.
    """

    def __init__(self, db_path: Optional[str] = None):
        """Initialize commitment store."""
        self.db_path = db_path or get_crm_db_path()
        self._init_db()

    def _init_db(self):
        """Create the commitments table if it doesn't exist."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS commitments (
                    id TEXT PRIMARY KEY,
                    person_id TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    description TEXT NOT NULL,
                    due_date TEXT,
                    status TEXT DEFAULT 'open',
                    confidence REAL DEFAULT 0.5,
                    source_interaction_id TEXT,
                    source_quote TEXT,
                    source_link TEXT,
                    extracted_at TEXT,
                    completed_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_commitments_person
                ON commitments(person_id)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_commitments_status
                ON commitments(status)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_commitments_due
                ON commitments(due_date)
            """)

            conn.commit()
            logger.info(f"Initialized commitments table in {self.db_path}")
        finally:
            conn.close()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        return sqlite3.connect(self.db_path)

    def get_for_person(
        self,
        person_id: str,
        status: Optional[str] = None,
        direction: Optional[str] = None,
    ) -> list[Commitment]:
        """Get commitments for a person, optionally filtered by status or direction."""
        conn = self._get_connection()
        try:
            query = "SELECT * FROM commitments WHERE person_id = ?"
            params = [person_id]

            if status:
                query += " AND status = ?"
                params.append(status)

            if direction:
                query += " AND direction = ?"
                params.append(direction)

            query += " ORDER BY due_date IS NULL, due_date ASC, created_at DESC"

            cursor = conn.execute(query, params)
            return [Commitment.from_row(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_open(self) -> list[Commitment]:
        """Get all open commitments across all people."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                SELECT * FROM commitments
                WHERE status = 'open'
                ORDER BY due_date IS NULL, due_date ASC
            """)
            return [Commitment.from_row(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_due_soon(self, days: int = 7) -> list[Commitment]:
        """Get open commitments due within N days."""
        conn = self._get_connection()
        try:
            cutoff = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
            cursor = conn.execute("""
                SELECT * FROM commitments
                WHERE status = 'open'
                AND due_date IS NOT NULL
                AND due_date <= ?
                ORDER BY due_date ASC
            """, (cutoff,))
            return [Commitment.from_row(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_overdue(self) -> list[Commitment]:
        """Get all overdue commitments."""
        conn = self._get_connection()
        try:
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.execute("""
                SELECT * FROM commitments
                WHERE status = 'open'
                AND due_date IS NOT NULL
                AND due_date < ?
                ORDER BY due_date ASC
            """, (now,))
            return [Commitment.from_row(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_by_id(self, commitment_id: str) -> Optional[Commitment]:
        """Get commitment by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM commitments WHERE id = ?", (commitment_id,)
            )
            row = cursor.fetchone()
            return Commitment.from_row(row) if row else None
        finally:
            conn.close()

    def upsert(self, commitment: Commitment) -> Commitment:
        """Insert or update a commitment."""
        conn = self._get_connection()
        try:
            conn.execute("""
                INSERT INTO commitments
                (id, person_id, direction, description, due_date, status, confidence,
                 source_interaction_id, source_quote, source_link, extracted_at,
                 completed_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    description = excluded.description,
                    due_date = excluded.due_date,
                    status = excluded.status,
                    confidence = excluded.confidence,
                    completed_at = excluded.completed_at
            """, (
                commitment.id,
                commitment.person_id,
                commitment.direction,
                commitment.description,
                commitment.due_date.isoformat() if commitment.due_date else None,
                commitment.status,
                commitment.confidence,
                commitment.source_interaction_id,
                commitment.source_quote,
                commitment.source_link,
                commitment.extracted_at.isoformat() if commitment.extracted_at else None,
                commitment.completed_at.isoformat() if commitment.completed_at else None,
                commitment.created_at.isoformat() if commitment.created_at else None,
            ))
            conn.commit()
            return commitment
        finally:
            conn.close()

    def update_status(
        self,
        commitment_id: str,
        status: str,
        completed_at: Optional[datetime] = None,
    ) -> bool:
        """Update commitment status."""
        conn = self._get_connection()
        try:
            if status == "completed" and completed_at is None:
                completed_at = datetime.now(timezone.utc)

            cursor = conn.execute("""
                UPDATE commitments
                SET status = ?, completed_at = ?
                WHERE id = ?
            """, (
                status,
                completed_at.isoformat() if completed_at else None,
                commitment_id,
            ))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def mark_overdue_expired(self) -> int:
        """Mark all overdue commitments as expired. Returns count updated."""
        conn = self._get_connection()
        try:
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.execute("""
                UPDATE commitments
                SET status = 'expired'
                WHERE status = 'open'
                AND due_date IS NOT NULL
                AND due_date < ?
            """, (now,))
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def delete(self, commitment_id: str) -> bool:
        """Delete a commitment."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM commitments WHERE id = ?", (commitment_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


class CommitmentExtractor:
    """
    Extracts commitments from interactions using Claude.

    Identifies promises/commitments in both directions:
    - "I'll send you..." -> made_by_me
    - "Can you..." -> made_to_me
    """

    # Model options
    MODEL_HAIKU = "claude-haiku-4-5"
    MODEL_SONNET = "claude-sonnet-4-5"
    DEFAULT_MODEL = MODEL_HAIKU

    # Batch settings
    MAX_INTERACTIONS_PER_BATCH = 30

    def __init__(self, store: Optional[CommitmentStore] = None):
        """Initialize extractor."""
        self.store = store or get_commitment_store()
        self._client: Any = None

    @property
    def client(self):
        """Lazy-load the Anthropic client."""
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    def extract_for_person(
        self,
        person_id: str,
        person_name: str,
        interactions: list[dict],
        model: Optional[str] = None,
    ) -> dict:
        """
        Extract commitments from a person's interactions.

        Args:
            person_id: The person's ID
            person_name: The person's name (for prompt context)
            interactions: List of interaction dicts
            model: Claude model to use

        Returns:
            dict with extraction stats
        """
        use_model = model or self.DEFAULT_MODEL

        if not interactions:
            return {"extracted": 0, "errors": 0}

        # Process in batches
        all_commitments = []
        errors = 0

        for i in range(0, len(interactions), self.MAX_INTERACTIONS_PER_BATCH):
            batch = interactions[i:i + self.MAX_INTERACTIONS_PER_BATCH]
            try:
                commitments = self._extract_batch(person_id, person_name, batch, use_model)
                all_commitments.extend(commitments)
            except Exception as e:
                logger.error(f"Commitment extraction failed for batch: {e}")
                errors += 1

        # Save commitments
        for commitment in all_commitments:
            self.store.upsert(commitment)

        return {
            "extracted": len(all_commitments),
            "errors": errors,
        }

    def _extract_batch(
        self,
        person_id: str,
        person_name: str,
        interactions: list[dict],
        model: str,
    ) -> list[Commitment]:
        """Extract commitments for a batch of interactions."""
        prompt = self._build_prompt(person_name, interactions)

        response = self.client.messages.create(
            model=model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = response.content[0].text
        return self._parse_response(response_text, person_id, interactions)

    def _build_prompt(self, person_name: str, interactions: list[dict]) -> str:
        """Build the commitment extraction prompt."""
        interactions_text = self._format_interactions(interactions)

        return f"""Extract commitments/promises from these interactions with {person_name}.

A commitment is a SPECIFIC promise to do something in the future.

LOOK FOR phrases like:
- "I'll send you...", "I will...", "Let me..." → direction: "made_by_me"
- "Can you...", "Would you...", "Please..." → direction: "made_to_me"
- "We should...", "Let's..." → mutual (pick the most relevant direction)

For each commitment, extract:
- direction: "made_by_me" (I promised them) or "made_to_me" (they promised me)
- description: What was promised (concise, actionable, e.g., "Send project proposal")
- due_date: ISO date format (YYYY-MM-DD) if mentioned, null otherwise
- confidence: 0.5-0.9 based on clarity of the commitment
- source_quote: The exact quote containing the commitment
- interaction_id: The ID from the interaction

RULES:
1. Only extract CLEAR, SPECIFIC commitments with actionable descriptions
2. Skip vague intentions like "we should catch up sometime"
3. Skip completed actions mentioned in past tense
4. Skip routine/recurring items like "see you tomorrow" unless it's a specific promise
5. The description should be 3-10 words, action-focused

Return ONLY valid JSON (no markdown, no explanation):
[
  {{
    "direction": "made_by_me",
    "description": "Send project proposal",
    "due_date": "2026-02-05",
    "confidence": 0.8,
    "source_quote": "I'll send you the proposal by Wednesday",
    "interaction_id": "abc123"
  }}
]

Return empty array [] if no clear commitments found.

Interactions:
{interactions_text}"""

    def _format_interactions(self, interactions: list[dict]) -> str:
        """Format interactions for the prompt."""
        lines = []
        for i in interactions:
            int_id = i.get("id", "unknown")
            source = i.get("source_type", "unknown")
            title = i.get("title", "")
            snippet = i.get("snippet", "")[:400] if i.get("snippet") else ""
            timestamp = i.get("timestamp", "")

            line = f"ID: {int_id}\n[{source}] {timestamp}\nTitle: {title}"
            if snippet:
                line += f"\nContent: {snippet}"
            lines.append(line)

        return "\n\n---\n\n".join(lines)

    def _parse_response(
        self,
        response_text: str,
        person_id: str,
        interactions: list[dict],
    ) -> list[Commitment]:
        """Parse Claude response into Commitment objects."""
        try:
            # Handle markdown code blocks
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()

            data = json.loads(response_text)

            # Build lookup for interactions
            interaction_lookup = {i.get("id"): i for i in interactions}

            commitments = []
            now = datetime.now(timezone.utc)

            for item in data:
                direction = item.get("direction", "made_by_me")
                if direction not in ("made_by_me", "made_to_me"):
                    direction = "made_by_me"

                description = item.get("description", "")
                if not description or len(description) < 3:
                    continue

                # Parse due_date
                due_date = None
                if item.get("due_date"):
                    try:
                        due_date = datetime.fromisoformat(item["due_date"])
                        due_date = _make_aware(due_date)
                    except ValueError:
                        pass

                confidence = float(item.get("confidence", 0.5))
                confidence = max(0.0, min(1.0, confidence))

                int_id = item.get("interaction_id", "")
                source_link = interaction_lookup.get(int_id, {}).get("source_link")

                commitment = Commitment(
                    person_id=person_id,
                    direction=direction,
                    description=description,
                    due_date=due_date,
                    status="open",
                    confidence=confidence,
                    source_interaction_id=int_id,
                    source_quote=item.get("source_quote"),
                    source_link=source_link,
                    extracted_at=now,
                )
                commitments.append(commitment)

            return commitments

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse commitment JSON: {e}")
            logger.debug(f"Response was: {response_text[:500]}")
            return []
        except Exception as e:
            logger.error(f"Error parsing commitment response: {e}")
            return []


# Singleton instances
_commitment_store: Optional[CommitmentStore] = None
_commitment_extractor: Optional[CommitmentExtractor] = None


def get_commitment_store(db_path: Optional[str] = None) -> CommitmentStore:
    """Get or create the singleton CommitmentStore."""
    global _commitment_store
    if _commitment_store is None:
        _commitment_store = CommitmentStore(db_path)
    return _commitment_store


def get_commitment_extractor() -> CommitmentExtractor:
    """Get or create the singleton CommitmentExtractor."""
    global _commitment_extractor
    if _commitment_extractor is None:
        _commitment_extractor = CommitmentExtractor()
    return _commitment_extractor

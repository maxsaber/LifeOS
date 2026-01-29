"""
Person Facts Service for LifeOS CRM.

Extracts and stores interesting facts about contacts using LLM analysis.
Facts are stored in SQLite and can be displayed in the CRM UI.
"""
import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

from config.settings import settings

logger = logging.getLogger(__name__)

# Fact categories with their icons
FACT_CATEGORIES = {
    "family": "👨‍👩‍👧",
    "preferences": "⚙️",
    "background": "🏠",
    "interests": "🎯",
    "dates": "📅",
    "work": "💼",
    "topics": "💬",
    "travel": "✈️",
}


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
class PersonFact:
    """
    A single fact about a person.

    Facts are extracted from interactions and stored for quick reference.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    person_id: str = ""
    category: str = ""  # family, preferences, background, interests, dates, work, topics, travel
    key: str = ""  # e.g., "spouse_name", "birthday", "hometown"
    value: str = ""  # The actual fact value
    confidence: float = 0.5  # 0.0-1.0
    source_interaction_id: Optional[str] = None  # For attribution
    extracted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confirmed_by_user: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            "id": self.id,
            "person_id": self.person_id,
            "category": self.category,
            "key": self.key,
            "value": self.value,
            "confidence": self.confidence,
            "source_interaction_id": self.source_interaction_id,
            "extracted_at": self.extracted_at.isoformat() if self.extracted_at else None,
            "confirmed_by_user": self.confirmed_by_user,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "category_icon": FACT_CATEGORIES.get(self.category, "📄"),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PersonFact":
        """Create PersonFact from dict."""
        # Handle datetime parsing
        if data.get("extracted_at") and isinstance(data["extracted_at"], str):
            data["extracted_at"] = _make_aware(datetime.fromisoformat(data["extracted_at"]))
        if data.get("created_at") and isinstance(data["created_at"], str):
            data["created_at"] = _make_aware(datetime.fromisoformat(data["created_at"]))
        # Remove icon field if present (it's computed)
        data.pop("category_icon", None)
        return cls(**data)

    @classmethod
    def from_row(cls, row: tuple) -> "PersonFact":
        """Create PersonFact from SQLite row."""
        return cls(
            id=row[0],
            person_id=row[1],
            category=row[2],
            key=row[3],
            value=row[4],
            confidence=row[5] or 0.5,
            source_interaction_id=row[6],
            extracted_at=_make_aware(datetime.fromisoformat(row[7])) if row[7] else datetime.now(timezone.utc),
            confirmed_by_user=bool(row[8]),
            created_at=_make_aware(datetime.fromisoformat(row[9])) if row[9] else datetime.now(timezone.utc),
        )


class PersonFactStore:
    """
    SQLite-backed storage for person facts.
    """

    def __init__(self, db_path: Optional[str] = None):
        """Initialize fact store."""
        self.db_path = db_path or get_crm_db_path()
        self._init_db()

    def _init_db(self):
        """Create the person_facts table if it doesn't exist."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS person_facts (
                    id TEXT PRIMARY KEY,
                    person_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    confidence REAL DEFAULT 0.5,
                    source_interaction_id TEXT,
                    extracted_at TEXT,
                    confirmed_by_user INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(person_id, category, key)
                )
            """)

            # Index for efficient person queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_person_facts_person
                ON person_facts(person_id)
            """)

            # Index for category queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_person_facts_category
                ON person_facts(category)
            """)

            conn.commit()
            logger.info(f"Initialized person_facts table in {self.db_path}")
        finally:
            conn.close()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        return sqlite3.connect(self.db_path)

    def add(self, fact: PersonFact) -> PersonFact:
        """Add a new fact."""
        conn = self._get_connection()
        try:
            conn.execute("""
                INSERT INTO person_facts
                (id, person_id, category, key, value, confidence, source_interaction_id,
                 extracted_at, confirmed_by_user, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                fact.id,
                fact.person_id,
                fact.category,
                fact.key,
                fact.value,
                fact.confidence,
                fact.source_interaction_id,
                fact.extracted_at.isoformat() if fact.extracted_at else None,
                1 if fact.confirmed_by_user else 0,
                fact.created_at.isoformat() if fact.created_at else None,
            ))
            conn.commit()
            return fact
        finally:
            conn.close()

    def upsert(self, fact: PersonFact) -> PersonFact:
        """
        Insert or update a fact.

        If a fact with the same (person_id, category, key) exists:
        - Update if new confidence is higher or fact is user-confirmed
        - Otherwise keep existing
        """
        conn = self._get_connection()
        try:
            # Check for existing fact
            cursor = conn.execute("""
                SELECT id, confidence, confirmed_by_user FROM person_facts
                WHERE person_id = ? AND category = ? AND key = ?
            """, (fact.person_id, fact.category, fact.key))
            existing = cursor.fetchone()

            if existing:
                existing_id, existing_conf, existing_confirmed = existing
                # Only update if: new confidence is higher OR new fact is confirmed
                # AND existing is not already confirmed (user confirmation is sticky)
                if existing_confirmed:
                    logger.debug(f"Skipping update for confirmed fact: {fact.key}")
                    fact.id = existing_id
                    return fact

                if fact.confidence >= existing_conf or fact.confirmed_by_user:
                    conn.execute("""
                        UPDATE person_facts
                        SET value = ?, confidence = ?, source_interaction_id = ?,
                            extracted_at = ?, confirmed_by_user = ?
                        WHERE id = ?
                    """, (
                        fact.value,
                        fact.confidence,
                        fact.source_interaction_id,
                        fact.extracted_at.isoformat() if fact.extracted_at else None,
                        1 if fact.confirmed_by_user else 0,
                        existing_id,
                    ))
                    fact.id = existing_id
                    conn.commit()
                else:
                    logger.debug(f"Skipping lower-confidence fact: {fact.key}")
                    fact.id = existing_id
            else:
                # Insert new fact
                conn.execute("""
                    INSERT INTO person_facts
                    (id, person_id, category, key, value, confidence, source_interaction_id,
                     extracted_at, confirmed_by_user, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    fact.id,
                    fact.person_id,
                    fact.category,
                    fact.key,
                    fact.value,
                    fact.confidence,
                    fact.source_interaction_id,
                    fact.extracted_at.isoformat() if fact.extracted_at else None,
                    1 if fact.confirmed_by_user else 0,
                    fact.created_at.isoformat() if fact.created_at else None,
                ))
                conn.commit()

            return fact
        finally:
            conn.close()

    def get_by_id(self, fact_id: str) -> Optional[PersonFact]:
        """Get fact by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM person_facts WHERE id = ?", (fact_id,)
            )
            row = cursor.fetchone()
            if row:
                return PersonFact.from_row(row)
            return None
        finally:
            conn.close()

    def get_for_person(self, person_id: str) -> list[PersonFact]:
        """Get all facts for a person, grouped by category."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                SELECT * FROM person_facts
                WHERE person_id = ?
                ORDER BY category, key
            """, (person_id,))
            return [PersonFact.from_row(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def update(self, fact: PersonFact) -> PersonFact:
        """Update an existing fact."""
        conn = self._get_connection()
        try:
            conn.execute("""
                UPDATE person_facts
                SET category = ?, key = ?, value = ?, confidence = ?,
                    source_interaction_id = ?, confirmed_by_user = ?
                WHERE id = ?
            """, (
                fact.category,
                fact.key,
                fact.value,
                fact.confidence,
                fact.source_interaction_id,
                1 if fact.confirmed_by_user else 0,
                fact.id,
            ))
            conn.commit()
            return fact
        finally:
            conn.close()

    def confirm(self, fact_id: str) -> bool:
        """Mark a fact as confirmed by user."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                UPDATE person_facts
                SET confirmed_by_user = 1
                WHERE id = ?
            """, (fact_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete(self, fact_id: str) -> bool:
        """Delete a fact by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM person_facts WHERE id = ?", (fact_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_for_person(self, person_id: str) -> int:
        """Delete all facts for a person."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM person_facts WHERE person_id = ?", (person_id,)
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()


class PersonFactExtractor:
    """
    Extracts facts from interactions using LLM analysis.
    """

    def __init__(self, fact_store: Optional[PersonFactStore] = None):
        """Initialize extractor."""
        self.fact_store = fact_store or get_person_fact_store()
        self._client: Any = None

    @property
    def client(self):
        """Lazy-load the Anthropic client."""
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    def extract_facts(self, person_id: str, person_name: str, interactions: list) -> list[PersonFact]:
        """
        Extract facts from a person's interactions.

        Args:
            person_id: The person's ID
            person_name: The person's name
            interactions: List of interaction records (with title, snippet, source_type, id)

        Returns:
            List of extracted PersonFact objects
        """
        if not interactions:
            logger.info(f"No interactions to extract facts from for {person_name}")
            return []

        # Build interaction text for prompt
        interaction_text = self._format_interactions(interactions)

        # Build the extraction prompt
        prompt = self._build_extraction_prompt(person_name, interaction_text)

        # Call LLM
        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = response.content[0].text
            logger.debug(f"LLM response for {person_name}: {response_text[:500]}...")

            # Parse response
            facts = self._parse_facts_response(response_text, person_id, interactions)

            # Save facts to store
            saved_facts = []
            for fact in facts:
                saved_fact = self.fact_store.upsert(fact)
                saved_facts.append(saved_fact)

            logger.info(f"Extracted {len(saved_facts)} facts for {person_name}")
            return saved_facts

        except Exception as e:
            logger.error(f"Failed to extract facts for {person_name}: {e}")
            raise

    def _format_interactions(self, interactions: list) -> str:
        """Format interactions for the prompt."""
        lines = []
        for i, interaction in enumerate(interactions[:50], 1):  # Limit to 50
            source_type = interaction.get("source_type", "unknown")
            title = interaction.get("title", "Untitled")
            snippet = interaction.get("snippet", "")
            timestamp = interaction.get("timestamp", "")

            line = f"[{i}] [{source_type}] {timestamp}: {title}"
            if snippet:
                line += f"\n    {snippet[:200]}"
            lines.append(line)

        return "\n\n".join(lines)

    def _build_extraction_prompt(self, person_name: str, interaction_text: str) -> str:
        """Build the LLM prompt for fact extraction."""
        return f"""Analyze these interactions about {person_name} and extract personal facts.

Return ONLY valid JSON with this structure (no markdown, no explanation):
{{
  "facts": [
    {{"category": "family", "key": "spouse_name", "value": "Sarah", "confidence": 0.9}},
    {{"category": "interests", "key": "hobby", "value": "hiking", "confidence": 0.7}}
  ]
}}

Categories and example keys:
- family: spouse_name, children_count, child_names, parent_names, sibling_names
- preferences: food_preference, communication_style, meeting_preference
- background: hometown, alma_mater, previous_companies, nationality
- interests: hobby, sport, music_taste, book_genre, favorite_team
- dates: birthday, anniversary, started_job
- work: current_role, expertise, projects, team_size, reports_to
- topics: frequent_discussion_topics, concerns, goals
- travel: visited_countries, planned_trips, favorite_destination

Rules:
- Only include facts you're confident about based on the interactions
- Set confidence between 0.5 (inferred) and 1.0 (explicitly stated)
- Use lowercase snake_case for keys
- Values should be concise (1-5 words when possible)
- Don't make up facts - only extract what's clearly mentioned or strongly implied

Interactions:
{interaction_text}"""

    def _parse_facts_response(
        self, response_text: str, person_id: str, interactions: list
    ) -> list[PersonFact]:
        """Parse the LLM response into PersonFact objects."""
        facts = []

        # Try to extract JSON from response
        try:
            # Handle potential markdown code blocks
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()

            data = json.loads(response_text)

            if "facts" not in data:
                logger.warning("No 'facts' key in response")
                return facts

            # Get first interaction ID for attribution (simplified)
            source_id = interactions[0].get("id") if interactions else None

            for fact_data in data["facts"]:
                category = fact_data.get("category", "").lower()
                key = fact_data.get("key", "")
                value = fact_data.get("value", "")
                confidence = float(fact_data.get("confidence", 0.5))

                # Validate category
                if category not in FACT_CATEGORIES:
                    logger.warning(f"Unknown category: {category}")
                    continue

                # Validate required fields
                if not key or not value:
                    continue

                # Clamp confidence
                confidence = max(0.0, min(1.0, confidence))

                fact = PersonFact(
                    person_id=person_id,
                    category=category,
                    key=key,
                    value=str(value),
                    confidence=confidence,
                    source_interaction_id=source_id,
                )
                facts.append(fact)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.debug(f"Response was: {response_text[:500]}")
        except Exception as e:
            logger.error(f"Error parsing facts: {e}")

        return facts


# Singleton instances
_fact_store: Optional[PersonFactStore] = None
_fact_extractor: Optional[PersonFactExtractor] = None


def get_person_fact_store(db_path: Optional[str] = None) -> PersonFactStore:
    """Get or create the singleton PersonFactStore."""
    global _fact_store
    if _fact_store is None:
        _fact_store = PersonFactStore(db_path)
    return _fact_store


def get_person_fact_extractor() -> PersonFactExtractor:
    """Get or create the singleton PersonFactExtractor."""
    global _fact_extractor
    if _fact_extractor is None:
        _fact_extractor = PersonFactExtractor()
    return _fact_extractor

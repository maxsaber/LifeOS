"""
Person Facts Service for LifeOS CRM.

Extracts and stores interesting facts about contacts using a multi-stage LLM pipeline.
Facts are stored in SQLite and can be displayed in the CRM UI.

Pipeline Architecture (v2):
- Stage 1: Filter interactions using local Ollama (fast, cheap)
- Stage 2: Extract candidate facts using Claude (accurate, expensive)
- Stage 3: Validate facts and assign confidence using Ollama (local)

Key improvements over v1:
- Focus on MEMORABLE facts (pet names, hobbies) not obvious ones (job titles)
- Calibrated confidence based on evidence strength, not LLM self-assessment
- Message context windows for better extraction from conversations
- Significant cost reduction via local Ollama for filtering/validation
"""
import asyncio
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
    "summary": "📊",  # Relationship summaries
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
    Each fact must have a source quote as evidence.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    person_id: str = ""
    category: str = ""  # family, preferences, background, interests, dates, work, topics, travel, summary
    key: str = ""  # e.g., "spouse_name", "birthday", "hometown"
    value: str = ""  # The actual fact value
    confidence: float = 0.5  # 0.0-1.0
    source_interaction_id: Optional[str] = None  # For attribution
    source_quote: Optional[str] = None  # Verbatim quote proving this fact
    source_link: Optional[str] = None  # Deep link to source (Gmail, Calendar, Obsidian)
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
            "source_quote": self.source_quote,
            "source_link": self.source_link,
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
        """Create PersonFact from SQLite row.

        Column order (after migration):
        0: id, 1: person_id, 2: category, 3: key, 4: value, 5: confidence,
        6: source_interaction_id, 7: extracted_at, 8: confirmed_by_user,
        9: created_at, 10: source_quote, 11: source_link
        """
        # Handle both old schema (10 columns) and new schema (12 columns)
        source_quote = row[10] if len(row) > 10 else None
        source_link = row[11] if len(row) > 11 else None

        return cls(
            id=row[0],
            person_id=row[1],
            category=row[2],
            key=row[3],
            value=row[4],
            confidence=row[5] or 0.5,
            source_interaction_id=row[6],
            source_quote=source_quote,
            source_link=source_link,
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
                    source_quote TEXT,
                    source_link TEXT,
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

            # Migrate existing table: add source_quote and source_link columns if missing
            try:
                conn.execute("ALTER TABLE person_facts ADD COLUMN source_quote TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

            try:
                conn.execute("ALTER TABLE person_facts ADD COLUMN source_link TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

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
                 source_quote, source_link, extracted_at, confirmed_by_user, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                fact.id,
                fact.person_id,
                fact.category,
                fact.key,
                fact.value,
                fact.confidence,
                fact.source_interaction_id,
                fact.source_quote,
                fact.source_link,
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
                            source_quote = ?, source_link = ?,
                            extracted_at = ?, confirmed_by_user = ?
                        WHERE id = ?
                    """, (
                        fact.value,
                        fact.confidence,
                        fact.source_interaction_id,
                        fact.source_quote,
                        fact.source_link,
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
                     source_quote, source_link, extracted_at, confirmed_by_user, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    fact.id,
                    fact.person_id,
                    fact.category,
                    fact.key,
                    fact.value,
                    fact.confidence,
                    fact.source_interaction_id,
                    fact.source_quote,
                    fact.source_link,
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
    Extracts facts from interactions using a multi-stage LLM pipeline.

    Pipeline v2:
    - Stage 1: Filter to high-signal interactions (Ollama - local, fast)
    - Stage 2: Extract candidate facts (Claude - accurate)
    - Stage 3: Validate and assign calibrated confidence (Ollama - local)

    Key improvements:
    - Focus on MEMORABLE facts, not obvious professional info
    - Calibrated confidence based on evidence strength
    - Message context windows for conversation-based sources
    - 70%+ cost reduction via local Ollama for filtering/validation
    """

    # Sampling configuration
    MAX_INTERACTIONS_PER_BATCH = 100
    RECENT_SAMPLE_SIZE = 100
    RANDOM_SAMPLE_SIZE = 100
    PRIORITY_SOURCE_TYPES = {"calendar", "vault", "granola"}  # Always include these

    # Confidence calibration (based on evidence strength, NOT LLM self-assessment)
    CONFIDENCE_MAP = {
        "single_mention": (0.3, 0.5),      # One casual reference
        "multiple_mentions": (0.5, 0.7),   # Referenced several times
        "self_identification": (0.7, 0.85), # They explicitly stated this
        "defining_trait": (0.85, 0.95),    # Central to identity, repeated
    }

    def __init__(self, fact_store: Optional[PersonFactStore] = None):
        """Initialize extractor."""
        self.fact_store = fact_store or get_person_fact_store()
        self._client: Any = None
        self._ollama_client: Any = None

    @property
    def client(self):
        """Lazy-load the Anthropic client."""
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    @property
    def ollama_client(self):
        """Lazy-load the Ollama client."""
        if self._ollama_client is None:
            from api.services.ollama_client import OllamaClient
            self._ollama_client = OllamaClient()
        return self._ollama_client

    def _ollama_available(self) -> bool:
        """Check if Ollama is available for local processing."""
        try:
            return self.ollama_client.is_available()
        except Exception:
            return False

    def extract_facts(self, person_id: str, person_name: str, interactions: list) -> list[PersonFact]:
        """
        Extract facts from a person's interactions using multi-stage pipeline.

        Pipeline v2:
        1. Enrich message-based interactions with conversation context
        2. Stage 1: Filter to high-signal interactions (Ollama - local)
        3. Stage 2: Extract candidate facts (Claude - accurate)
        4. Stage 3: Validate facts and assign calibrated confidence (Ollama)

        Args:
            person_id: The person's ID
            person_name: The person's name
            interactions: List of interaction records

        Returns:
            List of extracted and validated PersonFact objects
        """
        if not interactions:
            logger.info(f"No interactions to extract facts from for {person_name}")
            return []

        # Strategic sampling for large interaction sets
        sampled_interactions = self._sample_interactions(interactions)
        logger.info(
            f"Sampling {len(sampled_interactions)} from {len(interactions)} interactions for {person_name}"
        )

        # Build interaction lookup for source attribution
        interaction_lookup = {i.get("id"): i for i in sampled_interactions if i.get("id")}

        # Step 1: Enrich with conversation context (for message-based sources)
        enriched_interactions = self._enrich_with_context(sampled_interactions)

        # Step 2: Stage 1 - Filter to high-signal interactions (Ollama)
        use_ollama = self._ollama_available()
        if use_ollama:
            filtered_interactions = asyncio.get_event_loop().run_until_complete(
                self._stage1_filter_interactions(person_name, enriched_interactions)
            )
            logger.info(
                f"Stage 1: {len(filtered_interactions)}/{len(enriched_interactions)} "
                f"interactions flagged as high-signal for {person_name}"
            )
        else:
            logger.warning("Ollama unavailable, skipping Stage 1 filtering")
            filtered_interactions = enriched_interactions

        if not filtered_interactions:
            logger.info(f"No high-signal interactions found for {person_name}")
            return []

        # Step 3: Stage 2 - Extract candidate facts (Claude)
        candidate_facts = self._stage2_extract_facts(person_name, filtered_interactions, interaction_lookup)
        logger.info(f"Stage 2: {len(candidate_facts)} candidate facts extracted for {person_name}")

        # Step 4: Stage 3 - Validate and assign confidence (Ollama)
        if use_ollama and candidate_facts:
            validated_facts = asyncio.get_event_loop().run_until_complete(
                self._stage3_validate_facts(person_id, person_name, candidate_facts, filtered_interactions)
            )
            logger.info(f"Stage 3: {len(validated_facts)} facts validated for {person_name}")
        else:
            # Fallback: use candidate facts directly with moderate confidence
            validated_facts = []
            for cf in candidate_facts:
                fact = PersonFact(
                    person_id=person_id,
                    category=cf.get("category", ""),
                    key=cf.get("key", ""),
                    value=str(cf.get("value", "")),
                    confidence=min(0.6, cf.get("confidence", 0.5)),  # Cap at 0.6 without validation
                    source_interaction_id=cf.get("source_id"),
                    source_quote=cf.get("quote"),
                    source_link=interaction_lookup.get(cf.get("source_id"), {}).get("source_link"),
                )
                validated_facts.append(fact)

        # Step 5: Generate relationship summaries
        if len(interactions) >= 10:
            try:
                summaries = self._generate_relationship_summaries(person_id, person_name, sampled_interactions)
                # Lower confidence for summaries (0.6-0.7) since they're synthesized
                for s in summaries:
                    s.confidence = min(s.confidence, 0.7)
                validated_facts.extend(summaries)
            except Exception as e:
                logger.error(f"Failed to generate summaries for {person_name}: {e}")

        # Step 6: Deduplicate and save facts
        saved_facts = []
        seen_keys = set()
        for fact in validated_facts:
            key = (fact.category, fact.key)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            saved_fact = self.fact_store.upsert(fact)
            saved_facts.append(saved_fact)

        logger.info(f"Extracted {len(saved_facts)} facts for {person_name}")
        return saved_facts

    def _enrich_with_context(self, interactions: list) -> list:
        """
        Enrich message-based interactions with conversation context.

        For iMessage, WhatsApp, and Slack interactions, fetches surrounding
        messages to provide better context for fact extraction.
        """
        try:
            from api.services.interaction_store import get_interaction_store
            store = get_interaction_store()
            return store.enrich_interactions_with_context(interactions)
        except Exception as e:
            logger.warning(f"Failed to enrich interactions with context: {e}")
            return interactions

    async def _stage1_filter_interactions(
        self,
        person_name: str,
        interactions: list[dict]
    ) -> list[dict]:
        """
        Stage 1: Filter to high-signal interactions using local Ollama.

        Identifies interactions that contain MEMORABLE personal facts worth
        extracting, filtering out logistics, scheduling, and routine messages.

        Args:
            person_name: The person's name
            interactions: All interactions to filter

        Returns:
            Subset of interactions flagged as containing memorable facts
        """
        if not interactions:
            return []

        # Process in batches of 25 for Ollama
        BATCH_SIZE = 25
        flagged_ids = set()

        for i in range(0, len(interactions), BATCH_SIZE):
            batch = interactions[i:i + BATCH_SIZE]

            # Format batch for filtering
            batch_text = self._format_interactions_for_filtering(batch)

            prompt = f"""Review these interactions with {person_name} and identify which ones
contain MEMORABLE personal details worth extracting.

LOOK FOR (high value for recall):
- Pet names ("my dog Max", "our cat Luna")
- Hobby specifics ("I've been learning pottery")
- Family member names ("my sister Emma", "my son Jake")
- Personal preferences ("I can't stand cilantro", "I'm a morning person")
- Personal anecdotes ("We went to Costa Rica last year")
- Health/medical mentions ("I have my infusion next week")
- Interests and passions ("I'm obsessed with Formula 1")

IGNORE (low value, findable elsewhere):
- Job titles and company names (LinkedIn has this)
- Meeting logistics ("Let's meet at 3pm")
- Routine scheduling ("See you next week")
- Generic pleasantries

For each interaction, respond ONLY with the IDs that contain memorable facts.
Return a JSON object with a single "ids" array.

Interactions:
{batch_text}

Return JSON:
{{"ids": ["id1", "id2", ...]}}
"""

            try:
                response = await self.ollama_client.generate_json(
                    prompt=prompt,
                    temperature=0.2,
                    max_tokens=1024,
                )
                ids = response.get("ids", [])
                flagged_ids.update(ids)
            except Exception as e:
                logger.warning(f"Stage 1 Ollama batch failed: {e}, including all interactions from batch")
                # Fallback: include all interactions from this batch
                for interaction in batch:
                    if interaction.get("id"):
                        flagged_ids.add(interaction["id"])

        # Return interactions that were flagged
        return [i for i in interactions if i.get("id") in flagged_ids]

    def _format_interactions_for_filtering(self, interactions: list) -> str:
        """Format interactions compactly for Stage 1 filtering."""
        lines = []
        for interaction in interactions:
            interaction_id = interaction.get("id", "unknown")
            source_type = interaction.get("source_type", "")
            title = interaction.get("title", "")
            snippet = interaction.get("snippet", "")[:300] if interaction.get("snippet") else ""
            context = interaction.get("context", "")[:200] if interaction.get("context") else ""

            line = f"[{interaction_id}] ({source_type}) {title}"
            if snippet:
                line += f"\n  {snippet}"
            if context:
                line += f"\n  Context: {context}"
            lines.append(line)

        return "\n\n".join(lines)

    def _stage2_extract_facts(
        self,
        person_name: str,
        interactions: list[dict],
        interaction_lookup: dict
    ) -> list[dict]:
        """
        Stage 2: Extract candidate facts using Claude.

        Focuses on MEMORABLE personal details that help with recall,
        not obvious professional information.

        Args:
            person_name: The person's name
            interactions: Filtered high-signal interactions
            interaction_lookup: Dict mapping interaction IDs to full records

        Returns:
            List of candidate fact dicts (without final confidence scores)
        """
        all_candidates = []
        batches = self._create_batches(interactions, self.MAX_INTERACTIONS_PER_BATCH)

        for batch_idx, batch in enumerate(batches):
            interaction_text = self._format_interactions(batch)
            prompt = self._build_stage2_extraction_prompt(person_name, interaction_text)

            try:
                response = self.client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=4096,
                    messages=[{"role": "user", "content": prompt}]
                )

                response_text = response.content[0].text

                # Parse JSON response
                candidates = self._parse_stage2_response(response_text)
                all_candidates.extend(candidates)

            except Exception as e:
                logger.error(f"Stage 2 extraction failed for batch {batch_idx + 1}: {e}")

        return all_candidates

    def _build_stage2_extraction_prompt(self, person_name: str, interaction_text: str) -> str:
        """Build the Stage 2 extraction prompt focused on memorable facts."""
        return f"""Extract MEMORABLE personal details about {person_name} from these interactions.

YOU ARE A RECALL ASSISTANT, not a biography builder. Extract facts that help remember
personal details about {person_name} - things you couldn't find on LinkedIn or in a quick search.

PRIORITIZE (high value for recall):
- Pet names ("my dog Max", "our cat Luna")
- Hobby specifics ("I've been learning pottery", "training for a triathlon")
- Family member names ("my sister Emma", "my son Jake")
- Personal preferences ("I can't stand cilantro", "I'm a morning person")
- Personal anecdotes ("We went to Costa Rica last year")
- Health/medical mentions ("I have my infusion next week", "my allergies")
- Interests and passions ("I'm obsessed with Formula 1")

SKIP (low value, findable elsewhere):
- Current job title (LinkedIn has this)
- Company name (LinkedIn has this)
- Generic professional info
- Meeting logistics
- Routine scheduling details

The user can find "{person_name} works at {{company}}" on LinkedIn.
They CANNOT find "{person_name}'s dog is named Max" anywhere else.

CRITICAL - ENTITY ATTRIBUTION:
These are conversations BETWEEN the user (Nathan) and {person_name}.
- If Nathan says "my daughter Malea" → This is Nathan's family, NOT {person_name}'s. DO NOT extract.
- If {person_name} says "my daughter Emma" → This IS {person_name}'s daughter. EXTRACT IT.
- If they discuss a third person "Sarah got a new job" → About Sarah, not {person_name}. DO NOT extract.

Return ONLY valid JSON with this structure (no markdown, no explanation):
{{
  "facts": [
    {{
      "category": "family",
      "key": "dog_name",
      "value": "Max",
      "quote": "I need to take Max to the vet tomorrow",
      "source_id": "abc123"
    }}
  ]
}}

DO NOT include confidence scores - those will be assessed separately in Stage 3.

Categories: family, preferences, background, interests, dates, work, topics, travel

Interactions:
{interaction_text}"""

    def _parse_stage2_response(self, response_text: str) -> list[dict]:
        """Parse Stage 2 Claude response into candidate fact dicts."""
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
            return data.get("facts", [])

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Stage 2 JSON: {e}")
            return []

    async def _stage3_validate_facts(
        self,
        person_id: str,
        person_name: str,
        candidate_facts: list[dict],
        interactions: list[dict]
    ) -> list[PersonFact]:
        """
        Stage 3: Validate facts and assign calibrated confidence using Ollama.

        For each candidate fact:
        1. Does the quote support this fact?
        2. Is this about {person_name} (not Nathan or a third party)?
        3. Evidence strength → calibrated confidence score

        Args:
            person_id: The person's ID
            person_name: The person's name
            candidate_facts: Facts from Stage 2
            interactions: Original interactions for context

        Returns:
            List of validated PersonFact objects with calibrated confidence
        """
        if not candidate_facts:
            return []

        # Build interaction lookup
        interaction_lookup = {i.get("id"): i for i in interactions if i.get("id")}

        # Process in batches of 10 facts
        BATCH_SIZE = 10
        validated_facts = []

        for i in range(0, len(candidate_facts), BATCH_SIZE):
            batch = candidate_facts[i:i + BATCH_SIZE]
            facts_json = json.dumps(batch, indent=2)

            # Build context from relevant interactions
            relevant_ids = {f.get("source_id") for f in batch if f.get("source_id")}
            context_parts = []
            for int_id in relevant_ids:
                if int_id in interaction_lookup:
                    interaction = interaction_lookup[int_id]
                    context_parts.append(
                        f"[{int_id}] {interaction.get('title', '')}: {interaction.get('snippet', '')[:300]}"
                    )
            context = "\n".join(context_parts)

            prompt = f"""Validate these candidate facts about {person_name}.

For each fact, assess:

1. QUOTE_SUPPORTS: Does the quote directly support this fact?
   - yes: Quote clearly states this fact
   - partial: Quote implies but doesn't directly state
   - no: Quote doesn't support this fact

2. ATTRIBUTION: Who does this fact apply to?
   - target: This is about {person_name}
   - nathan: This is about Nathan (the user), not {person_name}
   - third_party: This is about someone else mentioned in conversation
   - unclear: Can't determine who this applies to

3. EVIDENCE_STRENGTH (determines confidence):
   - single_mention: One casual reference → confidence 0.3-0.5
   - multiple_mentions: Referenced several times → confidence 0.5-0.7
   - self_identification: They explicitly stated this about themselves → confidence 0.7-0.85
   - defining_trait: Central to their identity, repeated emphasis → confidence 0.85-0.95

CRITICAL: If ATTRIBUTION is not "target", REJECT the fact.

Return JSON:
{{
  "validations": [
    {{
      "fact_index": 0,
      "quote_supports": "yes",
      "attribution": "target",
      "evidence_strength": "self_identification",
      "confidence": 0.8,
      "reject": false,
      "reject_reason": null
    }}
  ]
}}

Candidate facts:
{facts_json}

Original context:
{context}"""

            try:
                response = await self.ollama_client.generate_json(
                    prompt=prompt,
                    temperature=0.1,
                    max_tokens=2048,
                )

                validations = response.get("validations", [])

                for validation in validations:
                    fact_index = validation.get("fact_index", -1)
                    if fact_index < 0 or fact_index >= len(batch):
                        continue

                    if validation.get("reject", False):
                        logger.debug(
                            f"Rejected fact: {batch[fact_index].get('key')} - "
                            f"{validation.get('reject_reason', 'no reason')}"
                        )
                        continue

                    candidate = batch[fact_index]

                    # Get calibrated confidence from evidence strength
                    evidence = validation.get("evidence_strength", "single_mention")
                    conf_range = self.CONFIDENCE_MAP.get(evidence, (0.3, 0.5))
                    confidence = validation.get("confidence", conf_range[0])
                    # Clamp to the appropriate range
                    confidence = max(conf_range[0], min(conf_range[1], confidence))

                    # Build the fact
                    source_id = candidate.get("source_id")
                    source_link = None
                    if source_id and source_id in interaction_lookup:
                        source_link = interaction_lookup[source_id].get("source_link")

                    fact = PersonFact(
                        person_id=person_id,
                        category=candidate.get("category", ""),
                        key=candidate.get("key", ""),
                        value=str(candidate.get("value", "")),
                        confidence=confidence,
                        source_interaction_id=source_id,
                        source_quote=candidate.get("quote"),
                        source_link=source_link,
                    )
                    validated_facts.append(fact)

            except Exception as e:
                logger.error(f"Stage 3 validation batch failed: {e}")
                # Fallback: include facts with reduced confidence
                for candidate in batch:
                    source_id = candidate.get("source_id")
                    source_link = None
                    if source_id and source_id in interaction_lookup:
                        source_link = interaction_lookup[source_id].get("source_link")

                    fact = PersonFact(
                        person_id=person_id,
                        category=candidate.get("category", ""),
                        key=candidate.get("key", ""),
                        value=str(candidate.get("value", "")),
                        confidence=0.4,  # Reduced confidence for unvalidated
                        source_interaction_id=source_id,
                        source_quote=candidate.get("quote"),
                        source_link=source_link,
                    )
                    validated_facts.append(fact)

        return validated_facts

    def _sample_interactions(self, interactions: list) -> list:
        """
        Strategic sampling of interactions for analysis.

        Ensures we cover:
        - Recent activity (last 100)
        - Historical breadth (random 100 from older)
        - All high-value sources (calendar, vault, granola)
        """
        import random

        if len(interactions) <= self.MAX_INTERACTIONS_PER_BATCH * 2:
            return interactions

        # Sort by timestamp (most recent first)
        sorted_interactions = sorted(
            interactions,
            key=lambda x: x.get("timestamp", ""),
            reverse=True
        )

        sampled = []
        sampled_ids = set()

        # 1. Add all priority source types (calendar events, vault notes)
        for interaction in sorted_interactions:
            if interaction.get("source_type") in self.PRIORITY_SOURCE_TYPES:
                if interaction.get("id") not in sampled_ids:
                    sampled.append(interaction)
                    sampled_ids.add(interaction.get("id"))

        # 2. Add recent interactions
        for interaction in sorted_interactions[:self.RECENT_SAMPLE_SIZE]:
            if interaction.get("id") not in sampled_ids:
                sampled.append(interaction)
                sampled_ids.add(interaction.get("id"))

        # 3. Add random sample from historical interactions
        historical = [
            i for i in sorted_interactions[self.RECENT_SAMPLE_SIZE:]
            if i.get("id") not in sampled_ids
        ]
        if historical:
            sample_size = min(self.RANDOM_SAMPLE_SIZE, len(historical))
            random_sample = random.sample(historical, sample_size)
            for interaction in random_sample:
                sampled.append(interaction)
                sampled_ids.add(interaction.get("id"))

        # Sort final sample by timestamp
        sampled.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        return sampled

    def _create_batches(self, interactions: list, batch_size: int) -> list[list]:
        """Split interactions into batches for processing."""
        return [
            interactions[i:i + batch_size]
            for i in range(0, len(interactions), batch_size)
        ]

    def _format_interactions(self, interactions: list) -> str:
        """Format interactions for the prompt with full context."""
        lines = []
        for i, interaction in enumerate(interactions, 1):
            source_type = interaction.get("source_type", "unknown")
            title = interaction.get("title", "Untitled")
            snippet = interaction.get("snippet", "")
            timestamp = interaction.get("timestamp", "")
            interaction_id = interaction.get("id", "")

            line = f"[{i}] ID:{interaction_id} [{source_type}] {timestamp}: {title}"
            if snippet:
                # Include more of the snippet for better context
                line += f"\n    Content: {snippet[:500]}"
            lines.append(line)

        return "\n\n".join(lines)

    def _build_extraction_prompt(self, person_name: str, interaction_text: str) -> str:
        """Build the strict LLM prompt for fact extraction."""
        return f"""Analyze these interactions and extract ONLY facts about {person_name} (the contact person).

CRITICAL - ENTITY ATTRIBUTION:
These are conversations BETWEEN the user (Nathan) and {person_name}. You must ONLY extract facts about {person_name}.
- If Nathan says "my daughter Malea" → This is Nathan's daughter, NOT {person_name}'s. DO NOT extract.
- If Nathan says "my wife Taylor" → This is Nathan's wife. Only extract if {person_name} IS Taylor.
- If {person_name} says "my daughter Emma" → This IS {person_name}'s daughter. Extract it.
- If they discuss a third person "Sarah got a new job" → This is about Sarah, NOT {person_name}. DO NOT extract.

CRITICAL RULES:
1. ONLY extract facts that are EXPLICITLY about {person_name}, not Nathan or third parties
2. Each fact MUST have a verbatim quote as evidence
3. The quote must show this fact belongs to {person_name}, not someone else
4. If unsure who a fact applies to, DO NOT extract it
5. Set confidence to 0.9+ ONLY if fact is explicitly about {person_name}

Return ONLY valid JSON with this structure (no markdown, no explanation):
{{
  "facts": [
    {{
      "category": "family",
      "key": "spouse_name",
      "value": "Sarah",
      "quote": "my wife Sarah and I went hiking",
      "source_id": "abc123",
      "confidence": 0.95
    }}
  ]
}}

Categories and example keys:
- family: spouse_name, children_count, child_names, parent_names, sibling_names, pet_name
- preferences: food_preference, communication_style, meeting_preference, schedule_preference
- background: hometown, alma_mater, previous_companies, nationality, languages, medication
- interests: hobby, sport, music_taste, book_genre, favorite_team, creative_pursuits
- dates: birthday, anniversary, started_job, important_dates
- work: current_role, company, expertise, projects, team_size, reports_to
- topics: frequent_discussion_topics, concerns, goals, current_focus
- travel: visited_countries, planned_trips, favorite_destination, travel_style

EXTRACTION RULES:
- Only include facts with clear textual evidence about {person_name} specifically
- The "quote" field MUST show this fact belongs to {person_name}
- The "source_id" field should match the ID shown in the interaction (e.g., "ID:abc123")
- Values should be specific (not "sister" but "sister named Jane")
- Use lowercase snake_case for keys
- Reject vague facts without specific names or details
- Reject any fact about Nathan (the user) or third parties mentioned in conversation

Example of GOOD extraction (when {person_name} says something):
- {person_name} says "I'm taking my daughter Emma to soccer practice"
- Fact: {{"category": "family", "key": "daughter_name", "value": "Emma", "quote": "I'm taking my daughter Emma", "confidence": 0.95}}

Example of BAD extraction (DO NOT do this):
- Nathan says "I need to pick up Malea" (Malea is Nathan's family, not {person_name}'s)
- BAD: {{"category": "family", "key": "child_name", "value": "Malea"}} <- Wrong person!

- They discuss "Sarah got a new job in Boston"
- BAD: {{"category": "work", "key": "employer", "value": "Boston company"}} <- About Sarah, not {person_name}!

Interactions:
{interaction_text}"""

    def _parse_facts_response(
        self, response_text: str, person_id: str, interactions: list, interaction_lookup: dict
    ) -> list[PersonFact]:
        """Parse the LLM response into PersonFact objects with source attribution."""
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

            for fact_data in data["facts"]:
                category = fact_data.get("category", "").lower()
                key = fact_data.get("key", "")
                value = fact_data.get("value", "")
                quote = fact_data.get("quote", "")
                source_id = fact_data.get("source_id", "")
                confidence = float(fact_data.get("confidence", 0.5))

                # Validate category
                if category not in FACT_CATEGORIES:
                    logger.warning(f"Unknown category: {category}")
                    continue

                # Validate required fields
                if not key or not value:
                    continue

                # Require quote for high-confidence facts
                if confidence >= 0.8 and not quote:
                    logger.warning(f"Rejecting high-confidence fact without quote: {key}")
                    confidence = 0.6  # Downgrade confidence

                # Clamp confidence
                confidence = max(0.0, min(1.0, confidence))

                # Find source interaction for link
                source_link = None
                source_interaction_id = None
                if source_id:
                    interaction = interaction_lookup.get(source_id)
                    if interaction:
                        source_link = interaction.get("source_link")
                        source_interaction_id = source_id
                    else:
                        # Try to find by partial match
                        for int_id, interaction in interaction_lookup.items():
                            if source_id in int_id or int_id in source_id:
                                source_link = interaction.get("source_link")
                                source_interaction_id = int_id
                                break

                # If no source found, use first interaction as fallback
                if not source_interaction_id and interactions:
                    source_interaction_id = interactions[0].get("id")
                    source_link = interactions[0].get("source_link")

                fact = PersonFact(
                    person_id=person_id,
                    category=category,
                    key=key,
                    value=str(value),
                    confidence=confidence,
                    source_interaction_id=source_interaction_id,
                    source_quote=quote if quote else None,
                    source_link=source_link,
                )
                facts.append(fact)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.debug(f"Response was: {response_text[:500]}")
        except Exception as e:
            logger.error(f"Error parsing facts: {e}")

        return facts

    def _generate_relationship_summaries(
        self, person_id: str, person_name: str, interactions: list
    ) -> list[PersonFact]:
        """
        Generate relationship summary facts.

        Creates high-level insights about:
        - Relationship trajectory
        - Key themes
        - Major events
        - Communication style
        """
        # Format a condensed view of interactions for summary
        summary_text = self._format_interactions_for_summary(interactions)

        prompt = f"""Analyze these interactions with {person_name} and provide relationship insights.

Return ONLY valid JSON with this structure (no markdown, no explanation):
{{
  "summaries": [
    {{
      "key": "relationship_trajectory",
      "value": "Started as professional contact, evolved to close friend over 2 years",
      "evidence": "First interaction was a work meeting in 2022, recent interactions include personal topics"
    }},
    {{
      "key": "key_themes",
      "value": "Technology, hiking, family updates",
      "evidence": "Recurring mentions of tech projects, outdoor activities, and family events"
    }},
    {{
      "key": "major_events",
      "value": "Collaborated on Project X, attended their wedding",
      "evidence": "Multiple references to working together on Project X, invitation to wedding in 2023"
    }},
    {{
      "key": "communication_style",
      "value": "Informal, emoji-heavy, quick responses",
      "evidence": "Most messages are casual in tone with frequent emoji usage"
    }}
  ]
}}

Summary keys to generate:
- relationship_trajectory: How the relationship has evolved over time
- key_themes: Recurring topics in conversations (3-5 themes)
- major_events: Important shared experiences or milestones
- communication_style: How you typically interact

Rules:
- Base summaries on patterns across multiple interactions
- Keep values concise but informative (10-30 words)
- The evidence field should describe what interactions support this summary
- Only include summaries you can support with evidence

Interactions:
{summary_text}"""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = response.content[0].text

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
            summaries = []

            for summary_data in data.get("summaries", []):
                key = summary_data.get("key", "")
                value = summary_data.get("value", "")
                evidence = summary_data.get("evidence", "")

                if not key or not value:
                    continue

                fact = PersonFact(
                    person_id=person_id,
                    category="summary",
                    key=key,
                    value=value,
                    confidence=0.8,  # Summaries are synthesized, so moderate confidence
                    source_quote=evidence,
                    source_interaction_id=interactions[0].get("id") if interactions else None,
                    source_link=interactions[0].get("source_link") if interactions else None,
                )
                summaries.append(fact)

            return summaries

        except Exception as e:
            logger.error(f"Failed to generate summaries for {person_name}: {e}")
            return []

    def _format_interactions_for_summary(self, interactions: list) -> str:
        """Format interactions in a condensed way for summary generation."""
        lines = []

        # Group by year/month for temporal context
        by_period: dict[str, list] = {}
        for interaction in interactions:
            timestamp = interaction.get("timestamp", "")
            if timestamp:
                period = timestamp[:7]  # YYYY-MM
            else:
                period = "unknown"

            if period not in by_period:
                by_period[period] = []
            by_period[period].append(interaction)

        # Format grouped interactions
        for period in sorted(by_period.keys(), reverse=True):
            period_interactions = by_period[period]
            lines.append(f"\n--- {period} ({len(period_interactions)} interactions) ---")

            for interaction in period_interactions[:20]:  # Limit per period
                source_type = interaction.get("source_type", "")
                title = interaction.get("title", "")
                snippet = interaction.get("snippet", "")[:200] if interaction.get("snippet") else ""

                lines.append(f"[{source_type}] {title}")
                if snippet:
                    lines.append(f"  {snippet}")

        return "\n".join(lines[:200])  # Limit total lines


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

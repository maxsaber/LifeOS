"""
Sentiment Tracking Service for LifeOS CRM.

Analyzes sentiment/tone of interactions with contacts using Claude.
Tracks sentiment trends over time to surface relationship health.

Architecture:
- SentimentScore: Per-interaction sentiment data
- SentimentStore: SQLite storage with trend queries
- SentimentExtractor: Claude-based sentiment analysis
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
class SentimentScore:
    """
    Sentiment analysis for a single interaction.

    Scores range from -1.0 (very negative) to +1.0 (very positive).
    Magnitude indicates intensity (0.0 = mild, 1.0 = intense).
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    interaction_id: str = ""
    person_id: str = ""
    score: float = 0.0  # -1.0 to +1.0
    magnitude: float = 0.5  # 0.0 to 1.0 (intensity)
    label: str = "neutral"  # "positive", "neutral", "negative"
    keywords: list[str] = field(default_factory=list)
    extracted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            "id": self.id,
            "interaction_id": self.interaction_id,
            "person_id": self.person_id,
            "score": self.score,
            "magnitude": self.magnitude,
            "label": self.label,
            "keywords": self.keywords,
            "extracted_at": self.extracted_at.isoformat() if self.extracted_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SentimentScore":
        """Create SentimentScore from dict."""
        if data.get("extracted_at") and isinstance(data["extracted_at"], str):
            data["extracted_at"] = _make_aware(datetime.fromisoformat(data["extracted_at"]))
        if data.get("created_at") and isinstance(data["created_at"], str):
            data["created_at"] = _make_aware(datetime.fromisoformat(data["created_at"]))
        if data.get("keywords") and isinstance(data["keywords"], str):
            data["keywords"] = json.loads(data["keywords"])
        return cls(**data)

    @classmethod
    def from_row(cls, row: tuple) -> "SentimentScore":
        """Create SentimentScore from SQLite row.

        Column order:
        0: id, 1: interaction_id, 2: person_id, 3: score, 4: magnitude,
        5: label, 6: keywords (JSON), 7: extracted_at, 8: created_at
        """
        keywords = []
        if row[6]:
            try:
                keywords = json.loads(row[6])
            except json.JSONDecodeError:
                keywords = []

        return cls(
            id=row[0],
            interaction_id=row[1],
            person_id=row[2],
            score=row[3] or 0.0,
            magnitude=row[4] or 0.5,
            label=row[5] or "neutral",
            keywords=keywords,
            extracted_at=_make_aware(datetime.fromisoformat(row[7])) if row[7] else datetime.now(timezone.utc),
            created_at=_make_aware(datetime.fromisoformat(row[8])) if row[8] else datetime.now(timezone.utc),
        )


class SentimentStore:
    """
    SQLite-backed storage for sentiment scores.

    Provides efficient queries for per-person sentiment trends.
    """

    def __init__(self, db_path: Optional[str] = None):
        """Initialize sentiment store."""
        self.db_path = db_path or get_crm_db_path()
        self._init_db()

    def _init_db(self):
        """Create the sentiment_scores table if it doesn't exist."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sentiment_scores (
                    id TEXT PRIMARY KEY,
                    interaction_id TEXT NOT NULL,
                    person_id TEXT NOT NULL,
                    score REAL NOT NULL,
                    magnitude REAL DEFAULT 0.5,
                    label TEXT NOT NULL,
                    keywords TEXT,
                    extracted_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(interaction_id)
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sentiment_person
                ON sentiment_scores(person_id)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sentiment_score
                ON sentiment_scores(person_id, score)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sentiment_extracted
                ON sentiment_scores(extracted_at)
            """)

            conn.commit()
            logger.info(f"Initialized sentiment_scores table in {self.db_path}")
        finally:
            conn.close()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        return sqlite3.connect(self.db_path)

    def get_for_person(self, person_id: str, days: int = 365) -> list[SentimentScore]:
        """Get sentiment scores for a person within the specified time range."""
        conn = self._get_connection()
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            cursor = conn.execute("""
                SELECT * FROM sentiment_scores
                WHERE person_id = ? AND extracted_at >= ?
                ORDER BY extracted_at DESC
            """, (person_id, cutoff))
            return [SentimentScore.from_row(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_for_interaction(self, interaction_id: str) -> Optional[SentimentScore]:
        """Get sentiment score for a specific interaction."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM sentiment_scores WHERE interaction_id = ?",
                (interaction_id,)
            )
            row = cursor.fetchone()
            return SentimentScore.from_row(row) if row else None
        finally:
            conn.close()

    def get_trend(self, person_id: str, days: int = 90) -> dict:
        """
        Calculate sentiment trend for a person.

        Returns:
            dict with:
            - average: Average score over period
            - trend: "improving", "stable", or "declining"
            - trend_delta: Change from first to second half of period
            - sparkline_data: List of scores for charting
            - count: Number of data points
        """
        scores = self.get_for_person(person_id, days=days)

        if not scores:
            return {
                "average": 0.0,
                "trend": "stable",
                "trend_delta": 0.0,
                "sparkline_data": [],
                "count": 0,
            }

        # Calculate average
        score_values = [s.score for s in scores]
        average = sum(score_values) / len(score_values)

        # Calculate trend (compare first half to second half)
        mid = len(scores) // 2
        if mid > 0:
            # Scores are ordered DESC, so first half is recent, second half is older
            recent_avg = sum(s.score for s in scores[:mid]) / mid
            older_avg = sum(s.score for s in scores[mid:]) / (len(scores) - mid)
            trend_delta = recent_avg - older_avg

            if trend_delta > 0.1:
                trend = "improving"
            elif trend_delta < -0.1:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "stable"
            trend_delta = 0.0

        # Generate sparkline data (chronological order, most recent last)
        sparkline_data = [s.score for s in reversed(scores)][-30:]  # Last 30 points

        return {
            "average": round(average, 2),
            "trend": trend,
            "trend_delta": round(trend_delta, 2),
            "sparkline_data": sparkline_data,
            "count": len(scores),
        }

    def upsert(self, score: SentimentScore) -> SentimentScore:
        """Insert or update a sentiment score."""
        conn = self._get_connection()
        try:
            conn.execute("""
                INSERT INTO sentiment_scores
                (id, interaction_id, person_id, score, magnitude, label, keywords, extracted_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(interaction_id) DO UPDATE SET
                    score = excluded.score,
                    magnitude = excluded.magnitude,
                    label = excluded.label,
                    keywords = excluded.keywords,
                    extracted_at = excluded.extracted_at
            """, (
                score.id,
                score.interaction_id,
                score.person_id,
                score.score,
                score.magnitude,
                score.label,
                json.dumps(score.keywords),
                score.extracted_at.isoformat() if score.extracted_at else None,
                score.created_at.isoformat() if score.created_at else None,
            ))
            conn.commit()
            return score
        finally:
            conn.close()

    def bulk_upsert(self, scores: list[SentimentScore]) -> int:
        """Bulk insert or update sentiment scores. Returns count inserted."""
        if not scores:
            return 0

        conn = self._get_connection()
        try:
            for score in scores:
                conn.execute("""
                    INSERT INTO sentiment_scores
                    (id, interaction_id, person_id, score, magnitude, label, keywords, extracted_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(interaction_id) DO UPDATE SET
                        score = excluded.score,
                        magnitude = excluded.magnitude,
                        label = excluded.label,
                        keywords = excluded.keywords,
                        extracted_at = excluded.extracted_at
                """, (
                    score.id,
                    score.interaction_id,
                    score.person_id,
                    score.score,
                    score.magnitude,
                    score.label,
                    json.dumps(score.keywords),
                    score.extracted_at.isoformat() if score.extracted_at else None,
                    score.created_at.isoformat() if score.created_at else None,
                ))
            conn.commit()
            return len(scores)
        finally:
            conn.close()

    def has_sentiment(self, interaction_id: str) -> bool:
        """Check if an interaction already has a sentiment score."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT 1 FROM sentiment_scores WHERE interaction_id = ? LIMIT 1",
                (interaction_id,)
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def get_unscored_interactions(self, person_id: str, limit: int = 50) -> list[str]:
        """Get interaction IDs that don't have sentiment scores yet."""
        conn = self._get_connection()
        try:
            # Query interactions table for this person that aren't in sentiment_scores
            int_db_path = str(Path(self.db_path).parent / "interactions.db")
            conn.execute(f"ATTACH DATABASE '{int_db_path}' AS int_db")

            cursor = conn.execute("""
                SELECT i.id FROM int_db.interactions i
                LEFT JOIN sentiment_scores s ON i.id = s.interaction_id
                WHERE i.person_id = ? AND s.id IS NULL
                ORDER BY i.timestamp DESC
                LIMIT ?
            """, (person_id, limit))

            result = [row[0] for row in cursor.fetchall()]
            conn.execute("DETACH DATABASE int_db")
            return result
        finally:
            conn.close()


class SentimentExtractor:
    """
    Extracts sentiment from interactions using Claude.

    Analyzes the emotional tone of conversations, not just the topic.
    A difficult topic discussed warmly should be positive.
    """

    # Model options - use Haiku for cost efficiency
    MODEL_HAIKU = "claude-haiku-4-5"
    MODEL_SONNET = "claude-sonnet-4-5"
    DEFAULT_MODEL = MODEL_HAIKU

    # Batch settings
    MAX_INTERACTIONS_PER_BATCH = 50

    def __init__(self, store: Optional[SentimentStore] = None):
        """Initialize extractor."""
        self.store = store or get_sentiment_store()
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
        force: bool = False,
        model: Optional[str] = None,
    ) -> dict:
        """
        Extract sentiment from a person's interactions.

        Args:
            person_id: The person's ID
            person_name: The person's name (for prompt context)
            interactions: List of interaction dicts with id, title, snippet, timestamp
            force: If True, re-extract even if sentiment exists
            model: Claude model to use

        Returns:
            dict with extraction stats
        """
        use_model = model or self.DEFAULT_MODEL

        if not interactions:
            return {"extracted": 0, "skipped": 0, "errors": 0}

        # Filter to unscored interactions unless forced
        if not force:
            scored_ids = set()
            for i in interactions:
                if self.store.has_sentiment(i.get("id", "")):
                    scored_ids.add(i.get("id"))
            interactions = [i for i in interactions if i.get("id") not in scored_ids]

        if not interactions:
            return {"extracted": 0, "skipped": 0, "errors": 0}

        # Process in batches
        all_scores = []
        errors = 0

        for i in range(0, len(interactions), self.MAX_INTERACTIONS_PER_BATCH):
            batch = interactions[i:i + self.MAX_INTERACTIONS_PER_BATCH]
            try:
                scores = self._extract_batch(person_id, person_name, batch, use_model)
                all_scores.extend(scores)
            except Exception as e:
                logger.error(f"Sentiment extraction failed for batch: {e}")
                errors += 1

        # Save scores
        if all_scores:
            self.store.bulk_upsert(all_scores)

        return {
            "extracted": len(all_scores),
            "skipped": 0,
            "errors": errors,
        }

    def _extract_batch(
        self,
        person_id: str,
        person_name: str,
        interactions: list[dict],
        model: str,
    ) -> list[SentimentScore]:
        """Extract sentiment for a batch of interactions."""
        prompt = self._build_prompt(person_name, interactions)

        response = self.client.messages.create(
            model=model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = response.content[0].text
        return self._parse_response(response_text, person_id, interactions)

    def _build_prompt(self, person_name: str, interactions: list[dict]) -> str:
        """Build the sentiment extraction prompt."""
        interactions_text = self._format_interactions(interactions)

        return f"""Analyze the sentiment of these interactions with {person_name}.

For each interaction, determine:
- score: -1.0 (very negative) to +1.0 (very positive), 0 = neutral
- magnitude: 0.0 (mild) to 1.0 (intense emotional expression)
- label: "positive", "neutral", or "negative"
- keywords: 2-3 words that drove the sentiment assessment

IMPORTANT: Focus on the EMOTIONAL TONE, not just the topic:
- A difficult topic discussed warmly should be positive
- A neutral topic discussed curtly should be negative
- Friendly banter = positive, even if the topic is trivial
- Formal/cold professional messages = neutral to slightly negative

Scoring guidelines:
- 0.7 to 1.0: Enthusiastic, grateful, excited, warm
- 0.3 to 0.6: Friendly, cooperative, pleasant
- -0.2 to 0.2: Neutral, purely informational
- -0.6 to -0.3: Tense, frustrated, disappointed
- -1.0 to -0.7: Angry, hostile, very upset

Return ONLY valid JSON (no markdown, no explanation):
[
  {{"interaction_id": "abc123", "score": 0.7, "magnitude": 0.6, "label": "positive", "keywords": ["thanks", "excited"]}}
]

Interactions:
{interactions_text}"""

    def _format_interactions(self, interactions: list[dict]) -> str:
        """Format interactions for the prompt."""
        lines = []
        for i in interactions:
            int_id = i.get("id", "unknown")
            source = i.get("source_type", "unknown")
            title = i.get("title", "")
            snippet = i.get("snippet", "")[:300] if i.get("snippet") else ""
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
    ) -> list[SentimentScore]:
        """Parse Claude response into SentimentScore objects."""
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

            # Build lookup for interaction IDs
            interaction_ids = {i.get("id") for i in interactions}

            scores = []
            now = datetime.now(timezone.utc)

            for item in data:
                int_id = item.get("interaction_id", "")
                if int_id not in interaction_ids:
                    logger.warning(f"Unknown interaction_id in response: {int_id}")
                    continue

                score_val = float(item.get("score", 0.0))
                score_val = max(-1.0, min(1.0, score_val))  # Clamp to [-1, 1]

                magnitude = float(item.get("magnitude", 0.5))
                magnitude = max(0.0, min(1.0, magnitude))  # Clamp to [0, 1]

                label = item.get("label", "neutral")
                if label not in ("positive", "neutral", "negative"):
                    # Derive label from score
                    if score_val > 0.2:
                        label = "positive"
                    elif score_val < -0.2:
                        label = "negative"
                    else:
                        label = "neutral"

                keywords = item.get("keywords", [])
                if isinstance(keywords, str):
                    keywords = [keywords]

                score = SentimentScore(
                    interaction_id=int_id,
                    person_id=person_id,
                    score=score_val,
                    magnitude=magnitude,
                    label=label,
                    keywords=keywords[:5],  # Limit to 5 keywords
                    extracted_at=now,
                )
                scores.append(score)

            return scores

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse sentiment JSON: {e}")
            logger.debug(f"Response was: {response_text[:500]}")
            return []
        except Exception as e:
            logger.error(f"Error parsing sentiment response: {e}")
            return []


# Singleton instances
_sentiment_store: Optional[SentimentStore] = None
_sentiment_extractor: Optional[SentimentExtractor] = None


def get_sentiment_store(db_path: Optional[str] = None) -> SentimentStore:
    """Get or create the singleton SentimentStore."""
    global _sentiment_store
    if _sentiment_store is None:
        _sentiment_store = SentimentStore(db_path)
    return _sentiment_store


def get_sentiment_extractor() -> SentimentExtractor:
    """Get or create the singleton SentimentExtractor."""
    global _sentiment_extractor
    if _sentiment_extractor is None:
        _sentiment_extractor = SentimentExtractor()
    return _sentiment_extractor

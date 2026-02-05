"""Tests for anomaly detection service helpers."""
import tempfile
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from api.services.anomaly_detection import (
    get_communication_anomalies,
    get_sentiment_drift_anomalies,
    get_meeting_overload_anomaly,
)
from api.services.interaction_store import Interaction, InteractionStore
from api.services.person_entity import PersonEntity, PersonEntityStore
from api.services.sentiment import SentimentStore, SentimentScore


def _temp_entity_store():
    temp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    temp.close()
    return PersonEntityStore(temp.name), temp.name


def _temp_interaction_store():
    temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    temp.close()
    return InteractionStore(temp.name), temp.name


def _temp_sentiment_store():
    temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    temp.close()
    return SentimentStore(temp.name), temp.name


def test_communication_gap_anomaly_detected():
    now = datetime.now(timezone.utc)
    person_store, person_path = _temp_entity_store()
    interaction_store, interaction_path = _temp_interaction_store()

    try:
        person = PersonEntity(id="person-1", canonical_name="Alex Example", dunbar_circle=1)
        person_store.add(person)

        # Weekly cadence, last interaction 21 days ago
        for idx, days_ago in enumerate([56, 49, 42, 35, 28, 21], start=1):
            interaction_store.add(
                Interaction(
                    id=f"int-{idx}",
                    person_id=person.id,
                    timestamp=now - timedelta(days=days_ago),
                    source_type="gmail",
                    title="Hello",
                )
            )

        with patch("api.services.anomaly_detection.get_person_entity_store", return_value=person_store), \
            patch("api.services.anomaly_detection.get_interaction_store", return_value=interaction_store):
            anomalies = get_communication_anomalies(days_back=120, min_interactions=5, gap_multiplier=2.0)

        assert len(anomalies) == 1
        assert anomalies[0].person_id == person.id
        assert anomalies[0].typical_gap_days >= 7
        assert anomalies[0].days_since_contact >= 21
    finally:
        Path(person_path).unlink(missing_ok=True)
        Path(interaction_path).unlink(missing_ok=True)


def test_sentiment_drift_anomaly_detected():
    now = datetime.now(timezone.utc)
    person_store, person_path = _temp_entity_store()
    sentiment_store, sentiment_path = _temp_sentiment_store()

    try:
        person = PersonEntity(id="person-2", canonical_name="Jordan Drift")
        person_store.add(person)

        # Older positive scores, recent negative scores -> declining trend
        timestamps = [
            now - timedelta(days=90),
            now - timedelta(days=80),
            now - timedelta(days=70),
            now - timedelta(days=10),
            now - timedelta(days=7),
            now - timedelta(days=3),
        ]
        scores = [0.6, 0.5, 0.4, -0.4, -0.5, -0.6]

        for idx, (ts, score) in enumerate(zip(timestamps, scores), start=1):
            sentiment_store.upsert(
                SentimentScore(
                    interaction_id=f"int-{idx}",
                    person_id=person.id,
                    score=score,
                    magnitude=0.8,
                    label="positive" if score > 0 else "negative",
                    extracted_at=ts,
                )
            )

        with patch("api.services.anomaly_detection.get_person_entity_store", return_value=person_store), \
            patch("api.services.anomaly_detection.get_sentiment_store", return_value=sentiment_store):
            anomalies = get_sentiment_drift_anomalies(days=120, min_count=5, min_delta=-0.1)

        assert len(anomalies) == 1
        assert anomalies[0].person_id == person.id
        assert anomalies[0].trend == "declining"
    finally:
        Path(person_path).unlink(missing_ok=True)
        Path(sentiment_path).unlink(missing_ok=True)


def test_meeting_overload_anomaly_detected():
    target_date = date(2026, 2, 6)
    start = datetime(2026, 2, 6, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 2, 6, 13, 0, tzinfo=timezone.utc)
    event = SimpleNamespace(
        title="Deep Work Block",
        start_time=start,
        end_time=end,
        is_all_day=False,
        source_account="work",
    )

    with patch("api.services.anomaly_detection.get_all_events_in_range", return_value=[event, event]):
        anomaly = get_meeting_overload_anomaly(target_date=target_date, threshold_hours=6.0)

    assert anomaly is not None
    assert anomaly.total_meeting_hours >= 8.0
    assert anomaly.event_count == 2

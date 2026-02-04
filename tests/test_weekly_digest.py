"""
Tests for weekly digest service helpers.
"""
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from api.services.interaction_store import Interaction, InteractionStore
from api.services.person_entity import PersonEntity, PersonEntityStore
from api.services.weekly_digest import build_weekly_digest


@pytest.fixture
def temp_entity_store():
    """Create a temporary entity store."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        store = PersonEntityStore(f.name)
        yield store
        Path(f.name).unlink(missing_ok=True)


@pytest.fixture
def temp_interaction_store():
    """Create a temporary interaction store."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        store = InteractionStore(f.name)
        yield store
        Path(f.name).unlink(missing_ok=True)


def test_recent_interactions_land_in_talked_to(
    temp_entity_store,
    temp_interaction_store,
):
    now = datetime.now(timezone.utc)
    person = PersonEntity(id="person-recent", canonical_name="Recent Person")
    temp_entity_store.add(person)

    temp_interaction_store.add(
        Interaction(
            id="int-recent",
            person_id=person.id,
            timestamp=now - timedelta(days=1),
            source_type="gmail",
            title="Hello",
        )
    )

    start = now - timedelta(days=7)
    end = now

    with patch("api.services.weekly_digest.get_person_entity_store", return_value=temp_entity_store), \
        patch("api.services.weekly_digest.get_interaction_store", return_value=temp_interaction_store), \
        patch("api.services.weekly_digest.compute_strength_for_person", return_value=72.5):
        result = build_weekly_digest(start, end)

    assert result["talked_to"]["count"] == 1
    assert result["talked_to"]["items"][0]["person_id"] == person.id
    assert result["talked_to"]["items"][0]["interaction_count"] == 1


def test_long_gaps_land_in_slipping_or_suggested_reachouts(
    temp_entity_store,
    temp_interaction_store,
):
    now = datetime.now(timezone.utc)
    slipping_person = PersonEntity(
        id="person-slip",
        canonical_name="Slip Person",
        last_seen=now - timedelta(days=30),
    )
    suggested_person = PersonEntity(
        id="person-suggest",
        canonical_name="Suggest Person",
        last_seen=now - timedelta(days=60),
    )
    temp_entity_store.add(slipping_person)
    temp_entity_store.add(suggested_person)

    start = now - timedelta(days=7)
    end = now

    def strength_side_effect(person):
        return {
            "person-slip": 80.0,
            "person-suggest": 40.0,
        }[person.id]

    with patch("api.services.weekly_digest.get_person_entity_store", return_value=temp_entity_store), \
        patch("api.services.weekly_digest.get_interaction_store", return_value=temp_interaction_store), \
        patch("api.services.weekly_digest.compute_strength_for_person", side_effect=strength_side_effect):
        result = build_weekly_digest(start, end)

    slipping_ids = {item["person_id"] for item in result["slipping"]["items"]}
    suggested_ids = {item["person_id"] for item in result["suggested_reachouts"]["items"]}

    assert slipping_person.id in slipping_ids
    assert suggested_person.id in suggested_ids


def test_default_date_range_behavior(
    temp_entity_store,
    temp_interaction_store,
):
    start = datetime(2024, 1, 1)
    end = datetime(2024, 1, 7)

    with patch("api.services.weekly_digest.get_person_entity_store", return_value=temp_entity_store), \
        patch("api.services.weekly_digest.get_interaction_store", return_value=temp_interaction_store), \
        patch("api.services.weekly_digest.compute_strength_for_person", return_value=0.0):
        result = build_weekly_digest(start, end)

    assert result["window"]["days"] == 7
    assert result["window"]["start"].endswith("+00:00")
    assert result["window"]["end"].endswith("+00:00")

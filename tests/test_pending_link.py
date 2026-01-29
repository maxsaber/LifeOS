"""Tests for PendingLink and PendingLinkStore."""
import tempfile
import pytest
from datetime import datetime, timezone

from api.services.pending_link import (
    PendingLink,
    PendingLinkStore,
    STATUS_PENDING,
    STATUS_CONFIRMED,
    STATUS_REJECTED,
    REASON_NEW_ENTITY,
    REASON_EMAIL_MATCH,
    REASON_NAME_MATCH,
    create_pending_link,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield f.name


@pytest.fixture
def store(temp_db):
    """Create a PendingLinkStore with temp database."""
    return PendingLinkStore(db_path=temp_db)


class TestPendingLink:
    """Tests for PendingLink dataclass."""

    def test_create_pending_link(self):
        """Test basic pending link creation."""
        link = PendingLink(
            source_entity_id="source123",
            proposed_canonical_id="person456",
            reason=REASON_EMAIL_MATCH,
            confidence=0.95,
        )

        assert link.source_entity_id == "source123"
        assert link.proposed_canonical_id == "person456"
        assert link.reason == REASON_EMAIL_MATCH
        assert link.confidence == 0.95
        assert link.status == STATUS_PENDING

    def test_is_pending(self):
        """Test is_pending property."""
        pending = PendingLink(
            source_entity_id="s1",
            proposed_canonical_id="p1",
        )
        assert pending.is_pending

        confirmed = PendingLink(
            source_entity_id="s1",
            proposed_canonical_id="p1",
            status=STATUS_CONFIRMED,
        )
        assert not confirmed.is_pending

    def test_is_resolved(self):
        """Test is_resolved property."""
        pending = PendingLink(
            source_entity_id="s1",
            proposed_canonical_id="p1",
        )
        assert not pending.is_resolved

        confirmed = PendingLink(
            source_entity_id="s1",
            proposed_canonical_id="p1",
            status=STATUS_CONFIRMED,
        )
        assert confirmed.is_resolved

        rejected = PendingLink(
            source_entity_id="s1",
            proposed_canonical_id="p1",
            status=STATUS_REJECTED,
        )
        assert rejected.is_resolved

    def test_reason_display(self):
        """Test human-readable reason display."""
        link = PendingLink(
            source_entity_id="s1",
            proposed_canonical_id="p1",
            reason=REASON_NEW_ENTITY,
        )
        assert link.reason_display == "New person"

        link.reason = REASON_EMAIL_MATCH
        assert link.reason_display == "Email match"

    def test_to_dict_from_dict(self):
        """Test serialization roundtrip."""
        now = datetime.now(timezone.utc)
        link = PendingLink(
            source_entity_id="source123",
            proposed_canonical_id="person456",
            reason=REASON_NAME_MATCH,
            confidence=0.85,
            created_at=now,
        )

        data = link.to_dict()
        restored = PendingLink.from_dict(data)

        assert restored.source_entity_id == link.source_entity_id
        assert restored.proposed_canonical_id == link.proposed_canonical_id
        assert restored.reason == link.reason
        assert restored.confidence == link.confidence


class TestPendingLinkStore:
    """Tests for PendingLinkStore."""

    def test_add_link(self, store):
        """Test adding a pending link."""
        link = PendingLink(
            source_entity_id="source123",
            proposed_canonical_id="person456",
            reason=REASON_EMAIL_MATCH,
            confidence=0.9,
        )

        added = store.add(link)
        assert added.id == link.id

        retrieved = store.get_by_id(link.id)
        assert retrieved is not None
        assert retrieved.source_entity_id == "source123"

    def test_get_pending(self, store):
        """Test getting pending links."""
        # Add pending link
        pending = PendingLink(
            source_entity_id="s1",
            proposed_canonical_id="p1",
        )
        store.add(pending)

        # Add confirmed link
        confirmed = PendingLink(
            source_entity_id="s2",
            proposed_canonical_id="p2",
            status=STATUS_CONFIRMED,
        )
        store.add(confirmed)

        links = store.get_pending()
        assert len(links) == 1
        assert links[0].source_entity_id == "s1"

    def test_get_pending_for_person(self, store):
        """Test getting pending links for a specific person."""
        # Add links for different people
        store.add(PendingLink(
            source_entity_id="s1",
            proposed_canonical_id="person1",
        ))
        store.add(PendingLink(
            source_entity_id="s2",
            proposed_canonical_id="person1",
        ))
        store.add(PendingLink(
            source_entity_id="s3",
            proposed_canonical_id="person2",
        ))

        links = store.get_pending_for_person("person1")
        assert len(links) == 2

        links = store.get_pending_for_person("person2")
        assert len(links) == 1

    def test_confirm(self, store):
        """Test confirming a pending link."""
        link = PendingLink(
            source_entity_id="s1",
            proposed_canonical_id="p1",
        )
        store.add(link)

        confirmed = store.confirm(link.id)
        assert confirmed is not None
        assert confirmed.status == STATUS_CONFIRMED
        assert confirmed.resolved_by == "user"
        assert confirmed.resolved_at is not None

        # Verify in store
        retrieved = store.get_by_id(link.id)
        assert retrieved.status == STATUS_CONFIRMED

    def test_reject(self, store):
        """Test rejecting a pending link."""
        link = PendingLink(
            source_entity_id="s1",
            proposed_canonical_id="p1",
        )
        store.add(link)

        rejected = store.reject(link.id)
        assert rejected is not None
        assert rejected.status == STATUS_REJECTED

        retrieved = store.get_by_id(link.id)
        assert retrieved.status == STATUS_REJECTED

    def test_confirm_nonexistent(self, store):
        """Test confirming a nonexistent link."""
        result = store.confirm("nonexistent")
        assert result is None

    def test_count_pending(self, store):
        """Test counting pending links."""
        # Add mix of pending and resolved
        store.add(PendingLink(
            source_entity_id="s1",
            proposed_canonical_id="p1",
        ))
        store.add(PendingLink(
            source_entity_id="s2",
            proposed_canonical_id="p2",
        ))
        store.add(PendingLink(
            source_entity_id="s3",
            proposed_canonical_id="p3",
            status=STATUS_CONFIRMED,
        ))

        count = store.count_pending()
        assert count == 2

    def test_statistics(self, store):
        """Test getting statistics."""
        store.add(PendingLink(
            source_entity_id="s1",
            proposed_canonical_id="p1",
            reason=REASON_EMAIL_MATCH,
        ))
        store.add(PendingLink(
            source_entity_id="s2",
            proposed_canonical_id="p2",
            reason=REASON_NAME_MATCH,
        ))
        store.add(PendingLink(
            source_entity_id="s3",
            proposed_canonical_id="p3",
            status=STATUS_CONFIRMED,
        ))

        stats = store.get_statistics()
        assert stats["total_links"] == 3
        assert stats["pending_count"] == 2
        assert stats["confirmed_count"] == 1
        assert stats["by_reason"][REASON_EMAIL_MATCH] == 1
        assert stats["by_reason"][REASON_NAME_MATCH] == 1


class TestFactoryFunction:
    """Tests for create_pending_link factory."""

    def test_create_pending_link(self):
        """Test factory function."""
        link = create_pending_link(
            source_entity_id="source123",
            proposed_canonical_id="person456",
            reason=REASON_EMAIL_MATCH,
            confidence=0.95,
        )

        assert link.source_entity_id == "source123"
        assert link.proposed_canonical_id == "person456"
        assert link.reason == REASON_EMAIL_MATCH
        assert link.confidence == 0.95
        assert link.status == STATUS_PENDING

    def test_create_pending_link_with_previous(self):
        """Test factory with previous canonical ID."""
        link = create_pending_link(
            source_entity_id="source123",
            proposed_canonical_id="person456",
            previous_canonical_id="person789",
        )

        assert link.previous_canonical_id == "person789"

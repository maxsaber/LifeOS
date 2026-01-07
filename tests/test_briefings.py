"""
Tests for Stakeholder Briefings.
P2.3 Acceptance Criteria:
- "Tell me about [person]" generates briefing
- Briefing includes last interaction date
- Briefing includes open action items
- Briefing includes recent discussion context
- Handles unknown people gracefully
- Sources cited with links
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient

from api.main import app
from api.services.briefings import BriefingsService, BriefingContext


class TestBriefingContext:
    """Test BriefingContext dataclass."""

    def test_creates_context_with_defaults(self):
        """Should create context with default values."""
        context = BriefingContext(
            person_name="yoni",
            resolved_name="Yoni"
        )

        assert context.person_name == "yoni"
        assert context.resolved_name == "Yoni"
        assert context.meeting_count == 0
        assert context.related_notes == []
        assert context.action_items == []

    def test_context_stores_all_fields(self):
        """Should store all provided fields."""
        context = BriefingContext(
            person_name="yoni",
            resolved_name="Yoni",
            email="yoni@example.com",
            company="Movement Labs",
            position="CEO",
            category="work",
            meeting_count=15,
            email_count=50,
            mention_count=30,
            last_interaction=datetime(2026, 1, 7, tzinfo=timezone.utc),
        )

        assert context.email == "yoni@example.com"
        assert context.company == "Movement Labs"
        assert context.meeting_count == 15
        assert context.last_interaction.year == 2026


class TestBriefingsService:
    """Test BriefingsService."""

    @pytest.fixture
    def mock_aggregator(self):
        """Create mock people aggregator."""
        aggregator = MagicMock()
        return aggregator

    @pytest.fixture
    def mock_vector_store(self):
        """Create mock vector store."""
        store = MagicMock()
        return store

    @pytest.fixture
    def mock_action_registry(self):
        """Create mock action registry."""
        registry = MagicMock()
        registry.get_actions_involving_person.return_value = []
        return registry

    @pytest.fixture
    def service(self, mock_aggregator, mock_vector_store, mock_action_registry):
        """Create briefings service with mocks."""
        return BriefingsService(
            people_aggregator=mock_aggregator,
            vector_store=mock_vector_store,
            action_registry=mock_action_registry,
        )

    def test_gather_context_resolves_name(self, service, mock_aggregator):
        """Should resolve person name."""
        mock_aggregator.search.return_value = []

        context = service.gather_context("yoni")

        assert context is not None
        assert context.resolved_name == "Yoni"

    def test_gather_context_includes_person_record(self, service, mock_aggregator):
        """Should include data from people aggregator."""
        from api.services.people_aggregator import PersonRecord

        mock_record = PersonRecord(
            canonical_name="Yoni",
            email="yoni@example.com",
            company="Movement Labs",
            position="CEO",
            sources=["linkedin", "calendar"],
            meeting_count=10,
            email_count=20,
        )
        mock_aggregator.search.return_value = [mock_record]

        context = service.gather_context("yoni")

        assert context.email == "yoni@example.com"
        assert context.company == "Movement Labs"
        assert context.meeting_count == 10

    def test_gather_context_searches_vault(self, service, mock_aggregator, mock_vector_store):
        """Should search vault for mentions."""
        mock_aggregator.search.return_value = []
        mock_vector_store.search.return_value = [
            {
                "content": "Meeting with Yoni about Q1 goals",
                "metadata": {"file_name": "Q1 Planning.md", "file_path": "/vault/Q1 Planning.md"},
                "score": 0.9,
            }
        ]

        context = service.gather_context("yoni")

        assert len(context.related_notes) == 1
        assert "Q1 Planning.md" in context.sources

    def test_gather_context_gets_action_items(self, service, mock_aggregator, mock_action_registry):
        """Should get action items for person."""
        mock_aggregator.search.return_value = []

        mock_action = MagicMock()
        mock_action.task = "Review budget proposal"
        mock_action.owner = "Yoni"
        mock_action.completed = False
        mock_action.due_date = None
        mock_action.source_file = "Budget.md"
        mock_action_registry.get_actions_involving_person.return_value = [mock_action]

        context = service.gather_context("yoni")

        assert len(context.action_items) == 1
        assert context.action_items[0]["task"] == "Review budget proposal"

    @pytest.mark.asyncio
    async def test_generate_briefing_for_known_person(self, service, mock_aggregator, mock_vector_store):
        """Should generate briefing for known person."""
        from api.services.people_aggregator import PersonRecord

        mock_record = PersonRecord(
            canonical_name="Yoni",
            email="yoni@movementlabs.com",
            company="Movement Labs",
            sources=["linkedin"],
        )
        mock_aggregator.search.return_value = [mock_record]
        mock_vector_store.search.return_value = [
            {"content": "Discussion about strategy", "metadata": {"file_name": "Strategy.md"}, "score": 0.9}
        ]

        with patch('api.services.briefings.get_synthesizer') as mock_synth:
            mock_synth.return_value.get_response = AsyncMock(
                return_value="## Yoni — Briefing\n\nThis is the briefing content."
            )

            result = await service.generate_briefing("yoni")

            assert result["status"] == "success"
            assert "briefing" in result
            assert result["person_name"] == "Yoni"

    @pytest.mark.asyncio
    async def test_generate_briefing_handles_unknown_person(self, service, mock_aggregator, mock_vector_store):
        """Should handle unknown person gracefully."""
        mock_aggregator.search.return_value = []
        mock_vector_store.search.return_value = []

        result = await service.generate_briefing("unknown_person_xyz")

        assert result["status"] in ["not_found", "limited"]


class TestBriefingsAPI:
    """Test briefings API endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    def test_briefing_endpoint_exists(self, client):
        """Briefing endpoint should exist."""
        response = client.post("/api/briefing", json={"person_name": "test"})
        assert response.status_code != 404
        assert response.status_code != 405

    def test_briefing_rejects_empty_name(self, client):
        """Should reject empty person name."""
        response = client.post("/api/briefing", json={"person_name": ""})
        assert response.status_code == 400

    def test_briefing_get_endpoint_exists(self, client):
        """GET briefing endpoint should exist."""
        response = client.get("/api/briefing/test")
        assert response.status_code != 404
        assert response.status_code != 405

    def test_briefing_returns_valid_response_structure(self, client):
        """Response should have valid structure."""
        with patch('api.routes.briefings.get_briefings_service') as mock_service:
            mock_service.return_value.generate_briefing = AsyncMock(
                return_value={
                    "status": "success",
                    "briefing": "Test briefing content",
                    "person_name": "Test Person",
                    "metadata": {},
                    "sources": [],
                }
            )

            response = client.post("/api/briefing", json={"person_name": "Test"})

            if response.status_code == 200:
                data = response.json()
                assert "status" in data
                assert "person_name" in data

    def test_briefing_includes_sources(self, client):
        """Briefing should include sources."""
        with patch('api.routes.briefings.get_briefings_service') as mock_service:
            mock_service.return_value.generate_briefing = AsyncMock(
                return_value={
                    "status": "success",
                    "briefing": "Briefing with sources",
                    "person_name": "Yoni",
                    "sources": ["Meeting Notes.md", "Strategy.md"],
                    "metadata": {},
                }
            )

            response = client.post("/api/briefing", json={"person_name": "Yoni"})

            if response.status_code == 200:
                data = response.json()
                assert "sources" in data
                assert isinstance(data.get("sources", []), list)

    def test_briefing_handles_not_found(self, client):
        """Should handle unknown person."""
        with patch('api.routes.briefings.get_briefings_service') as mock_service:
            mock_service.return_value.generate_briefing = AsyncMock(
                return_value={
                    "status": "not_found",
                    "message": "I don't have notes about this person",
                    "person_name": "Unknown Person",
                }
            )

            response = client.post("/api/briefing", json={"person_name": "Unknown Person"})

            # Should return 200 with status="not_found", not 404
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "not_found"

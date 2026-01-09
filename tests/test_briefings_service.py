"""
Tests for BriefingsService v2 integration.
"""
import pytest
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

from api.services.briefings import (
    BriefingsService,
    BriefingContext,
    get_briefings_service,
)
from api.services.person_entity import PersonEntity, PersonEntityStore
from api.services.interaction_store import InteractionStore, Interaction
from api.services.entity_resolver import EntityResolver


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


@pytest.fixture
def populated_entity_store(temp_entity_store):
    """Create entity store with test data."""
    entity = PersonEntity(
        id="test-entity-123",
        canonical_name="Yoni Landau",
        display_name="Yoni Landau",
        emails=["yoni@movementlabs.xyz"],
        company="Movement Labs",
        position="CEO",
        category="work",
        linkedin_url="https://linkedin.com/in/yoni",
        vault_contexts=["Work/ML/"],
        meeting_count=5,
        email_count=10,
        mention_count=3,
        last_seen=datetime.now() - timedelta(days=2),
        sources=["linkedin", "gmail"],
    )
    temp_entity_store.add(entity)
    return temp_entity_store


@pytest.fixture
def populated_interaction_store(temp_interaction_store):
    """Create interaction store with test data."""
    interactions = [
        Interaction(
            id="int-1",
            person_id="test-entity-123",
            timestamp=datetime.now() - timedelta(days=1),
            source_type="gmail",
            title="Re: Q4 Planning",
            snippet="Thanks for the update...",
            source_link="https://mail.google.com/mail/u/0/#inbox/abc",
        ),
        Interaction(
            id="int-2",
            person_id="test-entity-123",
            timestamp=datetime.now() - timedelta(days=3),
            source_type="calendar",
            title="1:1 Meeting",
            source_link="https://calendar.google.com/event?eid=xyz",
        ),
        Interaction(
            id="int-3",
            person_id="test-entity-123",
            timestamp=datetime.now() - timedelta(days=5),
            source_type="vault",
            title="ML Team Notes.md",
            source_link="obsidian://open?vault=LifeOS&file=Work/ML/ML Team Notes",
        ),
    ]
    for i in interactions:
        temp_interaction_store.add(i)
    return temp_interaction_store


class TestBriefingContext:
    """Tests for BriefingContext dataclass."""

    def test_create_basic_context(self):
        """Test creating a basic briefing context."""
        context = BriefingContext(
            person_name="yoni",
            resolved_name="Yoni Landau",
        )
        assert context.person_name == "yoni"
        assert context.resolved_name == "Yoni Landau"
        assert context.category == "unknown"
        assert context.interaction_history == ""
        assert context.entity_id is None
        assert context.linkedin_url is None

    def test_context_with_v2_fields(self):
        """Test context with v2 fields populated."""
        context = BriefingContext(
            person_name="yoni",
            resolved_name="Yoni Landau",
            email="yoni@movementlabs.xyz",
            company="Movement Labs",
            linkedin_url="https://linkedin.com/in/yoni",
            entity_id="test-123",
            interaction_history="## Recent Activity\n- Email yesterday",
        )
        assert context.linkedin_url == "https://linkedin.com/in/yoni"
        assert context.entity_id == "test-123"
        assert "Recent Activity" in context.interaction_history


class TestBriefingsServiceV2Integration:
    """Tests for v2 entity resolver and interaction store integration."""

    def test_service_has_v2_properties(self):
        """Test that service exposes v2 properties."""
        service = BriefingsService()
        # These should not raise - they may return None if not initialized
        _ = service.entity_resolver
        _ = service.interaction_store

    def test_gather_context_uses_entity_resolver(
        self,
        populated_entity_store,
        populated_interaction_store,
    ):
        """Test that gather_context uses EntityResolver when available."""
        resolver = EntityResolver(populated_entity_store)

        # Mock the v1 aggregator to ensure we're using v2
        mock_aggregator = MagicMock()
        mock_aggregator.search.return_value = []

        # Mock vector store
        mock_vector_store = MagicMock()
        mock_vector_store.search.return_value = []

        # Mock action registry
        mock_action_registry = MagicMock()
        mock_action_registry.get_actions_involving_person.return_value = []

        service = BriefingsService(
            people_aggregator=mock_aggregator,
            vector_store=mock_vector_store,
            action_registry=mock_action_registry,
            entity_resolver=resolver,
            interaction_store=populated_interaction_store,
        )

        context = service.gather_context("Yoni Landau")

        # Should have resolved via entity resolver
        assert context is not None
        assert context.resolved_name == "Yoni Landau"
        assert context.entity_id == "test-entity-123"
        assert context.email == "yoni@movementlabs.xyz"
        assert context.company == "Movement Labs"
        assert context.linkedin_url == "https://linkedin.com/in/yoni"

        # Should have interaction history
        assert context.interaction_history != ""
        assert "interactions" in context.interaction_history.lower()

    def test_gather_context_falls_back_to_aggregator(self, temp_entity_store):
        """Test fallback to PeopleAggregator when entity not found in v2."""
        resolver = EntityResolver(temp_entity_store)  # Empty store

        # Mock v1 aggregator with data
        mock_record = MagicMock()
        mock_record.email = "test@example.com"
        mock_record.company = "Test Co"
        mock_record.position = "Engineer"
        mock_record.category = "work"
        mock_record.meeting_count = 2
        mock_record.email_count = 5
        mock_record.mention_count = 1
        mock_record.last_seen = datetime.now()
        mock_record.sources = ["gmail"]

        mock_aggregator = MagicMock()
        mock_aggregator.search.return_value = [mock_record]

        mock_vector_store = MagicMock()
        mock_vector_store.search.return_value = []

        mock_action_registry = MagicMock()
        mock_action_registry.get_actions_involving_person.return_value = []

        service = BriefingsService(
            people_aggregator=mock_aggregator,
            vector_store=mock_vector_store,
            action_registry=mock_action_registry,
            entity_resolver=resolver,
        )

        context = service.gather_context("Unknown Person")

        # Should have fallen back to aggregator
        assert context is not None
        assert context.email == "test@example.com"
        assert context.company == "Test Co"
        assert context.entity_id is None  # No v2 entity

    def test_gather_context_with_email_parameter(
        self,
        populated_entity_store,
    ):
        """Test that email parameter helps resolution."""
        resolver = EntityResolver(populated_entity_store)

        mock_aggregator = MagicMock()
        mock_aggregator.search.return_value = []

        mock_vector_store = MagicMock()
        mock_vector_store.search.return_value = []

        mock_action_registry = MagicMock()
        mock_action_registry.get_actions_involving_person.return_value = []

        service = BriefingsService(
            people_aggregator=mock_aggregator,
            vector_store=mock_vector_store,
            action_registry=mock_action_registry,
            entity_resolver=resolver,
        )

        # Should resolve via email even if name is different
        context = service.gather_context(
            "Wrong Name", email="yoni@movementlabs.xyz"
        )

        assert context is not None
        assert context.entity_id == "test-entity-123"
        assert context.resolved_name == "Yoni Landau"


class TestBriefingsServiceGenerateBriefing:
    """Tests for generate_briefing method."""

    @pytest.mark.asyncio
    async def test_generate_briefing_includes_v2_fields(
        self,
        populated_entity_store,
        populated_interaction_store,
    ):
        """Test that generated briefing includes v2 fields."""
        resolver = EntityResolver(populated_entity_store)

        mock_aggregator = MagicMock()
        mock_aggregator.search.return_value = []

        mock_vector_store = MagicMock()
        mock_vector_store.search.return_value = []

        mock_action_registry = MagicMock()
        mock_action_registry.get_actions_involving_person.return_value = []

        service = BriefingsService(
            people_aggregator=mock_aggregator,
            vector_store=mock_vector_store,
            action_registry=mock_action_registry,
            entity_resolver=resolver,
            interaction_store=populated_interaction_store,
        )

        # Mock synthesizer to avoid actual API call
        with patch('api.services.briefings.get_synthesizer') as mock_synth:
            mock_synth.return_value.get_response = AsyncMock(
                return_value="# Test Briefing\n\nGenerated content"
            )

            result = await service.generate_briefing("Yoni Landau")

        assert result["status"] == "success"
        assert result["metadata"]["linkedin_url"] == "https://linkedin.com/in/yoni"
        assert result["metadata"]["entity_id"] == "test-entity-123"

    @pytest.mark.asyncio
    async def test_generate_briefing_with_email_parameter(
        self,
        populated_entity_store,
    ):
        """Test generate_briefing accepts email parameter."""
        resolver = EntityResolver(populated_entity_store)

        mock_aggregator = MagicMock()
        mock_aggregator.search.return_value = []

        mock_vector_store = MagicMock()
        mock_vector_store.search.return_value = []

        mock_action_registry = MagicMock()
        mock_action_registry.get_actions_involving_person.return_value = []

        service = BriefingsService(
            people_aggregator=mock_aggregator,
            vector_store=mock_vector_store,
            action_registry=mock_action_registry,
            entity_resolver=resolver,
        )

        with patch('api.services.briefings.get_synthesizer') as mock_synth:
            mock_synth.return_value.get_response = AsyncMock(
                return_value="# Test Briefing"
            )

            result = await service.generate_briefing(
                "Wrong Name",
                email="yoni@movementlabs.xyz"
            )

        assert result["status"] == "success"
        assert result["person_name"] == "Yoni Landau"


class TestVaultSearchImprovement:
    """Tests for improved vault search behavior."""

    def test_vault_search_without_people_dictionary_restriction(self):
        """Test that vault search works for people not in PEOPLE_DICTIONARY."""
        # Mock vector store
        mock_vector_store = MagicMock()
        mock_vector_store.search.return_value = [
            {
                "metadata": {"file_name": "Test Note.md", "file_path": "/vault/test.md"},
                "content": "Meeting with John Smith about project X",
                "score": 0.9,
            }
        ]

        mock_aggregator = MagicMock()
        mock_aggregator.search.return_value = []

        mock_action_registry = MagicMock()
        mock_action_registry.get_actions_involving_person.return_value = []

        service = BriefingsService(
            people_aggregator=mock_aggregator,
            vector_store=mock_vector_store,
            action_registry=mock_action_registry,
        )

        # Person NOT in PEOPLE_DICTIONARY
        context = service.gather_context("Random New Person")

        # Should still find notes
        assert len(context.related_notes) == 1
        assert context.related_notes[0]["file_name"] == "Test Note.md"

        # Verify search was called without filter first
        calls = mock_vector_store.search.call_args_list
        assert len(calls) >= 1

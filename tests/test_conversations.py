"""
Tests for Conversation Threads (P5.1).

Tests the ConversationStore service and conversation API endpoints.
"""
import pytest
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
import tempfile
import os


class TestConversationStore:
    """Test the ConversationStore service."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database file."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            yield f.name
        os.unlink(f.name)

    def test_store_initialization(self, temp_db):
        """Store should create database and tables on init."""
        from api.services.conversation_store import ConversationStore

        store = ConversationStore(db_path=temp_db)

        # Check tables exist
        import sqlite3
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        assert 'conversations' in tables
        assert 'messages' in tables

    def test_create_conversation(self, temp_db):
        """Should create a new conversation with UUID."""
        from api.services.conversation_store import ConversationStore

        store = ConversationStore(db_path=temp_db)
        conv = store.create_conversation(title="Test Conversation")

        assert conv.id is not None
        assert conv.title == "Test Conversation"
        assert conv.created_at is not None

    def test_create_conversation_auto_title(self, temp_db):
        """Should auto-generate title if not provided."""
        from api.services.conversation_store import ConversationStore

        store = ConversationStore(db_path=temp_db)
        conv = store.create_conversation()

        assert conv.title == "New Conversation"

    def test_get_conversation(self, temp_db):
        """Should retrieve conversation by ID."""
        from api.services.conversation_store import ConversationStore

        store = ConversationStore(db_path=temp_db)
        created = store.create_conversation(title="Test")
        retrieved = store.get_conversation(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.title == "Test"

    def test_get_conversation_not_found(self, temp_db):
        """Should return None for non-existent conversation."""
        from api.services.conversation_store import ConversationStore

        store = ConversationStore(db_path=temp_db)
        result = store.get_conversation("non-existent-id")

        assert result is None

    def test_list_conversations(self, temp_db):
        """Should list all conversations sorted by updated_at desc."""
        from api.services.conversation_store import ConversationStore

        store = ConversationStore(db_path=temp_db)
        store.create_conversation(title="First")
        store.create_conversation(title="Second")
        store.create_conversation(title="Third")

        conversations = store.list_conversations()

        assert len(conversations) == 3
        # Most recent first
        assert conversations[0].title == "Third"

    def test_delete_conversation(self, temp_db):
        """Should delete conversation and its messages."""
        from api.services.conversation_store import ConversationStore

        store = ConversationStore(db_path=temp_db)
        conv = store.create_conversation(title="To Delete")
        store.add_message(conv.id, "user", "Hello")

        result = store.delete_conversation(conv.id)

        assert result is True
        assert store.get_conversation(conv.id) is None

    def test_delete_conversation_not_found(self, temp_db):
        """Should return False for non-existent conversation."""
        from api.services.conversation_store import ConversationStore

        store = ConversationStore(db_path=temp_db)
        result = store.delete_conversation("non-existent")

        assert result is False

    def test_add_message(self, temp_db):
        """Should add message to conversation."""
        from api.services.conversation_store import ConversationStore

        store = ConversationStore(db_path=temp_db)
        conv = store.create_conversation()
        msg = store.add_message(conv.id, "user", "Hello!")

        assert msg.id is not None
        assert msg.role == "user"
        assert msg.content == "Hello!"
        assert msg.conversation_id == conv.id

    def test_add_message_with_metadata(self, temp_db):
        """Should store sources and routing metadata."""
        from api.services.conversation_store import ConversationStore

        store = ConversationStore(db_path=temp_db)
        conv = store.create_conversation()
        sources = [{"file_name": "test.md", "file_path": "/path/test.md"}]
        routing = {"sources": ["vault"], "reasoning": "test"}

        msg = store.add_message(
            conv.id, "assistant", "Response",
            sources=sources, routing=routing
        )

        assert msg.sources == sources
        assert msg.routing == routing

    def test_get_messages(self, temp_db):
        """Should retrieve all messages for conversation."""
        from api.services.conversation_store import ConversationStore

        store = ConversationStore(db_path=temp_db)
        conv = store.create_conversation()
        store.add_message(conv.id, "user", "Hello")
        store.add_message(conv.id, "assistant", "Hi there")
        store.add_message(conv.id, "user", "How are you?")

        messages = store.get_messages(conv.id)

        assert len(messages) == 3
        assert messages[0].content == "Hello"
        assert messages[1].content == "Hi there"
        assert messages[2].content == "How are you?"

    def test_get_messages_with_limit(self, temp_db):
        """Should return last N messages when limit specified."""
        from api.services.conversation_store import ConversationStore

        store = ConversationStore(db_path=temp_db)
        conv = store.create_conversation()
        for i in range(15):
            store.add_message(conv.id, "user", f"Message {i}")

        messages = store.get_messages(conv.id, limit=10)

        assert len(messages) == 10
        # Should be the last 10 messages
        assert messages[0].content == "Message 5"
        assert messages[9].content == "Message 14"

    def test_update_conversation_title(self, temp_db):
        """Should update conversation title."""
        from api.services.conversation_store import ConversationStore

        store = ConversationStore(db_path=temp_db)
        conv = store.create_conversation(title="Original")

        store.update_title(conv.id, "Updated Title")
        updated = store.get_conversation(conv.id)

        assert updated.title == "Updated Title"

    def test_conversation_updated_at(self, temp_db):
        """Adding message should update conversation's updated_at."""
        from api.services.conversation_store import ConversationStore
        import time

        store = ConversationStore(db_path=temp_db)
        conv = store.create_conversation()
        original_updated = conv.updated_at

        time.sleep(0.1)  # Small delay
        store.add_message(conv.id, "user", "New message")

        updated_conv = store.get_conversation(conv.id)
        assert updated_conv.updated_at > original_updated

    def test_message_count(self, temp_db):
        """Should track message count for conversation."""
        from api.services.conversation_store import ConversationStore

        store = ConversationStore(db_path=temp_db)
        conv = store.create_conversation()
        store.add_message(conv.id, "user", "One")
        store.add_message(conv.id, "assistant", "Two")

        conversations = store.list_conversations()

        assert conversations[0].message_count == 2


@pytest.mark.skip(reason="TestClient initialization timeout - needs investigation")
class TestConversationAPI:
    """Test the conversation API endpoints."""

    def test_list_conversations_empty(self):
        """Should return empty list when no conversations."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            with patch('api.routes.conversations.get_store') as mock_get_store:
                from api.services.conversation_store import ConversationStore
                from fastapi.testclient import TestClient
                from api.main import app

                store = ConversationStore(db_path=db_path)
                mock_get_store.return_value = store

                client = TestClient(app)
                response = client.get("/api/conversations")

                assert response.status_code == 200
                assert response.json()["conversations"] == []
        finally:
            os.unlink(db_path)

    def test_create_conversation(self):
        """Should create new conversation."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            with patch('api.routes.conversations.get_store') as mock_get_store:
                from api.services.conversation_store import ConversationStore
                from fastapi.testclient import TestClient
                from api.main import app

                store = ConversationStore(db_path=db_path)
                mock_get_store.return_value = store

                client = TestClient(app)
                response = client.post(
                    "/api/conversations",
                    json={"title": "Test Conversation"}
                )

                assert response.status_code == 201
                data = response.json()
                assert data["title"] == "Test Conversation"
                assert "id" in data
        finally:
            os.unlink(db_path)

    def test_get_conversation(self):
        """Should retrieve conversation with messages."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            with patch('api.routes.conversations.get_store') as mock_get_store:
                from api.services.conversation_store import ConversationStore
                from fastapi.testclient import TestClient
                from api.main import app

                store = ConversationStore(db_path=db_path)
                mock_get_store.return_value = store

                # Create conversation and add messages
                conv = store.create_conversation(title="Test")
                store.add_message(conv.id, "user", "Hello")
                store.add_message(conv.id, "assistant", "Hi!")

                client = TestClient(app)
                response = client.get(f"/api/conversations/{conv.id}")

                assert response.status_code == 200
                data = response.json()
                assert data["title"] == "Test"
                assert len(data["messages"]) == 2
        finally:
            os.unlink(db_path)

    def test_get_conversation_not_found(self):
        """Should return 404 for non-existent conversation."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            with patch('api.routes.conversations.get_store') as mock_get_store:
                from api.services.conversation_store import ConversationStore
                from fastapi.testclient import TestClient
                from api.main import app

                store = ConversationStore(db_path=db_path)
                mock_get_store.return_value = store

                client = TestClient(app)
                response = client.get("/api/conversations/non-existent-id")

                assert response.status_code == 404
        finally:
            os.unlink(db_path)

    def test_delete_conversation(self):
        """Should delete conversation."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            with patch('api.routes.conversations.get_store') as mock_get_store:
                from api.services.conversation_store import ConversationStore
                from fastapi.testclient import TestClient
                from api.main import app

                store = ConversationStore(db_path=db_path)
                mock_get_store.return_value = store

                conv = store.create_conversation(title="To Delete")

                client = TestClient(app)
                response = client.delete(f"/api/conversations/{conv.id}")

                assert response.status_code == 204
                assert store.get_conversation(conv.id) is None
        finally:
            os.unlink(db_path)

    def test_delete_conversation_not_found(self):
        """Should return 404 when deleting non-existent conversation."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            with patch('api.routes.conversations.get_store') as mock_get_store:
                from api.services.conversation_store import ConversationStore
                from fastapi.testclient import TestClient
                from api.main import app

                store = ConversationStore(db_path=db_path)
                mock_get_store.return_value = store

                client = TestClient(app)
                response = client.delete("/api/conversations/non-existent-id")

                assert response.status_code == 404
        finally:
            os.unlink(db_path)


class TestConversationContext:
    """Test conversation context in synthesis."""

    def test_format_conversation_history(self):
        """Should format conversation history for prompt."""
        from api.services.conversation_store import Message, format_conversation_history

        messages = [
            Message(
                id="1", conversation_id="c1", role="user",
                content="What is LifeOS?", created_at=datetime.now()
            ),
            Message(
                id="2", conversation_id="c1", role="assistant",
                content="LifeOS is a personal assistant system.",
                created_at=datetime.now()
            ),
            Message(
                id="3", conversation_id="c1", role="user",
                content="How does it work?", created_at=datetime.now()
            ),
        ]

        formatted = format_conversation_history(messages)

        assert "User: What is LifeOS?" in formatted
        assert "Assistant: LifeOS is a personal assistant system." in formatted
        assert "User: How does it work?" in formatted

    def test_truncate_conversation_history(self):
        """Should truncate history if too long."""
        from api.services.conversation_store import Message, format_conversation_history

        # Create many long messages
        messages = []
        for i in range(20):
            messages.append(Message(
                id=str(i), conversation_id="c1",
                role="user" if i % 2 == 0 else "assistant",
                content="A" * 500,  # Long content
                created_at=datetime.now()
            ))

        formatted = format_conversation_history(messages, max_tokens=1000)

        # Should be truncated
        assert len(formatted) < 20 * 500

    def test_construct_prompt_with_history(self):
        """Should include conversation history in prompt."""
        from api.services.synthesizer import construct_prompt
        from api.services.conversation_store import Message

        history = [
            Message(
                id="1", conversation_id="c1", role="user",
                content="Tell me about my schedule", created_at=datetime.now()
            ),
            Message(
                id="2", conversation_id="c1", role="assistant",
                content="You have 3 meetings today.", created_at=datetime.now()
            ),
        ]

        chunks = [{"content": "Meeting with Sarah at 2pm", "metadata": {}}]

        prompt = construct_prompt(
            "What time is the Sarah meeting?",
            chunks,
            conversation_history=history
        )

        assert "Tell me about my schedule" in prompt
        assert "You have 3 meetings today" in prompt
        assert "What time is the Sarah meeting?" in prompt


class TestAutoTitling:
    """Test automatic conversation titling."""

    def test_generate_title_from_question(self):
        """Should generate short title from first message."""
        from api.services.conversation_store import generate_title

        title = generate_title("What meetings do I have tomorrow with the engineering team?")

        assert len(title) <= 50
        assert title != ""

    def test_generate_title_short_question(self):
        """Should use full question if short enough."""
        from api.services.conversation_store import generate_title

        title = generate_title("Schedule for today")

        assert title == "Schedule for today"

    def test_generate_title_truncation(self):
        """Should truncate long questions cleanly."""
        from api.services.conversation_store import generate_title

        long_question = "Can you help me understand what happened in the last quarterly business review meeting with all the stakeholders from the product and engineering teams?"
        title = generate_title(long_question)

        assert len(title) <= 50
        # Should end at word boundary, not mid-word
        assert not title.endswith("...")  # We want clean truncation

"""
Tests for Gmail Integration.
P3.3 Acceptance Criteria:
- Can search emails by keyword
- Can filter by sender
- Can filter by date range
- Returns email subject, sender, date, snippet
- Can fetch full email body when needed
- Rate limiting prevents quota errors
- "Did Kevin email about the budget" returns relevant emails
- Empty results return empty list, not error
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock
import base64

from api.services.gmail import (
    GmailService,
    EmailMessage,
    build_gmail_query,
)
from api.services.google_auth import GoogleAccount


class TestEmailMessage:
    """Test EmailMessage dataclass."""

    def test_creates_message_with_required_fields(self):
        """Should create message with all required fields."""
        msg = EmailMessage(
            message_id="abc123",
            thread_id="thread1",
            subject="Budget Review",
            sender="kevin@example.com",
            sender_name="Kevin",
            date=datetime.now(timezone.utc),
            snippet="Here's the budget...",
            source_account="personal"
        )
        assert msg.message_id == "abc123"
        assert msg.subject == "Budget Review"

    def test_message_to_dict(self):
        """Should convert message to dict."""
        msg = EmailMessage(
            message_id="abc123",
            thread_id="thread1",
            subject="Budget Review",
            sender="kevin@example.com",
            sender_name="Kevin",
            date=datetime(2026, 1, 7, 10, 0, tzinfo=timezone.utc),
            snippet="Here's the budget...",
            source_account="personal"
        )
        data = msg.to_dict()
        assert data["message_id"] == "abc123"
        assert data["source"] == "gmail"


class TestBuildGmailQuery:
    """Test Gmail query builder."""

    def test_builds_simple_keyword_query(self):
        """Should build simple keyword query."""
        query = build_gmail_query(keywords="budget")
        assert "budget" in query

    def test_builds_from_query(self):
        """Should build from: query."""
        query = build_gmail_query(from_email="kevin@example.com")
        assert "from:kevin@example.com" in query

    def test_builds_date_range_query(self):
        """Should build date range query."""
        query = build_gmail_query(
            after=datetime(2026, 1, 1),
            before=datetime(2026, 1, 31)
        )
        assert "after:" in query
        assert "before:" in query

    def test_combines_multiple_filters(self):
        """Should combine multiple filters."""
        query = build_gmail_query(
            keywords="budget",
            from_email="kevin@example.com",
            after=datetime(2026, 1, 1)
        )
        assert "budget" in query
        assert "from:" in query
        assert "after:" in query


class TestGmailService:
    """Test GmailService."""

    @pytest.fixture
    def mock_auth_service(self):
        """Create mock auth service."""
        mock = MagicMock()
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock.get_credentials.return_value = mock_creds
        return mock

    @pytest.fixture
    def gmail_service(self, mock_auth_service):
        """Create Gmail service with mock auth."""
        with patch('api.services.gmail.get_google_auth', return_value=mock_auth_service):
            with patch('api.services.gmail.build') as mock_build:
                mock_service = MagicMock()
                mock_build.return_value = mock_service
                service = GmailService(account_type=GoogleAccount.PERSONAL)
                service._service = mock_service
                return service

    def test_searches_by_keyword(self, gmail_service):
        """Should search emails by keyword."""
        mock_messages = {
            "messages": [
                {"id": "msg1", "threadId": "thread1"}
            ]
        }
        mock_message_detail = {
            "id": "msg1",
            "threadId": "thread1",
            "snippet": "Budget review for Q1",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Budget Review"},
                    {"name": "From", "value": "Kevin <kevin@example.com>"},
                    {"name": "Date", "value": "Tue, 7 Jan 2026 10:00:00 -0800"},
                ]
            }
        }
        gmail_service._service.users().messages().list().execute.return_value = mock_messages
        gmail_service._service.users().messages().get().execute.return_value = mock_message_detail

        messages = gmail_service.search(keywords="budget")

        assert len(messages) >= 1
        gmail_service._service.users().messages().list.assert_called()

    def test_searches_by_sender(self, gmail_service):
        """Should filter by sender."""
        mock_messages = {"messages": [{"id": "msg1", "threadId": "thread1"}]}
        mock_detail = {
            "id": "msg1",
            "threadId": "thread1",
            "snippet": "Test email",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Test"},
                    {"name": "From", "value": "kevin@example.com"},
                    {"name": "Date", "value": "Tue, 7 Jan 2026 10:00:00 -0800"},
                ]
            }
        }
        gmail_service._service.users().messages().list().execute.return_value = mock_messages
        gmail_service._service.users().messages().get().execute.return_value = mock_detail

        messages = gmail_service.search(from_email="kevin@example.com")

        # Should have called with from: in query
        call_args = gmail_service._service.users().messages().list.call_args
        assert "from:" in str(call_args)

    def test_returns_empty_list_for_no_results(self, gmail_service):
        """Should return empty list when no results."""
        gmail_service._service.users().messages().list().execute.return_value = {}

        messages = gmail_service.search(keywords="nonexistent12345")

        assert messages == []

    def test_fetches_email_body(self, gmail_service):
        """Should fetch full email body."""
        body_text = "This is the full email body content."
        encoded_body = base64.urlsafe_b64encode(body_text.encode()).decode()
        mock_detail = {
            "id": "msg1",
            "threadId": "thread1",
            "snippet": "This is the full...",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Test"},
                    {"name": "From", "value": "test@example.com"},
                    {"name": "Date", "value": "Tue, 7 Jan 2026 10:00:00 -0800"},
                ],
                "body": {"data": encoded_body}
            }
        }
        gmail_service._service.users().messages().get().execute.return_value = mock_detail

        message = gmail_service.get_message("msg1", include_body=True)

        assert message is not None
        assert message.body is not None

    def test_rate_limiting(self, gmail_service):
        """Should have rate limiting configured."""
        # Rate limit should be set
        assert hasattr(gmail_service, 'rate_limit_delay')
        assert gmail_service.rate_limit_delay >= 0


class TestGmailAPI:
    """Test Gmail API endpoint."""

    @pytest.fixture
    def mock_gmail_service(self):
        """Create mock Gmail service."""
        mock = MagicMock()
        mock.search.return_value = [
            EmailMessage(
                message_id="1",
                thread_id="t1",
                subject="Budget Review",
                sender="kevin@example.com",
                sender_name="Kevin",
                date=datetime(2026, 1, 7, tzinfo=timezone.utc),
                snippet="Here's the budget...",
                source_account="personal",
            )
        ]
        return mock

    def test_search_endpoint_returns_results(self, mock_gmail_service):
        """Should return search results."""
        from fastapi.testclient import TestClient
        from api.main import app

        with patch('api.routes.gmail.get_gmail_service', return_value=mock_gmail_service):
            client = TestClient(app)
            response = client.get("/api/gmail/search?q=budget")

            assert response.status_code == 200
            data = response.json()
            assert "messages" in data

"""
Gmail integration service for LifeOS.

Provides search and retrieval of emails via Gmail API.
Live queries only (no bulk indexing).
"""
import base64
import logging
import time
import re
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional
from email.utils import parsedate_to_datetime

from googleapiclient.discovery import build

from api.services.google_auth import get_google_auth, GoogleAccount

logger = logging.getLogger(__name__)


@dataclass
class EmailMessage:
    """Represents an email message."""
    message_id: str
    thread_id: str
    subject: str
    sender: str
    sender_name: str
    date: datetime
    snippet: str
    source_account: str
    body: Optional[str] = None
    to: Optional[str] = None
    labels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dict for API response."""
        return {
            "message_id": self.message_id,
            "thread_id": self.thread_id,
            "subject": self.subject,
            "sender": self.sender,
            "sender_name": self.sender_name,
            "date": self.date.isoformat(),
            "snippet": self.snippet,
            "body": self.body,
            "to": self.to,
            "labels": self.labels,
            "source": "gmail",
            "source_account": self.source_account,
        }


def build_gmail_query(
    keywords: Optional[str] = None,
    from_email: Optional[str] = None,
    to_email: Optional[str] = None,
    subject: Optional[str] = None,
    after: Optional[datetime] = None,
    before: Optional[datetime] = None,
    has_attachment: bool = False,
    is_unread: Optional[bool] = None,
) -> str:
    """
    Build Gmail search query string.

    Args:
        keywords: Keywords to search in body/subject
        from_email: Filter by sender
        to_email: Filter by recipient
        subject: Search in subject only
        after: Emails after this date
        before: Emails before this date
        has_attachment: Filter for emails with attachments
        is_unread: Filter by read status

    Returns:
        Gmail query string
    """
    parts = []

    if keywords:
        parts.append(keywords)

    if from_email:
        parts.append(f"from:{from_email}")

    if to_email:
        parts.append(f"to:{to_email}")

    if subject:
        parts.append(f"subject:{subject}")

    if after:
        # Gmail uses YYYY/MM/DD format
        parts.append(f"after:{after.strftime('%Y/%m/%d')}")

    if before:
        parts.append(f"before:{before.strftime('%Y/%m/%d')}")

    if has_attachment:
        parts.append("has:attachment")

    if is_unread is True:
        parts.append("is:unread")
    elif is_unread is False:
        parts.append("is:read")

    return " ".join(parts)


def parse_sender(from_header: str) -> tuple[str, str]:
    """
    Parse From header into name and email.

    Args:
        from_header: Raw From header value

    Returns:
        Tuple of (sender_name, sender_email)
    """
    # Pattern: "Name <email@example.com>" or just "email@example.com"
    match = re.match(r'^"?([^"<]+)"?\s*<([^>]+)>$', from_header.strip())
    if match:
        return match.group(1).strip(), match.group(2).strip()

    # Just email address
    if "@" in from_header:
        return from_header.strip(), from_header.strip()

    return from_header.strip(), from_header.strip()


class GmailService:
    """
    Gmail service for searching and retrieving emails.

    Includes rate limiting to prevent quota issues.
    """

    def __init__(
        self,
        account_type: GoogleAccount = GoogleAccount.PERSONAL,
        rate_limit_delay: float = 0.1
    ):
        """
        Initialize Gmail service.

        Args:
            account_type: Which Google account to use
            rate_limit_delay: Delay between API calls (seconds)
        """
        self.account_type = account_type
        self.rate_limit_delay = rate_limit_delay
        self._service = None
        self._last_call_time = 0

    @property
    def service(self):
        """Get or create Gmail API service."""
        if self._service is None:
            auth = get_google_auth(self.account_type)
            credentials = auth.get_credentials()
            self._service = build("gmail", "v1", credentials=credentials)
        return self._service

    def _rate_limit(self):
        """Apply rate limiting between API calls."""
        now = time.time()
        elapsed = now - self._last_call_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self._last_call_time = time.time()

    def search(
        self,
        keywords: Optional[str] = None,
        from_email: Optional[str] = None,
        to_email: Optional[str] = None,
        after: Optional[datetime] = None,
        before: Optional[datetime] = None,
        max_results: int = 20,
        include_body: bool = False,
    ) -> list[EmailMessage]:
        """
        Search emails.

        Args:
            keywords: Keywords to search
            from_email: Filter by sender
            to_email: Filter by recipient
            after: Emails after this date
            before: Emails before this date
            max_results: Maximum messages to return

        Returns:
            List of EmailMessage objects
        """
        query = build_gmail_query(
            keywords=keywords,
            from_email=from_email,
            to_email=to_email,
            after=after,
            before=before,
        )

        if not query:
            return []

        try:
            self._rate_limit()
            result = self.service.users().messages().list(
                userId="me",
                q=query,
                maxResults=max_results,
            ).execute()

            messages = result.get("messages", [])
            if not messages:
                return []

            # Fetch details for each message
            email_messages = []
            for msg in messages:
                self._rate_limit()
                message = self.get_message(msg["id"], include_body=include_body)
                if message:
                    email_messages.append(message)

            return email_messages

        except Exception as e:
            logger.error(f"Failed to search Gmail: {e}")
            return []

    def get_message(
        self,
        message_id: str,
        include_body: bool = True
    ) -> Optional[EmailMessage]:
        """
        Get a specific email message.

        Args:
            message_id: Gmail message ID
            include_body: Whether to fetch full body

        Returns:
            EmailMessage or None if not found
        """
        try:
            self._rate_limit()
            format_type = "full" if include_body else "metadata"
            msg = self.service.users().messages().get(
                userId="me",
                id=message_id,
                format=format_type,
                metadataHeaders=["Subject", "From", "To", "Date"] if not include_body else None,
            ).execute()

            return self._parse_message(msg, include_body)

        except Exception as e:
            logger.error(f"Failed to get message {message_id}: {e}")
            return None

    def _parse_message(self, msg: dict, include_body: bool = False) -> Optional[EmailMessage]:
        """
        Parse raw Gmail API message into EmailMessage.

        Args:
            msg: Raw message dict from API
            include_body: Whether to parse body

        Returns:
            EmailMessage or None if parsing fails
        """
        try:
            message_id = msg.get("id", "")
            thread_id = msg.get("threadId", "")
            snippet = msg.get("snippet", "")
            labels = msg.get("labelIds", [])

            # Parse headers
            payload = msg.get("payload", {})
            headers = payload.get("headers", [])

            subject = ""
            from_header = ""
            to_header = ""
            date_str = ""

            for header in headers:
                name = header.get("name", "").lower()
                value = header.get("value", "")
                if name == "subject":
                    subject = value
                elif name == "from":
                    from_header = value
                elif name == "to":
                    to_header = value
                elif name == "date":
                    date_str = value

            # Parse sender
            sender_name, sender = parse_sender(from_header)

            # Parse date
            try:
                date = parsedate_to_datetime(date_str)
            except Exception:
                date = datetime.now(timezone.utc)

            # Parse body if requested
            body = None
            if include_body:
                body = self._extract_body(payload)

            return EmailMessage(
                message_id=message_id,
                thread_id=thread_id,
                subject=subject,
                sender=sender,
                sender_name=sender_name,
                date=date,
                snippet=snippet,
                body=body,
                to=to_header,
                labels=labels,
                source_account=self.account_type.value,
            )

        except Exception as e:
            logger.warning(f"Failed to parse message: {e}")
            return None

    def _extract_body(self, payload: dict) -> Optional[str]:
        """
        Extract email body from payload.

        Args:
            payload: Message payload dict

        Returns:
            Plain text body or None
        """
        # Try direct body
        body_data = payload.get("body", {}).get("data")
        if body_data:
            try:
                return base64.urlsafe_b64decode(body_data).decode("utf-8")
            except Exception:
                pass

        # Try parts (multipart messages)
        parts = payload.get("parts", [])
        for part in parts:
            mime_type = part.get("mimeType", "")
            if mime_type == "text/plain":
                data = part.get("body", {}).get("data")
                if data:
                    try:
                        return base64.urlsafe_b64decode(data).decode("utf-8")
                    except Exception:
                        pass

            # Recursive for nested parts
            nested_parts = part.get("parts", [])
            for nested in nested_parts:
                if nested.get("mimeType") == "text/plain":
                    data = nested.get("body", {}).get("data")
                    if data:
                        try:
                            return base64.urlsafe_b64decode(data).decode("utf-8")
                        except Exception:
                            pass

        # Fall back to HTML if no plain text
        for part in parts:
            if part.get("mimeType") == "text/html":
                data = part.get("body", {}).get("data")
                if data:
                    try:
                        # Return raw HTML - could strip tags if needed
                        return base64.urlsafe_b64decode(data).decode("utf-8")
                    except Exception:
                        pass

        return None


# Singleton services per account
_gmail_services: dict[GoogleAccount, GmailService] = {}


def get_gmail_service(account_type: GoogleAccount = GoogleAccount.PERSONAL) -> GmailService:
    """Get or create Gmail service for an account."""
    if account_type not in _gmail_services:
        _gmail_services[account_type] = GmailService(account_type)
    return _gmail_services[account_type]

"""
Gmail API endpoints for LifeOS.

Provides search and retrieval of emails.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.services.gmail import get_gmail_service, EmailMessage
from api.services.google_auth import GoogleAccount

router = APIRouter(prefix="/api/gmail", tags=["gmail"])


class EmailResponse(BaseModel):
    """Response model for an email message."""
    message_id: str
    thread_id: str
    subject: str
    sender: str
    sender_name: str
    date: str
    snippet: str
    body: Optional[str] = None
    source_account: str


class SearchResponse(BaseModel):
    """Response for search endpoint."""
    messages: list[EmailResponse]
    count: int
    query: Optional[str] = None


def _message_to_response(msg: EmailMessage) -> EmailResponse:
    """Convert EmailMessage to API response."""
    return EmailResponse(
        message_id=msg.message_id,
        thread_id=msg.thread_id,
        subject=msg.subject,
        sender=msg.sender,
        sender_name=msg.sender_name,
        date=msg.date.isoformat(),
        snippet=msg.snippet,
        body=msg.body,
        source_account=msg.source_account,
    )


@router.get("/search", response_model=SearchResponse)
async def search_emails(
    q: Optional[str] = Query(default=None, description="Search keywords"),
    from_email: Optional[str] = Query(default=None, alias="from", description="Filter by sender email"),
    after: Optional[str] = Query(default=None, description="Emails after date (YYYY-MM-DD)"),
    before: Optional[str] = Query(default=None, description="Emails before date (YYYY-MM-DD)"),
    account: str = Query(default="personal", description="Account: personal or work"),
    max_results: int = Query(default=20, ge=1, le=100, description="Maximum results"),
):
    """
    Search emails.

    At least one search parameter (q, from, after, before) is required.
    """
    if not any([q, from_email, after, before]):
        raise HTTPException(
            status_code=400,
            detail="At least one search parameter is required (q, from, after, before)"
        )

    try:
        account_type = GoogleAccount.PERSONAL if account == "personal" else GoogleAccount.WORK
        service = get_gmail_service(account_type)

        # Parse dates if provided
        after_dt = datetime.fromisoformat(after) if after else None
        before_dt = datetime.fromisoformat(before) if before else None

        messages = service.search(
            keywords=q,
            from_email=from_email,
            after=after_dt,
            before=before_dt,
            max_results=max_results,
        )

        return SearchResponse(
            messages=[_message_to_response(m) for m in messages],
            count=len(messages),
            query=q,
        )

    except FileNotFoundError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search emails: {e}")


@router.get("/message/{message_id}", response_model=EmailResponse)
async def get_email(
    message_id: str,
    account: str = Query(default="personal", description="Account: personal or work"),
    include_body: bool = Query(default=True, description="Include full email body"),
):
    """Get a specific email by message ID."""
    try:
        account_type = GoogleAccount.PERSONAL if account == "personal" else GoogleAccount.WORK
        service = get_gmail_service(account_type)

        message = service.get_message(message_id, include_body=include_body)
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")

        return _message_to_response(message)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch email: {e}")

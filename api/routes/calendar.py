"""
Calendar API endpoints for LifeOS.

Provides access to Google Calendar events.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.services.calendar import (
    get_calendar_service,
    CalendarEvent,
    format_event_time,
)
from api.services.google_auth import GoogleAccount

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


class EventResponse(BaseModel):
    """Response model for a calendar event."""
    event_id: str
    title: str
    start_time: str
    end_time: str
    start_formatted: str
    end_formatted: str
    attendees: list[str]
    description: Optional[str] = None
    location: Optional[str] = None
    is_all_day: bool
    source_account: str


class UpcomingResponse(BaseModel):
    """Response for upcoming events endpoint."""
    events: list[EventResponse]
    count: int
    account: str


class SearchResponse(BaseModel):
    """Response for search endpoint."""
    events: list[EventResponse]
    count: int
    query: Optional[str] = None
    attendee: Optional[str] = None


def _event_to_response(event: CalendarEvent) -> EventResponse:
    """Convert CalendarEvent to API response."""
    return EventResponse(
        event_id=event.event_id,
        title=event.title,
        start_time=event.start_time.isoformat(),
        end_time=event.end_time.isoformat(),
        start_formatted=format_event_time(event.start_time, event.is_all_day),
        end_formatted=format_event_time(event.end_time, event.is_all_day),
        attendees=event.attendees,
        description=event.description,
        location=event.location,
        is_all_day=event.is_all_day,
        source_account=event.source_account,
    )


@router.get("/upcoming", response_model=UpcomingResponse)
async def get_upcoming_events(
    days: int = Query(default=7, ge=1, le=30, description="Number of days to look ahead"),
    account: str = Query(default="personal", description="Account: personal or work"),
    max_results: int = Query(default=50, ge=1, le=100, description="Maximum events to return"),
):
    """
    **Get upcoming calendar events** from Google Calendar.

    Use this to answer questions like:
    - "What's on my calendar today/this week?"
    - "Do I have any meetings tomorrow?"
    - "What's my schedule for the next few days?"

    Returns event title, start/end times, attendees, location, and description.
    Query both `account=personal` AND `account=work` for complete schedule.
    """
    try:
        account_type = GoogleAccount.PERSONAL if account == "personal" else GoogleAccount.WORK
        service = get_calendar_service(account_type)
        events = service.get_upcoming_events(days=days, max_results=max_results)

        return UpcomingResponse(
            events=[_event_to_response(e) for e in events],
            count=len(events),
            account=account,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch calendar events: {e}")


@router.get("/search", response_model=SearchResponse)
async def search_events(
    q: Optional[str] = Query(default=None, description="Search query for title/description"),
    attendee: Optional[str] = Query(default=None, description="Filter by attendee name/email"),
    account: str = Query(default="personal", description="Account: personal or work"),
    days_back: int = Query(default=30, ge=1, le=365, description="Days to search in the past"),
    days_forward: int = Query(default=30, ge=1, le=365, description="Days to search in the future"),
):
    """
    **Search calendar events** by keyword or attendee.

    Use this for:
    - "When did I last meet with John?" → `attendee=john@email.com`
    - "Find meetings about project X" → `q=project X`
    - "When is my next 1:1 with Sarah?" → `attendee=sarah@email.com`

    **TIP**: Use `people_v2_resolve` first to get attendee's email for accurate filtering.

    Searches past 30 days and future 30 days by default.
    Query both personal and work accounts for complete results.
    """
    if not q and not attendee:
        raise HTTPException(
            status_code=400,
            detail="At least one of 'q' (query) or 'attendee' is required"
        )

    try:
        account_type = GoogleAccount.PERSONAL if account == "personal" else GoogleAccount.WORK
        service = get_calendar_service(account_type)
        events = service.search_events(
            query=q,
            attendee=attendee,
            days_back=days_back,
            days_forward=days_forward,
        )

        return SearchResponse(
            events=[_event_to_response(e) for e in events],
            count=len(events),
            query=q,
            attendee=attendee,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search calendar events: {e}")


@router.get("/events/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: str,
    account: str = Query(default="personal", description="Account: personal or work"),
):
    """Get a specific calendar event by ID."""
    try:
        account_type = GoogleAccount.PERSONAL if account == "personal" else GoogleAccount.WORK
        service = get_calendar_service(account_type)

        # Fetch from API directly
        result = service.service.events().get(
            calendarId="primary",
            eventId=event_id
        ).execute()

        event = service._parse_event(result)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")

        return _event_to_response(event)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch event: {e}")

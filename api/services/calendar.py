"""
Calendar integration service for LifeOS.

Uses iCalBuddy to fetch events from macOS Calendar app.
Falls back to Google Calendar API if iCalBuddy is unavailable.
"""
import logging
import shutil
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Check if iCalBuddy is available
ICALBUDDY_PATH = shutil.which("icalBuddy") or "/opt/homebrew/bin/icalBuddy"
USE_ICALBUDDY = shutil.which("icalBuddy") is not None or __import__("pathlib").Path(ICALBUDDY_PATH).exists()

if USE_ICALBUDDY:
    logger.info("Using iCalBuddy for calendar access")
    from api.services.calendar_icalbuddy import (
        CalendarService,
        CalendarEvent,
        CalendarAttachment,
        format_event_time,
        get_calendar_service,
        GoogleAccount,
        get_all_events_today,
        get_all_events_in_range,
    )
else:
    logger.info("iCalBuddy not found, falling back to Google Calendar API")
    # Import original Google Calendar implementation
    from api.services.calendar_google import (
        CalendarService,
        CalendarEvent,
        CalendarAttachment,
        format_event_time,
        get_calendar_service,
        GoogleAccount,
    )

    def get_all_events_today():
        """Get all events for today from all configured calendars."""
        events = []
        for account in [GoogleAccount.PERSONAL, GoogleAccount.WORK]:
            try:
                service = get_calendar_service(account)
                events.extend(service.get_upcoming_events(days=0))
            except Exception as e:
                logger.warning(f"Failed to get events from {account}: {e}")
        events.sort(key=lambda e: e.start_time)
        return events

    def get_all_events_in_range(start_date: datetime, end_date: datetime):
        """Get all events in range from all configured calendars."""
        events = []
        for account in [GoogleAccount.PERSONAL, GoogleAccount.WORK]:
            try:
                service = get_calendar_service(account)
                events.extend(service.get_events_in_range(start_date, end_date))
            except Exception as e:
                logger.warning(f"Failed to get events from {account}: {e}")
        events.sort(key=lambda e: e.start_time)
        return events


# Re-export for backwards compatibility
__all__ = [
    "CalendarService",
    "CalendarEvent",
    "CalendarAttachment",
    "format_event_time",
    "get_calendar_service",
    "GoogleAccount",
    "get_all_events_today",
    "get_all_events_in_range",
    "USE_ICALBUDDY",
]

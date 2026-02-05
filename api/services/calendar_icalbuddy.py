"""
iCalBuddy-based calendar integration for LifeOS.

Replaces Google Calendar API with local macOS calendar access via iCalBuddy.
"""
import logging
import subprocess
import re
import hashlib
from datetime import datetime, timedelta, timezone, date
from dataclasses import dataclass, field
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Local timezone
LOCAL_TZ = ZoneInfo("America/New_York")

# Path to iCalBuddy
ICALBUDDY_PATH = "/opt/homebrew/bin/icalBuddy"

# Calendar configuration - map account types to calendar UIDs
# These can be overridden via settings
CALENDAR_CONFIG = {
    "work": [
        "6B15EDC3-7A88-4662-9923-E0CEEA72912F",  # MCPHS
    ],
    "personal": [
        "1E467FA8-0DD3-42DF-AFA6-3355E5781AB4",  # Personal
        "5460F620-C3CF-465F-AF25-FF4D07BD15E6",  # Calendar (CalDAV)
    ],
}


@dataclass
class CalendarAttachment:
    """Represents a file attachment on a calendar event."""
    file_url: str
    title: str
    mime_type: Optional[str] = None
    icon_link: Optional[str] = None


@dataclass
class CalendarEvent:
    """Represents a calendar event."""
    event_id: str
    title: str
    start_time: datetime
    end_time: datetime
    source_account: str  # "personal" or "work"
    attendees: list[str] = field(default_factory=list)
    description: Optional[str] = None
    location: Optional[str] = None
    is_all_day: bool = False
    calendar_id: str = "primary"
    html_link: Optional[str] = None
    attachments: list[CalendarAttachment] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dict for indexing."""
        return {
            "event_id": self.event_id,
            "title": self.title,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "attendees": self.attendees,
            "description": self.description or "",
            "location": self.location or "",
            "is_all_day": self.is_all_day,
            "source": "icalbuddy",
            "source_account": self.source_account,
            "html_link": self.html_link or "",
        }

    def to_text(self) -> str:
        """Convert to searchable text for embedding."""
        parts = [self.title]
        if self.description:
            parts.append(self.description)
        if self.attendees:
            parts.append(f"Attendees: {', '.join(self.attendees)}")
        if self.location:
            parts.append(f"Location: {self.location}")
        return "\n".join(parts)


def format_event_time(dt: datetime, is_all_day: bool = False) -> str:
    """Format event time for display."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone(LOCAL_TZ)

    if is_all_day:
        return local_dt.strftime("%A, %B %d, %Y")
    else:
        return local_dt.strftime("%A, %B %d, %Y at %I:%M %p")


def _extract_attendees_from_title(title: str) -> list[str]:
    """
    Extract potential attendee names from meeting titles.

    Handles patterns like:
    - "1:1 with John"
    - "Meeting with Sarah and Bob"
    - "Call with Dr. Smith"
    - "John / Sarah sync"
    """
    attendees = []

    # Pattern: "with NAME" or "with NAME and NAME"
    with_pattern = r'\bwith\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?(?:\s+(?:and|&)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)*)'
    with_match = re.search(with_pattern, title, re.IGNORECASE)
    if with_match:
        names_str = with_match.group(1)
        # Split by "and" or "&"
        names = re.split(r'\s+(?:and|&)\s+', names_str, flags=re.IGNORECASE)
        attendees.extend([n.strip() for n in names if n.strip()])

    # Pattern: "NAME / NAME" (sync meetings)
    slash_pattern = r'^([A-Z][a-z]+)\s*/\s*([A-Z][a-z]+)'
    slash_match = re.match(slash_pattern, title)
    if slash_match:
        attendees.extend([slash_match.group(1), slash_match.group(2)])

    # Pattern: "NAME: topic" (often used for 1:1s)
    colon_pattern = r'^([A-Z][a-z]+):\s'
    colon_match = re.match(colon_pattern, title)
    if colon_match and len(colon_match.group(1)) > 2:
        attendees.append(colon_match.group(1))

    return list(set(attendees))  # Deduplicate


def _parse_datetime(date_str: str, time_str: str = None) -> tuple[datetime, bool]:
    """
    Parse iCalBuddy date/time strings into datetime objects.

    Returns (datetime, is_all_day)
    """
    is_all_day = time_str is None or time_str.strip() == ""

    # Parse the date part
    # Format: "Feb 4, 2026" or "2026-02-04"
    date_obj = None

    for fmt in ["%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"]:
        try:
            date_obj = datetime.strptime(date_str.strip(), fmt).date()
            break
        except ValueError:
            continue

    if date_obj is None:
        # Try to extract date from combined string like "Feb 4, 2026 at 09:00"
        at_match = re.match(r'(.+?)\s+at\s+(\d{1,2}:\d{2})', date_str)
        if at_match:
            date_part, time_part = at_match.groups()
            for fmt in ["%b %d, %Y", "%B %d, %Y"]:
                try:
                    date_obj = datetime.strptime(date_part.strip(), fmt).date()
                    time_str = time_part
                    is_all_day = False
                    break
                except ValueError:
                    continue

    if date_obj is None:
        raise ValueError(f"Could not parse date: {date_str}")

    if is_all_day:
        dt = datetime.combine(date_obj, datetime.min.time())
        dt = dt.replace(tzinfo=LOCAL_TZ)
        return dt, True

    # Parse time (format: "09:00" or "9:00")
    try:
        time_obj = datetime.strptime(time_str.strip(), "%H:%M").time()
    except ValueError:
        time_obj = datetime.strptime(time_str.strip(), "%I:%M %p").time()

    dt = datetime.combine(date_obj, time_obj)
    dt = dt.replace(tzinfo=LOCAL_TZ)
    return dt, False


def _run_icalbuddy(args: list[str]) -> str:
    """Run iCalBuddy with given arguments and return output."""
    cmd = [ICALBUDDY_PATH] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        logger.error("iCalBuddy command timed out")
        return ""
    except Exception as e:
        logger.error(f"iCalBuddy error: {e}")
        return ""


class CalendarService:
    """
    iCalBuddy-based calendar service.

    Provides methods to fetch and search calendar events from macOS Calendar.
    """

    def __init__(self, account_type = "personal"):
        """
        Initialize calendar service.

        Args:
            account_type: "personal" or "work" (string or _AccountType)
        """
        # Handle both string and _AccountType
        if hasattr(account_type, 'value'):
            self.account_type = account_type.value
        else:
            self.account_type = str(account_type)
        self._calendar_uids = CALENDAR_CONFIG.get(self.account_type, [])

    def get_upcoming_events(
        self,
        days: int = 7,
        max_results: int = 50,
        calendar_id: str = None
    ) -> list[CalendarEvent]:
        """Get upcoming events."""
        return self._fetch_events(
            command=f"eventsToday+{days}",
            max_results=max_results,
            calendar_ids=self._get_calendar_ids(calendar_id)
        )

    def get_events_in_range(
        self,
        start_date: datetime,
        end_date: datetime,
        max_results: int = 100,
        calendar_id: str = None
    ) -> list[CalendarEvent]:
        """Get events within a date range."""
        # Format dates for iCalBuddy (use simpler format)
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        # Build command parts separately for proper escaping
        return self._fetch_events_range(
            start_str=start_str,
            end_str=end_str,
            max_results=max_results,
            calendar_ids=self._get_calendar_ids(calendar_id)
        )

    def get_events_today(self, calendar_id: str = None) -> list[CalendarEvent]:
        """Get today's events."""
        return self._fetch_events(
            command="eventsToday",
            calendar_ids=self._get_calendar_ids(calendar_id)
        )

    def search_events(
        self,
        query: Optional[str] = None,
        attendee: Optional[str] = None,
        days_back: int = 30,
        days_forward: int = 30,
        calendar_id: str = None
    ) -> list[CalendarEvent]:
        """Search events by keyword or attendee."""
        now = datetime.now(LOCAL_TZ)
        start_date = now - timedelta(days=days_back)
        end_date = now + timedelta(days=days_forward)

        events = self.get_events_in_range(
            start_date=start_date,
            end_date=end_date,
            max_results=500,
            calendar_id=calendar_id
        )

        # Filter by query
        if query:
            query_lower = query.lower()
            events = [
                e for e in events
                if query_lower in e.title.lower()
                or (e.description and query_lower in e.description.lower())
                or (e.location and query_lower in e.location.lower())
            ]

        # Filter by attendee
        if attendee:
            attendee_lower = attendee.lower()
            events = [
                e for e in events
                if any(attendee_lower in a.lower() for a in e.attendees)
                or attendee_lower in e.title.lower()
            ]

        return events

    def _get_calendar_ids(self, calendar_id: str = None) -> list[str]:
        """Get calendar IDs to query."""
        if calendar_id:
            return [calendar_id]
        return self._calendar_uids

    def _fetch_events(
        self,
        command: str,
        max_results: int = 100,
        calendar_ids: list[str] = None
    ) -> list[CalendarEvent]:
        """Fetch events using iCalBuddy."""
        args = [
            "-nc",  # No calendar names in output
            "-uid",  # Show UIDs
            "-nrd",  # No relative dates
            "-npn",  # No property names
            "-iep", "datetime,title,location,uid",
            "-po", "uid,datetime,title,location",
            "-tf", "%H:%M",
            "-df", "%Y-%m-%d",
        ]

        # Add calendar filter if specified
        if calendar_ids:
            args.extend(["-ic", ",".join(calendar_ids)])

        # Add the command
        args.append(command)

        output = _run_icalbuddy(args)
        if not output:
            return []

        events = self._parse_output(output)

        # Limit results
        if max_results and len(events) > max_results:
            events = events[:max_results]

        return events

    def _fetch_events_range(
        self,
        start_str: str,
        end_str: str,
        max_results: int = 100,
        calendar_ids: list[str] = None
    ) -> list[CalendarEvent]:
        """Fetch events using iCalBuddy with date range (handles shell escaping)."""
        args = [
            "-nc",  # No calendar names in output
            "-uid",  # Show UIDs
            "-nrd",  # No relative dates
            "-npn",  # No property names
            "-iep", "datetime,title,location,uid",
            "-po", "uid,datetime,title,location",
            "-tf", "%H:%M",
            "-df", "%Y-%m-%d",
        ]

        # Add calendar filter if specified
        if calendar_ids:
            args.extend(["-ic", ",".join(calendar_ids)])

        # Add the date range command - use shell=True for proper handling
        # eventsFrom:DATE to:DATE syntax
        args.extend([f"eventsFrom:{start_str}", f"to:{end_str}"])

        output = _run_icalbuddy(args)
        if not output:
            return []

        events = self._parse_output(output)

        # Limit results
        if max_results and len(events) > max_results:
            events = events[:max_results]

        return events

    def _parse_output(self, output: str) -> list[CalendarEvent]:
        """
        Parse iCalBuddy output into CalendarEvent objects.

        Format (with -npn -uid):
        • UID: TIME_RANGE
        TITLE
        LOCATION (optional)
        • UID: TIME_RANGE
        ...
        """
        events = []
        lines = output.strip().split("\n")

        current_event = None
        current_lines = []

        for line in lines:
            # New event starts with bullet point
            if line.startswith("• "):
                # Save previous event if exists
                if current_event:
                    event = self._parse_event_block(current_event, current_lines)
                    if event:
                        events.append(event)

                # Start new event
                current_event = line[2:]  # Remove "• "
                current_lines = []
            elif current_event is not None:
                # Continuation of current event
                current_lines.append(line)

        # Don't forget the last event
        if current_event:
            event = self._parse_event_block(current_event, current_lines)
            if event:
                events.append(event)

        return events

    def _parse_event_block(self, header: str, detail_lines: list[str]) -> Optional[CalendarEvent]:
        """
        Parse an event block into CalendarEvent.

        header: "UID: TIME_RANGE" or "UID: DATE" (all-day)
        detail_lines: [TITLE, LOCATION, ...]
        """
        try:
            # Parse header: "UID: TIME_RANGE" or "UID: TITLE (all-day)"
            # Format: "38604A86-54F7-42D8-998D-E09BF65F9181: 09:00 - 10:00"
            colon_idx = header.find(": ")
            if colon_idx == -1:
                return None

            event_id = header[:colon_idx].strip()
            datetime_str = header[colon_idx + 2:].strip()

            # Parse datetime
            start_time, end_time, is_all_day = self._parse_datetime_field(datetime_str)

            # Get title from first detail line
            title = detail_lines[0].strip() if detail_lines else datetime_str

            # If datetime parsing failed, the header might contain the title for all-day events
            if start_time is None:
                # All-day event with title in header
                title = datetime_str
                start_time = datetime.now(LOCAL_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
                end_time = start_time + timedelta(days=1)
                is_all_day = True

            # Get location from second detail line (if exists and looks like a location)
            location = None
            if len(detail_lines) > 1:
                potential_location = detail_lines[1].strip()
                # Location often contains address or URL
                if potential_location and not potential_location.startswith("http"):
                    location = potential_location
                elif len(detail_lines) > 1:
                    location = potential_location

            # Extract attendees from title
            attendees = _extract_attendees_from_title(title)

            # Generate calendar.app link
            html_link = f"x-apple-calendar://?eventId={event_id}" if event_id else None

            return CalendarEvent(
                event_id=event_id,
                title=title,
                start_time=start_time,
                end_time=end_time,
                source_account=self.account_type,
                attendees=attendees,
                description=None,
                location=location,
                is_all_day=is_all_day,
                html_link=html_link,
            )

        except Exception as e:
            logger.warning(f"Failed to parse event block: {header[:50]}... Error: {e}")
            return None

    def _parse_datetime_field(self, datetime_str: str) -> tuple[Optional[datetime], Optional[datetime], bool]:
        """
        Parse datetime field from iCalBuddy.

        Formats:
        - "2026-02-04" (all-day)
        - "09:00 - 10:00" (timed, today)
        - "2026-02-04 at 09:00 - 10:00"
        - "Feb 4, 2026 at 09:00 - 10:00"

        Returns (start_time, end_time, is_all_day)
        """
        datetime_str = datetime_str.strip()

        if not datetime_str:
            return None, None, False

        today = date.today()

        # Pattern: "HH:MM - HH:MM" (time range for today)
        time_range_match = re.match(r'^(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})$', datetime_str)
        if time_range_match:
            start_time_str, end_time_str = time_range_match.groups()
            start_time = datetime.strptime(start_time_str, "%H:%M").time()
            end_time = datetime.strptime(end_time_str, "%H:%M").time()

            start_dt = datetime.combine(today, start_time).replace(tzinfo=LOCAL_TZ)
            end_dt = datetime.combine(today, end_time).replace(tzinfo=LOCAL_TZ)
            return start_dt, end_dt, False

        # Pattern: "YYYY-MM-DD" (all-day)
        date_only_match = re.match(r'^(\d{4}-\d{2}-\d{2})$', datetime_str)
        if date_only_match:
            event_date = datetime.strptime(date_only_match.group(1), "%Y-%m-%d").date()
            start_dt = datetime.combine(event_date, datetime.min.time()).replace(tzinfo=LOCAL_TZ)
            end_dt = start_dt + timedelta(days=1)
            return start_dt, end_dt, True

        # Pattern: "DATE at HH:MM - HH:MM"
        full_match = re.match(r'^(.+?)\s+at\s+(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})$', datetime_str)
        if full_match:
            date_str, start_time_str, end_time_str = full_match.groups()

            # Parse date
            event_date = None
            for fmt in ["%Y-%m-%d", "%b %d, %Y", "%B %d, %Y"]:
                try:
                    event_date = datetime.strptime(date_str.strip(), fmt).date()
                    break
                except ValueError:
                    continue

            if event_date is None:
                return None, None, False

            start_time = datetime.strptime(start_time_str, "%H:%M").time()
            end_time = datetime.strptime(end_time_str, "%H:%M").time()

            start_dt = datetime.combine(event_date, start_time).replace(tzinfo=LOCAL_TZ)
            end_dt = datetime.combine(event_date, end_time).replace(tzinfo=LOCAL_TZ)
            return start_dt, end_dt, False

        # Pattern: All-day event with date like "Feb 4, 2026"
        for fmt in ["%b %d, %Y", "%B %d, %Y"]:
            try:
                event_date = datetime.strptime(datetime_str, fmt).date()
                start_dt = datetime.combine(event_date, datetime.min.time()).replace(tzinfo=LOCAL_TZ)
                end_dt = start_dt + timedelta(days=1)
                return start_dt, end_dt, True
            except ValueError:
                continue

        logger.warning(f"Could not parse datetime: {datetime_str}")
        return None, None, False


# Singleton services per account type
_calendar_services: dict[str, CalendarService] = {}


def get_calendar_service(account_type = "personal") -> CalendarService:
    """Get or create calendar service for an account type."""
    # Handle both string and _AccountType
    if hasattr(account_type, 'value'):
        account_key = account_type.value
    else:
        account_key = str(account_type)

    if account_key not in _calendar_services:
        _calendar_services[account_key] = CalendarService(account_key)
    return _calendar_services[account_key]


# For backwards compatibility with code that imports GoogleAccount
class _AccountType:
    """Enum-like wrapper for account type strings."""
    def __init__(self, value: str):
        self.value = value

    def __str__(self):
        return self.value

    def __eq__(self, other):
        if isinstance(other, _AccountType):
            return self.value == other.value
        return self.value == other

    def __hash__(self):
        return hash(self.value)


class GoogleAccount:
    """Compatibility shim for code expecting GoogleAccount enum."""
    PERSONAL = _AccountType("personal")
    WORK = _AccountType("work")


def get_all_events_today() -> list[CalendarEvent]:
    """Get all events for today from all configured calendars."""
    events = []

    for account_type in ["work", "personal"]:
        service = get_calendar_service(account_type)
        events.extend(service.get_events_today())

    # Sort by start time
    events.sort(key=lambda e: e.start_time)

    return events


def get_all_events_in_range(
    start_date: datetime,
    end_date: datetime
) -> list[CalendarEvent]:
    """Get all events in range from all configured calendars."""
    events = []

    for account_type in ["work", "personal"]:
        service = get_calendar_service(account_type)
        events.extend(service.get_events_in_range(start_date, end_date))

    # Sort by start time
    events.sort(key=lambda e: e.start_time)

    return events

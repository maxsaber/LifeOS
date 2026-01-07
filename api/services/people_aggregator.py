"""
People Aggregator - Multi-source people tracking for LifeOS.

Aggregates people from:
- LinkedIn connections CSV
- Gmail contacts (last 2 years)
- Calendar attendees
- Granola meeting notes (via Obsidian)
- Obsidian note mentions
"""
import csv
import json
import logging
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional

from api.services.people import (
    PEOPLE_DICTIONARY,
    ALIAS_MAP,
    resolve_person_name,
    extract_people_from_text,
)

logger = logging.getLogger(__name__)


@dataclass
class PersonRecord:
    """Comprehensive record for a person from multiple sources."""
    canonical_name: str
    email: Optional[str] = None
    sources: list[str] = field(default_factory=list)
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    company: Optional[str] = None
    position: Optional[str] = None
    linkedin_url: Optional[str] = None
    meeting_count: int = 0
    email_count: int = 0
    mention_count: int = 0
    related_notes: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    category: str = "unknown"  # work, personal, family, etc.

    def merge(self, other: "PersonRecord") -> "PersonRecord":
        """Merge another record into this one."""
        # Combine sources
        sources = list(set(self.sources + other.sources))

        # Take earliest first_seen
        first_seen = self.first_seen
        if other.first_seen:
            if first_seen is None or other.first_seen < first_seen:
                first_seen = other.first_seen

        # Take latest last_seen
        last_seen = self.last_seen
        if other.last_seen:
            if last_seen is None or other.last_seen > last_seen:
                last_seen = other.last_seen

        # Sum counts
        meeting_count = self.meeting_count + other.meeting_count
        email_count = self.email_count + other.email_count
        mention_count = self.mention_count + other.mention_count

        # Combine related notes
        related_notes = list(set(self.related_notes + other.related_notes))

        # Take first non-None values for single fields
        company = self.company or other.company
        position = self.position or other.position
        linkedin_url = self.linkedin_url or other.linkedin_url
        email = self.email or other.email

        # Combine aliases
        aliases = list(set(self.aliases + other.aliases))

        return PersonRecord(
            canonical_name=self.canonical_name,
            email=email,
            sources=sources,
            first_seen=first_seen,
            last_seen=last_seen,
            company=company,
            position=position,
            linkedin_url=linkedin_url,
            meeting_count=meeting_count,
            email_count=email_count,
            mention_count=mention_count,
            related_notes=related_notes,
            aliases=aliases,
            category=self.category if self.category != "unknown" else other.category,
        )

    def to_dict(self) -> dict:
        """Convert to dict for serialization."""
        data = asdict(self)
        if self.first_seen:
            data['first_seen'] = self.first_seen.isoformat()
        if self.last_seen:
            data['last_seen'] = self.last_seen.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "PersonRecord":
        """Create from dict."""
        if data.get('first_seen'):
            data['first_seen'] = datetime.fromisoformat(data['first_seen'])
        if data.get('last_seen'):
            data['last_seen'] = datetime.fromisoformat(data['last_seen'])
        return cls(**data)


def load_linkedin_connections(csv_path: str) -> list[dict]:
    """
    Load LinkedIn connections from CSV export.

    Args:
        csv_path: Path to LinkedIn connections CSV

    Returns:
        List of connection dicts
    """
    if not csv_path or not Path(csv_path).exists():
        logger.warning(f"LinkedIn CSV not found: {csv_path}")
        return []

    connections = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                connections.append({
                    'first_name': row.get('First Name', ''),
                    'last_name': row.get('Last Name', ''),
                    'email': row.get('Email Address', ''),
                    'company': row.get('Company', ''),
                    'position': row.get('Position', ''),
                    'linkedin_url': row.get('URL', ''),
                    'connected_on': row.get('Connected On', ''),
                })
    except Exception as e:
        logger.error(f"Failed to load LinkedIn CSV: {e}")
        return []

    return connections


def extract_gmail_contacts(gmail_service, days_back: int = 730) -> list[dict]:
    """
    Extract contacts from Gmail messages.

    Args:
        gmail_service: GmailService instance
        days_back: How many days to look back (default 2 years)

    Returns:
        List of contact dicts with email, name, last_contact
    """
    if gmail_service is None:
        return []

    contacts = {}
    after_date = datetime.now(timezone.utc) - timedelta(days=days_back)

    try:
        # Search for sent emails (people we emailed)
        messages = gmail_service.search(
            keywords="in:sent",
            after=after_date,
            max_results=500,
        )

        for msg in messages:
            # Track recipients from sent emails
            if hasattr(msg, 'to') and msg.to:
                for recipient in msg.to.split(','):
                    email = recipient.strip()
                    if '@' in email:
                        # Extract name from "Name <email>" format
                        match = re.match(r'"?([^"<]+)"?\s*<([^>]+)>', email)
                        if match:
                            name = match.group(1).strip()
                            email = match.group(2).strip()
                        else:
                            name = email.split('@')[0]

                        if email not in contacts:
                            contacts[email] = {
                                'email': email,
                                'name': name,
                                'last_contact': msg.date,
                                'email_count': 0,
                            }
                        contacts[email]['email_count'] += 1
                        if msg.date > contacts[email]['last_contact']:
                            contacts[email]['last_contact'] = msg.date

        # Also search received emails
        messages = gmail_service.search(
            keywords="in:inbox",
            after=after_date,
            max_results=500,
        )

        for msg in messages:
            email = msg.sender
            name = msg.sender_name

            if email and '@' in email:
                if email not in contacts:
                    contacts[email] = {
                        'email': email,
                        'name': name,
                        'last_contact': msg.date,
                        'email_count': 0,
                    }
                contacts[email]['email_count'] += 1
                if msg.date > contacts[email]['last_contact']:
                    contacts[email]['last_contact'] = msg.date

    except Exception as e:
        logger.error(f"Failed to extract Gmail contacts: {e}")

    return list(contacts.values())


def extract_calendar_attendees(calendar_service, days_back: int = 365) -> list[dict]:
    """
    Extract attendees from calendar events.

    Args:
        calendar_service: CalendarService instance
        days_back: How many days to look back

    Returns:
        List of attendee dicts with name, email, meeting_count, last_meeting
    """
    if calendar_service is None:
        return []

    attendees = {}
    start_date = datetime.now(timezone.utc) - timedelta(days=days_back)
    end_date = datetime.now(timezone.utc)

    try:
        events = calendar_service.get_events_in_range(
            start_date=start_date,
            end_date=end_date,
            max_results=500,
        )

        for event in events:
            for attendee in event.attendees:
                # attendee might be email or "Name" format
                if '@' in attendee:
                    email = attendee
                    name = attendee.split('@')[0]
                else:
                    name = attendee
                    email = None

                key = email or name.lower()
                if key not in attendees:
                    attendees[key] = {
                        'name': name,
                        'email': email,
                        'meeting_count': 0,
                        'last_meeting': event.start_time,
                    }
                attendees[key]['meeting_count'] += 1
                if event.start_time > attendees[key]['last_meeting']:
                    attendees[key]['last_meeting'] = event.start_time

    except Exception as e:
        logger.error(f"Failed to extract calendar attendees: {e}")

    return list(attendees.values())


class PeopleAggregator:
    """
    Aggregates people from multiple sources into unified registry.
    """

    def __init__(
        self,
        linkedin_csv_path: Optional[str] = None,
        gmail_service=None,
        calendar_service=None,
        storage_path: str = "./data/people_aggregated.json",
    ):
        """
        Initialize aggregator.

        Args:
            linkedin_csv_path: Path to LinkedIn connections CSV
            gmail_service: GmailService instance
            calendar_service: CalendarService instance
            storage_path: Path to store aggregated data
        """
        self.linkedin_csv_path = linkedin_csv_path
        self.gmail_service = gmail_service
        self.calendar_service = calendar_service
        self.storage_path = Path(storage_path)

        # In-memory registry keyed by canonical name
        self._people: dict[str, PersonRecord] = {}
        self._load()

    def _load(self) -> None:
        """Load existing data from disk."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, 'r') as f:
                    data = json.load(f)
                    for item in data:
                        record = PersonRecord.from_dict(item)
                        self._people[record.canonical_name.lower()] = record
            except Exception as e:
                logger.error(f"Failed to load people aggregator data: {e}")

    def save(self) -> None:
        """Persist data to disk."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.storage_path, 'w') as f:
                data = [p.to_dict() for p in self._people.values()]
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save people aggregator data: {e}")

    def add_person_from_source(
        self,
        name: str,
        source: str,
        email: Optional[str] = None,
        company: Optional[str] = None,
        position: Optional[str] = None,
        linkedin_url: Optional[str] = None,
        meeting_count: int = 0,
        email_count: int = 0,
        mention_count: int = 0,
        seen_date: Optional[datetime] = None,
        related_note: Optional[str] = None,
    ) -> None:
        """
        Add or update a person from a specific source.

        Args:
            name: Person's name
            source: Source identifier (gmail, calendar, linkedin, obsidian, granola)
            email: Email address
            company: Company name
            position: Job position
            linkedin_url: LinkedIn profile URL
            meeting_count: Number of meetings
            email_count: Number of emails
            mention_count: Number of mentions
            seen_date: When this person was seen
            related_note: Path to related note
        """
        # Resolve to canonical name
        canonical = resolve_person_name(name)
        key = canonical.lower()

        # Get category from people dictionary
        category = "unknown"
        if canonical in PEOPLE_DICTIONARY:
            category = PEOPLE_DICTIONARY[canonical].get('category', 'unknown')

        # Create new record
        new_record = PersonRecord(
            canonical_name=canonical,
            email=email,
            sources=[source],
            first_seen=seen_date,
            last_seen=seen_date,
            company=company,
            position=position,
            linkedin_url=linkedin_url,
            meeting_count=meeting_count,
            email_count=email_count,
            mention_count=mention_count,
            related_notes=[related_note] if related_note else [],
            category=category,
        )

        # Merge with existing or add new
        if key in self._people:
            self._people[key] = self._people[key].merge(new_record)
        else:
            self._people[key] = new_record

    def sync_all_sources(self) -> dict[str, int]:
        """
        Sync all configured sources.

        Returns:
            Dict of source -> count of people added
        """
        results = {}

        # LinkedIn
        if self.linkedin_csv_path:
            connections = load_linkedin_connections(self.linkedin_csv_path)
            for conn in connections:
                full_name = f"{conn['first_name']} {conn['last_name']}".strip()
                self.add_person_from_source(
                    name=full_name,
                    source='linkedin',
                    email=conn['email'] if conn['email'] else None,
                    company=conn['company'],
                    position=conn['position'],
                    linkedin_url=conn['linkedin_url'],
                )
            results['linkedin'] = len(connections)

        # Gmail
        if self.gmail_service:
            contacts = extract_gmail_contacts(self.gmail_service)
            for contact in contacts:
                self.add_person_from_source(
                    name=contact['name'],
                    source='gmail',
                    email=contact['email'],
                    email_count=contact.get('email_count', 1),
                    seen_date=contact.get('last_contact'),
                )
            results['gmail'] = len(contacts)

        # Calendar
        if self.calendar_service:
            attendees = extract_calendar_attendees(self.calendar_service)
            for att in attendees:
                self.add_person_from_source(
                    name=att['name'],
                    source='calendar',
                    email=att.get('email'),
                    meeting_count=att.get('meeting_count', 1),
                    seen_date=att.get('last_meeting'),
                )
            results['calendar'] = len(attendees)

        self.save()
        return results

    def add_from_obsidian_note(
        self,
        file_path: str,
        content: str,
        note_date: Optional[datetime] = None,
    ) -> list[str]:
        """
        Extract and add people from an Obsidian note.

        Args:
            file_path: Path to the note
            content: Note content
            note_date: Date of the note

        Returns:
            List of people found
        """
        people = extract_people_from_text(content)

        # Determine source based on path
        source = 'granola' if 'granola' in file_path.lower() else 'obsidian'

        for name in people:
            self.add_person_from_source(
                name=name,
                source=source,
                mention_count=1,
                seen_date=note_date,
                related_note=file_path,
            )

        return people

    def get_all_people(self) -> list[PersonRecord]:
        """Get all people records."""
        return list(self._people.values())

    def search(self, query: str) -> list[PersonRecord]:
        """
        Search people by name or email.

        Args:
            query: Search query

        Returns:
            List of matching PersonRecords
        """
        query_lower = query.lower()
        results = []

        for person in self._people.values():
            if query_lower in person.canonical_name.lower():
                results.append(person)
            elif person.email and query_lower in person.email.lower():
                results.append(person)
            elif any(query_lower in alias.lower() for alias in person.aliases):
                results.append(person)

        return results

    def get_person(self, name: str) -> Optional[PersonRecord]:
        """
        Get a person by name.

        Args:
            name: Person name (will be resolved)

        Returns:
            PersonRecord or None
        """
        canonical = resolve_person_name(name)
        return self._people.get(canonical.lower())

    def get_person_summary(self, name: str) -> Optional[dict]:
        """
        Get summary dict for a person.

        Args:
            name: Person name

        Returns:
            Summary dict or None
        """
        person = self.get_person(name)
        if not person:
            return None

        return {
            'name': person.canonical_name,
            'email': person.email,
            'company': person.company,
            'position': person.position,
            'sources': person.sources,
            'meeting_count': person.meeting_count,
            'email_count': person.email_count,
            'mention_count': person.mention_count,
            'last_seen': person.last_seen.isoformat() if person.last_seen else None,
            'related_notes': person.related_notes[:10],  # Limit to 10
            'category': person.category,
        }

    def get_statistics(self) -> dict:
        """Get statistics about aggregated people."""
        total = len(self._people)
        by_source = {}

        for person in self._people.values():
            for source in person.sources:
                by_source[source] = by_source.get(source, 0) + 1

        return {
            'total_people': total,
            'by_source': by_source,
        }


# Singleton instance
_aggregator: Optional[PeopleAggregator] = None


def get_people_aggregator(
    linkedin_csv_path: Optional[str] = "./data/LinkedInConnections.csv",
    gmail_service=None,
    calendar_service=None,
) -> PeopleAggregator:
    """Get or create people aggregator singleton."""
    global _aggregator
    if _aggregator is None:
        _aggregator = PeopleAggregator(
            linkedin_csv_path=linkedin_csv_path,
            gmail_service=gmail_service,
            calendar_service=calendar_service,
        )
    return _aggregator

# People System v2 Integration Design

**Date:** 2026-01-09
**Status:** Approved
**Author:** Claude (with Nathan)

## Overview

This document describes the integration of People System v2 components (EntityResolver, PersonEntityStore, InteractionStore) with existing data sources: Gmail, Calendar, and Vault indexer.

## Goals

1. **Migrate existing data** from v1 `people_aggregated.json` to v2 `people_entities.json`
2. **Wire up Gmail sync** to create interactions and resolve entities by email
3. **Wire up Calendar sync** to create interactions for meetings
4. **Wire up Vault indexer** to resolve people mentioned in notes with context-aware matching

## Design Decisions

### Migration Strategy
- **One-time import**: Run migration script to convert all v1 PersonRecords to v2 PersonEntities
- Backup original data before migration
- Generate migration report with duplicate detection and merge decisions
- Keep v1 code intact but deprecated

### Gmail Filtering
Only extract contacts from emails where:
- User sent a message in the thread (query `in:sent`)
- Email domain is not commercial (exclude noreply, marketing, notifications, mailchimp, sendgrid, etc.)
- Not a mailing list

One sent email is sufficient to create an entity.

### Calendar Filtering
- Include all events regardless of attendee count
- Skip all-day events without attendees
- Skip declined events

### Vault Context Matching
When resolving people from vault notes, use file path to boost matching:
- `Work/ML/` → `movementlabs.xyz`, `movementlabs.com`
- `Personal/zArchive/Murm/` → `murmuration.org`
- `Personal/zArchive/BlueLabs/` → `bluelabs.com`
- `Personal/zArchive/Deck/` → `deck.tools`

---

## Component 1: Data Migration Script

**File:** `scripts/migrate_people_v1_to_v2.py`

### Process
1. Load existing `people_aggregated.json`
2. For each PersonRecord, use `PersonEntity.from_person_record()` to convert
3. Apply entity resolution to detect duplicates (same person, different spellings)
4. Generate UUIDs for each unique entity
5. Infer `vault_contexts` from existing `related_notes` paths
6. Save to `people_entities.json`
7. Generate migration report

### Safety Measures
- Backup original file before migration
- Dry-run mode to preview changes
- Log all merge decisions for audit

---

## Component 2: Gmail Integration

**Modified file:** `api/services/people_aggregator.py`

### New Method: `sync_gmail_to_v2()`

```python
def sync_gmail_to_v2(gmail_service, entity_resolver, interaction_store):
    """
    Sync Gmail contacts to v2 people system.

    Only processes sent emails to capture intentional communication.
    """
    # Query sent emails from last N days
    sent_messages = gmail_service.search("in:sent", days_back=90)

    for message in sent_messages:
        # Skip commercial/automated emails
        if is_excluded_email(message.to):
            continue

        # Resolve recipient to entity
        result = entity_resolver.resolve(
            name=message.recipient_name,
            email=message.to,
            create_if_missing=True
        )

        # Create interaction
        interaction = Interaction(
            id=str(uuid4()),
            person_id=result.entity.id,
            timestamp=message.date,
            source_type="gmail",
            title=message.subject,
            snippet=message.snippet[:100],
            source_link=build_gmail_link(message.message_id),
            source_id=message.message_id,
        )
        interaction_store.add_if_not_exists(interaction)

        # Update entity stats
        result.entity.email_count += 1
        result.entity.last_seen = max(result.entity.last_seen, message.date)
        entity_resolver.store.update(result.entity)
```

### Exclusion Patterns
```python
EXCLUDED_EMAIL_PATTERNS = [
    r".*noreply.*",
    r".*no-reply.*",
    r".*notifications?@.*",
    r".*marketing@.*",
    r".*support@.*",
    r".*@mailchimp\.com",
    r".*@sendgrid\..*",
    r".*@intercom\..*",
    r".*@zendesk\..*",
]
```

---

## Component 3: Calendar Integration

**Modified file:** `api/services/people_aggregator.py`

### New Method: `sync_calendar_to_v2()`

```python
def sync_calendar_to_v2(calendar_service, entity_resolver, interaction_store):
    """
    Sync Calendar attendees to v2 people system.
    """
    events = calendar_service.get_events_in_range(days_back=90, days_forward=0)

    for event in events:
        # Skip all-day events without attendees
        if event.is_all_day and not event.attendees:
            continue

        for attendee in event.attendees:
            # Parse attendee (could be name or email)
            name, email = parse_attendee(attendee)

            # Resolve to entity
            result = entity_resolver.resolve(
                name=name,
                email=email,
                create_if_missing=True
            )

            # Create interaction
            interaction = Interaction(
                id=str(uuid4()),
                person_id=result.entity.id,
                timestamp=event.start_time,
                source_type="calendar",
                title=event.title,
                source_link=event.html_link or build_calendar_link(event.event_id),
                source_id=event.event_id,
            )
            interaction_store.add_if_not_exists(interaction)

            # Update entity stats
            result.entity.meeting_count += 1
            result.entity.last_seen = max(result.entity.last_seen, event.start_time)
            entity_resolver.store.update(result.entity)
```

---

## Component 4: Vault Indexer Integration

**Modified file:** `api/services/indexer.py`

### Hook: After People Extraction

```python
def index_file(self, path: Path):
    # ... existing code to read file, extract frontmatter, chunk ...

    # Extract people from content
    extracted_people = extract_people_from_text(body)
    frontmatter_people = frontmatter.get("people", [])
    all_people = list(set(extracted_people + frontmatter_people))

    # NEW: Resolve people to v2 entities and create interactions
    if HAS_V2_PEOPLE:
        self._sync_people_to_v2(path, all_people)

    # ... rest of existing indexing code ...

def _sync_people_to_v2(self, path: Path, people: list[str]):
    """Resolve extracted people and create vault mention interactions."""
    from api.services.entity_resolver import get_entity_resolver
    from api.services.interaction_store import get_interaction_store, build_obsidian_link

    resolver = get_entity_resolver()
    interaction_store = get_interaction_store()

    for person_name in people:
        # Resolve with context path for domain boosting
        result = resolver.resolve(
            name=person_name,
            context_path=str(path),
            create_if_missing=True
        )

        if result:
            # Create interaction
            interaction = Interaction(
                id=str(uuid4()),
                person_id=result.entity.id,
                timestamp=self._get_note_date(path),
                source_type="vault",
                title=path.name,
                source_link=build_obsidian_link(str(path)),
                source_id=str(path),
            )
            interaction_store.add_if_not_exists(interaction)

            # Update entity
            result.entity.mention_count += 1
            if str(path) not in result.entity.related_notes:
                result.entity.related_notes.append(str(path))
            resolver.store.update(result.entity)
```

---

## Component 5: Orchestration & Scheduling

**Modified files:** `api/main.py`, `api/services/people_aggregator.py`

### Nightly Sync Loop (`api/main.py`)

The `_nightly_sync_loop()` function runs at 3 AM Eastern and performs:

1. **Vault Reindex** - Full reindex triggers v2 people extraction for all notes
2. **LinkedIn Sync** - Processes CSV to create/update entities with company context
3. **Gmail Sync** - Processes sent emails from last 24h
4. **Calendar Sync** - Processes meetings from last 24h

```python
def _nightly_sync_loop(stop_event, schedule_hour=3, timezone="America/New_York"):
    """Background thread for nightly sync operations."""
    while not stop_event.is_set():
        # Wait until 3 AM
        # ...

        # Step 1: Vault Reindex
        indexer = IndexerService(vault_path=settings.vault_path)
        indexer.index_all()  # Triggers _sync_people_to_v2() for each file

        # Step 2-4: LinkedIn + Gmail + Calendar
        sync_people_v2(
            gmail_service=get_gmail_service(),
            linkedin_csv_path="./data/LinkedInConnections.csv",
            days_back=1
        )
```

### Orchestration Method (`api/services/people_aggregator.py`)

```python
def sync_people_v2(
    gmail_service=None,
    calendar_services=None,
    linkedin_csv_path=None,  # NEW: LinkedIn CSV path
    days_back=1
):
    """Orchestrate v2 sync for LinkedIn, Gmail, and Calendar."""

    # Sync LinkedIn first (provides company context)
    if linkedin_csv_path:
        sync_linkedin_to_v2(csv_path=linkedin_csv_path)

    # Sync Gmail
    if gmail_service:
        sync_gmail_to_v2(gmail_service, days_back=days_back)

    # Sync Calendar
    sync_calendar_to_v2(calendar_services, days_back=days_back)
```

### Real-Time Processing

- **Granola notes**: Watched by `GranolaProcessor`, processed immediately
- **Calendar events**: Indexed 3x daily (8 AM, noon, 3 PM) for search queries
- **Regular vault notes**: Not watched; updated during nightly reindex

---

## File Changes Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `scripts/migrate_people_v1_to_v2.py` | New | Migration script |
| `api/services/people_aggregator.py` | Modified | Add v2 sync methods (LinkedIn, Gmail, Calendar) |
| `api/services/indexer.py` | Modified | Add v2 people hook |
| `api/main.py` | Modified | Add nightly sync scheduler |
| `config/people_config.py` | Modified | Add email exclusion patterns |

---

## Testing Plan

1. **Migration tests**: Verify v1→v2 conversion, duplicate detection, backup/restore
2. **Gmail sync tests**: Mock Gmail API, verify filtering, entity creation
3. **Calendar sync tests**: Mock Calendar API, verify attendee parsing
4. **Indexer tests**: Verify context-aware resolution, interaction creation
5. **Integration tests**: Full flow from source to briefing

---

## Rollback Plan

1. Keep v1 `people_aggregated.json` backed up
2. v1 code remains functional (just deprecated)
3. BriefingsService falls back to v1 if v2 unavailable
4. Can disable v2 via `HAS_V2_PEOPLE = False` flag

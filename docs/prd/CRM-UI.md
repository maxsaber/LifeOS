# Personal CRM PRD

A comprehensive Personal CRM built on LifeOS's People System v2 for network management and relationship context.

**Primary Use Cases:**
- Network discovery: "Who do I know at company X?"
- Relationship visualization: "Show me my connections"
- Meeting prep context: "What do I know about this person?"
- Communication tracking: "When did I last talk to X?"

**Non-Goals:**
- Outbound sales/marketing CRM features
- Contact management (creating/editing contact details)
- Email automation or scheduling

---

## System Overview

**Architecture:**
- Builds on People System v2 (P8.x) PersonEntity + Interaction models
- Extends with SourceEntity (raw observations) and Relationship tracking
- Dedicated CRM UI at `/crm` route
- API routes at `/api/crm/*`

**Data Flow:**
```
Data Sources                Entity Resolution              CRM Data
──────────────             ──────────────────             ────────────
Gmail emails    ─┐
Calendar events  │         ┌──────────────────┐         ┌─────────────┐
iMessage texts   ├────────▶│  EntityResolver  │────────▶│ PersonEntity│
Vault mentions   │         │  (email-based    │         │ Interaction │
LinkedIn CSV     │         │   + fuzzy name)  │         │ Relationship│
Phone Contacts   │         └──────────────────┘         └─────────────┘
Slack users    ──┤
Apple Contacts ──┤                                       CRM UI
WhatsApp export ─┤                                    ┌─────────────┐
Signal export  ──┘                                    │  /crm page  │
                                                      │ - People    │
                                                      │ - Timeline  │
                                                      │ - Graph     │
                                                      └─────────────┘
```

---

## Phase 9: CRM Foundation

### P9.1: Data Integrity Verification

**Requirements:**
Verify that existing People System v2 data flows correctly through to CRM display. The CRM must accurately reflect data from all integrated sources.

**Canonical Test Case:**
Taylor (partner) - `annetaylorwalker@gmail.com`, `+19012295017`

This person should show:
- ✓ Correct name, email, phone from multiple sources
- ✓ High interaction count (most frequent contact)
- ✓ Multiple sources: phone_contacts, gmail, calendar, imessage
- ✓ Timeline populated with recent communications
- ✓ Relationship strength > 0.8

**Verification Query:**
```python
# This should return populated data, not zeros
person = person_store.find_by_email("annetaylorwalker@gmail.com")
assert person is not None
assert person.interaction_count > 0
assert len(person.sources) > 1

interactions = interaction_store.get_for_person(person.id, days=90)
assert len(interactions) > 0
```

**Acceptance Criteria:**
```
[ ] PersonEntity.emails correctly populated from all sources
[ ] PersonEntity.phone_numbers correctly populated from phone_contacts + iMessage
[ ] PersonEntity.sources includes all data sources where person appears
[ ] PersonEntity.meeting_count matches actual calendar interactions
[ ] PersonEntity.email_count matches actual Gmail interactions
[ ] PersonEntity.mention_count matches actual vault mentions
[ ] PersonEntity.last_seen reflects most recent interaction
[ ] Interaction store has records for Gmail, Calendar, Vault, iMessage
[ ] Interactions correctly linked to PersonEntity by person_id
[ ] Taylor test case passes with >50 interactions across >2 sources
[ ] Yoni test case passes with calendar meetings and vault mentions
[ ] Top 10 contacts by interaction count all have >0 interactions
```

**Test File:** `tests/test_crm_data_integrity.py`

**Completion Promise:** `<promise>P9.1-DATA-INTEGRITY-COMPLETE</promise>`

---

### P9.2: CRM API - People Listing

**Requirements:**
API endpoint to list people with filtering, sorting, and pagination.

**Endpoint:** `GET /api/crm/people`

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| q | string | Search query (name, email, company) |
| category | string | Filter by category: work, personal, family |
| source | string | Filter by source: gmail, calendar, linkedin, etc. |
| sort | string | Sort field: name, last_seen, interaction_count, strength |
| order | string | Sort order: asc, desc (default: desc) |
| limit | int | Results per page (default: 50, max: 200) |
| offset | int | Pagination offset |

**Response Schema:**
```json
{
  "people": [
    {
      "id": "uuid",
      "canonical_name": "Taylor Walker",
      "display_name": "Taylor Walker",
      "emails": ["annetaylorwalker@gmail.com"],
      "phone_numbers": ["+19012295017"],
      "company": null,
      "position": null,
      "category": "personal",
      "sources": ["phone_contacts", "gmail", "calendar", "imessage"],
      "interaction_count": 847,
      "meeting_count": 23,
      "email_count": 156,
      "mention_count": 12,
      "first_seen": "2024-01-15T...",
      "last_seen": "2026-01-27T...",
      "relationship_strength": 0.92
    }
  ],
  "count": 50,
  "total": 2236,
  "offset": 0,
  "has_more": true
}
```

**Acceptance Criteria:**
```
[ ] Search by name returns fuzzy matches
[ ] Search by email returns exact match
[ ] Search by company returns all employees
[ ] Category filter works for work/personal/family
[ ] Source filter works for all source types
[ ] Sort by name alphabetically works
[ ] Sort by last_seen shows most recent first
[ ] Sort by interaction_count shows most active first
[ ] Sort by relationship_strength shows strongest first
[ ] Pagination with limit/offset works correctly
[ ] Response includes correct total count
[ ] has_more flag accurate
[ ] interaction_count > 0 for active contacts (not all zeros)
[ ] sources array populated correctly (not just "phone_contacts")
[ ] Performance: <500ms for 50 results
```

**Test File:** `tests/test_crm_api_people.py`

**Completion Promise:** `<promise>P9.2-PEOPLE-LIST-COMPLETE</promise>`

---

### P9.3: CRM API - Person Detail & Timeline

**Requirements:**
API endpoints to get full person detail and interaction timeline.

**Endpoint:** `GET /api/crm/people/{id}`

**Response Schema:**
```json
{
  "id": "uuid",
  "canonical_name": "Taylor Walker",
  "emails": ["annetaylorwalker@gmail.com"],
  "phone_numbers": ["+19012295017"],
  "company": null,
  "category": "personal",
  "vault_contexts": ["Personal/Relationship/"],
  "tags": [],
  "notes": "",
  "sources": ["phone_contacts", "gmail", "calendar", "imessage"],
  "interaction_count": 847,
  "meeting_count": 23,
  "email_count": 156,
  "imessage_count": 656,
  "mention_count": 12,
  "first_seen": "2024-01-15T...",
  "last_seen": "2026-01-27T...",
  "relationship_strength": 0.92,
  "aliases": ["Tay", "Anne Taylor Walker"]
}
```

**Endpoint:** `GET /api/crm/people/{id}/timeline`

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| days | int | Lookback period (default: 90) |
| source | string | Filter by source type |
| limit | int | Max items (default: 50) |

**Response Schema:**
```json
{
  "items": [
    {
      "id": "interaction-uuid",
      "timestamp": "2026-01-27T10:30:00Z",
      "source_type": "imessage",
      "title": "Text conversation",
      "snippet": "Hey, are you coming home for dinner?",
      "source_link": "imessage://+19012295017"
    },
    {
      "id": "interaction-uuid",
      "timestamp": "2026-01-26T15:00:00Z",
      "source_type": "calendar",
      "title": "Doctor appointment",
      "snippet": "Annual checkup",
      "source_link": "https://calendar.google.com/..."
    }
  ],
  "count": 50,
  "has_more": true,
  "total_interactions": 847
}
```

**Acceptance Criteria:**
```
[ ] Person detail returns all PersonEntity fields
[ ] interaction_count matches sum of email + meeting + mention + imessage
[ ] Timeline returns chronologically sorted interactions (newest first)
[ ] Timeline includes Gmail interactions with clickable links
[ ] Timeline includes Calendar interactions with clickable links
[ ] Timeline includes Vault mentions with obsidian:// links
[ ] Timeline includes iMessage conversations
[ ] Timeline filtering by source works
[ ] Timeline filtering by days works
[ ] Timeline pagination works
[ ] Snippet text is sanitized (no HTML, truncated)
[ ] Source links are valid and openable
[ ] Performance: <200ms for person detail
[ ] Performance: <500ms for timeline with 50 items
```

**Test File:** `tests/test_crm_api_person_detail.py`

**Completion Promise:** `<promise>P9.3-PERSON-DETAIL-COMPLETE</promise>`

---

### P9.4: CRM API - Connections & Relationships

**Requirements:**
API endpoints to discover and display relationships between people.

**Relationship Detection:**
1. **Shared calendar events** - people who attend same meetings
2. **Shared email threads** - people CC'd on same threads
3. **Vault co-mentions** - people mentioned in same notes
4. **Explicit relationships** - manually tagged (family, coworker, etc.)

**Endpoint:** `GET /api/crm/people/{id}/connections`

**Response Schema:**
```json
{
  "connections": [
    {
      "person_id": "uuid",
      "name": "Yoni Goldstein",
      "company": "Movement Labs",
      "relationship_type": "coworker",
      "shared_events_count": 45,
      "shared_threads_count": 12,
      "shared_contexts": ["Work/ML/"],
      "connection_strength": 0.78
    }
  ],
  "count": 15
}
```

**Relationship Discovery Algorithm:**
```python
def discover_relationships(person_id: str) -> list[Relationship]:
    """
    Find people connected to this person through:
    1. Shared calendar events (same attendee lists)
    2. Shared email threads (CC'd together)
    3. Vault co-mentions (same note)
    """
    relationships = []

    # Get all interactions for this person
    interactions = interaction_store.get_for_person(person_id)

    for interaction in interactions:
        if interaction.source_type == "calendar":
            # Find other attendees from same event
            other_attendees = get_event_attendees(interaction.source_id)
            for attendee in other_attendees:
                if attendee != person_id:
                    relationships.append(Relationship(
                        person_a=person_id,
                        person_b=attendee,
                        type="shared_meeting",
                        context=interaction.source_id
                    ))

    return aggregate_and_score(relationships)
```

**Acceptance Criteria:**
```
[ ] Connections discovered from shared calendar events
[ ] Connections discovered from shared email threads
[ ] Connections discovered from vault co-mentions
[ ] Connection strength calculated from interaction frequency
[ ] Relationship type inferred from context (coworker if Work/ML/)
[ ] Connections sorted by strength descending
[ ] No self-connections returned
[ ] Performance: <1s for person with 50 connections
[ ] Test: Yoni has connections to other ML employees
[ ] Test: Taylor has connections to family members
```

**Test File:** `tests/test_crm_connections.py`

**Completion Promise:** `<promise>P9.4-CONNECTIONS-COMPLETE</promise>`

---

### P9.5: Relationship Strength Scoring

**Requirements:**
Calculate relationship strength score (0.0-1.0) for each person based on recency, frequency, and diversity of interactions.

**Formula:**
```
strength = (recency × 0.3) + (frequency × 0.4) + (diversity × 0.3)

Where:
- recency = max(0, 1 - days_since_last_interaction / 90)
- frequency = min(1, interactions_in_90_days / 20)
- diversity = unique_source_types / total_source_types
```

**Example Calculations:**
| Person | Days Since | Interactions (90d) | Sources | Recency | Frequency | Diversity | Strength |
|--------|------------|-------------------|---------|---------|-----------|-----------|----------|
| Taylor | 1 | 50 | 4 (gmail, cal, imsg, vault) | 0.99 | 1.0 | 0.67 | 0.90 |
| Yoni | 3 | 30 | 3 (gmail, cal, vault) | 0.97 | 1.0 | 0.50 | 0.84 |
| Old friend | 60 | 2 | 1 (gmail) | 0.33 | 0.10 | 0.17 | 0.19 |

**Acceptance Criteria:**
```
[ ] Recency score = 1.0 for interaction today
[ ] Recency score = 0.0 for interaction >90 days ago
[ ] Frequency score = 1.0 for 20+ interactions in 90 days
[ ] Frequency score capped at 1.0 (no bonus for >20)
[ ] Diversity score increases with more source types
[ ] Overall strength between 0.0 and 1.0
[ ] Strength updates when new interactions recorded
[ ] Strength persisted on PersonEntity
[ ] Strength used for default sort in people list
[ ] Test: Taylor strength > 0.8
[ ] Test: Inactive contact strength < 0.3
```

**Test File:** `tests/test_relationship_metrics.py` (exists, verify coverage)

**Completion Promise:** `<promise>P9.5-STRENGTH-SCORING-COMPLETE</promise>`

---

## Phase 10: CRM Frontend

### P10.1: People List View

**Requirements:**
Main CRM page showing filterable, searchable list of people.

**URL:** `/crm`

**UI Components:**
```
┌─────────────────────────────────────────────────────────────┐
│  LifeOS CRM                    [Search...] [👥 2,236 people]│
├───────────────────────┬─────────────────────────────────────┤
│ [All] [Work] [Personal]                                     │
├───────────────────────┤                                     │
│                       │                                     │
│  ┌─────────────────┐  │  Select a person to view details    │
│  │ 🔵 Taylor Walker│  │                                     │
│  │ Personal · 847  │  │                                     │
│  │ ████████████░░ │  │                                     │
│  └─────────────────┘  │                                     │
│  ┌─────────────────┐  │                                     │
│  │ 🔵 Yoni         │  │                                     │
│  │ Movement Labs   │  │                                     │
│  │ ████████░░░░░░ │  │                                     │
│  └─────────────────┘  │                                     │
│  ...                  │                                     │
│                       │                                     │
└───────────────────────┴─────────────────────────────────────┘
```

**Acceptance Criteria:**
```
[ ] Page loads at /crm route
[ ] Header shows total people count
[ ] Search box filters people list in real-time (<300ms)
[ ] Category tabs filter by work/personal/family
[ ] People cards show: avatar, name, company/category, interaction count
[ ] People cards show relationship strength bar
[ ] List sorted by relationship strength by default
[ ] Clicking person opens detail panel
[ ] Infinite scroll loads more people
[ ] Loading states shown during API calls
[ ] Empty states shown when no results
[ ] Mobile responsive layout
```

**Test File:** `tests/test_crm_ui_people_list.py` (E2E with Playwright)

**Completion Promise:** `<promise>P10.1-PEOPLE-LIST-UI-COMPLETE</promise>`

---

### P10.2: Person Detail View

**Requirements:**
Detail panel showing full information about selected person.

**UI Components:**
```
┌─────────────────────────────────────────────────────────────┐
│  Taylor Walker                                    [← Back]  │
│  annetaylorwalker@gmail.com · +1 901-229-5017              │
│  Personal · 847 interactions · Last seen: Today             │
├─────────────────────────────────────────────────────────────┤
│  [Overview] [Timeline] [Connections] [Graph]                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Contact Information                                        │
│  📧 annetaylorwalker@gmail.com                             │
│  📱 +1 901-229-5017                                        │
│                                                             │
│  Statistics                                                 │
│  📧 156 emails · 📅 23 meetings · 💬 656 texts             │
│  📝 12 mentions                                            │
│                                                             │
│  Sources                                                    │
│  [gmail] [calendar] [imessage] [phone_contacts] [vault]    │
│                                                             │
│  Notes                                                      │
│  [                                                  ]       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Acceptance Criteria:**
```
[ ] Detail panel slides in when person selected
[ ] Shows all contact information (emails, phones)
[ ] Shows interaction statistics (not all zeros)
[ ] Shows source badges for all data sources
[ ] Shows last seen date
[ ] Shows relationship strength indicator
[ ] Notes textarea saves on blur
[ ] Tags can be added/removed
[ ] Back button closes detail panel
```

**Test File:** `tests/test_crm_ui_person_detail.py`

**Completion Promise:** `<promise>P10.2-PERSON-DETAIL-UI-COMPLETE</promise>`

---

### P10.3: Timeline View

**Requirements:**
Chronological list of all interactions with a person.

**UI Components:**
```
┌─────────────────────────────────────────────────────────────┐
│  Timeline                                    [All sources ▼]│
├─────────────────────────────────────────────────────────────┤
│  Today                                                      │
│  ├─ 💬 10:30 AM  Text conversation                         │
│  │  "Hey, are you coming home for dinner?"                 │
│  │                                                          │
│  Yesterday                                                  │
│  ├─ 📅 3:00 PM   Doctor appointment                        │
│  │  Annual checkup · [Open in Calendar]                    │
│  │                                                          │
│  ├─ 📧 11:15 AM  Re: Weekend plans                         │
│  │  "Sounds good! Let's do brunch at 11" · [Open in Gmail] │
│  │                                                          │
│  Jan 25                                                     │
│  ├─ 📝 Mentioned in "Daily Note 2026-01-25"                │
│  │  Discussed vacation plans with Taylor · [Open Note]     │
│  │                                                          │
│  [Load more...]                                             │
└─────────────────────────────────────────────────────────────┘
```

**Acceptance Criteria:**
```
[ ] Timeline shows interactions from interaction_store
[ ] Interactions grouped by date
[ ] Each interaction shows: icon, time, title, snippet
[ ] Source filter dropdown works
[ ] Clicking interaction opens source link
[ ] Gmail links open correct email
[ ] Calendar links open correct event
[ ] Obsidian links open correct note
[ ] iMessage shows conversation snippet
[ ] Infinite scroll loads older interactions
[ ] "No interactions" shown when empty
[ ] Test: Taylor has >50 timeline items
```

**Test File:** `tests/test_crm_ui_timeline.py`

**Completion Promise:** `<promise>P10.3-TIMELINE-UI-COMPLETE</promise>`

---

### P10.4: Graph Visualization

**Requirements:**
D3.js force-directed graph showing relationship network.

**UI Components:**
```
┌─────────────────────────────────────────────────────────────┐
│  Graph                    [Reset Zoom] [☑ Show Labels]      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│              ○ Madi                                         │
│             /    \                                          │
│         ○ Yoni ── ● Taylor ── ○ Mom                        │
│           \                   /                             │
│            ○ Hayley ─────────○ Dad                         │
│                                                             │
│                                                             │
│  Legend:  ● Selected  ○ Connection  ━ Strong  ─ Weak       │
└─────────────────────────────────────────────────────────────┘
```

**Acceptance Criteria:**
```
[ ] Graph renders with D3.js force-directed layout
[ ] Selected person shown as center node (different color)
[ ] Connections shown as surrounding nodes
[ ] Edge thickness represents relationship strength
[ ] Nodes are draggable
[ ] Graph is zoomable and pannable
[ ] Clicking node navigates to that person
[ ] Hovering node shows tooltip with name/company
[ ] Show Labels toggle works
[ ] Reset Zoom button resets view
[ ] Graph updates when person selection changes
[ ] Performance: renders <2s for 30 nodes
```

**Test File:** `tests/test_crm_ui_graph.py`

**Completion Promise:** `<promise>P10.4-GRAPH-UI-COMPLETE</promise>`

---

## Phase 11: Additional Data Sources

### P11.1: Slack Integration

**Requirements:**
OAuth integration with Slack to sync workspace users and message history.

**Configuration:**
```
SLACK_CLIENT_ID=xxx
SLACK_CLIENT_SECRET=xxx
SLACK_REDIRECT_URI=http://localhost:8000/api/crm/slack/callback
```

**OAuth Scopes:**
- `users:read` - Read user profiles
- `users:read.email` - Read user emails
- `channels:history` - Read channel messages
- `im:history` - Read DM messages

**API Endpoints:**
- `GET /api/crm/slack/status` - Check connection status
- `GET /api/crm/slack/oauth/start` - Get OAuth URL
- `GET /api/crm/slack/callback` - OAuth callback
- `POST /api/crm/slack/sync` - Sync users

**Entity Resolution:**
- Match Slack users to PersonEntity by email
- Create new entities for unmatched users
- Add "slack" to sources list

**Acceptance Criteria:**
```
[ ] OAuth flow completes successfully
[ ] Token stored securely
[ ] Users synced with email, name, title
[ ] Existing entities matched by email
[ ] New entities created for unknown users
[ ] "slack" added to person sources
[ ] Slack messages create interactions
[ ] DM conversations tracked
[ ] Test: After sync, Slack user appears in CRM
```

**Test File:** `tests/test_slack_integration.py` (exists, verify coverage)

**Completion Promise:** `<promise>P11.1-SLACK-COMPLETE</promise>`

---

### P11.2: Apple Contacts Integration

**Requirements:**
Read contacts from macOS Contacts.app to enhance person records.

**Platform:** macOS only (uses pyobjc-framework-Contacts)

**API Endpoints:**
- `GET /api/crm/contacts/status` - Check availability and authorization
- `POST /api/crm/contacts/sync` - Sync contacts

**Entity Resolution:**
- Match by email first
- Match by phone second
- Match by exact name third
- Create new entity if no match

**Acceptance Criteria:**
```
[ ] Contacts framework availability detected
[ ] Authorization status checked
[ ] All contacts read with: name, emails, phones, company
[ ] Existing entities matched by email
[ ] Existing entities matched by phone
[ ] New entities created for unknown contacts
[ ] "contacts" added to person sources
[ ] Multiple phone numbers supported
[ ] Test: After sync, contact appears in CRM
```

**Test File:** `tests/test_apple_contacts.py` (exists, verify coverage)

**Completion Promise:** `<promise>P11.2-APPLE-CONTACTS-COMPLETE</promise>`

---

### P11.3: WhatsApp & Signal Import

**Requirements:**
Parse exported chat files from WhatsApp (.txt) and Signal (.json).

**API Endpoint:**
- `POST /api/crm/sources/import?source_type=whatsapp|signal`
- Accepts file upload

**WhatsApp Format:**
```
[12/1/2024, 10:30:15 AM] John Doe: Hello!
[12/1/2024, 10:31:00 AM] Jane Smith: Hi John!
```

**Signal Format:**
```json
{
  "conversations": [...],
  "messages": [...]
}
```

**Acceptance Criteria:**
```
[ ] WhatsApp .txt files parsed correctly
[ ] Signal .json files parsed correctly
[ ] Participants extracted from messages
[ ] Phone numbers normalized to E.164
[ ] Message counts tracked per participant
[ ] First/last message timestamps captured
[ ] Entities created/matched for participants
[ ] Import statistics returned
[ ] Test: Import WhatsApp chat, participants appear in CRM
```

**Test Files:** `tests/test_whatsapp_import.py`, `tests/test_signal_import.py` (exist, verify coverage)

**Completion Promise:** `<promise>P11.3-CHAT-IMPORT-COMPLETE</promise>`

---

## Critical Integration Tests

These tests verify end-to-end functionality using real data.

### Test: Taylor Data Integrity

```python
def test_taylor_data_integrity():
    """
    Taylor is the primary test case - should have highest interaction count.
    """
    # Find by email
    person = crm_api.search_people(q="annetaylorwalker@gmail.com")[0]

    # Basic info
    assert person.canonical_name in ["Tay", "Taylor", "Anne Taylor Walker"]
    assert "annetaylorwalker@gmail.com" in person.emails
    assert "+19012295017" in person.phone_numbers

    # Interaction counts (should NOT be zero)
    assert person.interaction_count > 100, f"Expected >100 interactions, got {person.interaction_count}"
    assert len(person.sources) >= 3, f"Expected >=3 sources, got {person.sources}"

    # Timeline
    timeline = crm_api.get_timeline(person.id, days=90)
    assert timeline.count > 50, f"Expected >50 timeline items, got {timeline.count}"

    # Relationship strength
    assert person.relationship_strength > 0.8, f"Expected strength >0.8, got {person.relationship_strength}"
```

### Test: Top Contacts Have Data

```python
def test_top_contacts_have_data():
    """
    Top 10 contacts by interaction count should all have real data.
    """
    people = crm_api.list_people(sort="interaction_count", order="desc", limit=10)

    for person in people:
        assert person.interaction_count > 0, f"{person.canonical_name} has 0 interactions"
        assert len(person.sources) > 0, f"{person.canonical_name} has no sources"
        assert person.last_seen is not None, f"{person.canonical_name} has no last_seen"
```

### Test: Work Contacts Have Company

```python
def test_work_contacts_have_context():
    """
    Work contacts should have company and vault context.
    """
    people = crm_api.list_people(category="work", limit=20)

    ml_count = sum(1 for p in people if p.company == "Movement Labs" or "Work/ML/" in p.vault_contexts)
    assert ml_count > 5, f"Expected >5 ML employees, got {ml_count}"
```

---

## Implementation Order

1. **P9.1: Data Integrity** - Fix the fundamental data flow issues first
2. **P9.5: Strength Scoring** - Calculate and persist relationship strengths
3. **P9.2: People List API** - Verified working endpoint with real data
4. **P9.3: Person Detail API** - Timeline with real interactions
5. **P9.4: Connections API** - Relationship discovery
6. **P10.1-4: Frontend** - UI components that display real data
7. **P11.x: Additional Sources** - Slack, Contacts, Chat imports

---

## Success Metrics

The CRM is complete when:

1. **Taylor test passes**: >100 interactions, >3 sources, strength >0.8
2. **Top 10 test passes**: All top contacts have non-zero interaction counts
3. **Timeline works**: Shows real Gmail, Calendar, iMessage, Vault interactions
4. **Graph renders**: Shows actual relationships from shared events
5. **All 137+ CRM tests pass**: Unit + integration + E2E

---

## Files Reference

| File | Purpose |
|------|---------|
| `api/routes/crm.py` | CRM API endpoints |
| `api/services/person_entity.py` | PersonEntity model & store |
| `api/services/interaction_store.py` | Interaction storage |
| `api/services/relationship.py` | Relationship model & store |
| `api/services/relationship_metrics.py` | Strength calculation |
| `api/services/entity_resolver.py` | Multi-source entity resolution |
| `web/crm.html` | CRM frontend UI |
| `tests/test_crm_*.py` | CRM test files |

---

## Phase 12: Multi-Source Relationship Tracking

### P12.1: Extended Relationship Data Model

**Requirements:**
Track relationship signals from all communication sources, not just calendar and email threads.

**Current Model Limitations:**
- `shared_events_count` - Only calendar events
- `shared_threads_count` - Only email threads
- No tracking of direct messaging (iMessage, WhatsApp, Slack DMs)
- No LinkedIn connection signal

**Extended Relationship Fields:**
```python
@dataclass
class Relationship:
    # Existing fields
    shared_events_count: int = 0      # Calendar events together
    shared_threads_count: int = 0     # Email threads together

    # NEW: Direct messaging counts
    shared_messages_count: int = 0    # iMessage/SMS direct threads
    shared_whatsapp_count: int = 0    # WhatsApp direct threads
    shared_slack_count: int = 0       # Slack DM message count

    # NEW: LinkedIn connection flag
    is_linkedin_connection: bool = False
```

**Acceptance Criteria:**
```
[ ] Database migration adds new columns to relationships table
[ ] Relationship model includes new fields
[ ] RelationshipStore supports reading/writing new fields
[ ] Existing relationships preserve current data during migration
```

---

### P12.2: Relationship Discovery Updates

**Requirements:**
Update discovery to populate new relationship fields from all data sources.

**iMessage Discovery (shared_messages_count):**
- Count DM thread interactions between two people
- Group chat membership already tracked in shared_contexts
- Direct 1:1 message threads contribute to count

**WhatsApp Discovery (shared_whatsapp_count):**
- Count WhatsApp interactions in direct threads
- Parse from imported WhatsApp data

**Slack DM Discovery (shared_slack_count):**
- Count Slack DM messages between two people
- Uses existing Slack indexer data

**LinkedIn Discovery (is_linkedin_connection):**
- Check if both people have LinkedIn source entities
- Parse LinkedIn connection data from CSV imports

**Acceptance Criteria:**
```
[ ] iMessage DM threads counted per relationship
[ ] WhatsApp DM threads counted per relationship
[ ] Slack DM messages counted per relationship
[ ] LinkedIn connections flagged on relationships
[ ] Discovery script updates all source counts
```

---

### P12.3: API Updates for Source Breakdown

**Requirements:**
API returns detailed breakdown of relationship sources.

**Updated RelationshipDetailResponse:**
```python
class RelationshipDetailResponse(BaseModel):
    # Existing fields
    person_a_id: str
    person_a_name: str
    person_b_id: str
    person_b_name: str
    relationship_type: str
    shared_contexts: list[str] = []

    # Source breakdown
    shared_events_count: int = 0      # Calendar
    shared_threads_count: int = 0     # Email
    shared_messages_count: int = 0    # iMessage
    shared_whatsapp_count: int = 0    # WhatsApp
    shared_slack_count: int = 0       # Slack DMs
    is_linkedin_connection: bool = False

    # Computed totals
    total_interactions: int = 0
    weight: int = 0
```

**Updated /api/crm/people/{id}/network Endpoint:**
- Include all source counts in edge data
- Allow filtering by source type in query params

**Acceptance Criteria:**
```
[ ] Relationship endpoint returns all source counts
[ ] Network endpoint includes source breakdown per edge
[ ] Edge weight calculation uses all sources
```

---

### P12.4: Graph Source Filter UI

**Requirements:**
Add multi-select dropdown to filter graph edges by source type.

**UI Component:**
```
Edge Strength: [===|=======] 15%    Sources: [▼ All Sources]
                                           ☑ Calendar
                                           ☑ Email
                                           ☑ iMessage
                                           ☑ WhatsApp
                                           ☑ Slack
                                           ☑ LinkedIn
```

**Behavior:**
- Default: All sources selected
- Edge visible if ANY selected source has count > 0
- Edge weight recalculated based on selected sources only
- Filter state preserved when navigating nodes

**Acceptance Criteria:**
```
[ ] Multi-select dropdown with all source types
[ ] Edges filter to show only edges with selected source types
[ ] Edge weight updates based on selected sources
[ ] Filter state preserved on node navigation
[ ] Edge panel shows breakdown by source
```

---

### P12.5: Edge Weight Calculation Update

**Requirements:**
Update edge weight to sum contributions from all sources.

**Weight Formula:**
```python
weight = (
    shared_events_count * 3 +      # Calendar meetings (high signal)
    shared_threads_count * 2 +     # Email threads
    shared_messages_count * 2 +    # iMessage threads
    shared_whatsapp_count * 2 +    # WhatsApp threads
    shared_slack_count * 1 +       # Slack DMs (weaker signal per message)
    (10 if is_linkedin_connection else 0)  # LinkedIn connection bonus
)
```

**Acceptance Criteria:**
```
[ ] Weight calculated from all sources
[ ] Configurable weights per source type
[ ] Graph filters respect new weight calculation
```

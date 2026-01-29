# Personal CRM Implementation Plan

**Date:** 2026-01-28
**Status:** Approved for Implementation
**Author:** Claude + Nathan

---

## Overview

Build a comprehensive Personal CRM on top of LifeOS's People system, focusing on **Network Management** and **Relationship Context** (not outbound CRM). New UI pages separate from chat, overhauled backend with additional data sources, and improved entity resolution with confirmation workflows.

## Key Requirements

- **Primary Use Cases**: Network discovery, relationship visualization, meeting prep context
- **NOT**: Outbound CRM, follow-ups, pipelines, reminders
- **Data Model**: One canonical record per person, auto-update from sources, user confirms/rejects at entity-linking level (not field level)
- **UI Stack**: Vanilla JS (match existing codebase)

## Data Sources

### Already Integrated (Reuse/Extend)
| Source | Current State | CRM Usage |
|--------|--------------|-----------|
| iMessage | Full integration in `api/services/imessage.py` | Extend for SourceEntity creation |
| Calendar (work+personal) | Full integration in `api/services/calendar.py` | Extend for SourceEntity creation |
| Gmail (work+personal) | Full integration in `api/services/gmail.py` | Extend for SourceEntity creation |
| LinkedIn Export | CSV import exists | Keep as-is, extend for SourceEntity |
| Apple Contacts Export | Static CSV import exists | **Replace with live sync** |

### New Integrations
| Source | Approach | Notes |
|--------|----------|-------|
| **Apple Contacts** | Live sync via pyobjc-framework-Contacts | Replace static export with continuous sync |
| **Phone Calls** | Read macOS CallHistoryDB | Requires Full Disk Access |
| **WhatsApp** | Use [wacli](https://github.com/steipete/wacli) | CLI tool for WhatsApp export |
| **Signal** | Parse exported JSON backup | User-initiated export |
| **Slack** | **Indirect approach** - no formal OAuth approval from org possible. Options: personal token, export parsing, or workspace admin tools | May need workaround |

---

## Architecture Decisions

### 1. Two-Tier Data Model

Separate **SourceEntity** (raw observations, immutable) from **CanonicalPerson** (unified records):

```
SourceEntity (SQLite)           CanonicalPerson (JSON)
├── id                          ├── id
├── source_type                 ├── canonical_name
├── observed_name/email/phone   ├── emails[], phone_numbers[]
├── metadata (JSON)             ├── company, position, linkedin_url
├── canonical_person_id ──────► ├── category, vault_contexts[], tags[]
├── link_confidence             ├── relationship_strength (computed)
├── link_status (auto/confirmed)├── source_entity_count
└── observed_at                 └── first_seen, last_seen
```

**Rationale**: Enables entity-level linking confirmation, preserves source data for re-linking, supports undo/history.

### 2. Storage Strategy

| Data | Storage | Rationale |
|------|---------|-----------|
| SourceEntity | SQLite (`crm.db`) | High-volume, needs efficient queries |
| CanonicalPerson | JSON (evolved from `people_entities.json`) | Moderate count, complex nested data |
| PendingLink | SQLite (`crm.db`) | Workflow state, simple records |
| Relationship | SQLite (`crm.db`) | Graph queries, overlaps |

### 3. Configurable Mappings

Move hardcoded `DOMAIN_CONTEXT_MAP` to `config/crm_mappings.yaml`:
```yaml
domain_mappings:
  movementlabs.xyz:
    company: "Movement Labs"
    vault_contexts: ["Work/ML/"]
    category: work
```

### 4. Relationship Strength Scoring

```
strength = (recency × 0.3) + (frequency × 0.4) + (diversity × 0.3)
```
- recency: max(0, 1 - days_since_last/90)
- frequency: min(1, interactions_90d/20)
- diversity: unique_sources / total_sources

### 5. Slack Integration Strategy

**Challenge**: Cannot get formal OAuth approval from organization.

**Options:**
1. **Personal User Token** - User generates personal token, limited scope
2. **Export Parsing** - User exports Slack history, we parse
3. **Workspace Admin Export** - If user has admin access
4. **Skip for MVP** - Defer Slack until workaround found

**Recommendation**: Start with option 2 (export parsing), add personal token later if user can generate one.

### 6. WhatsApp via wacli

Use https://github.com/steipete/wacli for WhatsApp integration:
- CLI tool that exports WhatsApp chats
- Run periodically or on-demand
- Parse exported data for SourceEntities and Interactions

---

## Database Schema

### source_entities (new table in crm.db)
```sql
CREATE TABLE source_entities (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,  -- gmail, calendar, slack, imessage, whatsapp, signal, contacts, linkedin, vault, phone_calls
    source_id TEXT,  -- External ID (message_id, event_id, etc.)

    -- Identity signals (what we observed)
    observed_name TEXT,
    observed_email TEXT,
    observed_phone TEXT,  -- E.164 format

    -- Source-specific metadata (JSON)
    metadata TEXT,

    -- Linking
    canonical_person_id TEXT,  -- FK to CanonicalPerson.id
    link_confidence REAL DEFAULT 0.0,
    link_status TEXT DEFAULT 'auto',  -- auto, confirmed, rejected
    linked_at TIMESTAMP,
    linked_by TEXT,  -- 'system' or 'user'

    -- Timestamps
    observed_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(source_type, source_id)
);

CREATE INDEX idx_source_entities_canonical ON source_entities(canonical_person_id);
CREATE INDEX idx_source_entities_email ON source_entities(observed_email);
CREATE INDEX idx_source_entities_phone ON source_entities(observed_phone);
CREATE INDEX idx_source_entities_name ON source_entities(observed_name);
CREATE INDEX idx_source_entities_type ON source_entities(source_type);
```

### pending_links (new table in crm.db)
```sql
CREATE TABLE pending_links (
    id TEXT PRIMARY KEY,
    source_entity_id TEXT NOT NULL,
    previous_canonical_id TEXT,
    proposed_canonical_id TEXT NOT NULL,
    reason TEXT,  -- new_entity, email_match, phone_match, name_match
    confidence REAL,
    status TEXT DEFAULT 'pending',  -- pending, confirmed, rejected
    resolved_at TIMESTAMP,
    resolved_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_pending_links_status ON pending_links(status);
CREATE INDEX idx_pending_links_canonical ON pending_links(proposed_canonical_id);
```

### relationships (new table in crm.db)
```sql
CREATE TABLE relationships (
    id TEXT PRIMARY KEY,
    person_a_id TEXT NOT NULL,
    person_b_id TEXT NOT NULL,
    relationship_type TEXT,  -- coworker, friend, family, inferred
    shared_contexts TEXT,  -- JSON array
    shared_events_count INTEGER DEFAULT 0,
    shared_threads_count INTEGER DEFAULT 0,
    first_seen_together TIMESTAMP,
    last_seen_together TIMESTAMP,
    user_notes TEXT,
    user_confirmed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(person_a_id, person_b_id)
);

CREATE INDEX idx_relationships_person_a ON relationships(person_a_id);
CREATE INDEX idx_relationships_person_b ON relationships(person_b_id);
```

---

## API Endpoints

### New CRM Routes (`/api/crm/*`)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/people` | GET | List/search with filters (category, source, pending, sort) |
| `/people/{id}` | GET | Full detail + source entities + pending links + relationships |
| `/people/{id}` | PATCH | Update notes, tags, category |
| `/people/{id}/timeline` | GET | Chronological interaction history |
| `/people/{id}/connections` | GET | Related people with overlap scores |
| `/pending-links` | GET | List pending entity links |
| `/pending-links/{id}/confirm` | POST | Confirm a proposed link |
| `/pending-links/{id}/reject` | POST | Reject (optionally create new person) |
| `/discover` | GET | Suggested connections based on shared contexts |
| `/sources/import` | POST | Upload WhatsApp/Signal export files |
| `/sources/{type}/sync` | POST | Trigger source sync |
| `/statistics` | GET | Dashboard stats |

---

## UI Structure

### New `/crm` Route (in index.html)

```
/crm
├── Header: Search bar + filters (category, source) + view toggle
├── Left Panel: People list
│   └── Person Card: Avatar, name, company, strength bar, source badges
├── Right Panel: Person detail (slide-in)
│   ├── Header: Photo, name, company, title, edit button
│   ├── Tabs:
│   │   ├── Overview: Contact info, metrics, editable notes, tags
│   │   ├── Timeline: Filterable chronological interactions
│   │   └── Connections: Relationship list + mini graph
│   └── Source Entities: Collapsible section showing linked sources
└── Modals:
    ├── Link Confirmation: Source details, proposed match, alternatives
    ├── Import Wizard: Source type selection, file upload, preview
    └── Relationship Graph: D3.js force-directed visualization
```

### CSS Variables (extend existing theme)
```css
:root {
  /* CRM-specific */
  --crm-strength-high: #4caf50;
  --crm-strength-medium: #ff9800;
  --crm-strength-low: #9e9e9e;

  /* Source badges */
  --source-gmail: #ea4335;
  --source-calendar: #4285f4;
  --source-slack: #4a154b;
  --source-imessage: #34c759;
  --source-whatsapp: #25d366;
  --source-signal: #3a76f0;
  --source-contacts: #ff9500;
  --source-linkedin: #0077b5;
  --source-phone: #8e8e93;

  /* People accent (existing) */
  --people: #00bcd4;
}
```

---

## Implementation Phases

### Phase 1: Foundation (Backend Data Model)

**Goal**: New data model without breaking existing functionality

**Files to create:**
- `api/services/source_entity.py` - SourceEntity store (SQLite)
- `api/services/canonical_person.py` - evolved from person_entity.py
- `api/services/pending_link.py` - link confirmation workflow
- `scripts/migrate_to_crm.py` - data migration

**Files to modify:**
- `api/services/entity_resolver.py` - two-tier resolution + pending links

**Tests:**
- `tests/test_source_entity.py`
- `tests/test_canonical_person.py`
- `tests/test_pending_link.py`

**Verification:**
1. Run migration script on backup data
2. Verify all existing PersonEntity records migrated
3. Run existing people tests (should still pass)

---

### Phase 2: Core API

**Goal**: CRM API endpoints working

**Files to create:**
- `api/routes/crm.py` - new CRM API routes
- `api/services/relationship_discovery.py` - overlap detection
- `api/services/relationship_metrics.py` - strength calculation

**Tests:**
- `tests/test_crm_api.py`
- `tests/test_relationship_discovery.py`

**Verification:**
1. All API endpoints return expected data
2. Relationship strength calculated correctly
3. Pending links workflow works end-to-end

---

### Phase 3: Data Source Extensions

**Goal**: Existing sources create SourceEntities; new sources integrated

**3a. Extend Existing Sources:**
- Modify `api/services/gmail.py` - create SourceEntities
- Modify `api/services/calendar.py` - create SourceEntities
- Modify `api/services/imessage.py` - create SourceEntities
- Keep LinkedIn CSV import, extend for SourceEntity

**3b. New Sources:**
- `api/services/apple_contacts_live.py` - pyobjc-framework-Contacts
- `api/services/phone_calls.py` - CallHistoryDB
- `api/services/whatsapp.py` - wacli integration
- `api/services/signal_import.py` - JSON backup parser
- (Slack deferred or export-based)

**Tests:**
- `tests/test_source_entity_gmail.py`
- `tests/test_apple_contacts_live.py`
- `tests/test_phone_calls.py`
- `tests/test_whatsapp.py`
- `tests/test_signal_import.py`

**Verification:**
1. Each source creates valid SourceEntities
2. Entity linking works across sources
3. Import flow handles errors gracefully

---

### Phase 4: Frontend - CRM Page

**Goal**: Functional CRM UI

**Files to modify:**
- `web/index.html` - add CRM page structure, routing, components

**Components to build:**
1. CRM header with search/filters
2. People list with cards
3. Person detail panel (slide-in or modal)
4. Tabs: Overview, Timeline, Connections
5. Pending links notification and modal

**Verification:**
1. Navigate to /crm, see people list
2. Search/filter works
3. Click person, see detail panel
4. Timeline loads and scrolls
5. Edit notes/tags saves correctly
6. Mobile responsive

---

### Phase 5: Relationship Visualization

**Goal**: Network graph and discovery features

**Files to modify:**
- `web/index.html` - add D3.js graph component

**Features:**
1. Force-directed graph of relationships
2. Click node to view person
3. Filter by relationship type
4. Zoom/pan controls
5. "People you may know" suggestions

**Verification:**
1. Graph renders with nodes/edges
2. Interactive features work
3. Performance acceptable with 100+ nodes

---

### Phase 6: Polish & Performance

**Goal**: Production readiness

**Tasks:**
- Add caching for expensive queries
- Optimize database indices
- E2E tests with Playwright
- Documentation
- Error handling and graceful degradation

---

## Critical Files Reference

| File | Purpose |
|------|---------|
| `api/services/person_entity.py` | Evolve to CanonicalPerson |
| `api/services/entity_resolver.py` | Enhance for two-tier + pending links |
| `api/services/interaction_store.py` | Pattern for SourceEntity store |
| `api/routes/people.py` | Maintain compatibility, base for CRM routes |
| `web/index.html` | Add CRM page structure |
| `config/crm_mappings.yaml` | New - domain mappings |

---

## New Dependencies

```python
# requirements.txt additions

# Apple Contacts (macOS)
pyobjc-framework-Contacts>=9.0

# (Slack SDK if using personal token approach)
# slack-sdk>=3.21.0
```

```html
<!-- Frontend (CDN in index.html) -->
<script src="https://d3js.org/d3.v7.min.js"></script>
```

---

## Migration Plan

1. **Backup existing data**
   ```bash
   cp data/people_entities.json data/people_entities.json.bak
   cp data/interactions.db data/interactions.db.bak
   ```

2. **Run migration script**
   ```bash
   python scripts/migrate_to_crm.py
   ```
   - Convert PersonEntity → CanonicalPerson
   - Create SourceEntity from existing interactions
   - Link sources to canonicals
   - Calculate initial relationship strengths

3. **Verify migration**
   - Compare record counts
   - Spot-check known persons
   - Run existing tests

4. **Rollback if needed**
   - Keep old code behind feature flag
   - Script to restore from backup

---

## Subagent Roles for Implementation

| Agent | Responsibility | Dependencies |
|-------|---------------|--------------|
| **Backend-Data** | Phase 1: Models, migration, tests | None |
| **Backend-API** | Phase 2: CRM routes, relationship services | Phase 1 |
| **Integrations** | Phase 3: Extend existing + new sources | Phase 1 |
| **Frontend** | Phase 4-5: CRM UI, visualizations | Phase 2 |
| **QA** | E2E testing, performance | Phase 4 |

**Parallelization**: After Phase 1, Backend-API, Integrations, and Frontend can work in parallel.

---

## Open Questions / Decisions Needed

1. **Slack**: Which indirect approach to pursue?
   - Export parsing (user exports manually)
   - Personal token (if user can generate one)
   - Defer entirely for MVP

2. **wacli setup**: Need to install and configure wacli for WhatsApp access

3. **Apple Contacts live sync frequency**: On-demand? Hourly? Daily?

4. **Phone calls database location**: Confirm path and permissions on user's system

---

## Success Criteria

1. Can search for any person across all sources
2. Can see unified timeline of all interactions with a person
3. Can see relationships and overlaps between people
4. Entity linking confirmation workflow works smoothly
5. New sources (Contacts, Phone, WhatsApp) populate correctly
6. UI is responsive and performant with 500+ people
7. Existing LifeOS features (chat, search) unaffected

---

## Phase 7: Data Sync Completeness

**Date Added:** 2026-01-29
**Status:** In Progress

### Current State Audit (2026-01-29)

| Source | Status | Count | Issue |
|--------|--------|-------|-------|
| iMessage | ✅ Working | 120,274 | Full history 2016-2026 |
| Personal Calendar | ✅ Working | 1,059 | - |
| Work Calendar (ML) | ✅ Working | 1,225 | - |
| Phone Calls | ✅ Working | 179 | - |
| Granola (meetings) | ✅ Working | 14 | - |
| Gmail | ⚠️ Partial | 2,812 | Only ~1 month synced |
| WhatsApp | ❌ Not syncing | 0 | wacli authenticated but sync never run |
| Vault Notes | ⚠️ Partial | 296 | Only 6% of 4,832 notes indexed |

### Vault Structure
```
/Users/nathanramia/Notes 2025/
├── Work/                    (543 notes - Movement Labs)
├── Personal/
│   └── zArchive/
│       ├── BlueLabs/        (39 notes)
│       ├── Deck/            (6 notes)
│       └── Murm/            (351 notes - Murmuration)
├── Granola/                 (meeting transcripts)
└── LifeOS/                  (system notes)
```

### Requirements

#### 7.1 WhatsApp Sync
- **Requirement**: Run `scripts/sync_whatsapp.py` to import WhatsApp contacts and link to PersonEntity
- **Success Criteria**:
  - WhatsApp contacts appear in CRM
  - Contacts linked to existing PersonEntity where phone matches
  - Source badges show "whatsapp" for linked people
- **Script**: `scripts/sync_whatsapp.py --execute`

#### 7.2 Vault Full Reindex
- **Requirement**: Index ALL 4,832 markdown notes, not just 296
- **Issue**: Current indexing only capturing ~6% of notes
- **Success Criteria**:
  - All vault notes scanned for person mentions
  - Work/ML notes create interactions for ML people
  - Personal/zArchive/Murm notes create interactions for Murm people
  - Personal/zArchive/BlueLabs notes create interactions for BlueLabs people
  - Personal/zArchive/Deck notes create interactions for Deck people
- **Expected Outcome**: 4,832+ vault interactions (vs current 296)

#### 7.3 Gmail Full History
- **Requirement**: Sync full Gmail history, not just last month
- **Success Criteria**:
  - Gmail interactions span full account history
  - Both personal and work accounts synced
  - Email counts match user expectation (~10K+ emails)

#### 7.4 Data Flow Validation
- **Requirement**: Verify all synced data appears correctly in UI
- **Success Criteria**:
  - Person detail page shows correct interaction counts
  - Timeline tab shows interactions from all sources
  - Source badges accurately reflect linked sources
  - Relationship graph includes edges from all shared contexts

### Implementation Tasks

1. [ ] Run WhatsApp sync (`scripts/sync_whatsapp.py --execute`)
2. [ ] Investigate vault indexing - why only 6% indexed?
3. [ ] Fix vault sync to scan all 4,832 notes
4. [ ] Run full vault reindex
5. [ ] Check Gmail sync configuration for date range
6. [ ] Run full Gmail history sync
7. [ ] Validate all data in UI
8. [ ] Run stats sync to update person counts
9. [ ] Run all tests to ensure no regressions

### Verification Queries

```sql
-- Check interaction counts by source
SELECT source_type, COUNT(*) FROM interactions GROUP BY source_type;

-- Check vault coverage
SELECT COUNT(*) FROM interactions WHERE source_type IN ('vault', 'granola');
-- Expected: 4,000+ after fix

-- Check WhatsApp
SELECT COUNT(*) FROM interactions WHERE source_type = 'whatsapp';
-- Expected: > 0 after sync

-- Check Gmail date range
SELECT MIN(timestamp), MAX(timestamp) FROM interactions WHERE source_type = 'gmail';
-- Expected: spans years, not just 1 month
```

---

## Phase 8: Next Priorities (Post Data Sync)

**Date Added:** 2026-01-29
**Status:** Pending (blocked by Phase 7)

### 8.1 Quick Facts Enhancement
- Pre-extract facts for top 50 people by strength
- Run `scripts/batch_extract_facts.py --limit 50 --execute`

### 8.2 UI Polish
- Fix any remaining loading state issues
- Ensure skeleton loading for slow operations
- Progressive enhancement for timeline/graph

### 8.3 Relationship Discovery Expansion
- Extend beyond calendar to include:
  - Same email thread (TO/CC together)
  - Same WhatsApp group
  - Same iMessage group chat
  - Co-mentioned in vault notes

### 8.4 Performance Validation
- All API endpoints < 100ms
- Person detail page loads in < 500ms
- Graph renders 100+ nodes smoothly

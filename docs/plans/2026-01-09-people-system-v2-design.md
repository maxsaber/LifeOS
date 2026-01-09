# People System v2 — Design Document

**Created:** 2026-01-09
**Status:** Approved for implementation
**Author:** Nathan + Claude (collaborative design session)

---

## Overview

Redesign of the LifeOS people/contacts system to provide robust entity resolution across Gmail, Calendar, Vault, and LinkedIn, with a queryable interaction history.

**Goal:** Answer questions like "Give me a detailed summary of everything I know about the person I'm about to meet with, as well as a full record of our past interactions and notes that mention them."

---

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Detail level | Hybrid (summary + drillable) | Quick prep at top, detail when needed |
| Data freshness | Nightly sync + query-time cache (15-30 min TTL) | Balance freshness vs API costs |
| Time window | Rolling 90 days default, expandable per-query | Focus on recent, allow historical deep dives |
| Entity resolution | Email-anchored, fuzzy name + domain context | Email is most reliable identifier |
| Ambiguous handling | Create separate entities | "Sarah (Movement)" vs "Sarah (Murmuration)" |
| Interaction storage | Metadata only + hyperlinks | Lightweight, leverages existing link infrastructure |
| Interaction display | Reverse chronological with source badges | Most recent first for meeting prep |

---

## Data Model

### PersonEntity

Replaces the existing `PersonRecord` dataclass. Key change: email is the primary anchor, not name.

```python
@dataclass
class PersonEntity:
    id: str                          # UUID
    canonical_name: str              # "Sarah Chen"
    display_name: str                # "Sarah Chen (Movement)" if disambiguation needed

    # Identity anchors (PRIMARY)
    emails: list[str]                # ["sarah@movementlabs.xyz", "sarah.chen@gmail.com"]
    linkedin_url: Optional[str]

    # Context
    company: Optional[str]           # Current/primary company
    position: Optional[str]
    category: str                    # "work", "personal", "family"
    vault_contexts: list[str]        # ["Work/ML/"] - folders where they appear

    # Aggregated stats
    email_count: int
    meeting_count: int
    mention_count: int
    first_seen: datetime
    last_seen: datetime

    # Linking
    aliases: list[str]               # ["Sarah", "S. Chen", "sarah.chen"]
    confidence_score: float          # 0.0-1.0, how confident we are in merges
```

### Interaction

Lightweight record with links to sources. Does NOT store full content.

```python
@dataclass
class Interaction:
    id: str
    person_id: str                   # FK to PersonEntity
    timestamp: datetime
    source_type: str                 # "gmail" | "calendar" | "vault" | "granola"

    # Metadata (not full content)
    title: str                       # Email subject, meeting title, note filename
    snippet: Optional[str]           # First 100 chars for context (optional)

    # Links to actual content
    source_link: str                 # Gmail URL, obsidian:// link, calendar event URL
    source_id: Optional[str]         # Gmail message ID, calendar event ID, file path
```

**Storage:** SQLite table `interactions`, indexed by `person_id` and `timestamp`.

---

## Entity Resolution Algorithm

### Pass 1: Email Anchoring

Email is the authoritative identifier. Same email across sources = same person.

```
LinkedIn CSV:  sarah@movementlabs.xyz → PersonEntity(emails=["sarah@movementlabs.xyz"])
Gmail:         sarah@movementlabs.xyz → same entity (exact email match)
Calendar:      sarah@movementlabs.xyz → same entity (exact email match)
```

### Pass 2: Fuzzy Name Matching with Context Boost

When we find a name without email (e.g., "Sarah" in a vault note), we score candidates:

```python
def score_candidate(name: str, note_path: str, candidate: PersonEntity) -> float:
    score = 0.0

    # Base fuzzy match on name (40% weight)
    name_similarity = fuzzy_ratio(name, candidate.canonical_name)  # 0-100
    score += name_similarity * 0.4

    # Context boost: domain → vault folder mapping (30 points)
    # If note is in "Work/ML/" and candidate has @movementlabs.xyz email
    if note_in_context(note_path, candidate.vault_contexts):
        score += 30

    # Recency boost: recently seen people more likely (10 points)
    days_since_seen = (now - candidate.last_seen).days
    if days_since_seen < 30:
        score += 10

    return score
```

### Pass 3: Disambiguation

If top two candidates score within 15 points of each other → create separate entities:
- "Sarah (Movement)" - linked to sarah@movementlabs.xyz
- "Sarah (Murmuration)" - linked to sarah@murmuration.org

### LinkedIn Integration

LinkedIn has company names (e.g., "Movement Labs") not email domains. Bridge via Company Normalization Map:

```python
COMPANY_NORMALIZATION = {
    "Movement Labs": {
        "domains": ["movementlabs.xyz", "movementlabs.com"],
        "vault_contexts": ["Work/ML/"],
    },
    "Murmuration": {
        "domains": ["murmuration.org"],
        "vault_contexts": ["Personal/zArchive/Murm/"],
    },
    "BlueLabs": {
        "domains": ["bluelabs.com", "bluelabs.io"],
        "vault_contexts": ["Personal/zArchive/BlueLabs/"],
    },
}
```

---

## Configuration

### Domain → Vault Context Map

```python
DOMAIN_CONTEXT_MAP = {
    "movementlabs.xyz": ["Work/ML/"],
    "movementlabs.com": ["Work/ML/"],
    "murmuration.org": ["Personal/zArchive/Murm/"],
    "bluelabs.com": ["Personal/zArchive/BlueLabs/"],
}
```

This is stored in `config/people_config.py` and loaded at runtime.

---

## Sync Strategy

### Nightly Sync (2-5 min, on Mac Mini)

1. Pull new Gmail contacts (last 24h of emails) → incremental add
2. Pull new Calendar attendees (last 24h of events) → incremental add
3. Vault changes tracked by existing file watcher (real-time)
4. LinkedIn only reprocessed if CSV file modified

### Query-Time Refresh (for briefings)

Before generating a briefing for a person:
1. Check cache TTL (15-30 min)
2. If stale, fetch recent Gmail/Calendar for that person only
3. Update PersonEntity and Interaction records
4. Generate briefing with fresh data

### One-Time Full Sync

Available via `POST /api/people/sync?full=true`:
- Gmail: `days_back=3650` (10 years)
- Calendar: `days_back=3650`
- Takes ~10-15 min due to API rate limits

---

## Interaction Log Format

### Summary View

```markdown
## Sarah Chen — Interaction History

**Summary:** 12 interactions since Oct 2025 | Last: 3 days ago
📧 5 emails | 📅 4 meetings | 📝 3 notes

### Recent Activity
- 📅 Jan 6: 1:1 re: Q1 planning — [View in Calendar](calendar-link)
- 📧 Jan 4: Re: Budget draft — [View in Gmail](gmail-link)
- 📝 Jan 3: ML Strategy meeting notes — [[ML Strategy meeting notes 20250103]]
- 📅 Dec 18: Q4 review — [View in Calendar](calendar-link)
...
```

All items link to source content. No full content stored in interaction records.

---

## Integration Points

### Components That Continue Working (No Changes)

| Component | Why |
|-----------|-----|
| `extract_people_from_text()` | Still extracts names → resolution happens downstream |
| Indexer | Still stores `people: ["Sarah", "Yoni"]` in chunk metadata |
| VectorStore | `people` filter continues to work |
| BM25 index | Indexes people field unchanged |
| Query Router | Routes "people" queries unchanged |
| Action Registry | `get_actions_involving_person()` works with resolved names |

### Components That Need Updates

| Component | Changes |
|-----------|---------|
| `PersonRecord` → `PersonEntity` | More fields (multiple emails, vault_contexts, confidence_score) |
| `PeopleAggregator` | New resolution logic, same `get_person()` / `search()` API |
| `BriefingsService` | Add interaction history section to output |
| `/api/people/*` routes | Return new fields |

### New Components

| Component | Purpose |
|-----------|---------|
| `interactions` SQLite table | Lightweight interaction log |
| `config/people_config.py` | Domain/company mapping configuration |
| `api/services/entity_resolver.py` | Fuzzy matching + context resolution |

---

## Database Schema

### SQLite: interactions table

```sql
CREATE TABLE interactions (
    id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    source_type TEXT NOT NULL,  -- gmail, calendar, vault, granola
    title TEXT NOT NULL,
    snippet TEXT,
    source_link TEXT NOT NULL,
    source_id TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (person_id) REFERENCES people(id)
);

CREATE INDEX idx_interactions_person_id ON interactions(person_id);
CREATE INDEX idx_interactions_timestamp ON interactions(timestamp DESC);
CREATE INDEX idx_interactions_person_timestamp ON interactions(person_id, timestamp DESC);
```

### JSON: people_entities.json

Replaces `people_aggregated.json`. Same location (`data/`), new structure.

---

## Migration Strategy

1. **Keep existing system running** during migration
2. **Build new system alongside** (new files, don't modify existing yet)
3. **Migrate data** from `people_aggregated.json` to new format
4. **Switch over** by updating imports in consumers (BriefingsService, routes)
5. **Deprecate** old `PersonRecord` after verification

---

## Acceptance Criteria

### Entity Resolution
- [ ] Email-based matching works across Gmail/Calendar/LinkedIn
- [ ] Fuzzy name matching with context boost works for vault mentions
- [ ] Ambiguous names create separate entities with disambiguation suffix
- [ ] LinkedIn company names resolve to email domains correctly
- [ ] Confidence scores track merge quality

### Interaction Log
- [ ] Interactions stored with metadata + links (no full content)
- [ ] Query by person returns reverse-chronological list
- [ ] 90-day default window, expandable per-query
- [ ] Source badges (📧 📅 📝) display correctly
- [ ] All links functional (Gmail, Calendar, Obsidian)

### Sync
- [ ] Nightly incremental sync completes in <5 min
- [ ] Query-time refresh works with 15-30 min cache TTL
- [ ] Full historical sync available on-demand
- [ ] No data loss during sync operations

### Integration
- [ ] BriefingsService includes interaction history section
- [ ] Existing vault search with people filter still works
- [ ] Existing action items by person still works
- [ ] API routes return new PersonEntity fields
- [ ] No regression in existing functionality

---

## Future Enhancements (Backlog)

- **Entity resolution manual review UI** - Flag ambiguous matches for user confirmation (added to LifeOS Backlog)

---

## Files to Create/Modify

### New Files
- `config/people_config.py` - Domain/company mapping
- `api/services/entity_resolver.py` - Resolution algorithm
- `api/services/interaction_store.py` - Interaction CRUD
- `tests/test_entity_resolver.py`
- `tests/test_interaction_store.py`

### Modified Files
- `api/services/people_aggregator.py` - Use new PersonEntity
- `api/services/briefings.py` - Add interaction history
- `api/routes/people.py` - Return new fields
- `data/people_entities.json` - New storage format (replaces people_aggregated.json)

---

*Last updated: 2026-01-09*

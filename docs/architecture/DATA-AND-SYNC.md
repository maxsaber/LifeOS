# Data & Sync Architecture

How LifeOS ingests, stores, and resolves data from multiple sources.

**Related Documentation:**
- [API & MCP Reference](API-MCP-REFERENCE.md) - API endpoints
- [CRM UI PRD](../prd/CRM-UI.md) - CRM features and requirements

---

## Table of Contents

1. [Data Sources](#data-sources)
2. [Sync Schedule](#sync-schedule)
3. [Data Stores](#data-stores)
4. [Entity Resolution](#entity-resolution)
5. [Search Pipeline](#search-pipeline)
6. [Relationship Tracking](#relationship-tracking)

---

## Data Sources

### Source Types and Sync Methods

| Source | Sync Method | Data Extracted |
|--------|-------------|----------------|
| Gmail | Google API | From/To/CC, subjects, timestamps, threads |
| Calendar | Google API | Attendees, organizer, titles, times |
| Apple Contacts | CSV Export | Names, emails, phone numbers, companies |
| Phone Calls | macOS CallHistoryDB | Numbers, names, duration, direction |
| WhatsApp | wacli CLI | JIDs, names, phone numbers |
| iMessage | macOS chat.db | Phone/email, message content, timestamps |
| Slack | Slack API (OAuth) | User profiles, DMs, channels |
| Vault Notes | Obsidian markdown | Name mentions, context paths |
| LinkedIn | CSV Import | Connections, companies, titles |
| Granola | Folder watcher | Meeting transcripts, attendees |

### Current Data Volume

| Metric | Count |
|--------|-------|
| Total People (Canonical) | ~3,645 |
| Total Source Entities | ~126,000 |
| Total Interactions | ~167,000 |
| Gmail (Personal) | ~33,000 emails |
| Gmail (Work) | ~6,000 emails |
| Calendar (Personal) | ~955 events |
| Calendar (Work) | ~6,000 events |
| Apple Contacts | ~1,175 contacts |
| WhatsApp Contacts | ~1,643 contacts |

---

## Sync Schedule

### Daily Timeline (Eastern Time)

```
00:00 - 03:00  System running, handling API requests, watching vault changes

03:00          Nightly sync starts
03:00          └─ Step 1: Vault reindex (all files → ChromaDB + BM25)
03:01          └─ Step 2: People v2 sync (LinkedIn + Gmail + Calendar)
03:02          └─ Step 3: Google Docs sync (configured docs → vault)
03:03          └─ Step 4: iMessage sync (macOS Messages → local store)
03:04          └─ Step 5: Google Sheets sync (form responses → vault)
03:05          └─ Step 6: Slack sync (incremental → ChromaDB + Interactions)
03:06          Nightly sync complete

06:00          CRM sync starts (via run_all_syncs.py)
06:00          └─ Gmail interactions
06:01          └─ Calendar interactions
06:02          └─ Contacts (Apple CSV)
06:03          └─ Phone calls
06:04          └─ WhatsApp (contacts + messages)
06:05          └─ iMessage interactions
06:06          └─ Slack users + entity linking
06:07          └─ Person stats + strengths
06:08          CRM sync complete

08:00          Calendar sync (Google Calendar → ChromaDB)
12:00          Calendar sync
15:00          Calendar sync

24/7           File watcher (real-time vault changes → ChromaDB + BM25)
24/7           Granola processor (every 5 min, Granola/ → vault)
24/7           Omi processor (every 5 min, Omi/Events/ → vault)
```

### Process Summary

| Process | Schedule | Reads From | Writes To |
|---------|----------|------------|-----------|
| ChromaDB Server | Continuous (boot) | HTTP requests | Vector data |
| Launchd API Service | Continuous (boot) | All data | API logs |
| Nightly Sync | Daily 3:00 AM ET | Vault, Gmail, Calendar, LinkedIn, iMessages, Slack | ChromaDB, BM25, Vault, PersonEntity |
| CRM Sync | Daily 6:00 AM ET | Gmail, Calendar, Contacts, Phone, WhatsApp, iMessage, Slack | SourceEntity, Interactions, Relationships |
| Calendar Indexer | 8 AM, 12 PM, 3 PM ET | Google Calendar | ChromaDB (`lifeos_calendar`) |
| Vault File Watcher | Continuous | Vault filesystem | ChromaDB, BM25 |
| Granola Processor | Every 5 minutes | `Granola/` folder | Vault (classified) |
| Omi Processor | Every 5 minutes | `Omi/Events/` folder | Vault (classified) |

### Failure Notifications

Configure `LIFEOS_ALERT_EMAIL` in `.env` to receive notifications when sync steps fail.

---

## Data Stores

### Two-Tier Data Model

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           TWO-TIER DATA MODEL                                    │
│                                                                                  │
│  TIER 1: SOURCE ENTITIES (Raw Observations)                                     │
│  • Stored in SQLite (data/crm.db)                                               │
│  • One record per observation from each source                                  │
│  • Immutable - preserves original data                                          │
│                                                                                  │
│  TIER 2: PERSON ENTITIES (Canonical Records)                                    │
│  • Stored in JSON (data/people_entities.json)                                   │
│  • One unified record per person                                                │
│  • Merged data from all sources                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Store Locations

| Store | Location | Purpose | Updated By |
|-------|----------|---------|------------|
| ChromaDB | `data/chromadb/` | Vector embeddings | Nightly reindex, File watcher |
| ChromaDB (Slack) | `lifeos_slack` collection | Slack message vectors | Nightly Slack sync |
| BM25 Index | `data/chromadb/bm25_index.db` | Keyword search | Nightly reindex, File watcher |
| Vault | `~/Notes 2025/` | Primary knowledge base | User, Granola, Omi, GDoc Sync |
| PersonEntity | `data/people_entities.json` | Resolved identities | People v2 sync, iMessage sync |
| SourceEntity | `data/crm.db` | Raw observations | All sync scripts |
| Interactions | `data/crm.db` | Interactions per person | People v2 sync, Slack sync |
| Relationships | `data/crm.db` | Person-to-person edges | Relationship discovery |
| iMessage | `data/imessage.db` | Message export cache | iMessage sync |

---

## Entity Resolution

### Resolution Algorithm

The EntityResolver uses a three-pass algorithm with weighted scoring:

**Pass 1: Exact Identifier Matching**
1. Email exact match → confidence=1.0
2. Phone exact match (E.164 format) → confidence=1.0

**Pass 2: Fuzzy Name Matching**
- Name similarity: RapidFuzz `token_set_ratio` × 0.4
- Context boost: +30 points if vault path matches
- Recency boost: +10 points if last_seen < 30 days
- Minimum threshold: score >= 40

**Pass 3: Disambiguation**
- If top two candidates differ by < 15 points → ambiguous
- Create new entity with disambiguation suffix or reduce confidence

### Scoring Weights

| Component | Weight/Points |
|-----------|---------------|
| Name Similarity | × 0.4 (0-40 points) |
| Context Boost | +30 points |
| Recency Boost | +10 points |
| Minimum Score | 40 |
| Disambiguation Threshold | 15 points |

### Domain-to-Context Mapping

Configured in `config/people_config.py`:

| Email Domain | Vault Context | Category |
|--------------|---------------|----------|
| movementlabs.xyz | Work/ML/ | work |
| gmail.com | Personal/ | personal |

---

## Relationship Discovery

The relationship discovery system scans interactions to build person-to-person relationship edges.

### Discovery Methods

| Method | Source | Signal |
|--------|--------|--------|
| `discover_from_calendar` | Calendar events | Shared attendees |
| `discover_from_calendar_direct` | Calendar events | User ↔ each attendee |
| `discover_from_email_threads` | Gmail threads | Co-recipients in threads |
| `discover_from_vault_comments` | Vault notes | Co-mentioned people |
| `discover_from_imessage_direct` | iMessage | User ↔ message recipient |
| `discover_from_whatsapp_direct` | WhatsApp | User ↔ chat participant |
| `discover_from_phone_calls` | Phone history | User ↔ caller/callee |
| `discover_from_slack_direct` | Slack DMs | User ↔ DM participant |
| `discover_linkedin_connections` | LinkedIn | Mark is_linkedin_connection |

### Discovery Window

- Default: 180 days lookback
- Configurable via `DISCOVERY_WINDOW_DAYS`
- Future calendar events excluded from last_seen_together

### Daily Sync Integration

Relationship discovery runs as part of the daily sync pipeline:
```
06:00 - Gmail/Calendar sync
06:05 - Contacts, Phone, WhatsApp sync
06:06 - iMessage, Slack sync
06:07 - Person stats update
06:08 - Relationship discovery ← discovers/updates relationships
06:09 - Strength recalculation
```

### Triggering Discovery

- **Automatic**: Daily sync at 06:08 AM
- **Manual**: `POST /api/crm/relationships/discover`
- **Script**: `uv run python scripts/sync_relationship_discovery.py`

---

## Search Pipeline

```
Query → Name Expansion → [Vector Search + BM25 Search] → RRF Fusion → Boosting → Results
```

### Components

1. **Name Expansion**: Nicknames → canonical names ("Al" → "Alex")
2. **Dual Search**:
   - Vector: semantic similarity via ChromaDB
   - BM25: keyword matching via SQLite FTS5
3. **RRF Fusion**: `score = Σ 1/(60 + rank)`
4. **Boosting**: Recency (0-50%) + Filename match (2x)

### Key Files

| File | Purpose |
|------|---------|
| `api/services/hybrid_search.py` | Main search logic |
| `api/services/vectorstore.py` | ChromaDB wrapper |
| `api/services/bm25_index.py` | BM25 index |
| `api/services/query_classifier.py` | Factual vs semantic detection |

---

## Relationship Tracking

### Relationship Data Model

Each relationship between two people tracks signals from multiple sources:

| Field | Description |
|-------|-------------|
| shared_events_count | Calendar events together |
| shared_threads_count | Email threads together |
| shared_messages_count | iMessage/SMS threads |
| shared_whatsapp_count | WhatsApp threads |
| shared_slack_count | Slack DM messages |
| is_linkedin_connection | Both have LinkedIn source |

### Edge Weight Formula

```python
edge_weight = (
    shared_events_count  × 3  +     # Calendar (high signal)
    shared_threads_count × 2  +     # Email threads
    shared_messages_count × 2 +     # iMessage/SMS
    shared_whatsapp_count × 2 +     # WhatsApp
    shared_slack_count   × 1  +     # Slack DMs
    (10 if is_linkedin_connection)  # LinkedIn bonus
)
```

### Relationship Strength Formula

```
strength = (recency × 0.3) + (frequency × 0.4) + (diversity × 0.3)

Where:
- recency = max(0, 1 - days_since_last / 90)
- frequency = min(1, interactions_90d / 20)
- diversity = unique_sources / total_sources
```

---

## Sync Scripts

All sync scripts in `scripts/` follow the pattern:
- Dry run by default (shows what would change)
- Use `--execute` flag to apply changes

| Script | Purpose | Data Source |
|--------|---------|-------------|
| `sync_gmail_calendar_interactions.py` | Sync emails and calendar | Gmail API |
| `sync_imessage_interactions.py` | Sync iMessage | `data/imessage.db` |
| `sync_whatsapp.py` | Sync WhatsApp contacts and messages | `~/.wacli/wacli.db` |
| `sync_phone_calls.py` | Sync phone calls | macOS CallHistoryDB |
| `sync_contacts_csv.py` | Import Apple Contacts | CSV export |
| `sync_slack.py` | Sync Slack users and DMs | Slack API |
| `link_slack_entities.py` | Link Slack users to people by email | `data/crm.db` |
| `sync_person_stats.py` | Update interaction counts | `data/interactions.db` |

### Unified Sync Runner

```bash
# View current stats
uv run python scripts/run_comprehensive_sync.py --stats-only

# Dry run
uv run python scripts/run_comprehensive_sync.py

# Execute full sync
uv run python scripts/run_comprehensive_sync.py --execute
```

---

## Configuration

### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `LIFEOS_VAULT_PATH` | Obsidian vault path | `./vault` |
| `LIFEOS_CHROMA_PATH` | ChromaDB data directory | `./data/chromadb` |
| `LIFEOS_CHROMA_URL` | ChromaDB server URL | `http://localhost:8001` |
| `LIFEOS_PORT` | API server port | `8000` |
| `LIFEOS_ALERT_EMAIL` | Sync failure alerts | None |
| `SLACK_USER_TOKEN` | Slack OAuth token | None |
| `SLACK_TEAM_ID` | Slack workspace ID | None |

All scheduled times use **America/New_York** (Eastern Time).

---

## Messaging Source Details

### WhatsApp Sync

**Data Source:** `~/.wacli/wacli.db` (wacli CLI tool database)

**Sync Process:**
1. Sync contacts from wacli's contact database
2. Sync messages from wacli's message database
3. Create interactions for each message thread
4. Link to PersonEntity via phone number (E.164 format)

**Phone Number Format:**
- Expected: E.164 format (`+15551234567`)
- JID extraction: `15551234567@s.whatsapp.net` → `+15551234567`
- 10-digit US numbers get `+1` prefix automatically

**Message Types:**
- DMs: `title = "WhatsApp DM: {contact_name}"`
- Groups: `title = "WhatsApp group: {group_name}"`

**Entity Resolution:**
- Messages sync uses `create_if_missing=True` to create PersonEntity for new contacts
- Ensures message history from unknown contacts is not lost

### Slack Sync

**Data Source:** Slack API via OAuth token

**Required Environment:**
```bash
SLACK_USER_TOKEN=xoxp-...  # User OAuth token with scopes: users:read, conversations.history, im:history
SLACK_TEAM_ID=T02F5DW71LY  # Workspace ID
```

**Sync Process:**
1. `sync_slack.py` - Syncs Slack users to SourceEntity, indexes DMs to ChromaDB
2. `link_slack_entities.py` - Links Slack users to PersonEntity by matching email addresses

**Entity Linking:**
- Slack users are matched to existing PersonEntity records by email address
- Email matching is case-insensitive
- Unmatched users remain as SourceEntity only (can be manually linked later)

**Interaction Counts:**
- `shared_slack_count` is populated by relationship discovery after entity linking
- Counts DM message exchanges between linked users

### Daily Sync Order

The unified sync runner (`run_all_syncs.py`) executes in this order:

1. `gmail` - Email sync
2. `calendar` - Calendar sync
3. `contacts` - Apple Contacts
4. `phone` - Phone calls
5. `whatsapp` - WhatsApp contacts and messages
6. `imessage` - iMessage sync
7. `slack` - Slack users and DMs
8. `link_slack` - Link Slack entities by email
9. `person_stats` - Update interaction counts
10. `strengths` - Recalculate relationship strengths

**Automated via launchd:**
- Service: `com.lifeos.crm-sync`
- Schedule: Daily at 6:00 AM
- Script: `scripts/run_all_syncs.py`

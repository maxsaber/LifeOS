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
| `sync_whatsapp.py` | Sync WhatsApp | `~/.wacli/wacli.db` |
| `sync_phone_calls.py` | Sync phone calls | macOS CallHistoryDB |
| `sync_contacts_csv.py` | Import Apple Contacts | CSV export |
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

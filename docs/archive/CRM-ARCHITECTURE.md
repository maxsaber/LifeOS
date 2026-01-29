# LifeOS Personal CRM - Architecture Documentation

A comprehensive Personal CRM system built on LifeOS, focused on **Network Management** and **Relationship Context** rather than traditional outbound CRM.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Data Sources](#data-sources)
3. [Data Flow Architecture](#data-flow-architecture)
4. [Storage Layer](#storage-layer)
5. [Entity Resolution System](#entity-resolution-system)
6. [Relationship Strength Scoring](#relationship-strength-scoring)
7. [Multi-Source Relationship Tracking](#multi-source-relationship-tracking)
8. [API Layer](#api-layer)
9. [UI Components](#ui-components)

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           LifeOS Personal CRM                                    │
│                                                                                  │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐          │
│  │   Gmail     │   │  Calendar   │   │   iMessage  │   │  WhatsApp   │          │
│  │   ~39K      │   │   ~7K       │   │   Chats     │   │  via wacli  │          │
│  └──────┬──────┘   └──────┬──────┘   └──────┬──────┘   └──────┬──────┘          │
│         │                 │                 │                 │                 │
│  ┌──────┴──────┐   ┌──────┴──────┐   ┌──────┴──────┐   ┌──────┴──────┐          │
│  │ Apple       │   │   Phone     │   │   Slack     │   │   Vault     │          │
│  │ Contacts    │   │   Calls     │   │   (DMs)     │   │   Notes     │          │
│  └──────┬──────┘   └──────┬──────┘   └──────┬──────┘   └──────┬──────┘          │
│         │                 │                 │                 │                 │
│         ▼                 ▼                 ▼                 ▼                 │
│  ┌─────────────────────────────────────────────────────────────────────┐        │
│  │                        SOURCE ENTITY LAYER                          │        │
│  │                  (SQLite: data/crm.db - source_entities)            │        │
│  │                                                                     │        │
│  │   Raw observations from each source, immutable, preserves history   │        │
│  └────────────────────────────────┬────────────────────────────────────┘        │
│                                   │                                             │
│                                   ▼                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐        │
│  │                       ENTITY RESOLVER                               │        │
│  │                                                                     │        │
│  │   Pass 1: Email Anchoring (exact match)                            │        │
│  │   Pass 2: Phone Anchoring (E.164 format)                           │        │
│  │   Pass 3: Fuzzy Name Matching + Context Boost                      │        │
│  │   Pass 4: Disambiguation (create separate entities if ambiguous)   │        │
│  └────────────────────────────────┬────────────────────────────────────┘        │
│                                   │                                             │
│                                   ▼                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐        │
│  │                     CANONICAL PERSON LAYER                          │        │
│  │                 (JSON: data/people_entities.json)                   │        │
│  │                                                                     │        │
│  │   One unified record per person, all sources merged                 │        │
│  │   ~3,600+ people with 126K+ source entities                         │        │
│  └────────────────────────────────┬────────────────────────────────────┘        │
│                                   │                                             │
│                                   ▼                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐        │
│  │                      RELATIONSHIP LAYER                             │        │
│  │                                                                     │        │
│  │   - Relationship Strength Scoring                                   │        │
│  │   - Connection Discovery (shared contexts, co-attendees)            │        │
│  │   - Multi-Source Edge Tracking (calendar, email, messaging, etc.)   │        │
│  │   - Network Graph with Source Filtering                             │        │
│  └─────────────────────────────────────────────────────────────────────┘        │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Sources

### Source Types and Sync Methods

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│                              DATA SOURCES                                          │
├───────────────┬──────────────────────────┬─────────────────────────────────────────┤
│ Source        │ Sync Method              │ Data Extracted                          │
├───────────────┼──────────────────────────┼─────────────────────────────────────────┤
│ Gmail         │ Google API               │ From/To/CC emails, timestamps, subjects │
│               │ scripts/sync_gmail_*     │ Thread IDs, snippets                    │
├───────────────┼──────────────────────────┼─────────────────────────────────────────┤
│ Calendar      │ Google API               │ Attendees, organizer, event titles      │
│               │ scripts/sync_gmail_*     │ Meeting times, descriptions             │
├───────────────┼──────────────────────────┼─────────────────────────────────────────┤
│ Apple         │ CSV Export               │ Names, emails, phone numbers            │
│ Contacts      │ scripts/sync_contacts_   │ Companies, addresses                    │
│               │ csv.py                   │                                         │
├───────────────┼──────────────────────────┼─────────────────────────────────────────┤
│ Phone Calls   │ macOS CallHistoryDB      │ Phone numbers, names, duration          │
│               │ scripts/sync_phone_      │ Call type (Phone/FaceTime)              │
│               │ calls.py                 │ Direction, answered status              │
├───────────────┼──────────────────────────┼─────────────────────────────────────────┤
│ WhatsApp      │ wacli CLI                │ JIDs, names, phone numbers              │
│               │ scripts/sync_whatsapp.py │ Aliases                                 │
├───────────────┼──────────────────────────┼─────────────────────────────────────────┤
│ iMessage      │ macOS chat.db            │ Phone/email, message content            │
│               │ api/services/imessage.py │ Timestamps, attachments                 │
├───────────────┼──────────────────────────┼─────────────────────────────────────────┤
│ Slack         │ Slack API (OAuth)        │ User profiles, DMs                      │
│               │ api/services/slack_*.py  │ Workspace info                          │
├───────────────┼──────────────────────────┼─────────────────────────────────────────┤
│ Vault Notes   │ Obsidian markdown        │ Name mentions in notes                  │
│               │ api/services/indexer.py  │ Context paths                           │
├───────────────┼──────────────────────────┼─────────────────────────────────────────┤
│ LinkedIn      │ CSV Import               │ Connections, companies, titles          │
│               │ Manual import            │ Profile URLs                            │
├───────────────┼──────────────────────────┼─────────────────────────────────────────┤
│ Granola       │ JSON Webhooks            │ Meeting transcripts, attendees          │
│               │ api/services/granola_*   │ AI notes                                │
└───────────────┴──────────────────────────┴─────────────────────────────────────────┘
```

### Current Data Volume

```
┌────────────────────────────────────────────────────────────────────────┐
│                     DATA VOLUME SNAPSHOT                               │
├──────────────────────────────┬─────────────────────────────────────────┤
│ Metric                       │ Count                                   │
├──────────────────────────────┼─────────────────────────────────────────┤
│ Total People (Canonical)     │ ~3,645                                  │
│ Total Source Entities        │ ~126,000                                │
│ Total Interactions           │ ~167,000                                │
├──────────────────────────────┼─────────────────────────────────────────┤
│ Gmail (Personal)             │ ~33,000 emails                          │
│ Gmail (Work)                 │ ~6,000 emails                           │
│ Calendar (Personal)          │ ~955 events                             │
│ Calendar (Work)              │ ~6,000 events                           │
│ Apple Contacts               │ ~1,175 contacts                         │
│ Phone Calls                  │ ~478 calls                              │
│ WhatsApp Contacts            │ ~1,643 contacts                         │
│ iMessage                     │ Active sync                             │
└──────────────────────────────┴─────────────────────────────────────────┘
```

---

## Data Flow Architecture

### Complete Data Flow Diagram

```
                                    DATA INGESTION
                                         │
         ┌───────────────┬───────────────┼───────────────┬───────────────┐
         │               │               │               │               │
         ▼               ▼               ▼               ▼               ▼
    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
    │  Gmail  │    │Calendar │    │Contacts │    │  Phone  │    │WhatsApp │
    │  API    │    │  API    │    │  CSV    │    │CallHist │    │ wacli   │
    └────┬────┘    └────┬────┘    └────┬────┘    └────┬────┘    └────┬────┘
         │               │               │               │               │
         ▼               ▼               ▼               ▼               ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │                     SYNC SCRIPTS LAYER                              │
    │                                                                     │
    │  sync_gmail_calendar_interactions.py                               │
    │  sync_contacts_csv.py                                              │
    │  sync_phone_calls.py                                               │
    │  sync_whatsapp.py                                                  │
    │                                                                     │
    │  Each script:                                                       │
    │  1. Reads raw data from source                                     │
    │  2. Creates SourceEntity records                                   │
    │  3. Calls EntityResolver to link to PersonEntity                   │
    │  4. Creates Interaction records (if applicable)                    │
    └────────────────────────────────┬────────────────────────────────────┘
                                     │
         ┌───────────────────────────┼───────────────────────────┐
         │                           │                           │
         ▼                           ▼                           ▼
┌─────────────────┐        ┌─────────────────┐        ┌─────────────────┐
│  SourceEntity   │        │  PersonEntity   │        │   Interaction   │
│                 │        │                 │        │                 │
│ SQLite table    │───────▶│ JSON file       │◀───────│ SQLite table    │
│ source_entities │        │ people_entities │        │ interactions    │
│                 │        │                 │        │                 │
│ - source_type   │        │ - canonical_name│        │ - person_id     │
│ - source_id     │        │ - emails[]      │        │ - timestamp     │
│ - observed_*    │        │ - phones[]      │        │ - source_type   │
│ - metadata      │        │ - company       │        │ - title         │
│ - person_id     │        │ - sources[]     │        │ - snippet       │
└─────────────────┘        └─────────────────┘        └─────────────────┘
                                     │
                                     ▼
                           ┌─────────────────┐
                           │ Relationship    │
                           │ Metrics         │
                           │                 │
                           │ - strength      │
                           │ - recency       │
                           │ - frequency     │
                           │ - diversity     │
                           └─────────────────┘
```

---

## Storage Layer

### Two-Tier Data Model

The CRM uses a **two-tier data model** to separate raw observations from unified records:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           TWO-TIER DATA MODEL                                    │
│                                                                                  │
│  TIER 1: SOURCE ENTITIES (Raw Observations)                                     │
│  ───────────────────────────────────────────                                    │
│  • Stored in SQLite (data/crm.db)                                               │
│  • One record per observation from each source                                  │
│  • Immutable - preserves original data                                          │
│  • Enables re-linking and undo                                                  │
│                                                                                  │
│  TIER 2: PERSON ENTITIES (Canonical Records)                                    │
│  ─────────────────────────────────────────────                                  │
│  • Stored in JSON (data/people_entities.json)                                   │
│  • One unified record per person                                                │
│  • Merged data from all sources                                                 │
│  • User-editable fields                                                         │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────┐         ┌───────────────────────────────────┐
│       SOURCE ENTITY (SQLite)      │         │      PERSON ENTITY (JSON)         │
├───────────────────────────────────┤         ├───────────────────────────────────┤
│ id: TEXT PRIMARY KEY              │         │ id: str                           │
│ source_type: TEXT                 │    ┌───▶│ canonical_name: str               │
│   gmail, calendar, slack,         │    │    │ display_name: str                 │
│   imessage, whatsapp, signal,     │    │    │ emails: list[str]                 │
│   contacts, linkedin, vault,      │    │    │ phone_numbers: list[str]          │
│   granola, phone                  │    │    │ phone_primary: str                │
│ source_id: TEXT                   │    │    │ company: str                      │
│ observed_name: TEXT               │    │    │ position: str                     │
│ observed_email: TEXT              │────┘    │ linkedin_url: str                 │
│ observed_phone: TEXT              │         │ category: str (work/personal/     │
│ metadata: TEXT (JSON)             │         │            family/unknown)        │
│ canonical_person_id: TEXT ────────┼────────▶│ vault_contexts: list[str]         │
│ link_confidence: REAL (0.0-1.0)   │         │ tags: list[str]                   │
│ link_status: TEXT                 │         │ aliases: list[str]                │
│   auto, confirmed, rejected       │         │ sources: list[str]                │
│ linked_at: TIMESTAMP              │         │ source_entity_count: int          │
│ observed_at: TIMESTAMP            │         │ relationship_strength: float      │
│ created_at: TIMESTAMP             │         │ first_seen: datetime              │
│                                   │         │ last_seen: datetime               │
│ UNIQUE(source_type, source_id)    │         │ confidence_score: float           │
└───────────────────────────────────┘         └───────────────────────────────────┘
```

### Interactions Table

```
┌───────────────────────────────────────────────────────────────────┐
│                    INTERACTIONS TABLE (SQLite)                     │
├───────────────────────────────────────────────────────────────────┤
│                                                                   │
│  CREATE TABLE interactions (                                      │
│      id TEXT PRIMARY KEY,                                         │
│      person_id TEXT NOT NULL,              -- FK to PersonEntity  │
│      timestamp TEXT NOT NULL,              -- ISO 8601            │
│      source_type TEXT NOT NULL,            -- gmail, calendar...  │
│      title TEXT NOT NULL,                  -- Display title       │
│      snippet TEXT,                         -- Preview text        │
│      source_link TEXT,                     -- URL/path to source  │
│      source_id TEXT,                       -- Unique within type  │
│      created_at TEXT DEFAULT CURRENT_TIMESTAMP,                   │
│      UNIQUE(source_type, source_id)                               │
│  );                                                               │
│                                                                   │
│  CREATE INDEX idx_interactions_person_id ON interactions(person_id);
│  CREATE INDEX idx_interactions_timestamp ON interactions(timestamp);
│  CREATE INDEX idx_interactions_source    ON interactions(source_type);
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

---

## Entity Resolution System

### Resolution Algorithm

The EntityResolver uses a **three-pass algorithm** with weighted scoring:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        ENTITY RESOLUTION ALGORITHM                               │
│                                                                                  │
│  INPUT: name, email, phone, context_path                                        │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │ PASS 1: EXACT IDENTIFIER MATCHING                                       │    │
│  │                                                                          │    │
│  │  1a. Email Exact Match                                                   │    │
│  │      ┌────────────────────────────────────────────────────────────┐     │    │
│  │      │  IF email provided:                                        │     │    │
│  │      │    lookup = store.get_by_email(email.lower())              │     │    │
│  │      │    IF found → RETURN (entity, confidence=1.0, "email_exact")     │    │
│  │      └────────────────────────────────────────────────────────────┘     │    │
│  │                                                                          │    │
│  │  1b. Phone Exact Match (E.164 format: +1XXXXXXXXXX)                     │    │
│  │      ┌────────────────────────────────────────────────────────────┐     │    │
│  │      │  IF phone provided:                                        │     │    │
│  │      │    lookup = store.get_by_phone(phone)                      │     │    │
│  │      │    IF found → RETURN (entity, confidence=1.0, "phone_exact")     │    │
│  │      └────────────────────────────────────────────────────────────┘     │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                      │                                           │
│                                      ▼                                           │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │ PASS 2: FUZZY NAME MATCHING WITH CONTEXT BOOST                          │    │
│  │                                                                          │    │
│  │  For each PersonEntity in store:                                        │    │
│  │    score = 0                                                            │    │
│  │                                                                          │    │
│  │    ┌──────────────────────────────────────────────────────────────┐     │    │
│  │    │  NAME SIMILARITY (weight: 0.4)                               │     │    │
│  │    │                                                              │     │    │
│  │    │  Using RapidFuzz token_set_ratio:                            │     │    │
│  │    │    name_sim = fuzz.token_set_ratio(input_name, entity_name)  │     │    │
│  │    │    score += name_sim × 0.4                                   │     │    │
│  │    │                                                              │     │    │
│  │    │  Also check aliases (take highest score)                     │     │    │
│  │    └──────────────────────────────────────────────────────────────┘     │    │
│  │                                                                          │    │
│  │    ┌──────────────────────────────────────────────────────────────┐     │    │
│  │    │  CONTEXT BOOST (+30 points)                                  │     │    │
│  │    │                                                              │     │    │
│  │    │  IF context_path matches entity.vault_contexts:              │     │    │
│  │    │    score += 30                                               │     │    │
│  │    │                                                              │     │    │
│  │    │  Example: "Work/ML/meeting.md" matches ["Work/ML/"]          │     │    │
│  │    └──────────────────────────────────────────────────────────────┘     │    │
│  │                                                                          │    │
│  │    ┌──────────────────────────────────────────────────────────────┐     │    │
│  │    │  RECENCY BOOST (+10 points)                                  │     │    │
│  │    │                                                              │     │    │
│  │    │  IF entity.last_seen within 30 days:                         │     │    │
│  │    │    score += 10                                               │     │    │
│  │    └──────────────────────────────────────────────────────────────┘     │    │
│  │                                                                          │    │
│  │  Candidates are sorted by score (descending)                            │    │
│  │  Minimum threshold: score >= 40                                         │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                      │                                           │
│                                      ▼                                           │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │ PASS 3: DISAMBIGUATION                                                   │    │
│  │                                                                          │    │
│  │  IF top_two_candidates exist:                                           │    │
│  │    score_diff = top.score - second.score                                │    │
│  │                                                                          │    │
│  │    ┌─────────────────────────────────────────────────────────────┐      │    │
│  │    │  IF score_diff < 15 (disambiguation threshold):             │      │    │
│  │    │                                                             │      │    │
│  │    │    → Ambiguous match detected                               │      │    │
│  │    │    → IF create_if_missing:                                  │      │    │
│  │    │        Create NEW entity with disambiguation suffix         │      │    │
│  │    │        Example: "John Smith (Movement)"                     │      │    │
│  │    │    → ELSE:                                                  │      │    │
│  │    │        Return top match with reduced confidence (×0.7)      │      │    │
│  │    └─────────────────────────────────────────────────────────────┘      │    │
│  │                                                                          │    │
│  │  ELSE:                                                                   │    │
│  │    → Return top match with full confidence                              │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Resolution Scoring Weights

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        ENTITY RESOLUTION WEIGHTS                                 │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │ COMPONENT              │ WEIGHT/POINTS │ DESCRIPTION                     │    │
│  ├────────────────────────┼───────────────┼─────────────────────────────────┤    │
│  │ Name Similarity        │ × 0.4         │ RapidFuzz token_set_ratio       │    │
│  │                        │               │ (0-100 → contributes 0-40)      │    │
│  ├────────────────────────┼───────────────┼─────────────────────────────────┤    │
│  │ Context Boost          │ +30 points    │ When vault path matches entity  │    │
│  │                        │               │ vault_contexts                  │    │
│  ├────────────────────────┼───────────────┼─────────────────────────────────┤    │
│  │ Recency Boost          │ +10 points    │ When last_seen < 30 days ago    │    │
│  ├────────────────────────┼───────────────┼─────────────────────────────────┤    │
│  │ Minimum Match Score    │ 40            │ Below this → no match           │    │
│  ├────────────────────────┼───────────────┼─────────────────────────────────┤    │
│  │ Disambiguation         │ 15 points     │ If score diff < 15 between      │    │
│  │ Threshold              │               │ top two → ambiguous             │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
│  EXAMPLE SCENARIOS:                                                              │
│                                                                                  │
│  1. "john.smith@movementlabs.xyz" → Email exact match → confidence=1.0          │
│                                                                                  │
│  2. "John" in "Work/ML/standup.md"                                              │
│     - John Smith (ML): name_sim=45×0.4=18, context=+30, recency=+10 → 58       │
│     - John Doe (Personal): name_sim=45×0.4=18, no boost → 18                   │
│     → John Smith wins clearly (diff=40 > 15)                                    │
│                                                                                  │
│  3. "Mike" with no context                                                       │
│     - Mike Johnson: 60 points                                                    │
│     - Mike Williams: 55 points                                                   │
│     → diff=5 < 15 → AMBIGUOUS → create "Mike (context)" or reduce confidence    │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Domain-to-Context Mapping

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        DOMAIN → CONTEXT MAPPING                                  │
│                        (config/people_config.py)                                 │
│                                                                                  │
│  Email Domain             │ Vault Context           │ Category                   │
│  ─────────────────────────┼─────────────────────────┼───────────────────────────│
│  movementlabs.xyz         │ Work/ML/                │ work                       │
│  movementlabs.com         │ Work/ML/                │ work                       │
│  murmuration.org          │ Personal/zArchive/Murm/ │ work (archived)            │
│  bluelabs.com             │ Personal/zArchive/Blue/ │ work (archived)            │
│  gmail.com                │ Personal/               │ personal                   │
│  icloud.com               │ Personal/               │ personal                   │
│                                                                                  │
│  This mapping enables:                                                           │
│  • Automatic vault_context assignment when creating entities from email         │
│  • Context boosting during name resolution                                       │
│  • Category inference (work vs personal)                                        │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Relationship Strength Scoring

### Strength Formula

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     RELATIONSHIP STRENGTH FORMULA                                │
│                                                                                  │
│     strength = (recency × 0.3) + (frequency × 0.4) + (diversity × 0.3)          │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │ RECENCY SCORE (weight: 0.3)                                             │    │
│  │                                                                          │    │
│  │   recency = max(0, 1 - days_since_last / 90)                            │    │
│  │                                                                          │    │
│  │   ┌─────────────────────────────────────────────────────┐               │    │
│  │   │  Days Since Last  │  Recency Score                  │               │    │
│  │   ├───────────────────┼─────────────────────────────────┤               │    │
│  │   │  0 (today)        │  1.0                            │               │    │
│  │   │  30               │  0.67                           │               │    │
│  │   │  45               │  0.5                            │               │    │
│  │   │  90+              │  0.0                            │               │    │
│  │   └───────────────────┴─────────────────────────────────┘               │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │ FREQUENCY SCORE (weight: 0.4)                                           │    │
│  │                                                                          │    │
│  │   frequency = min(1, interactions_90d / 20)                             │    │
│  │                                                                          │    │
│  │   ┌─────────────────────────────────────────────────────┐               │    │
│  │   │  Interactions (90d) │  Frequency Score              │               │    │
│  │   ├─────────────────────┼───────────────────────────────┤               │    │
│  │   │  0                  │  0.0                          │               │    │
│  │   │  5                  │  0.25                         │               │    │
│  │   │  10                 │  0.5                          │               │    │
│  │   │  20+                │  1.0                          │               │    │
│  │   └─────────────────────┴───────────────────────────────┘               │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │ DIVERSITY SCORE (weight: 0.3)                                           │    │
│  │                                                                          │    │
│  │   diversity = unique_sources / total_sources                            │    │
│  │                                                                          │    │
│  │   Total sources: 12 (gmail, calendar, slack, imessage, whatsapp,        │    │
│  │                      signal, contacts, linkedin, vault, granola,        │    │
│  │                      phone_call, phone)                                 │    │
│  │                                                                          │    │
│  │   ┌─────────────────────────────────────────────────────┐               │    │
│  │   │  Sources Used    │  Diversity Score                 │               │    │
│  │   ├──────────────────┼──────────────────────────────────┤               │    │
│  │   │  1               │  0.083                           │               │    │
│  │   │  3               │  0.25                            │               │    │
│  │   │  6               │  0.5                             │               │    │
│  │   │  12              │  1.0                             │               │    │
│  │   └──────────────────┴──────────────────────────────────┘               │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
│  EXAMPLE CALCULATION:                                                            │
│                                                                                  │
│    John Smith:                                                                   │
│    - Last seen: 15 days ago → recency = 1 - 15/90 = 0.833                       │
│    - Interactions (90d): 12 → frequency = 12/20 = 0.6                           │
│    - Sources: gmail, calendar, slack (3) → diversity = 3/12 = 0.25             │
│                                                                                  │
│    strength = (0.833 × 0.3) + (0.6 × 0.4) + (0.25 × 0.3)                        │
│             = 0.25 + 0.24 + 0.075                                                │
│             = 0.565                                                              │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Strength Visualization

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    STRENGTH VISUALIZATION IN UI                                  │
│                                                                                  │
│  Heat Map Colors (person list):                                                  │
│                                                                                  │
│    0.0 ──────── 0.25 ──────── 0.5 ──────── 0.75 ──────── 1.0                   │
│      │           │            │            │             │                       │
│    Cold       Cooling       Warm        Strong       Very Strong               │
│   #4299e1     #48bb78      #ecc94b     #ed8936      #e53e3e                    │
│   (blue)      (green)      (yellow)    (orange)     (red)                       │
│                                                                                  │
│  Strength Breakdown (person detail):                                            │
│                                                                                  │
│    ┌─────────────────────────────────────────┐                                  │
│    │ Relationship Strength: 0.565            │                                  │
│    │ ████████████████░░░░░░░░░░░░ 56.5%      │                                  │
│    │                                         │                                  │
│    │ Recency (30%)                           │                                  │
│    │ ████████████████████░░░░░░░░ 83.3%      │                                  │
│    │ Last seen: 15 days ago                  │                                  │
│    │                                         │                                  │
│    │ Frequency (40%)                         │                                  │
│    │ ████████████░░░░░░░░░░░░░░░░ 60%        │                                  │
│    │ 12 interactions in 90 days              │                                  │
│    │                                         │                                  │
│    │ Diversity (30%)                         │                                  │
│    │ ██████░░░░░░░░░░░░░░░░░░░░░░ 25%        │                                  │
│    │ Sources: gmail, calendar, slack         │                                  │
│    └─────────────────────────────────────────┘                                  │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Multi-Source Relationship Tracking

### Relationship Edge Model

Each relationship between two people tracks signals from multiple sources:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     RELATIONSHIP (EDGE) DATA MODEL                               │
│                     (api/services/relationship.py)                               │
│                                                                                  │
│  Core Fields:                                                                   │
│  - person_a_id, person_b_id    (ordered pair, a < b)                           │
│  - relationship_type           (friend, family, coworker, inferred)             │
│  - shared_contexts             (["Work/ML/", "imessage", "linkedin"])           │
│  - first_seen_together         (timestamp)                                      │
│  - last_seen_together          (timestamp)                                      │
│                                                                                  │
│  Multi-Source Counts:                                                           │
│  - shared_events_count         (calendar events together)                       │
│  - shared_threads_count        (email threads together)                         │
│  - shared_messages_count       (iMessage/SMS direct threads)                    │
│  - shared_whatsapp_count       (WhatsApp direct threads)                        │
│  - shared_slack_count          (Slack DM messages)                              │
│  - is_linkedin_connection      (boolean: both have LinkedIn)                    │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Edge Weight Formula

The edge weight for graph visualization is calculated from all sources:

```
edge_weight = (
    shared_events_count  × 3  +     # Calendar (high signal)
    shared_threads_count × 2  +     # Email threads
    shared_messages_count × 2 +     # iMessage/SMS
    shared_whatsapp_count × 2 +     # WhatsApp
    shared_slack_count   × 1  +     # Slack DMs (weaker per-message)
    (10 if is_linkedin_connection)  # LinkedIn connection bonus
)
```

**Example Edge Weights:**
- Coworker (high): 10 events × 3 + 20 threads × 2 + LinkedIn = 80
- Friend (iMessage focus): 2 events × 3 + 50 messages × 2 = 106
- LinkedIn-only connection: 10

### Graph Source Filtering

The network graph UI supports filtering edges by source type:

| Control | Description |
|---------|-------------|
| Show Labels | Toggle node name labels |
| Edge Strength | Filter by minimum edge weight (0-100%) |
| Degree Filter | Show 1st degree only or 1st & 2nd degree |
| Sources | Multi-select: Calendar, Email, iMessage, WhatsApp, Slack, LinkedIn |

**Filter Behavior:**
- Edge visible if ANY selected source has count > 0
- Edge weight recalculated using only selected sources
- Edge strength threshold applies to filtered weight
- Filter state preserved when navigating between nodes

### Edge Panel

Click on an edge to see detailed source breakdown:

| Field | Description |
|-------|-------------|
| Edge Weight | Computed weight from all sources |
| 📅 Calendar Events | Shared calendar event count |
| 📧 Email Threads | Shared email thread count |
| 💬 iMessage | Shared iMessage/SMS count |
| 📱 WhatsApp | Shared WhatsApp message count |
| 💼 Slack DMs | Shared Slack DM count |
| 🔗 LinkedIn | Connection status (✓ Connected or —) |
| First/Last Seen | Timestamps of relationship |

### Relationship Discovery by Source

| Discovery Function | Source Field Updated | Data Source |
|-------------------|---------------------|-------------|
| `discover_from_calendar()` | `shared_events_count` | Calendar API events |
| `discover_from_email_threads()` | `shared_threads_count` | Gmail API threads |
| `discover_from_imessage_direct()` | `shared_messages_count` | macOS Messages.app |
| `discover_from_whatsapp_direct()` | `shared_whatsapp_count` | wacli WhatsApp data |
| `discover_linkedin_connections()` | `is_linkedin_connection` | LinkedIn source entities |

---

## API Layer

### CRM API Endpoints

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           CRM API ENDPOINTS                                      │
│                          (api/routes/crm.py)                                     │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │ PEOPLE ENDPOINTS                                                         │    │
│  ├─────────────────────────────────────────────────────────────────────────┤    │
│  │                                                                          │    │
│  │ GET /api/crm/people                                                      │    │
│  │   List/search people with filters                                        │    │
│  │   Query params: q, category, source, has_pending, sort, offset, limit    │    │
│  │                                                                          │    │
│  │ GET /api/crm/people/{id}                                                 │    │
│  │   Get person detail with source entities and pending links               │    │
│  │                                                                          │    │
│  │ GET /api/crm/people/{id}/timeline                                        │    │
│  │   Get chronological interaction history                                  │    │
│  │   Query params: source_type, days_back, offset, limit                    │    │
│  │                                                                          │    │
│  │ GET /api/crm/people/{id}/connections                                     │    │
│  │   Get related people with overlap scores                                 │    │
│  │                                                                          │    │
│  │ GET /api/crm/people/{id}/strength-breakdown                              │    │
│  │   Get detailed relationship strength components                          │    │
│  │                                                                          │    │
│  │ GET /api/crm/network                                                     │    │
│  │   Get network graph data (nodes + edges with source breakdown)           │    │
│  │   Query params: center_on, depth, min_strength, category                 │    │
│  │   Edges include: shared_events_count, shared_threads_count,              │    │
│  │                  shared_messages_count, shared_whatsapp_count,           │    │
│  │                  shared_slack_count, is_linkedin_connection              │    │
│  │                                                                          │    │
│  │ GET /api/crm/relationship/{person_a_id}/{person_b_id}                    │    │
│  │   Get detailed edge data between two people                              │    │
│  │   Returns: all source counts, timestamps, shared contexts                │    │
│  │                                                                          │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │ PENDING LINKS ENDPOINTS                                                  │    │
│  ├─────────────────────────────────────────────────────────────────────────┤    │
│  │                                                                          │    │
│  │ GET /api/crm/pending-links                                               │    │
│  │   List pending entity links for review                                   │    │
│  │                                                                          │    │
│  │ POST /api/crm/pending-links/{id}/confirm                                 │    │
│  │   Confirm a proposed entity link                                         │    │
│  │                                                                          │    │
│  │ POST /api/crm/pending-links/{id}/reject                                  │    │
│  │   Reject and optionally create new person                                │    │
│  │                                                                          │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │ DISCOVERY & STATS ENDPOINTS                                              │    │
│  ├─────────────────────────────────────────────────────────────────────────┤    │
│  │                                                                          │    │
│  │ GET /api/crm/discover                                                    │    │
│  │   Get suggested connections based on shared contexts                     │    │
│  │                                                                          │    │
│  │ GET /api/crm/statistics                                                  │    │
│  │   Dashboard stats (counts by category, source, strength distribution)    │    │
│  │                                                                          │    │
│  │ POST /api/crm/sources/import                                             │    │
│  │   Upload WhatsApp/Signal export files                                    │    │
│  │                                                                          │    │
│  │ POST /api/crm/sources/{type}/sync                                        │    │
│  │   Trigger source sync (gmail, calendar, contacts, etc.)                  │    │
│  │                                                                          │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## UI Components

### Page Structure

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           CRM UI STRUCTURE                                       │
│                          (web/index.html #/crm)                                  │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                           HEADER BAR                                     │    │
│  │  ┌──────────────┐  ┌────────────────────────────────┐  ┌────────────┐   │    │
│  │  │ 👥 CRM       │  │ 🔍 Search people...            │  │ Filters ▼  │   │    │
│  │  └──────────────┘  └────────────────────────────────┘  └────────────┘   │    │
│  │                                        │                                │    │
│  │        Category:  All | Work | Personal | Family | Unknown              │    │
│  │        Sources:   📧 📅 💬 📞 📇 (toggleable badges)                     │    │
│  │        Sort:      Strength | Recent | Name | Interactions               │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
│  ┌────────────────────────┬────────────────────────────────────────────────┐    │
│  │      PEOPLE LIST       │              PERSON DETAIL                     │    │
│  │      (Left Column)     │              (Right Panel)                     │    │
│  │                        │                                                │    │
│  │  ┌──────────────────┐  │  ┌────────────────────────────────────────┐   │    │
│  │  │ ○ John Smith     │  │  │ ○ John Smith                           │   │    │
│  │  │   Movement Labs  │  │  │   Movement Labs • Product Manager      │   │    │
│  │  │   ████████░░ 78% │  │  │   john@movementlabs.xyz                 │   │    │
│  │  │   📧 📅 💬       │  │  │   +1 (555) 123-4567                     │   │    │
│  │  └──────────────────┘  │  │                                         │   │    │
│  │  ┌──────────────────┐  │  │  ┌────────────────────────────────────┐│   │    │
│  │  │ ○ Jane Doe       │  │  │  │ Overview │ Timeline │ Network      ││   │    │
│  │  │   Freelance      │  │  │  └────────────────────────────────────┘│   │    │
│  │  │   ██████░░░░ 55% │  │  │                                         │   │    │
│  │  │   📧 📇          │  │  │  STRENGTH BREAKDOWN                    │   │    │
│  │  └──────────────────┘  │  │  ████████████████░░░░░░░░ 78%          │   │    │
│  │  ┌──────────────────┐  │  │                                         │   │    │
│  │  │ ○ Mike Johnson   │  │  │  Recency:   ████████████████ 90%       │   │    │
│  │  │   ...            │  │  │  Frequency: ████████████░░░░ 75%       │   │    │
│  │  └──────────────────┘  │  │  Diversity: ██████████░░░░░░ 60%       │   │    │
│  │                        │  │                                         │   │    │
│  │  [Load More...]        │  │  RECENT INTERACTIONS                   │   │    │
│  │                        │  │  📅 Meeting: Product Review (2d ago)    │   │    │
│  │                        │  │  📧 Re: Q4 Planning (5d ago)           │   │    │
│  │                        │  │  💬 WhatsApp message (1w ago)          │   │    │
│  │                        │  └────────────────────────────────────────┘   │    │
│  └────────────────────────┴────────────────────────────────────────────────┘    │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Source Badges

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           SOURCE BADGES                                          │
│                                                                                  │
│   Source Type    │ Badge │ Color                                                │
│   ───────────────┼───────┼─────────────────────────────────────────────────────│
│   gmail          │ 📧    │ --gmail: #ea4335 (red)                               │
│   calendar       │ 📅    │ --calendar: #4285f4 (blue)                           │
│   vault          │ 📝    │ --vault: #7c3aed (purple)                            │
│   granola        │ 📝    │ --granola: #7c3aed (purple)                          │
│   imessage       │ 💬    │ --imessage: #34c759 (green)                          │
│   whatsapp       │ 💬    │ --whatsapp: #25d366 (whatsapp green)                 │
│   contacts       │ 📇    │ --contacts: #5856d6 (indigo)                         │
│   phone          │ 📞    │ --phone: #ff9500 (orange)                            │
│   slack          │ 💼    │ --slack: #4a154b (slack purple)                      │
│   linkedin       │ 💼    │ --linkedin: #0077b5 (linkedin blue)                  │
│   signal         │ 🔒    │ --signal: #3a76f0 (signal blue)                      │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## File Reference

### Core Services

| File | Purpose |
|------|---------|
| `api/services/person_entity.py` | PersonEntity model and JSON store |
| `api/services/source_entity.py` | SourceEntity model and SQLite store |
| `api/services/entity_resolver.py` | Three-pass resolution algorithm |
| `api/services/interaction_store.py` | Interaction storage and queries |
| `api/services/relationship.py` | Relationship model with multi-source tracking |
| `api/services/relationship_metrics.py` | Strength scoring calculations |
| `api/services/relationship_discovery.py` | Connection/overlap detection, source discovery |
| `api/services/pending_link.py` | Link confirmation workflow |

### Sync Scripts

| Script | Purpose |
|--------|---------|
| `scripts/sync_gmail_calendar_interactions.py` | Gmail/Calendar sync |
| `scripts/sync_contacts_csv.py` | Apple Contacts CSV import |
| `scripts/sync_phone_calls.py` | macOS CallHistoryDB sync |
| `scripts/sync_whatsapp.py` | wacli-based WhatsApp sync |
| `scripts/sync_person_stats.py` | Update person statistics |

### Configuration

| File | Purpose |
|------|---------|
| `config/people_config.py` | Domain mappings, resolution weights |
| `config/people_dictionary.json` | Known people and aliases |

### Data Files

| File | Purpose |
|------|---------|
| `data/people_entities.json` | Canonical person records |
| `data/crm.db` | SQLite: source_entities, interactions, relationships |

---

## Data Sync & Relationship Discovery

### Sync Scripts

All sync scripts are in `scripts/` and follow the pattern:
- Dry run by default (shows what would change)
- Use `--execute` flag to apply changes

| Script | Purpose | Data Source |
|--------|---------|-------------|
| `sync_gmail_calendar_interactions.py` | Sync emails and calendar events | Gmail API |
| `sync_imessage_interactions.py` | Sync iMessage to interactions | `data/imessage.db` |
| `sync_whatsapp.py` | Sync WhatsApp contacts and messages | `~/.wacli/wacli.db` |
| `sync_phone_calls.py` | Sync phone call history | macOS CallHistoryDB |
| `sync_contacts_csv.py` | Import Apple Contacts | Contacts export CSV |
| `sync_person_stats.py` | Update interaction counts on PersonEntity | `data/interactions.db` |
| `link_imessage_entities.py` | Link iMessage handles to CRM people | CRM + imessage.db |

### Relationship Discovery Scripts

| Script | Purpose |
|--------|---------|
| `discover_whatsapp_relationships.py` | Find relationships from WhatsApp group membership |
| `discover_imessage_relationships.py` | Find relationships from iMessage group chats |
| `create_relationship.py` | Manually create relationships (single or batch) |

### Unified Sync Runner

Run all syncs in correct order with a single command:

```bash
# View current stats
uv run python scripts/run_comprehensive_sync.py --stats-only

# Dry run (see what would change)
uv run python scripts/run_comprehensive_sync.py

# Execute full sync
uv run python scripts/run_comprehensive_sync.py --execute
```

**Execution Order:**
1. Link iMessage entities to CRM people
2. Sync iMessage interactions
3. Sync WhatsApp contacts and messages
4. Update person statistics
5. Discover WhatsApp group relationships
6. Discover iMessage group relationships
7. Run full relationship discovery (calendar, email, vault, messaging)

### Data Health API

Monitor data coverage and sync health:

```bash
# Full health report
curl http://localhost:8000/api/crm/data-health

# Summary for UI
curl http://localhost:8000/api/crm/data-health/summary
```

**Response includes:**
- Interaction counts by source with date ranges
- iMessage linking statistics
- Relationship counts by context
- Sync recommendations for stale/incomplete data

### Manual Relationship Creation

For relationships that can't be auto-discovered:

```bash
# Interactive mode
uv run python scripts/create_relationship.py -i

# Single relationship
uv run python scripts/create_relationship.py \
  --person1 "Taylor Walker" \
  --person2 "Alix Haber" \
  --type friend \
  --execute

# Batch mode (link everyone in a friend group)
uv run python scripts/create_relationship.py \
  --batch "Taylor Walker" "Alix Haber" "Heather Williams" "Emily Durfee" \
  --type friend \
  --execute
```

---

## Implemented Features

### Network Graph Visualization (Complete)
- D3.js force-directed network graph
- Click nodes to view person details
- Zoom/pan controls with mouse wheel
- Edge strength filtering (0-100%)
- Degree filtering (1st only vs 1st & 2nd)
- Multi-source edge filtering (Calendar, Email, iMessage, WhatsApp, Slack, LinkedIn)
- Click edges to view relationship details
- Filter state preserved when navigating

### Multi-Source Relationship Tracking (Complete)
- Edge weight calculated from all sources
- Source breakdown in edge panel
- Discovery functions for each source type
- LinkedIn connection detection

---

## Future Enhancements (Planned)

### Performance Optimization
- Query caching
- Database index optimization
- E2E Playwright tests

### Interesting Facts Extraction
- LLM-based extraction from interactions
- Store facts: family, hobbies, dietary prefs, etc.
- Display on person detail page
- User confirmation workflow

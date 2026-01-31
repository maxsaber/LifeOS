# CRM Integration Plan: Relationship-Centric Routing

**Date:** 2026-01-31
**Status:** 📋 Planning
**Goal:** Make relationship strength and channel-specific interaction data drive smart routing

---

## Context for Executing Agent

This section provides everything you need to understand the system before implementing changes.

### Background: Why This Plan Exists

LifeOS recently underwent a major CRM enhancement. We now have rich relationship data:
- **Relationship strength** (0-100 score based on recency, frequency, diversity)
- **Interaction counts by channel** (gmail, imessage, calendar, whatsapp, slack, vault)
- **Per-channel recency** (when did we last interact on each channel)
- **Extracted facts** (family members, interests, important dates - though these are sparse)

**The Problem:** This CRM data is isolated. The chat UI and MCP tools don't use it for routing decisions. When you ask "What's going on with Ben?", the system doesn't know that Ben is someone you talk to daily on WhatsApp vs. someone you emailed once 2 years ago.

**The Solution:** Surface relationship context to guide smart routing. If Ben has recent WhatsApp activity, query WhatsApp. If Sarah only has iMessages, skip Gmail entirely.

### System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│ USER INTERFACES                                                  │
├─────────────────────────────────────────────────────────────────┤
│ Chat UI (/api/ask/stream)     │  MCP Tools (mcp_server.py)      │
│ - Web chat interface          │  - Claude Desktop integration    │
│ - Streaming responses         │  - External agent access         │
└───────────────┬───────────────┴────────────────┬────────────────┘
                │                                 │
                ▼                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ QUERY ROUTING (api/services/query_router.py)                    │
│ - Classifies queries by type (people, calendar, email, etc.)    │
│ - Extracts person names from queries                            │
│ - Decides which data sources to query                           │
└───────────────┬─────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────┐
│ DATA SOURCES                                                     │
├──────────────────┬──────────────────┬───────────────────────────┤
│ LIVE APIs        │ LOCAL STORES     │ VECTOR STORE              │
│ (queried fresh)  │ (synced nightly) │ (ChromaDB)                │
├──────────────────┼──────────────────┼───────────────────────────┤
│ • Gmail API      │ • InteractionStore│ • Vault markdown files   │
│ • Calendar API   │   (interactions.db)│ • Granola meeting notes │
│ • Drive API      │ • PersonEntity    │ • ❌ NO people/CRM data  │
│                  │   (crm.db)        │                          │
│                  │ • iMessage        │                          │
│                  │   (imessage.db)   │                          │
│                  │ • Slack (indexed) │                          │
└──────────────────┴──────────────────┴───────────────────────────┘
```

### Key Distinction: Live APIs vs Stored Data

This is critical to understand:

| Source | How MCP Tools Query It | What's Stored Locally |
|--------|------------------------|----------------------|
| **Gmail** | LIVE Gmail API call | Interaction metadata only (subject, link) |
| **Calendar** | LIVE Google Calendar API | Interaction metadata only |
| **Drive** | LIVE Drive API | Nothing |
| **iMessage** | LOCAL `imessage.db` | Full message content |
| **Slack** | LOCAL vector index | Full message content |

**Why this matters:** We're NOT duplicating Gmail content locally. The sync scripts store *metadata about interactions* (who, when, subject) to build the relationship graph. When you actually want to READ an email, we hit the live Gmail API.

### Key Files Reference

#### Core Services
| File | Purpose |
|------|---------|
| `api/services/query_router.py` | Classifies queries, decides which sources to query |
| `api/services/synthesizer.py` | Generates answers from gathered context |
| `api/services/briefings.py` | Generates person briefings (used by chat for people queries) |
| `api/services/entity_resolver.py` | Resolves names/emails to PersonEntity IDs |

#### CRM Data Layer
| File | Purpose |
|------|---------|
| `api/services/person_entity.py` | PersonEntity model + PersonEntityStore (crm.db) |
| `api/services/interaction_store.py` | Interaction records linking people to touchpoints |
| `api/services/relationship_metrics.py` | Computes relationship_strength scores |
| `api/services/person_facts.py` | Extracted facts about people (sparse, not focus of this plan) |

#### API Routes
| File | Purpose |
|------|---------|
| `api/routes/chat.py` | `/api/ask/stream` - main chat endpoint |
| `api/routes/people.py` | `/api/people/search` - people search (used by MCP) |
| `api/routes/crm.py` | `/api/crm/*` - full CRM CRUD (not exposed to MCP currently) |

#### MCP Server
| File | Purpose |
|------|---------|
| `mcp_server.py` | Exposes LifeOS APIs as MCP tools for Claude Desktop |

#### Sync Scripts
| File | Purpose |
|------|---------|
| `scripts/run_all_syncs.py` | Orchestrates nightly sync pipeline |
| `scripts/sync_gmail_calendar_interactions.py` | Syncs Gmail/Calendar → InteractionStore |
| `scripts/sync_imessage_interactions.py` | Syncs iMessage → InteractionStore |

### Documentation References

For deeper understanding, see:
- `docs/architecture/DATA-AND-SYNC.md` - Data flow and sync architecture
- `docs/architecture/API-MCP-REFERENCE.md` - API and MCP tool documentation
- `docs/prd/MCP-TOOLS.md` - MCP tools product requirements
- `docs/prd/CHAT-UI.md` - Chat UI product requirements
- `docs/prd/CRM-UI.md` - CRM system product requirements
- `README.md` - Overall system architecture

### Audit That Led to This Plan

Before this plan was created, we audited the system to identify gaps:
- See: `docs/plans/2026-01-31-chat-mcp-crm-audit.md`

Key findings from that audit:
1. MCP tools don't expose relationship_strength or channel activity
2. Briefings don't include per-channel recency
3. Query router doesn't use relationship context for source selection
4. Vector store only indexes vault files, not people/CRM data

---

## Core Insight

The most valuable CRM data for routing decisions is:

1. **Relationship Strength** (0-100) - Who matters most
2. **Interaction Counts by Channel** - Where we communicate
3. **Recency by Channel** - Which channels are currently active

This enables queries like:
- "Tell me about Ben" → Find Ben with highest strength → See recent WhatsApp + emails → Query those specifically
- "What did Sarah say?" → Sarah only has iMessages → Skip Gmail, query iMessage

Facts are secondary - nice when available, but not the routing foundation.

---

## Data Already Available

### PersonEntity has:
- `relationship_strength` (0-100)
- `meeting_count`, `email_count`, `mention_count`, `message_count`
- `last_seen` (overall, not per-channel)

### InteractionStore has:
- `get_interaction_counts(person_id)` → `{gmail: 15, imessage: 42, calendar: 8}`
- `get_last_interaction(person_id)` → Most recent overall
- `get_for_person(person_id, source_type=...)` → Filter by channel

### Vector Store (currently):
- **Only indexes vault markdown files** - no people/CRM data
- Person profiles, relationship data, facts → NOT searchable semantically
- This plan adds people to the vector store (new functionality)

### MCP Tools (currently):
- **One people tool:** `lifeos_people_search` → basic search by name/email
- Returns: name, email, company, sources, counts
- **Missing:** relationship_strength, active_channels, recency

### What's Missing:
- `get_last_interaction_by_source(person_id)` → `{gmail: "2026-01-30", imessage: "2026-01-31"}`
- Relationship context in MCP tool responses
- People data in vector store

---

## Implementation Plan

### Phase 1: Add Channel-Specific Recency (Foundation)

#### 1.1 Add `get_last_interaction_by_source()` to InteractionStore
**File:** `api/services/interaction_store.py`

```python
def get_last_interaction_by_source(self, person_id: str) -> dict[str, datetime]:
    """
    Get the most recent interaction timestamp for each source type.

    Returns:
        Dict mapping source_type to last interaction timestamp
        e.g., {"gmail": datetime(...), "imessage": datetime(...), "calendar": datetime(...)}
    """
    conn = self._get_connection()
    try:
        cursor = conn.execute(
            """
            SELECT source_type, MAX(timestamp) as last_ts
            FROM interactions
            WHERE person_id = ?
            GROUP BY source_type
            """,
            (person_id,),
        )
        result = {}
        for row in cursor.fetchall():
            source_type = row[0]
            ts_str = row[1]
            if ts_str:
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                result[source_type] = _make_aware(dt)
        return result
    finally:
        conn.close()
```

#### 1.2 Create Relationship Summary Helper (Computed On-Demand)
**New:** `api/services/relationship_summary.py`

**Important:** This is NOT stored or synced. It's computed fresh on each call by querying
the InteractionStore. The interaction data gets synced nightly; this helper just reads it.

```python
@dataclass
class ChannelActivity:
    """Activity summary for a single channel."""
    source_type: str
    count_90d: int
    last_interaction: Optional[datetime]
    is_recent: bool  # Within 7 days

@dataclass
class RelationshipSummary:
    """Complete relationship context for a person."""
    person_id: str
    person_name: str
    relationship_strength: float

    # Channel breakdown
    channels: list[ChannelActivity]
    active_channels: list[str]  # Channels with recent activity
    primary_channel: Optional[str]  # Most frequent channel

    # Quick stats
    total_interactions_90d: int
    last_interaction: Optional[datetime]
    days_since_contact: int

    # Optional extras (when available)
    facts_count: int = 0
    has_facts: bool = False

def get_relationship_summary(person_id: str) -> RelationshipSummary:
    """Build complete relationship context for routing decisions."""
    person_store = get_person_entity_store()
    interaction_store = get_interaction_store()

    person = person_store.get_by_id(person_id)
    if not person:
        return None

    # Get channel-specific data
    counts = interaction_store.get_interaction_counts(person_id, days_back=90)
    recency = interaction_store.get_last_interaction_by_source(person_id)

    now = datetime.now(timezone.utc)
    channels = []
    active = []

    for source_type, count in counts.items():
        last = recency.get(source_type)
        is_recent = last and (now - last).days <= 7
        channels.append(ChannelActivity(
            source_type=source_type,
            count_90d=count,
            last_interaction=last,
            is_recent=is_recent,
        ))
        if is_recent:
            active.append(source_type)

    # Sort by count to find primary channel
    channels.sort(key=lambda c: c.count_90d, reverse=True)
    primary = channels[0].source_type if channels else None

    # Check for facts
    fact_store = get_person_fact_store()
    facts = fact_store.get_for_person(person_id)

    return RelationshipSummary(
        person_id=person_id,
        person_name=person.display_name,
        relationship_strength=person.relationship_strength,
        channels=channels,
        active_channels=active,
        primary_channel=primary,
        total_interactions_90d=sum(counts.values()),
        last_interaction=person.last_seen,
        days_since_contact=(now - person.last_seen).days if person.last_seen else 999,
        facts_count=len(facts),
        has_facts=len(facts) > 0,
    )
```

---

### Phase 2: Enhance Existing MCP Tool (No New Tools)

**Philosophy:** Don't create new tools when we can enrich existing ones. One coherent tool
that returns everything is better than multiple tools that do similar things.

#### 2.1 Enhance `lifeos_people_search` with Relationship Context
**Files:** `api/routes/people.py`, `mcp_server.py`

The existing `lifeos_people_search` tool calls `/api/people/search`. We enhance the
response to include relationship data, so agents get everything in one call.
**File:** `api/routes/people.py`

Update `PersonResponse` and `_entity_to_response()`:

```python
class PersonResponse(BaseModel):
    # ... existing fields ...
    relationship_strength: float = 0.0
    active_channels: list[str] = []  # Quick hint: ["imessage", "gmail"]
    days_since_contact: int = 999

def _entity_to_response(entity, include_channels: bool = True) -> PersonResponse:
    response = PersonResponse(
        # ... existing fields ...
        relationship_strength=entity.relationship_strength,
    )

    if include_channels:
        interaction_store = get_interaction_store()
        recency = interaction_store.get_last_interaction_by_source(entity.id)
        now = datetime.now(timezone.utc)
        response.active_channels = [
            source for source, last in recency.items()
            if last and (now - last).days <= 7
        ]
        if entity.last_seen:
            response.days_since_contact = (now - entity.last_seen).days

    return response
```

#### 2.2 Update MCP Tool Description
**File:** `mcp_server.py`

Update the description to reflect the richer response:

```python
"/api/people/search": {
    "name": "lifeos_people_search",
    "description": """Search for people in your network by name or email.

Returns relationship context to guide follow-up queries:
- relationship_strength: How important this person is (0-100)
- active_channels: Which channels have recent activity (last 7 days)
- days_since_contact: How long since last interaction

Use active_channels to decide what to query next:
- If "imessage" is active, call lifeos_imessage_search with their entity_id
- If "gmail" is active, call lifeos_gmail_search with their email
- If no active channels, they may be a dormant contact
""",
    "method": "GET"
}
```

---

### Phase 3: Smart Routing with Relationship Context

#### 3.1 Update Query Router for People Queries
**File:** `api/services/query_router.py`

When a person is mentioned, fetch their relationship context and use it:

```python
async def route(self, query: str) -> RoutingResult:
    # Extract person names
    person_names = self._extract_person_names(query)

    # Build context for routing
    person_context = []
    for name in person_names:
        result = self.entity_resolver.resolve(name=name)
        if result and result.entity:
            summary = get_relationship_summary(result.entity.id)
            if summary:
                person_context.append({
                    "name": name,
                    "strength": summary.relationship_strength,
                    "active_channels": summary.active_channels,
                    "primary_channel": summary.primary_channel,
                })

    # Enhance the routing prompt with this context
    if person_context:
        context_str = "\n".join([
            f"- {p['name']}: strength={p['strength']}, active on {p['active_channels']}"
            for p in person_context
        ])
        enhanced_query = f"{query}\n\n[Person context:\n{context_str}]"
    else:
        enhanced_query = query

    # Continue with LLM-based routing, now informed by actual data
    ...
```

#### 3.2 Update Chat Route to Use Context
**File:** `api/routes/chat.py`

When handling people queries, include channel-specific guidance:

```python
# In ask_stream(), after resolving entity:
if entity_id:
    summary = get_relationship_summary(entity_id)
    if summary:
        # Build targeted search strategy
        context_hint = f"## Relationship Context for {summary.person_name}\n"
        context_hint += f"- Strength: {summary.relationship_strength}/100\n"
        context_hint += f"- Active channels: {', '.join(summary.active_channels) or 'none recently'}\n"
        context_hint += f"- Primary channel: {summary.primary_channel}\n"
        context_hint += f"- Days since contact: {summary.days_since_contact}\n"

        extra_context.append({
            "source": "relationship_context",
            "content": context_hint
        })

        # Automatically search active channels
        for channel in summary.active_channels:
            if channel == "imessage":
                # Fetch recent messages
                messages = query_person_messages(entity_id=entity_id, limit=20)
                if messages["count"] > 0:
                    extra_context.append({
                        "source": "imessage",
                        "content": f"## Recent iMessages\n{messages['formatted']}"
                    })
            # Similar for other channels...
```

---

### Phase 4: Index to Vector Store

#### 4.1 Create Person Profile Documents
**File:** `api/services/person_indexer.py`

Generate searchable documents focused on relationship data:

```python
def generate_person_document(person: PersonEntity, summary: RelationshipSummary) -> str:
    """Generate a searchable document for a person."""
    parts = [
        f"# {person.display_name}",
        f"Relationship Strength: {summary.relationship_strength}/100",
        f"Category: {person.category}",
    ]

    if person.company:
        parts.append(f"Company: {person.company}")

    # Channel activity
    if summary.channels:
        parts.append("\n## Communication Channels")
        for ch in summary.channels:
            recency = "active" if ch.is_recent else "dormant"
            parts.append(f"- {ch.source_type}: {ch.count_90d} interactions ({recency})")

    # Tags and notes
    if person.tags:
        parts.append(f"\nTags: {', '.join(person.tags)}")

    if person.notes:
        parts.append(f"\nNotes: {person.notes}")

    # Facts (when available)
    if summary.has_facts:
        fact_store = get_person_fact_store()
        facts = fact_store.get_for_person(person.id)
        if facts:
            parts.append("\n## Known Facts")
            for fact in facts[:10]:  # Limit to top 10
                parts.append(f"- {fact.category}: {fact.value}")

    return "\n".join(parts)
```

#### 4.2 Index Significant Contacts
**File:** `scripts/sync_crm_to_vectorstore.py`

```python
def sync_crm_to_vectorstore():
    """Index relationship data for semantic search."""
    person_store = get_person_entity_store()
    vector_store = VectorStore()

    indexed = 0
    for person in person_store.get_all():
        # Only index meaningful relationships
        if person.relationship_strength < 15 and person.hidden:
            continue

        summary = get_relationship_summary(person.id)
        if not summary or summary.total_interactions_90d < 3:
            continue

        doc = generate_person_document(person, summary)

        vector_store.upsert(
            id=f"person:{person.id}",
            content=doc,
            metadata={
                "source_type": "crm_person",
                "person_id": person.id,
                "person_name": person.canonical_name,
                "relationship_strength": person.relationship_strength,
                "category": person.category,
                "active_channels": ",".join(summary.active_channels),
            }
        )
        indexed += 1

    logger.info(f"Indexed {indexed} person profiles to vector store")
```

#### 4.3 Add to Sync Pipeline
**File:** `scripts/run_all_syncs.py`

Add as Phase 5 after relationship metrics:

```python
# Phase 5: Index CRM to Vector Store
logger.info("Phase 5: Indexing CRM profiles to vector store...")
sync_crm_to_vectorstore()
```

---

## Implementation Order

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| 1 | Add `get_last_interaction_by_source()` | 30 min | Foundation for all else |
| 2 | Create `RelationshipSummary` helper | 1 hr | Encapsulates context (computed on-demand, no sync needed) |
| 3 | Enhance `PersonResponse` + update MCP description | 45 min | Existing tool returns richer data |
| 4 | Update query router with person context | 1.5 hr | Smart source selection |
| 5 | Update chat route to use context | 1.5 hr | Auto-search active channels |
| 6 | Create person profile indexer | 1 hr | Vector store integration (NEW - people not currently indexed) |
| 7 | Add to sync pipeline | 30 min | Keep index fresh |

**Total: ~7 hours**

### Design Principles Applied

1. **No new MCP tools** - Enhanced existing `lifeos_people_search` instead of adding `lifeos_people_context`
2. **No new storage** - `RelationshipSummary` computed on-demand from existing InteractionStore data
3. **Vector store is new** - People/CRM data not currently in vector store; this adds it

---

## Success Criteria

1. **MCP agents get relationship context from existing tool:**
   - Call `lifeos_people_search("Ben")`
   - Response includes: strength=72, active_channels=["whatsapp", "gmail"]
   - Agent knows to query WhatsApp and Gmail, not iMessage
   - **No new tool needed** - same endpoint, richer response

2. **Chat UI auto-searches active channels:**
   - Ask "What's going on with Ben?"
   - System sees Ben has recent WhatsApp → automatically includes those messages
   - Response includes actual message content, not just "Ben is in your contacts"

3. **Vector search finds people by relationship (NEW capability):**
   - Search "my important contacts" → returns high-strength people
   - Search "people I talk to on WhatsApp" → returns WhatsApp-active people
   - Search "dormant work relationships" → returns work category with no recent activity
   - *Currently not possible - people not in vector store*

4. **Routing is channel-aware:**
   - Query mentions Sarah (only has iMessage) → skips Gmail, queries iMessage
   - Query mentions Kevin (has Gmail + Calendar) → queries both, skips iMessage

---

## What's NOT in This Plan (Intentionally)

- **Deep facts integration** - Facts are included when available but not the focus
- **Dunbar circles** - Future enhancement, not needed for routing
- **Live API caching** - Keep current architecture (live APIs stay live)

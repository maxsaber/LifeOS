# CRM Integration & Orchestration Intelligence Implementation

**Date:** 2026-02-01
**Status:** Complete
**Commit:** 36164ad
**Based on:** [CRM Integration Audit](./2026-02-01-crm-integration-audit.md)

---

## Overview

This implementation addresses the integration gaps identified in the audit:
1. **Data Integration** - Rich CRM data (PersonFacts, aliases, notes, tags, relationship_strength) now surfaced in briefings and MCP
2. **Orchestration Intelligence** - Chat UI now uses CRM context to inform fetch depth and synthesis

---

## Key IDs Referenced
- User: `<user-uuid>` (your PersonEntity ID)
- Partner: `<partner-uuid>` (your partner's PersonEntity ID)

---

## Part 1: Briefings Enhancement

### 1.1 New Fields in BriefingContext

**File:** `api/services/briefings.py`

Added to dataclass:
```python
person_facts: list[dict] = field(default_factory=list)  # Extracted facts
aliases: list[str] = field(default_factory=list)        # Known aliases
relationship_strength: float = 0.0                       # 0-100 scale
tags: list[str] = field(default_factory=list)           # User-defined tags
notes: str = ""                                          # User notes on person
```

### 1.2 Fetch New Data in gather_context()

After entity resolution, now fetches:
- `aliases`, `tags`, `notes`, `relationship_strength` from PersonEntity
- PersonFacts filtered by `confidence >= 0.6`

### 1.3 Updated BRIEFING_PROMPT Template

New sections added:
- Aliases display
- Relationship Strength score
- Tags listing
- User Notes section
- Known Facts About This Person (grouped by category)

### 1.4 Updated generate_briefing() Formatting

- `aliases_text`: comma-separated aliases or "None known"
- `tags_text`: comma-separated tags or "None"
- `notes_text`: user notes or "_No notes._"
- `person_facts_text`: facts grouped by category with key-value pairs

---

## Part 2: MCP Tool Addition

### 2.1 New Tools Added

**lifeos_person_facts** (`/api/crm/people/{person_id}/facts`)
- Returns facts organized by category with confidence scores
- Categories: family, interests, preferences, background, work, dates, travel
- Each fact includes: key, value, confidence, confirmed status, source_quote

**lifeos_person_profile** (`/api/crm/people/{person_id}`)
- Returns comprehensive CRM profile
- Includes: all emails, phone numbers, LinkedIn, company, position
- Relationship metrics: strength, category, sources, interaction counts
- User annotations: tags, notes

### 2.2 Updated lifeos_people_search

Description now includes:
- FOLLOW-UP TOOLS guidance (use entity_id)
- ROUTING GUIDANCE based on active_channels

### 2.3 Response Formatters

Added formatters for both new tools:
- Facts: grouped by category with confidence and confirmation status
- Profile: structured display of contact info, relationship metrics, user annotations

---

## Part 3: Relationship Facts Dual Association

### 3.1 Junction Table Schema

**File:** `api/services/person_facts.py`

```sql
CREATE TABLE IF NOT EXISTS person_fact_associations (
    fact_id TEXT NOT NULL,
    person_id TEXT NOT NULL,
    is_primary BOOLEAN DEFAULT 0,
    PRIMARY KEY (fact_id, person_id)
);
```

### 3.2 Modified get_for_person()

Now supports `include_shared` parameter:
- `True` (default): includes facts owned by person OR associated via junction table
- `False`: only facts directly owned by the person

### 3.3 New Methods Added

- `add_association(fact_id, person_id, is_primary)` - Associate a fact with an additional person
- `get_associations(fact_id)` - Get all person associations for a fact
- `remove_association(fact_id, person_id)` - Remove an association

---

## Part 4: Orchestration Intelligence

### 4.1 RoutingResult Enhancement

**File:** `api/services/query_router.py`

Extended dataclass:
```python
fetch_depth: str = "normal"  # "shallow", "normal", "deep"
min_results_threshold: int = 3  # Minimum chunks needed
relationship_context: Optional[dict] = None  # CRM signals
```

### 4.2 Adaptive Fetch Depth

**File:** `api/routes/chat.py`

Message limit varies by relationship strength:
| Strength | Limit | Context |
|----------|-------|---------|
| ≥70 | 150 | Close relationship - deep context |
| ≥40 | 100 | Moderate relationship |
| <40 | 50 | Distant contact - less context needed |
| Explicit query | 200 | Date/search specified |

### 4.3 Confidence Metadata for Synthesis

Added context block to synthesis prompt for people queries:
- Routing confidence percentage
- Sources queried
- Vault chunks found
- Message count
- Guidance for handling sparse/rich data

---

## Files Modified

| File | Changes |
|------|---------|
| `api/services/briefings.py` | +5 BriefingContext fields, gather_context() CRM fetch, BRIEFING_PROMPT sections, generate_briefing() formatting |
| `api/services/person_facts.py` | Junction table schema, get_for_person() include_shared, add_association(), get_associations(), remove_association() |
| `mcp_server.py` | +2 CURATED_ENDPOINTS, +2 fallback_schemas, +2 response formatters, updated people_search description |
| `api/routes/chat.py` | Adaptive fetch depth, confidence metadata block |
| `api/services/query_router.py` | Extended RoutingResult dataclass |

---

## Verification Results

### Briefing Endpoint
```bash
curl "http://localhost:8000/api/briefing/Jane%20Doe" | jq '.metadata'
```
Returns:
- `relationship_strength`: 100.0
- `aliases`: ["Jane", "Jane Doe", "JD", ...]
- `facts_count`: 11

### MCP Tools
```
MCP tools registered: 16 tools
- lifeos_person_facts: True
- lifeos_person_profile: True
```

### Facts Endpoint
```bash
curl "http://localhost:8000/api/crm/people/{id}/facts" | jq '.by_category | keys'
```
Returns: ["background", "interests", "preferences", "summary", "travel"]

### Tests
- 1162 unit tests pass
- Smoke tests pass
- 6 pre-existing data integrity failures (unrelated)

---

## Audit Recommendations Status

| Recommendation | Status |
|----------------|--------|
| Add PersonFacts to BriefingContext | **DONE** |
| Add relationship_strength to BriefingContext | **DONE** |
| Add `lifeos_person_facts` MCP tool | **DONE** |
| Add `lifeos_person_profile` MCP tool | **DONE** |
| Add tags/notes to briefings | **DONE** |
| Add aliases to briefings | **DONE** |
| Adaptive fetch depth based on CRM context | **DONE** |
| Confidence metadata for synthesis | **DONE** |

---

## Future Enhancements

Not implemented in this phase:
- Strength-based search boosting in hybrid_search.py
- Source skipping based on entity metadata (email_count, meeting_count)
- Channel-aware source ordering
- Post-retrieval confidence check with search expansion
- Migration script for associating partner's relationship facts with user

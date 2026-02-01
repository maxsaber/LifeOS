# Audit: Chat UI & MCP Tools Integration with CRM Data

**Date:** 2026-01-31
**Status:** 🔄 In Progress
**Goal:** Evaluate whether chat UI query routing and MCP tools fully leverage the new CRM system

---

## 1. Audit Scope

### What We're Evaluating

1. **Chat UI Query Routing** (`/api/ask/stream`)
   - How does the query router classify queries?
   - What data sources does it query for each type?
   - Is CRM data (relationship strength, facts, Dunbar circles) used in retrieval or synthesis?

2. **MCP Tools** (`mcp_server.py`)
   - What tools are exposed?
   - What data fields do they return?
   - Are they missing new CRM fields?

3. **Stakeholder Briefings** (`/api/people/{name}/briefing`)
   - Does it use relationship strength?
   - Does it include extracted facts?
   - Does it use Dunbar circle context?

4. **Vector Store Indexing** (`indexer.py`)
   - Is CRM person data indexed into the vector store?
   - Could relationship strength boost retrieval?

---

## 2. New CRM Fields to Track

These are the new CRM fields that could add value but might not be utilized:

| Field | Source | Potential Use |
|-------|--------|---------------|
| `relationship_strength` | PersonEntity | Prioritize results, boost retrieval |
| `dunbar_circle` | PersonEntity | Filter by importance tier (1-4) |
| `facts` | PersonFact table | Include in briefings, context |
| `category` | PersonEntity | Filter work/personal/family |
| `sources` (multi-source) | PersonEntity | Show interaction diversity |
| `shared_*_count` | Relationship | Edge context in queries |
| `vault_contexts` | PersonEntity | Semantic context boost |
| `aliases` | PersonEntity | Name expansion in search |

---

## 3. Audit Plan

### Phase 1: Query Router Analysis
- [ ] Read `api/services/query_router.py` - understand classification
- [ ] Read `config/prompts/query_router.txt` - see routing prompt
- [ ] Document which sources are queried for "people" queries

### Phase 2: Chat Synthesis Pipeline
- [ ] Read `api/services/synthesis.py` - understand how answers are built
- [ ] Read `api/routes/ask.py` - see full ask pipeline
- [ ] Document what CRM data is included in context

### Phase 3: MCP Server Analysis
- [ ] Read `mcp_server.py` - see all exposed tools
- [ ] Compare MCP tool outputs to CRM API capabilities
- [ ] Identify missing fields/endpoints

### Phase 4: People-Specific Features
- [ ] Read `api/routes/people.py` - briefing endpoint
- [ ] Check if facts are included in briefings
- [ ] Check if relationship strength is used

### Phase 5: Vector Store Integration
- [ ] Read `api/services/indexer.py` - what gets indexed
- [ ] Read `api/services/vectorstore.py` - retrieval logic
- [ ] Check if CRM metadata could boost results

---

## 4. Findings Log

### 4.1 Query Router (`api/services/query_router.py`)

**Current State:**
- Routes queries to sources: vault, calendar, gmail, drive, people, slack, actions
- Uses Claude Haiku for classification (fast, cheap)
- Extracts person names using regex patterns

**CRM Integration Issues:**
- ❌ No access to relationship_strength for prioritization
- ❌ No awareness of Dunbar circles for filtering important people
- ❌ No use of aliases from CRM for better name matching
- ✅ Does use entity resolver for email lookup when routing gmail queries

**Impact:** When queries involve multiple people or ambiguous references, the router cannot prioritize based on relationship importance.

---

### 4.2 Chat Synthesis Pipeline (`api/routes/chat.py`)

**Current State:**
- `/api/ask/stream` is the main chat endpoint
- For "people" queries:
  - Extracts person name via query_router._extract_person_name()
  - Resolves entity via EntityResolver
  - Queries iMessage if date range specified
  - Generates briefing via BriefingsService

**CRM Integration Issues:**
- ❌ `BriefingContext` does NOT include:
  - `relationship_strength`
  - `facts` (PersonFact entries)
  - `dunbar_circle` (not computed yet)
  - `tags` (user-defined tags)
  - `notes` (user notes)
  - `phone_numbers`
- ❌ Briefing prompt does NOT reference extracted facts
- ❌ When synthesizing answers, CRM metadata isn't used to boost relevance

**Impact:** Briefings miss valuable context like "her dog is named Max" or "she's in my inner circle".

---

### 4.3 MCP Tools (`mcp_server.py`)

**Current Exposed Tools:**
| Tool | CRM Data Used | Missing Data |
|------|--------------|--------------|
| `lifeos_ask` | Indirect (via chat route) | All CRM fields except basic metadata |
| `lifeos_people_search` | canonical_name, email, company | relationship_strength, facts, tags, notes |
| `lifeos_people_resolve` | canonical_name, emails, aliases | relationship_strength, facts, dunbar_circle |
| `lifeos_imessage_search` | entity_id lookup | - |

**CRM Integration Issues:**
- ❌ No MCP tool exposes PersonFacts
- ❌ No MCP tool exposes relationship_strength
- ❌ No MCP tool exposes Dunbar circle / importance tier
- ❌ No MCP tool for getting a person's complete CRM profile
- ❌ `lifeos_people_search` returns PersonResponse, not PersonDetailResponse

**Impact:** External agents (Claude Desktop, other MCP clients) can't access the rich CRM data.

---

### 4.4 People/Briefing (`api/services/briefings.py`, `api/routes/people.py`)

**BriefingsService:**
- Uses EntityResolver → gets entity with: emails, company, position, category, linkedin_url, meeting_count, email_count, mention_count, last_seen
- Uses InteractionStore → gets formatted interaction history
- Uses IMessageStore → gets recent messages
- Uses HybridSearch → searches vault for person mentions

**Missing from Briefings:**
- ❌ `PersonFact` entries (e.g., "Spouse: John", "Birthday: March 15")
- ❌ `relationship_strength` score
- ❌ `tags` (user-defined)
- ❌ `notes` (user notes)
- ❌ `dunbar_circle` assignment

**People API (`api/routes/people.py`):**
- `PersonResponse` model includes basics only
- Does NOT match `PersonDetailResponse` from CRM routes

**Impact:** Briefings are missing the most valuable curated facts about people.

---

### 4.5 Vector Store (`api/services/indexer.py`)

**Current State:**
- Indexes Obsidian vault files with frontmatter metadata
- Extracts people mentions via `extract_people_from_text()`
- Creates vault source entities for v2 people system

**CRM Integration Issues:**
- ❌ CRM person metadata NOT indexed into vector store
- ❌ No way to search "my important contacts" (by relationship_strength)
- ❌ No way to search "people interested in X" (by facts/interests)
- ❌ Could boost retrieval for notes mentioning high-strength relationships

**Impact:** Semantic search can't leverage CRM knowledge about people.

---

## 5. Gap Summary

| Area | Gap Identified | Severity | Recommendation |
|------|----------------|----------|----------------|
| **MCP Tools** | No tool exposes PersonFacts | HIGH | Add `lifeos_people_facts` tool |
| **MCP Tools** | No tool exposes relationship_strength | HIGH | Add field to resolve/search response |
| **MCP Tools** | No "get full profile" tool | MEDIUM | Add `lifeos_people_profile` using CRM API |
| **Briefings** | Missing PersonFacts in context | HIGH | Fetch facts and include in briefing prompt |
| **Briefings** | Missing relationship_strength | MEDIUM | Include strength in briefing metadata |
| **Chat Route** | No facts in people query response | HIGH | Include facts when generating briefings |
| **Query Router** | Can't prioritize by relationship | LOW | Consider strength when multiple people match |
| **People API** | Response model differs from CRM | MEDIUM | Unify or expose full CRM response |
| **Vector Store** | CRM metadata not indexed | LOW | Consider indexing high-strength contacts |

---

## 6. Recommendations

### 6.1 High Priority (Core Functionality Gaps)

1. **Add PersonFacts to Briefings**
   - Modify `BriefingsService.gather_context()` to fetch facts via PersonFactStore
   - Include facts in `BriefingContext` dataclass
   - Update `BRIEFING_PROMPT` to reference facts section

2. **Expose PersonFacts via MCP**
   - Add `lifeos_people_facts` tool that returns facts for a person
   - Include fact categories: family, interests, background, preferences, etc.

3. **Add relationship_strength to MCP responses**
   - Modify `lifeos_people_search` and `lifeos_people_resolve` to include strength
   - Allows external agents to prioritize contacts

### 6.2 Medium Priority (UX Improvements)

4. **Add "Get Full Profile" MCP Tool**
   - New tool `lifeos_people_profile` that returns `PersonDetailResponse`
   - Includes: facts, relationships, source entities, tags, notes, strength

5. **Unify People API Response Models**
   - Either extend `PersonResponse` to match `PersonDetailResponse`
   - Or add `include_detail=true` query param

6. **Include CRM Context in Chat Synthesis**
   - When generating answers about people, include facts as additional context
   - Could improve answers to questions like "what's Sarah's dog's name?"

### 6.3 Lower Priority (Future Enhancements)

7. **Dunbar Circle Assignment**
   - Compute Dunbar circles from relationship_strength
   - Use for filtering/prioritization in queries

8. **Vector Store CRM Integration**
   - Index high-strength contacts as "virtual documents"
   - Enable searches like "my closest friends" or "key work relationships"

---

## 7. Implementation Priorities

| Priority | Item | Effort | Impact |
|----------|------|--------|--------|
| 1 | Add PersonFacts to Briefings | 2-3 hrs | HIGH - Unlocks curated facts |
| 2 | Add `lifeos_people_facts` MCP tool | 1-2 hrs | HIGH - External agent access |
| 3 | Add relationship_strength to MCP | 1 hr | MEDIUM - Priority context |
| 4 | Add `lifeos_people_profile` MCP tool | 1-2 hrs | MEDIUM - Full data access |
| 5 | Include facts in chat synthesis | 2-3 hrs | MEDIUM - Better Q&A |

---

## 8. Open Questions

1. Should relationship_strength be computed on-demand or cached in DB?
   - Currently: computed but can be cached via `_relationship_strength` field

2. Should Dunbar circles be a computed property or stored?
   - Not currently implemented - needs design decision

3. Should PersonFacts be included in every people query or only on demand?
   - Currently: only available via `/api/crm/people/{id}/facts`
   - Consider: adding to briefing context always

---

## 9. Subagent Challenge Results

### Challenge Status: Findings VALIDATED with important nuances

---

### A. VALIDATED GAPS

| Gap Claimed | Evidence | Verdict |
|-------------|----------|---------|
| MCP doesn't expose PersonFacts | Facts exist at `/api/crm/people/{id}/facts` but NOT in `mcp_server.py:CURATED_ENDPOINTS` | ✅ CONFIRMED |
| Briefings missing PersonFacts | `briefings.py:33-65` - BriefingContext has no `facts` field, `gather_context()` doesn't fetch facts | ✅ CONFIRMED |
| relationship_strength CRM-only | 10+ refs in `crm.py`, 0 refs in briefings/chat/query_router | ✅ CONFIRMED |
| PersonResponse ≠ PersonDetailResponse | `people.py:22-37` missing: strength, tags, notes, vault_contexts | ✅ CONFIRMED |
| Dunbar circles not implemented | Only 1 ref in `crm.py:1851`, no computation logic exists | ✅ CONFIRMED |

---

### B. NUANCES DISCOVERED

1. **PersonFactExtractor is Production-Ready** (`person_facts.py:398-1184`)
   - Sophisticated implementation with strategic sampling, confidence scoring
   - Ready to use but NOT integrated into briefing pipeline
   - **Quick win:** Just need to connect existing infrastructure

2. **Chat Route Uses Briefings** (`chat.py:1077-1097`)
   - Fixing briefings automatically improves chat responses
   - **Upgrade severity:** Chat response enrichment → HIGH (was MEDIUM)

3. **CRM Facts Endpoint Already Exists** (`crm.py:1890-1926`)
   - Route: `/api/crm/people/{person_id}/facts`
   - Fully implemented with CRUD operations
   - Just needs MCP exposure + briefing integration

---

### C. MISSED INTEGRATION POINTS

1. **vault_contexts, tags, notes** stored in PersonEntity but unused by briefings/chat
2. **phone_numbers** in PersonDetailResponse but not PersonResponse
3. **PersonFactExtractor** has relationship summary generation (`person_facts.py:1025-1129`) - not auto-triggered

---

### D. REVISED QUICK WINS

| Fix | Effort | Impact |
|-----|--------|--------|
| Add facts to `BriefingContext` | 30 min | HIGH - Unlocks curated facts in briefings + chat |
| Add `lifeos_people_facts` to MCP | 30 min | HIGH - Endpoint already exists, just expose it |
| Add relationship_strength to PersonResponse | 15 min | MEDIUM - External agents get priority signal |
| Add `lifeos_people_profile` MCP tool | 45 min | MEDIUM - Full CRM data access |

---

### E. KEY INSIGHT

> **The CRM data infrastructure exists and is production-ready. It just needs to be connected to the chat/MCP surfaces.**

Everything needed is already implemented:
- PersonFacts: ✅ Implemented
- Fact extraction: ✅ Implemented
- Relationship strength: ✅ Computed
- CRM API: ✅ Full CRUD

The gaps are purely **integration gaps**, not missing functionality.

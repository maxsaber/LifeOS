# Slack Integration PRD - LifeOS

**Status**: In Progress
**Created**: 2026-01-29
**Author**: Claude (AI Agent)
**Version**: 1.0

---

## 1. Overview

### 1.1 Objective
Integrate Slack DM and channel message context into LifeOS to enable:
- Semantic search across Slack messages via vector store
- Chat interface queries that include Slack context
- CRM enrichment with Slack interaction data
- Automated sync of historical and new messages

### 1.2 Success Metrics
| Metric | Target | Measurement |
|--------|--------|-------------|
| Historical DMs indexed | 100% of accessible DMs | Count in ChromaDB collection |
| Query latency | <2 seconds | API response time |
| Person resolution | >90% of Slack users linked | SourceEntity → PersonEntity link rate |
| Sync reliability | 99% success rate | Nightly sync completion logs |

---

## 2. Requirements

### 2.1 Functional Requirements

#### FR-1: Vector Store Integration
**Priority**: P0 (Critical)

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-1.1 | Create `lifeos_slack` ChromaDB collection | Collection exists and accepts documents |
| FR-1.2 | Index DM messages with metadata | Messages searchable with user, channel, timestamp metadata |
| FR-1.3 | Index channel messages user has access to | Public/private channel messages indexed |
| FR-1.4 | Support semantic search over Slack content | Vector similarity search returns relevant messages |
| FR-1.5 | Include Slack results in hybrid search | RRF fusion includes Slack alongside vault |

#### FR-2: Chat Interface Integration
**Priority**: P0 (Critical)

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-2.1 | Add "slack" as query router source | Router can classify queries as slack-relevant |
| FR-2.2 | Include Slack context in synthesis | Chat responses cite Slack messages when relevant |
| FR-2.3 | Support Slack-specific queries | "What did X say about Y in Slack?" returns results |

#### FR-3: CRM/People Integration
**Priority**: P0 (Critical)

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-3.1 | Create SourceEntity for each Slack user | All workspace users have source_type="slack" records |
| FR-3.2 | Link Slack users to PersonEntity | Entity resolver matches by email/name |
| FR-3.3 | Create Interaction records for DM exchanges | Each DM conversation creates interaction |
| FR-3.4 | Update relationship strength with Slack data | Slack DMs contribute to relationship scoring |
| FR-3.5 | Display Slack interactions in person timeline | CRM UI shows Slack touchpoints |

#### FR-4: API & MCP Access
**Priority**: P1 (High)

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-4.1 | Create `/api/slack/search` endpoint | Returns messages matching query |
| FR-4.2 | Create `/api/slack/conversations` endpoint | Lists accessible DMs and channels |
| FR-4.3 | Expose `lifeos_slack_search` MCP tool | Claude Code can search Slack via MCP |

#### FR-5: Data Sync
**Priority**: P0 (Critical)

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FR-5.1 | Historical import of all accessible DMs | All DM history indexed on first run |
| FR-5.2 | Historical import of channel messages | Last 90 days of channel messages indexed |
| FR-5.3 | Incremental sync of new messages | New messages synced within 1 hour |
| FR-5.4 | Nightly full sync at 3 AM | Slack sync runs as part of nightly job |
| FR-5.5 | Handle rate limits gracefully | Exponential backoff on 429 errors |

### 2.2 Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-1 | Initial sync completes | <30 minutes for full history |
| NFR-2 | Incremental sync completes | <5 minutes |
| NFR-3 | Storage efficiency | <1KB per message average |
| NFR-4 | No duplicate messages | Upsert by source_id prevents dupes |

---

## 3. Technical Design

### 3.1 Data Model

#### Slack Message Document (ChromaDB)
```python
{
    "id": "slack:{channel_id}:{message_ts}",
    "content": "Message text content...",
    "metadata": {
        "source_type": "slack",
        "channel_id": "D0AADR650D8",
        "channel_name": "DM with John Smith",
        "channel_type": "im|mpim|channel|group",
        "user_id": "U07E5RS5L07",
        "user_name": "John Smith",
        "timestamp": "2026-01-29T10:30:00Z",
        "thread_ts": null,  # or parent thread timestamp
        "team_id": "T02F5DW71LY"
    }
}
```

#### Slack SourceEntity
```python
SourceEntity(
    source_type="slack",
    source_id="T02F5DW71LY:U07E5RS5L07",
    observed_name="John Smith",
    observed_email="john@company.com",
    metadata={
        "username": "jsmith",
        "display_name": "John",
        "title": "Engineer",
        "team_id": "T02F5DW71LY",
        "image_url": "https://..."
    }
)
```

#### Slack Interaction
```python
Interaction(
    person_id=123,
    timestamp="2026-01-29T10:30:00Z",
    source_type="slack",
    title="DM with John Smith",
    snippet="Hey, can you review the PR?",
    source_link="slack://channel?team=T02F5DW71LY&id=D0AADR650D8",
    source_id="D0AADR650D8:1706521800.123456"
)
```

### 3.2 File Structure

```
api/
├── services/
│   ├── slack_integration.py    # Existing - add user token support
│   ├── slack_indexer.py        # NEW - ChromaDB indexing
│   └── slack_sync.py           # NEW - Sync orchestration
├── routes/
│   └── slack.py                # NEW - API endpoints
scripts/
└── sync_slack.py               # NEW - Manual sync script
tests/
├── test_slack_indexer.py       # NEW - Unit tests
├── test_slack_sync.py          # NEW - Integration tests
└── test_slack_api.py           # NEW - API tests
```

### 3.3 Integration Points

```
┌─────────────────────────────────────────────────────────────┐
│                      Slack API                              │
│  (conversations.list, conversations.history, users.list)    │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│                   slack_integration.py                      │
│  SlackClient with user token from SLACK_USER_TOKEN env var  │
└────────────────────────────┬────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│ slack_indexer │   │  slack_sync   │   │ source_entity │
│               │   │               │   │               │
│ ChromaDB      │   │ Orchestrates  │   │ SourceEntity  │
│ lifeos_slack  │   │ full/incr     │   │ PersonEntity  │
│ collection    │   │ sync jobs     │   │ Interactions  │
└───────────────┘   └───────────────┘   └───────────────┘
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
                             ▼
                    ┌───────────────┐
                    │  Nightly Sync │
                    │  (3 AM step)  │
                    └───────────────┘
```

---

## 4. Implementation Plan

### Phase 1: Core Infrastructure (This Session) ✅
- [x] Update `slack_integration.py` to use env token
- [x] Create `slack_indexer.py` for ChromaDB indexing
- [x] Create `slack_sync.py` for sync orchestration
- [x] Write unit tests for indexer

### Phase 2: API & Search Integration ✅
- [x] Create `/api/slack/search` endpoint
- [x] Create `/api/slack/conversations` endpoint
- [x] Add Slack to query router
- [x] Add Slack to hybrid search (via chat.py)

### Phase 3: CRM Integration ✅
- [x] Sync Slack users to SourceEntity (106 users synced)
- [x] Link to PersonEntity via entity resolver
- [x] Create Interactions from DM messages
- [ ] Update relationship scoring (deferred - existing scoring applies)

### Phase 4: Production Readiness ✅
- [x] Add to nightly sync schedule (Step 6 at 3 AM Eastern)
- [ ] Add MCP tool exposure (deferred for Phase 2)
- [x] Enable in crm_settings.yaml
- [ ] Integration tests (deferred)

---

## 5. Test Plan

### 5.1 Unit Tests

```python
# test_slack_indexer.py

def test_index_dm_message():
    """FR-1.2: DM messages indexed with correct metadata"""
    indexer = SlackIndexer()
    message = SlackMessage(
        ts="1706521800.123456",
        channel_id="D0AADR650D8",
        user_id="U07E5RS5L07",
        text="Hello world",
        timestamp=datetime.now()
    )
    indexer.index_message(message, channel_name="DM with John", channel_type="im")

    results = indexer.search("Hello world")
    assert len(results) >= 1
    assert results[0].metadata["channel_type"] == "im"

def test_no_duplicate_messages():
    """NFR-4: Upsert prevents duplicate messages"""
    indexer = SlackIndexer()
    message = SlackMessage(ts="1706521800.123456", ...)

    indexer.index_message(message, ...)
    indexer.index_message(message, ...)  # Same message again

    count = indexer.collection.count()
    assert count == 1  # Only one document

def test_search_by_user():
    """FR-1.2: Can filter search by user"""
    indexer = SlackIndexer()
    # ... index messages from multiple users

    results = indexer.search("project", user_id="U07E5RS5L07")
    assert all(r.metadata["user_id"] == "U07E5RS5L07" for r in results)
```

### 5.2 Integration Tests

```python
# test_slack_sync.py

def test_full_sync_creates_source_entities():
    """FR-3.1: Full sync creates SourceEntity for each user"""
    sync = SlackSync()
    stats = sync.sync_users()

    assert stats["created"] > 0
    entities = SourceEntityStore().get_by_source_type("slack")
    assert len(entities) == stats["created"] + stats["updated"]

def test_incremental_sync_only_new_messages():
    """FR-5.3: Incremental sync only fetches new messages"""
    sync = SlackSync()

    # First sync
    sync.sync_messages(full=True)
    initial_count = sync.indexer.collection.count()

    # Second sync (no new messages)
    sync.sync_messages(full=False)
    final_count = sync.indexer.collection.count()

    assert final_count == initial_count
```

### 5.3 API Tests

```python
# test_slack_api.py

def test_slack_search_endpoint():
    """FR-4.1: Search endpoint returns results"""
    response = client.get("/api/slack/search?q=meeting")
    assert response.status_code == 200
    assert "results" in response.json()

def test_slack_conversations_endpoint():
    """FR-4.2: Conversations endpoint lists DMs"""
    response = client.get("/api/slack/conversations")
    assert response.status_code == 200
    channels = response.json()["channels"]
    assert any(c["is_im"] for c in channels)
```

### 5.4 Success Criteria Validation

| Requirement | Test | Pass Criteria |
|-------------|------|---------------|
| FR-1.1 | `test_collection_exists` | Collection "lifeos_slack" in ChromaDB |
| FR-1.2 | `test_index_dm_message` | Message retrievable with metadata |
| FR-3.1 | `test_full_sync_creates_source_entities` | SourceEntity count matches users |
| FR-5.1 | `test_historical_import` | All DMs from API in ChromaDB |
| NFR-4 | `test_no_duplicate_messages` | Re-index same message, count unchanged |

---

## 6. Rollback Plan

If issues arise:

1. **Disable Slack in settings**:
   ```yaml
   # config/crm_settings.yaml
   sources:
     slack:
       enabled: false
   ```

2. **Remove from nightly sync** (comment out in `api/main.py`)

3. **Delete indexed data**:
   ```python
   # Clear ChromaDB collection
   chroma_client.delete_collection("lifeos_slack")

   # Clear SourceEntities
   DELETE FROM source_entities WHERE source_type = 'slack';

   # Clear Interactions
   DELETE FROM interactions WHERE source_type = 'slack';
   ```

4. **Revoke app** (optional): https://api.slack.com/apps/A0ABBN26DJB

---

## 7. Open Questions

1. **Channel message scope**: Index all channels or only DMs initially?
   - **Decision**: Start with DMs only, add channels in Phase 2

2. **Message retention**: How far back to index?
   - **Decision**: All available DM history, 90 days for channels

3. **Thread handling**: Index thread replies separately or as part of parent?
   - **Decision**: Index as separate documents with thread_ts metadata

---

## 8. Appendix

### A. Environment Variables Required

```bash
SLACK_CLIENT_ID=2515472239712.10385750217623
SLACK_CLIENT_SECRET=<secret>
SLACK_USER_TOKEN=xoxp-<token>
SLACK_TEAM_ID=T02F5DW71LY
```

### B. API Rate Limits

| Method | Tier | Limit |
|--------|------|-------|
| conversations.list | Tier 2 | 20/min |
| conversations.history | Tier 3 | 50/min |
| users.list | Tier 2 | 20/min |

### C. References

- Slack API Docs: https://api.slack.com/methods
- App Dashboard: https://api.slack.com/apps/A0ABBN26DJB
- Integration Plan: `docs/plans/2026-01-29-slack-integration.md`

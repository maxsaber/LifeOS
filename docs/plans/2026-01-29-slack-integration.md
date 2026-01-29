# Slack Integration for LifeOS

**Status**: In Progress
**Created**: 2026-01-29
**Last Updated**: 2026-01-29

## Overview

Integrate Slack DM and channel message context into LifeOS for:
1. **General search/synthesis** - Query Slack messages alongside vault, email, calendar
2. **CRM enrichment** - Add Slack interactions to person timelines and relationship scoring

## Approach

Use a **Slack Development App** with OAuth user token. This approach:
- Doesn't appear in workspace "Installed Apps" until deployed publicly
- Only visible if someone logs into api.slack.com with your account and checks "Your Apps"
- Provides clean API access with proper scopes

## Prerequisites

- [x] Confirmed: User has admin access to Movement Labs Staff workspace
- [x] Confirmed: User is logged into Slack in browser
- [x] Create Slack app at api.slack.com
- [x] Configure OAuth scopes
- [x] Install to workspace (dev mode)
- [x] Store credentials securely

---

## Implementation Plan

### Phase 1: Slack App Setup (Manual - Browser)

1. Navigate to https://api.slack.com/apps
2. Click "Create New App" → "From scratch"
3. App Name: `LifeOS Personal` (or similar personal name)
4. Workspace: `Movement Labs Staff`
5. Configure OAuth scopes (see below)
6. Install to workspace
7. Copy tokens to `.env`

#### Required OAuth Scopes (User Token Scopes)

For reading DMs and messages the user has access to:

```
# User info
users:read
users:read.email

# Conversations
conversations:read        # View basic channel info
conversations:history     # Read messages in public channels

# DMs
im:read                   # List DMs
im:history               # Read DM messages

# Group DMs
mpim:read                # List group DMs
mpim:history             # Read group DM messages

# Private channels (user is member of)
groups:read              # List private channels
groups:history           # Read private channel messages
```

### Phase 2: Backend Integration

#### 2.1 Configuration

Update `.env`:
```bash
SLACK_USER_TOKEN=xoxp-...        # User OAuth token
SLACK_TEAM_ID=T02F5DW71LY        # Movement Labs Staff
```

Update `config/crm_settings.yaml`:
```yaml
sources:
  slack:
    enabled: true
    sync_dms: true
    sync_channels: false  # Start with DMs only
    sync_interval_minutes: 60
```

#### 2.2 Service Updates

Files to modify/create:
- `api/services/slack_integration.py` - Already exists, needs user token support
- `scripts/sync_slack_messages.py` - New: Sync script for messages
- `api/routes/crm.py` - Add Slack sync endpoint

#### 2.3 Data Model

**SourceEntity** for Slack users (already supported):
```python
source_type = "slack"
source_id = "{team_id}:{user_id}"
observed_name = "Real Name"
observed_email = "user@company.com"
```

**Interaction** for Slack messages:
```python
source_type = "slack"
source_id = "{channel_id}:{message_ts}"
title = "DM with {person_name}" or "#{channel_name}"
snippet = "Message preview..."
timestamp = message_timestamp
```

### Phase 3: CRM Integration

1. Sync Slack users → SourceEntity → PersonEntity (entity resolution)
2. Sync DM conversations → Interactions
3. Update relationship metrics to include Slack diversity score
4. Display Slack interactions in CRM timeline

### Phase 4: Search Integration

1. Index Slack messages in ChromaDB (optional, for semantic search)
2. Add "slack" as a query router source
3. Update synthesizer to include Slack context

---

## Progress Log

### 2026-01-29 - App Created & Installed

**Completed**:
- [x] Explored workspace permissions - user has admin access
- [x] Found existing `api/services/slack_integration.py` with OAuth flow
- [x] Identified that existing code uses Bot tokens, need User tokens
- [x] Created this plan document
- [x] Created Slack app "Personal Notes Sync" (App ID: A0ABBN26DJB)
- [x] Added all 10 User Token scopes:
  - users:read, users:read.email
  - channels:read, channels:history
  - im:read, im:history
  - mpim:read, mpim:history
  - groups:read, groups:history
- [x] Installed app to Movement Labs Staff workspace
- [x] Stored credentials in `.env`:
  - SLACK_CLIENT_ID
  - SLACK_CLIENT_SECRET
  - SLACK_USER_TOKEN (xoxp-...)
  - SLACK_TEAM_ID

**Current State**:
- Slack app is installed and working
- User OAuth token is ready to use
- Credentials stored securely in .env (gitignored)
- Full integration completed (2026-01-29)

**Completed (2026-01-29)**:
1. ✅ Updated slack_integration.py with env token support + rate limiting
2. ✅ Created slack_indexer.py for ChromaDB indexing (lifeos_slack collection)
3. ✅ Created slack_sync.py for sync orchestration
4. ✅ Created api/routes/slack.py with search, conversations, sync endpoints
5. ✅ Added Slack to query router (query_router.py, query_router.txt)
6. ✅ Added Slack context to chat interface (chat.py)
7. ✅ Added Slack to nightly sync (main.py step 6)
8. ✅ Enabled Slack in crm_settings.yaml
9. ✅ Synced 106 users to SourceEntity
10. ⏳ Historical DM sync in progress (103 DMs + 560 group DMs, rate limited)

**Files Created/Modified**:
- `api/services/slack_indexer.py` - NEW: ChromaDB indexing
- `api/services/slack_sync.py` - NEW: Sync orchestration
- `api/routes/slack.py` - NEW: API endpoints
- `api/services/slack_integration.py` - MODIFIED: Env token + rate limiting
- `api/routes/chat.py` - MODIFIED: Slack context in synthesis
- `api/services/query_router.py` - MODIFIED: Slack as source
- `api/main.py` - MODIFIED: Nightly sync step 6
- `config/prompts/query_router.txt` - MODIFIED: Slack routing
- `config/crm_settings.yaml` - MODIFIED: Slack enabled

---

## Technical Notes

### User Token vs Bot Token

- **Bot Token (xoxb-)**: Acts as a bot user, limited to channels bot is invited to
- **User Token (xoxp-)**: Acts as the user, can access everything user can see

We want **User Token** for personal CRM - it sees exactly what you see.

### Existing Code Analysis

`api/services/slack_integration.py` currently:
- Has OAuth flow implemented
- Uses `oauth.v2.access` endpoint
- Stores tokens in `data/slack_tokens.json`
- Has `SlackClient` class with API methods
- Has `sync_slack_users()` function

**Modifications needed**:
- Add user token scope configuration
- Add message sync functionality
- Create interaction records from messages

### API Rate Limits

Slack API Tier 3 (conversations.history): 50+ requests/minute
- Sufficient for periodic sync of DMs

---

## Files Reference

| File | Purpose | Status |
|------|---------|--------|
| `api/services/slack_integration.py` | Core Slack API client | Exists, needs updates |
| `api/routes/crm.py` | CRM routes including Slack endpoints | Exists |
| `config/crm_settings.yaml` | CRM source configuration | Exists |
| `scripts/sync_slack_messages.py` | Message sync script | To create |
| `data/slack_tokens.json` | Token storage | Auto-created |

---

## Credentials (DO NOT COMMIT)

Credentials are stored in `.env` (gitignored):
```bash
SLACK_CLIENT_ID=2515472239712.10385750217623
SLACK_CLIENT_SECRET=<secret>
SLACK_USER_TOKEN=xoxp-<token>
SLACK_TEAM_ID=T02F5DW71LY
```

App management: https://api.slack.com/apps/A0ABBN26DJB

---

## Rollback Plan

If integration causes issues:
1. Set `slack.enabled: false` in `config/crm_settings.yaml`
2. Remove SLACK_* from `.env`
3. Delete `data/slack_tokens.json`
4. Optionally revoke app at api.slack.com/apps

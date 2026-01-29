# MCP Tools PRD

MCP (Model Context Protocol) server that exposes LifeOS capabilities to AI assistants like Claude Code.

**Primary Use Cases:**
- Enable Claude to search your knowledge base
- Allow AI assistants to query calendar, email, messages
- Create memories and drafts programmatically
- Provide personal context during coding sessions

**Related Documentation:**
- [API & MCP Reference](../architecture/API-MCP-REFERENCE.md) - Full API specs
- [Data & Sync](../architecture/DATA-AND-SYNC.md) - Data sources

---

## Table of Contents

1. [Overview](#overview)
2. [Available Tools](#available-tools)
3. [Setup](#setup)
4. [Tool Specifications](#tool-specifications)

---

## Overview

The LifeOS MCP server dynamically discovers endpoints from the LifeOS OpenAPI spec and exposes them as Claude Code tools. It runs as a subprocess and communicates via JSON-RPC over stdin/stdout.

**Key Features:**
- Auto-discovery from OpenAPI spec
- Curated tool descriptions for optimal AI use
- Formatted responses for human readability
- Fallback schemas when API unavailable

**Architecture:**
```
Claude Code  ←→  MCP Protocol  ←→  mcp_server.py  ←→  LifeOS API
              (JSON-RPC/stdio)                         (HTTP)
```

---

## Available Tools

| Tool | Description |
|------|-------------|
| `lifeos_ask` | Query knowledge base with synthesized answer |
| `lifeos_search` | Search vault without synthesis (raw results) |
| `lifeos_calendar_upcoming` | Get upcoming calendar events |
| `lifeos_calendar_search` | Search calendar events |
| `lifeos_gmail_search` | Search emails (includes body for top 5) |
| `lifeos_gmail_draft` | Create Gmail draft |
| `lifeos_drive_search` | Search Google Drive files |
| `lifeos_imessage_search` | Search iMessage/SMS history |
| `lifeos_slack_search` | Semantic search Slack messages |
| `lifeos_people_search` | Search people in network |
| `lifeos_memories_create` | Save a memory |
| `lifeos_memories_search` | Search saved memories |
| `lifeos_conversations_list` | List chat conversations |
| `lifeos_health` | Check service health |

---

## Setup

### Register with Claude Code

```bash
# Add MCP server
claude mcp add lifeos -s user -- python /path/to/LifeOS/mcp_server.py

# Verify
claude mcp list
```

### Environment Variables

```bash
LIFEOS_API_URL=http://localhost:8000  # Default
```

### Requirements

- LifeOS server running (`./scripts/server.sh start`)
- Python 3.11+ with httpx installed

---

## Tool Specifications

### lifeos_ask

Query your knowledge base and get a synthesized answer with citations.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| question | string | Yes | The question to ask |
| include_sources | boolean | No | Include source citations (default: true) |

**Example:**
```json
{
  "question": "What did we discuss in the product meeting yesterday?",
  "include_sources": true
}
```

### lifeos_search

Search the vault without synthesis. Returns raw search results.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| query | string | Yes | Search query |
| top_k | integer | No | Number of results (1-100, default: 10) |

### lifeos_calendar_upcoming

Get upcoming calendar events.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| days | integer | No | Days to look ahead (default: 7) |

### lifeos_calendar_search

Search calendar events by keyword.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| q | string | Yes | Search query |

### lifeos_gmail_search

Search emails in Gmail. Automatically fetches full body for top 5 results.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| q | string | Yes | Search query |
| account | string | No | Account: personal or work |

### lifeos_gmail_draft

Create a draft email in Gmail.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| to | string | Yes | Recipient email |
| subject | string | Yes | Email subject |
| body | string | Yes | Email body |
| cc | string | No | CC recipients |
| bcc | string | No | BCC recipients |
| html | boolean | No | Send as HTML |
| account | string | No | Account: personal or work |

**Returns:** Draft ID and Gmail URL to open draft.

### lifeos_drive_search

Search files in Google Drive.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| q | string | Yes | Search query (name or content) |
| account | string | No | Account: personal or work |

### lifeos_imessage_search

Search iMessage/SMS text message history.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| q | string | No | Search query for message text |
| phone | string | No | Filter by phone (E.164 format) |
| entity_id | string | No | Filter by PersonEntity ID |
| after | string | No | Messages after date (YYYY-MM-DD) |
| before | string | No | Messages before date (YYYY-MM-DD) |
| direction | string | No | Filter: sent or received |
| max_results | integer | No | Max results (1-200, default: 50) |

### lifeos_slack_search

Semantic search across Slack messages.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| query | string | Yes | Search query |
| top_k | integer | No | Number of results (1-50, default: 20) |
| channel_id | string | No | Filter by channel ID |
| user_id | string | No | Filter by user ID |

### lifeos_people_search

Search for people in your network.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| q | string | Yes | Name or email to search |

### lifeos_memories_create

Save a memory for future reference.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| content | string | Yes | Memory content |
| category | string | No | Category (default: facts) |

### lifeos_memories_search

Search saved memories.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| query | string | Yes | Search query |

### lifeos_conversations_list

List recent chat conversations.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| limit | integer | No | Max results (default: 10) |

### lifeos_health

Check if all LifeOS services are healthy.

**Parameters:** None

---

## Implementation

See `mcp_server.py` for implementation details:
- Dynamic endpoint discovery from OpenAPI spec
- Curated tool descriptions in `CURATED_ENDPOINTS`
- Response formatting for readability
- Fallback schemas when API unavailable

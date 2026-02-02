#!/usr/bin/env python3
"""
Dynamic MCP Server for LifeOS API.

Automatically discovers endpoints from the LifeOS OpenAPI spec and exposes them
as Claude Code tools. No manual updates needed when the API changes.

Usage:
    python mcp_server.py

Register with Claude Code:
    claude mcp add lifeos -s user -- python /path/to/mcp_server.py
"""
import json
import sys
import httpx
import logging
from typing import Any

# Configure logging to stderr (stdout is for MCP protocol)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

import os
API_BASE = os.environ.get("LIFEOS_API_URL", "http://localhost:8000")
OPENAPI_URL = f"{API_BASE}/openapi.json"

# Curated list of endpoints to expose as tools (path -> tool config)
# This allows us to control which endpoints are exposed and how they're described
CURATED_ENDPOINTS = {
    "/api/ask": {
        "name": "lifeos_ask",
        "description": "Ask a question to LifeOS. Queries your knowledge base (vault notes, calendar, email, drive, people) and returns a synthesized answer with source citations. Use this for general questions about your personal data.",
        "method": "POST"
    },
    "/api/search": {
        "name": "lifeos_search",
        "description": "Search the LifeOS vault without synthesis. Returns raw search results ranked by relevance. Use this when you want to see the actual source documents rather than a synthesized answer.",
        "method": "POST"
    },
    "/api/calendar/upcoming": {
        "name": "lifeos_calendar_upcoming",
        "description": "Get upcoming calendar events from Google Calendar (personal and work accounts).",
        "method": "GET"
    },
    "/api/calendar/search": {
        "name": "lifeos_calendar_search",
        "description": "Search calendar events by keyword.",
        "method": "GET"
    },
    "/api/gmail/search": {
        "name": "lifeos_gmail_search",
        "description": "Search emails in Gmail by keyword.",
        "method": "GET"
    },
    "/api/drive/search": {
        "name": "lifeos_drive_search",
        "description": "Search files in Google Drive by name or content.",
        "method": "GET"
    },
    "/api/conversations": {
        "name": "lifeos_conversations_list",
        "description": "List recent LifeOS conversations.",
        "method": "GET"
    },
    "/api/memories": {
        "name": "lifeos_memories_create",
        "description": "Save a memory to LifeOS for future reference. Memories persist across sessions and can be retrieved later.",
        "method": "POST"
    },
    "/api/memories/search/{query}": {
        "name": "lifeos_memories_search",
        "description": "Search saved memories by keyword.",
        "method": "GET"
    },
    "/api/people/search": {
        "name": "lifeos_people_search",
        "description": """Search for people in your network by name or email.

RETURNS for each match:
- canonical_name, email, company, position
- relationship_strength: How important (0-100, higher = closer)
- active_channels: Communication channels with recent activity (last 7 days)
- days_since_contact: How long since last interaction
- entity_id: Use this ID for follow-up tools

FOLLOW-UP TOOLS (use entity_id):
- lifeos_person_facts(entity_id) → Get extracted facts (family, interests, etc.)
- lifeos_person_profile(entity_id) → Get full CRM profile with notes/tags
- lifeos_imessage_search(entity_id=...) → Get message history

ROUTING GUIDANCE:
Based on active_channels, decide what to query next:
- If "imessage" active → lifeos_imessage_search with entity_id
- If "gmail" active → lifeos_gmail_search with their email
- If "slack" active → lifeos_slack_search with user_id
- If no active channels → May be dormant contact, check profile for notes""",
        "method": "GET"
    },
    "/health/full": {
        "name": "lifeos_health",
        "description": "Check if all LifeOS services are healthy and responding. Tests vault search, calendar, gmail, drive, people, memories, and more.",
        "method": "GET"
    },
    "/api/imessage/search": {
        "name": "lifeos_imessage_search",
        "description": "Search iMessage/SMS text message history. Search by text content (q), phone number (phone), or person entity ID (entity_id). Filter by date range (after/before) or direction (sent/received). Returns message text, timestamp, and associated person.",
        "method": "GET"
    },
    "/api/gmail/drafts": {
        "name": "lifeos_gmail_draft",
        "description": "Create a draft email in Gmail. Provide 'to' (recipient), 'subject', and 'body'. Optional: 'cc', 'bcc', 'html' (bool), 'account' (personal/work). Returns draft_id and gmail_url to open the draft directly in Gmail for review before sending.",
        "method": "POST"
    },
    "/api/slack/search": {
        "name": "lifeos_slack_search",
        "description": "Search Slack messages semantically. Searches DMs, group DMs, and channels you have access to. Returns messages with sender, channel, and timestamp. Useful for finding what someone said about a topic or recalling conversations.",
        "method": "POST"
    },
    "/api/crm/people/{person_id}/facts": {
        "name": "lifeos_person_facts",
        "description": """Get extracted facts about a person from their interactions.

WHEN TO USE:
- After lifeos_people_search to get deep personal context
- Before drafting personalized messages (to reference their interests, family, etc.)
- When preparing for meetings (to recall key details)

WHAT IT RETURNS:
Facts are organized by category with confidence scores (0-1):
- family: spouse_name, children, pets, siblings, parents
- interests: hobbies, sports, music_taste, favorite_team
- preferences: communication_style, meeting_preference, food_preference
- background: hometown, alma_mater, previous_companies, languages
- work: current_role, expertise, projects, team
- dates: birthday, anniversary, important_dates
- travel: visited_countries, planned_trips, favorite_destinations

Each fact includes:
- key: What the fact is about (e.g., "spouse_name")
- value: The actual fact (e.g., "Sarah")
- confidence: How certain (0.5-0.95, higher = more reliable)
- confirmed: Whether user has verified this fact
- source_quote: The verbatim text that proves this fact

REQUIRES: entity_id from lifeos_people_search results.

EXAMPLE WORKFLOW:
1. lifeos_people_search("Sarah") → get entity_id
2. lifeos_person_facts(entity_id) → get "her dog is named Max", "she likes hiking"
3. Use facts in drafting email or preparing for meeting""",
        "method": "GET"
    },
    "/api/crm/people/{person_id}": {
        "name": "lifeos_person_profile",
        "description": """Get comprehensive CRM profile for a person.

WHEN TO USE:
- When you need FULL context about someone important
- To understand relationship depth and communication patterns
- To see user's notes and tags about this person

WHAT IT RETURNS:
Contact Information:
- emails: All known email addresses
- phone_numbers: All known phone numbers
- linkedin_url: LinkedIn profile if known

Professional Context:
- company: Current organization
- position: Job title
- vault_contexts: Where they appear in notes (e.g., "Work/ML/", "Personal/")

Relationship Metrics:
- relationship_strength: 0-100 score (higher = closer relationship)
- category: "work", "personal", or "family"
- sources: Where data comes from (gmail, calendar, slack, etc.)
- meeting_count, email_count, message_count: Interaction counts

User Annotations:
- tags: User-defined labels (e.g., ["priority", "mentor"])
- notes: User's personal notes about this person

Extracted Facts:
- facts: Array of extracted personal details (use lifeos_person_facts for full detail)

REQUIRES: entity_id from lifeos_people_search results.

USE INSTEAD OF lifeos_people_search when you need:
- All emails (not just primary)
- Phone numbers
- User's notes and tags
- Full relationship context""",
        "method": "GET"
    },
    "/api/crm/people/{person_id}/timeline": {
        "name": "lifeos_person_timeline",
        "description": """Get chronological interaction timeline for a person.

WHEN TO USE:
- "Catch me up on Kevin" → See recent interactions in chronological order
- "What's been happening with Sarah?" → Timeline of all touchpoints
- "When did I last talk to Mike?" → Find last interaction

WHAT IT RETURNS:
- items: Chronological list of interactions (newest first)
- Each item includes:
  - source_type: "gmail", "imessage", "calendar", "slack", "vault", etc.
  - timestamp: When it happened
  - summary: Brief description of the interaction
  - metadata: Source-specific details (subject, attendees, etc.)

PARAMETERS:
- person_id (required): entity_id from lifeos_people_search
- days_back (optional): How far back to look (default: 365, max: 3650)
- source_type (optional): Filter by source (e.g., "imessage", "gmail,slack")
- limit (optional): Max results (default: 50)

EXAMPLE WORKFLOW:
1. lifeos_people_search("Kevin") → get entity_id
2. lifeos_person_timeline(entity_id, days_back=30) → recent interactions
3. Summarize what's been happening""",
        "method": "GET"
    },
    "/api/calendar/meeting-prep": {
        "name": "lifeos_meeting_prep",
        "description": """Get intelligent meeting preparation context for a date.

WHEN TO USE:
- "Prep me for my meetings today" → Get context for all meetings
- "What do I need to know for my 1:1 with Sarah?" → Context for specific meeting
- "What meetings do I have tomorrow and what should I prepare?" → Planning ahead

WHAT IT RETURNS for each meeting:
- Meeting details: title, time, attendees, location, description
- related_notes: Relevant vault notes including:
  - People notes for attendees
  - Past meeting notes from similar recurring meetings
  - Topic-related notes mentioning attendees or subjects
- attachments: Any files attached to the calendar event
- agenda_summary: Brief description if available

PARAMETERS:
- date (optional): Date in YYYY-MM-DD format (defaults to today)
- include_all_day (optional): Include all-day events (default: false)
- max_related_notes (optional): Max notes per meeting (default: 4)

RETURNS:
- date: The date queried
- meetings: List of meetings with prep context
- count: Number of meetings

USE THIS when preparing for meetings instead of separate calendar + vault searches.""",
        "method": "GET"
    },
    "/api/crm/family/communication-gaps": {
        "name": "lifeos_communication_gaps",
        "description": """Identify people you haven't contacted recently.

WHEN TO USE:
- "Who should I reach out to?" → Find neglected relationships
- "Who haven't I talked to in a while?" → Communication gaps
- "Which family members need a call?" → Family check-in suggestions

WHAT IT RETURNS:
- gaps: List of significant communication gaps with:
  - person_id, person_name
  - gap_start, gap_end: The period of no contact
  - gap_days: How long the gap was
- person_summaries: For each person:
  - days_since_last_contact
  - average_gap_days: Their typical communication frequency
  - longest_gap_days: Their longest ever gap
  - current_gap_days: Current time since contact

PARAMETERS:
- person_ids (required): Comma-separated person IDs to analyze
- days_back (optional): History to analyze (default: 365)
- min_gap_days (optional): Minimum gap to report (default: 14)

WORKFLOW:
1. Get family member IDs from lifeos_people_search
2. Call this with those IDs to find who needs attention
3. Suggest reaching out to those with unusually long gaps

NOTE: This tool requires person_ids parameter. First use lifeos_people_search
to find people, then pass their entity_ids here.""",
        "method": "GET"
    },
}


class LifeOSMCPServer:
    """MCP Server that dynamically discovers LifeOS API endpoints."""

    def __init__(self):
        self.client = httpx.Client(timeout=30.0)
        self.openapi_spec: dict | None = None
        self.tools: list[dict] = []
        self._load_openapi_spec()

    def _load_openapi_spec(self):
        """Load OpenAPI spec from LifeOS API."""
        try:
            resp = self.client.get(OPENAPI_URL)
            resp.raise_for_status()
            self.openapi_spec = resp.json()
            self._build_tools_from_spec()
            logger.info(f"Loaded OpenAPI spec: {len(self.tools)} tools available")
        except Exception as e:
            logger.warning(f"Could not load OpenAPI spec: {e}. Using curated endpoints only.")
            self._build_tools_fallback()

    def _build_tools_from_spec(self):
        """Build tool definitions from OpenAPI spec."""
        if not self.openapi_spec:
            return

        paths = self.openapi_spec.get("paths", {})
        schemas = self.openapi_spec.get("components", {}).get("schemas", {})

        for path, config in CURATED_ENDPOINTS.items():
            # Find matching path in OpenAPI spec (handle path parameters)
            spec_path = self._find_spec_path(path, paths)
            if not spec_path:
                logger.debug(f"Path {path} not found in OpenAPI spec")
                continue

            method = config["method"].lower()
            endpoint_spec = paths.get(spec_path, {}).get(method, {})

            tool = {
                "name": config["name"],
                "description": config["description"],
                "inputSchema": self._build_input_schema(endpoint_spec, schemas, method, path)
            }
            self.tools.append(tool)

    def _find_spec_path(self, curated_path: str, paths: dict) -> str | None:
        """Find the matching OpenAPI spec path for a curated path."""
        # Direct match
        if curated_path in paths:
            return curated_path

        # Handle path parameters (e.g., /api/memories/search/{query})
        for spec_path in paths:
            # Convert OpenAPI path params to regex-like pattern
            pattern = spec_path.replace("{", "(?P<").replace("}", ">[^/]+)")
            import re
            if re.fullmatch(pattern, curated_path):
                return spec_path

        return None

    def _build_input_schema(self, endpoint_spec: dict, schemas: dict, method: str, path: str) -> dict:
        """Build JSON Schema for tool input from OpenAPI endpoint spec."""
        properties = {}
        required = []

        # Handle query parameters (GET requests)
        for param in endpoint_spec.get("parameters", []):
            if param.get("in") == "query":
                name = param["name"]
                param_schema = param.get("schema", {"type": "string"})
                properties[name] = {
                    "type": param_schema.get("type", "string"),
                    "description": param.get("description", f"Query parameter: {name}")
                }
                if param.get("required"):
                    required.append(name)

        # Handle path parameters
        if "{" in path:
            import re
            path_params = re.findall(r"\{(\w+)\}", path)
            for param_name in path_params:
                properties[param_name] = {
                    "type": "string",
                    "description": f"Path parameter: {param_name}"
                }
                required.append(param_name)

        # Handle request body (POST requests)
        if method == "post":
            request_body = endpoint_spec.get("requestBody", {})
            content = request_body.get("content", {})
            json_content = content.get("application/json", {})
            body_schema = json_content.get("schema", {})

            # Resolve $ref if present
            if "$ref" in body_schema:
                ref_name = body_schema["$ref"].split("/")[-1]
                body_schema = schemas.get(ref_name, {})

            # Merge body properties into tool schema
            for prop_name, prop_schema in body_schema.get("properties", {}).items():
                properties[prop_name] = {
                    "type": prop_schema.get("type", "string"),
                    "description": prop_schema.get("description", f"Request field: {prop_name}")
                }
                if prop_schema.get("default") is not None:
                    properties[prop_name]["default"] = prop_schema["default"]

            # Add required fields
            for req_field in body_schema.get("required", []):
                if req_field not in required:
                    required.append(req_field)

        schema = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema

    def _build_tools_fallback(self):
        """Build tools from curated list without OpenAPI spec."""
        # Fallback schemas for when OpenAPI is unavailable
        fallback_schemas = {
            "lifeos_ask": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The question to ask"},
                    "include_sources": {"type": "boolean", "description": "Include source citations", "default": True}
                },
                "required": ["question"]
            },
            "lifeos_search": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "top_k": {"type": "integer", "description": "Number of results (1-100)", "default": 10}
                },
                "required": ["query"]
            },
            "lifeos_calendar_upcoming": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Days to look ahead", "default": 7}
                }
            },
            "lifeos_calendar_search": {
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Search query"}
                },
                "required": ["q"]
            },
            "lifeos_gmail_search": {
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Search query"}
                },
                "required": ["q"]
            },
            "lifeos_drive_search": {
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Search query (name or content)"},
                    "account": {"type": "string", "description": "Account: personal or work", "default": "personal"}
                },
                "required": ["q"]
            },
            "lifeos_conversations_list": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max results", "default": 10}
                }
            },
            "lifeos_memories_create": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Memory content"},
                    "category": {"type": "string", "description": "Category", "default": "facts"}
                },
                "required": ["content"]
            },
            "lifeos_memories_search": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"]
            },
            "lifeos_people_search": {
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Name or email to search"}
                },
                "required": ["q"]
            },
            "lifeos_health": {
                "type": "object",
                "properties": {}
            },
            "lifeos_imessage_search": {
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Search query for message text (case-insensitive)"},
                    "phone": {"type": "string", "description": "Filter by phone number (E.164 format, e.g., +15551234567)"},
                    "entity_id": {"type": "string", "description": "Filter by PersonEntity ID"},
                    "after": {"type": "string", "description": "Messages after date (YYYY-MM-DD)"},
                    "before": {"type": "string", "description": "Messages before date (YYYY-MM-DD)"},
                    "direction": {"type": "string", "description": "Filter by direction: 'sent' or 'received'"},
                    "max_results": {"type": "integer", "description": "Maximum results (1-200)", "default": 50}
                }
            },
            "lifeos_slack_search": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query for Slack messages (semantic search)"},
                    "top_k": {"type": "integer", "description": "Number of results to return (1-50)", "default": 20},
                    "channel_id": {"type": "string", "description": "Filter by specific channel ID"},
                    "user_id": {"type": "string", "description": "Filter by specific user ID"}
                },
                "required": ["query"]
            },
            "lifeos_person_facts": {
                "type": "object",
                "properties": {
                    "person_id": {"type": "string", "description": "The person's entity_id from lifeos_people_search"}
                },
                "required": ["person_id"]
            },
            "lifeos_person_profile": {
                "type": "object",
                "properties": {
                    "person_id": {"type": "string", "description": "The person's entity_id from lifeos_people_search"}
                },
                "required": ["person_id"]
            },
            "lifeos_person_timeline": {
                "type": "object",
                "properties": {
                    "person_id": {"type": "string", "description": "The person's entity_id from lifeos_people_search"},
                    "days_back": {"type": "integer", "description": "Days of history to include (default: 365)", "default": 365},
                    "source_type": {"type": "string", "description": "Filter by source type (e.g., 'imessage', 'gmail,slack')"},
                    "limit": {"type": "integer", "description": "Max results (default: 50)", "default": 50}
                },
                "required": ["person_id"]
            },
            "lifeos_meeting_prep": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD format (defaults to today)"},
                    "include_all_day": {"type": "boolean", "description": "Include all-day events", "default": False},
                    "max_related_notes": {"type": "integer", "description": "Max related notes per meeting (1-10)", "default": 4}
                }
            },
            "lifeos_communication_gaps": {
                "type": "object",
                "properties": {
                    "person_ids": {"type": "string", "description": "Comma-separated person IDs to analyze"},
                    "days_back": {"type": "integer", "description": "Days of history to analyze (default: 365)", "default": 365},
                    "min_gap_days": {"type": "integer", "description": "Minimum gap to report in days (default: 14)", "default": 14}
                },
                "required": ["person_ids"]
            }
        }

        for config in CURATED_ENDPOINTS.values():
            tool = {
                "name": config["name"],
                "description": config["description"],
                "inputSchema": fallback_schemas.get(config["name"], {"type": "object", "properties": {}})
            }
            self.tools.append(tool)

    def _fetch_email_body(self, message_id: str, account: str = "personal") -> str | None:
        """Fetch full email body for a specific message."""
        try:
            url = f"{API_BASE}/api/gmail/message/{message_id}"
            resp = self.client.get(url, params={"account": account, "include_body": True})
            resp.raise_for_status()
            data = resp.json()
            return data.get("body")
        except Exception as e:
            logger.warning(f"Failed to fetch email body for {message_id}: {e}")
            return None

    def _call_api(self, tool_name: str, arguments: dict) -> dict:
        """Call the LifeOS API based on tool name and arguments."""
        # Find the endpoint config
        endpoint_config = None
        endpoint_path = None
        for path, config in CURATED_ENDPOINTS.items():
            if config["name"] == tool_name:
                endpoint_config = config
                endpoint_path = path
                break

        if not endpoint_config:
            return {"error": f"Unknown tool: {tool_name}"}

        method = endpoint_config["method"]
        url = f"{API_BASE}{endpoint_path}"

        # Handle path parameters
        if "{" in endpoint_path:
            import re
            path_params = re.findall(r"\{(\w+)\}", endpoint_path)
            for param in path_params:
                if param in arguments:
                    url = url.replace(f"{{{param}}}", str(arguments.pop(param)))

        try:
            if method == "GET":
                resp = self.client.get(url, params=arguments)
            else:  # POST
                resp = self.client.post(url, json=arguments)

            resp.raise_for_status()
            result = resp.json()

            # For gmail search, fetch bodies for top 5 results
            if tool_name == "lifeos_gmail_search":
                messages = result.get("messages", [])
                account = arguments.get("account", "personal")
                for msg in messages[:5]:
                    if msg.get("message_id"):
                        body = self._fetch_email_body(msg["message_id"], account)
                        if body:
                            msg["body"] = body

            return result
        except httpx.HTTPStatusError as e:
            return {"error": f"API error {e.response.status_code}: {e.response.text[:200]}"}
        except httpx.RequestError as e:
            return {"error": f"Request failed: {e}"}
        except Exception as e:
            return {"error": f"Unexpected error: {e}"}

    def _format_response(self, tool_name: str, data: dict) -> str:
        """Format API response for human readability."""
        if "error" in data:
            return f"Error: {data['error']}"

        # Tool-specific formatting
        if tool_name == "lifeos_ask":
            text = data.get("answer", "No answer returned")
            if sources := data.get("sources"):
                text += "\n\n**Sources:**\n"
                for s in sources[:5]:
                    text += f"- {s.get('file_name', 'Unknown')} (relevance: {s.get('relevance', 0):.2f})\n"
            return text

        elif tool_name == "lifeos_search":
            results = data.get("results", [])
            if not results:
                return "No results found."
            text = f"Found {len(results)} results:\n\n"
            for r in results[:10]:
                text += f"**{r.get('file_name', 'Unknown')}** (score: {r.get('score', 0):.2f})\n"
                content = r.get('content', '')[:150]
                text += f"{content}...\n\n"
            return text

        elif tool_name in ("lifeos_calendar_upcoming", "lifeos_calendar_search"):
            events = data.get("events", [])
            if not events:
                return "No events found."
            text = f"Found {len(events)} events:\n\n"
            for e in events[:10]:
                text += f"- **{e.get('summary', 'Untitled')}**\n"
                text += f"  When: {e.get('start', 'No time')}\n"
                if attendees := e.get('attendees'):
                    text += f"  With: {', '.join(attendees[:3])}\n"
            return text

        elif tool_name == "lifeos_gmail_search":
            emails = data.get("emails", data.get("messages", []))
            if not emails:
                return "No emails found."
            text = f"Found {len(emails)} emails:\n\n"
            for i, e in enumerate(emails[:10]):
                text += f"- **{e.get('subject', 'No subject')}**\n"
                # Show sender or recipient depending on what's available
                if sender := e.get('sender_name') or e.get('sender') or e.get('from'):
                    text += f"  From: {sender}\n"
                if to := e.get('to'):
                    text += f"  To: {to}\n"
                text += f"  Date: {e.get('date', 'Unknown')}\n"
                # Show body for first 5 emails if available
                if i < 5 and (body := e.get('body')):
                    # Truncate long bodies
                    body_preview = body[:2000] + "..." if len(body) > 2000 else body
                    text += f"  Body:\n{body_preview}\n"
                text += "\n"
            return text

        elif tool_name == "lifeos_drive_search":
            files = data.get("files", [])
            if not files:
                return "No files found."
            text = f"Found {len(files)} files:\n\n"
            for f in files[:10]:
                text += f"- **{f.get('name', 'Untitled')}**\n"
                text += f"  Type: {f.get('mime_type', 'Unknown')}\n"
                text += f"  Modified: {f.get('modified_time', 'Unknown')}\n"
                if f.get('web_link'):
                    text += f"  Link: {f.get('web_link')}\n"
                text += f"  Account: {f.get('source_account', 'Unknown')}\n\n"
            return text

        elif tool_name == "lifeos_conversations_list":
            convs = data.get("conversations", [])
            if not convs:
                return "No conversations found."
            text = f"Found {len(convs)} conversations:\n\n"
            for c in convs[:10]:
                text += f"- **{c.get('title', 'Untitled')}** (ID: {c.get('id', '')})\n"
            return text

        elif tool_name == "lifeos_memories_create":
            return f"Memory saved with ID: {data.get('id', 'unknown')}"

        elif tool_name == "lifeos_memories_search":
            memories = data.get("memories", [])
            if not memories:
                return "No memories found."
            text = f"Found {len(memories)} memories:\n\n"
            for m in memories[:10]:
                text += f"- {m.get('content', '')[:100]}...\n"
            return text

        elif tool_name == "lifeos_people_search":
            people = data.get("people", data.get("results", []))
            if not people:
                return "No people found."
            text = f"Found {len(people)} people:\n\n"
            for p in people[:10]:
                name = p.get("name", p.get("canonical_name", "Unknown"))
                text += f"- **{name}**"
                if email := p.get("email"):
                    text += f" ({email})"
                text += "\n"
                # Show relationship context for routing decisions
                strength = p.get("relationship_strength", 0)
                days = p.get("days_since_contact", 999)
                active = p.get("active_channels", [])
                entity_id = p.get("entity_id", "")
                text += f"  Strength: {strength:.0f}/100 | Last contact: {days} days ago\n"
                if active:
                    text += f"  Active channels: {', '.join(active)}\n"
                else:
                    text += f"  Active channels: none recently\n"
                if entity_id:
                    text += f"  Entity ID: {entity_id}\n"
                text += "\n"
            return text

        elif tool_name == "lifeos_health":
            status = data.get("status", "unknown")
            return f"LifeOS API status: {status}"

        elif tool_name == "lifeos_imessage_search":
            messages = data.get("messages", [])
            if not messages:
                return "No messages found."
            text = f"Found {len(messages)} messages:\n\n"
            for m in messages[:30]:
                direction = "→" if m.get("is_from_me") else "←"
                timestamp = m.get("timestamp", "")[:16].replace("T", " ")
                msg_text = m.get("text", "")
                # Truncate long messages
                if len(msg_text) > 150:
                    msg_text = msg_text[:150] + "..."
                msg_text = msg_text.replace("\n", " ").strip()
                text += f"- **{timestamp}** {direction} {msg_text}\n"
            return text

        elif tool_name == "lifeos_slack_search":
            results = data.get("results", [])
            if not results:
                return "No Slack messages found."
            text = f"Found {len(results)} Slack messages:\n\n"
            for r in results[:20]:
                channel = r.get("channel_name", "Unknown channel")
                user = r.get("user_name", "Unknown user")
                timestamp = r.get("timestamp", "")[:16].replace("T", " ")
                content = r.get("content", "")
                # Truncate long messages
                if len(content) > 200:
                    content = content[:200] + "..."
                content = content.replace("\n", " ").strip()
                text += f"- **{timestamp}** in {channel}\n"
                text += f"  {user}: {content}\n\n"
            return text

        elif tool_name == "lifeos_person_facts":
            facts = data.get("facts", [])
            if not facts:
                return "No facts extracted for this person yet."
            by_category = data.get("by_category", {})
            text = f"Found {len(facts)} facts:\n\n"
            for cat, cat_facts in by_category.items():
                text += f"**{cat.title()}:**\n"
                for f in cat_facts:
                    key = f.get("key", "")
                    value = f.get("value", "")
                    confidence = f.get("confidence", 0)
                    confirmed = "✓" if f.get("confirmed_by_user") else ""
                    text += f"  - {key}: {value} (conf: {confidence:.0%}) {confirmed}\n"
                text += "\n"
            return text

        elif tool_name == "lifeos_person_profile":
            name = data.get("display_name", data.get("canonical_name", "Unknown"))
            text = f"**{name}**\n\n"
            if emails := data.get("emails"):
                text += f"**Emails:** {', '.join(emails)}\n"
            if phones := data.get("phone_numbers"):
                text += f"**Phones:** {', '.join(phones)}\n"
            if company := data.get("company"):
                text += f"**Company:** {company}\n"
            if position := data.get("position"):
                text += f"**Position:** {position}\n"
            if linkedin := data.get("linkedin_url"):
                text += f"**LinkedIn:** {linkedin}\n"
            text += f"**Relationship Strength:** {data.get('relationship_strength', 0):.0f}/100\n"
            text += f"**Category:** {data.get('category', 'unknown')}\n"
            if sources := data.get("sources"):
                text += f"**Data Sources:** {', '.join(sources)}\n"
            if tags := data.get("tags"):
                text += f"**Tags:** {', '.join(tags)}\n"
            if notes := data.get("notes"):
                text += f"\n**Notes:**\n{notes}\n"
            # Interaction counts
            meeting_count = data.get("meeting_count", 0)
            email_count = data.get("email_count", 0)
            mention_count = data.get("mention_count", 0)
            if meeting_count or email_count or mention_count:
                text += f"\n**Interactions:** {meeting_count} meetings, {email_count} emails, {mention_count} mentions\n"
            return text

        elif tool_name == "lifeos_person_timeline":
            items = data.get("items", [])
            total = data.get("total_count", len(items))
            if not items:
                return "No interactions found for this person."
            text = f"Found {total} interactions:\n\n"
            for item in items[:30]:  # Limit display
                source = item.get("source_type", "unknown")
                timestamp = item.get("timestamp", "")[:16].replace("T", " ")
                summary = item.get("summary", "")[:200]
                # Use emoji for source type
                emoji = {
                    "gmail": "📧",
                    "imessage": "💬",
                    "whatsapp": "💬",
                    "calendar": "📅",
                    "slack": "💼",
                    "vault": "📝",
                    "granola": "📝",
                }.get(source, "•")
                text += f"{emoji} **{timestamp}** [{source}]\n"
                text += f"   {summary}\n\n"
            if total > 30:
                text += f"\n_... and {total - 30} more interactions_\n"
            return text

        elif tool_name == "lifeos_meeting_prep":
            meetings = data.get("meetings", [])
            date = data.get("date", "")
            if not meetings:
                return f"No meetings found for {date}."
            text = f"**Meeting Prep for {date}** ({len(meetings)} meetings)\n\n"
            for m in meetings:
                text += f"### {m.get('title', 'Untitled')}\n"
                text += f"**Time:** {m.get('start_time', '')} - {m.get('end_time', '')}\n"
                if attendees := m.get("attendees"):
                    text += f"**With:** {', '.join(attendees[:5])}"
                    if len(attendees) > 5:
                        text += f" (+{len(attendees) - 5} more)"
                    text += "\n"
                if location := m.get("location"):
                    text += f"**Location:** {location}\n"
                if description := m.get("description"):
                    text += f"**Description:** {description}\n"
                # Related notes
                if related := m.get("related_notes"):
                    text += "\n**Related Notes:**\n"
                    for note in related:
                        relevance = note.get("relevance", "")
                        title = note.get("title", "")
                        relevance_emoji = {
                            "attendee": "👤",
                            "past_meeting": "📅",
                            "topic": "📄",
                        }.get(relevance, "•")
                        text += f"  {relevance_emoji} {title}"
                        if note.get("date"):
                            text += f" ({note['date']})"
                        text += "\n"
                # Attachments
                if attachments := m.get("attachments"):
                    text += "\n**Attachments:**\n"
                    for att in attachments:
                        text += f"  📎 [{att.get('title', 'File')}]({att.get('url', '')})\n"
                text += "\n---\n\n"
            return text

        elif tool_name == "lifeos_communication_gaps":
            gaps = data.get("gaps", [])
            summaries = data.get("person_summaries", [])
            if not summaries:
                return "No communication data found for these people."
            text = "## Communication Gap Analysis\n\n"
            # Show person summaries first
            text += "### Overview\n"
            for s in summaries:
                name = s.get("person_name", "Unknown")
                days = s.get("days_since_last_contact", 999)
                avg = s.get("average_gap_days", 0)
                current = s.get("current_gap_days", 0)
                # Flag if current gap is significantly longer than average
                alert = "⚠️ " if current > avg * 1.5 and current > 14 else ""
                text += f"- **{name}**: {alert}{days} days since contact"
                if avg:
                    text += f" (avg gap: {avg:.0f} days)"
                text += "\n"
            # Show significant gaps
            if gaps:
                text += "\n### Significant Gaps\n"
                for g in gaps[:10]:
                    name = g.get("person_name", "Unknown")
                    gap_days = g.get("gap_days", 0)
                    start = g.get("gap_start", "")[:10]
                    end = g.get("gap_end", "")[:10]
                    text += f"- **{name}**: {gap_days} days ({start} to {end})\n"
            return text

        # Default: return formatted JSON
        return json.dumps(data, indent=2)


def send_response(response: dict, request_id: str | int):
    """Send JSON-RPC response to stdout."""
    result = {"jsonrpc": "2.0", "id": request_id, "result": response}
    print(json.dumps(result), flush=True)


def send_error(message: str, request_id: str | int, code: int = -32000):
    """Send JSON-RPC error to stdout."""
    error = {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    print(json.dumps(error), flush=True)


def main():
    """Main MCP server loop."""
    server = LifeOSMCPServer()

    for line in sys.stdin:
        try:
            request = json.loads(line.strip())
            method = request.get("method")
            request_id = request.get("id")

            if method == "initialize":
                send_response({
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "lifeos", "version": "1.0.0"}
                }, request_id)

            elif method == "notifications/initialized":
                pass  # No response needed

            elif method == "tools/list":
                send_response({"tools": server.tools}, request_id)

            elif method == "tools/call":
                params = request.get("params", {})
                tool_name = params.get("name")
                arguments = params.get("arguments", {})

                result = server._call_api(tool_name, arguments)
                formatted = server._format_response(tool_name, result)

                send_response({
                    "content": [{"type": "text", "text": formatted}]
                }, request_id)

            else:
                if request_id is not None:
                    send_error(f"Unknown method: {method}", request_id)

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
        except Exception as e:
            logger.error(f"Error handling request: {e}")
            if 'request_id' in dir() and request_id is not None:
                send_error(str(e), request_id)


if __name__ == "__main__":
    main()

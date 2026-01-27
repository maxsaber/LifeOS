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
        "description": "Search for people in your network by name or email.",
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

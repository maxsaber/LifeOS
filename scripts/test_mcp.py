#!/usr/bin/env python3
"""
Test the LifeOS MCP server by simulating Claude Code's protocol.

This tests the actual MCP protocol, not just the underlying API.
Run this to verify the MCP server will work when Claude Code connects.

Usage:
    python scripts/test_mcp.py
    python scripts/test_mcp.py --verbose
"""
import json
import subprocess
import sys
from pathlib import Path

VERBOSE = "--verbose" in sys.argv or "-v" in sys.argv
MCP_SERVER = Path(__file__).parent.parent / "mcp_server.py"


def send_request(proc, method: str, params: dict = None, request_id: int = 1) -> dict:
    """Send a JSON-RPC request to the MCP server and get response."""
    request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params:
        request["params"] = params

    request_str = json.dumps(request) + "\n"
    if VERBOSE:
        print(f"  → {method}", end="", flush=True)

    proc.stdin.write(request_str)
    proc.stdin.flush()

    response_line = proc.stdout.readline()
    if not response_line:
        raise Exception("No response from MCP server")

    response = json.loads(response_line)
    if VERBOSE:
        if "error" in response:
            print(f" ❌ {response['error'].get('message', 'Unknown error')}")
        else:
            print(" ✓")

    return response


def test_mcp_server():
    """Run full MCP protocol test suite."""
    print("=" * 60)
    print("LifeOS MCP Server Test Suite")
    print("=" * 60)
    print()

    # Start the MCP server
    print("Starting MCP server...")
    proc = subprocess.Popen(
        [sys.executable, str(MCP_SERVER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    try:
        results = {}
        request_id = 1

        # 1. Initialize
        print("\n[1/4] Testing MCP Protocol...")
        resp = send_request(proc, "initialize", request_id=request_id)
        request_id += 1
        if "result" in resp and resp["result"].get("protocolVersion"):
            results["initialize"] = "✓"
            print(f"  Protocol version: {resp['result']['protocolVersion']}")
        else:
            results["initialize"] = "✗"
            print(f"  ERROR: {resp.get('error', 'No result')}")

        # Send initialized notification
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()

        # 2. List tools
        print("\n[2/4] Listing available tools...")
        resp = send_request(proc, "tools/list", request_id=request_id)
        request_id += 1
        if "result" in resp and "tools" in resp["result"]:
            tools = resp["result"]["tools"]
            results["tools_list"] = "✓"
            print(f"  Found {len(tools)} tools:")
            for tool in tools:
                print(f"    - {tool['name']}")
        else:
            results["tools_list"] = "✗"
            print(f"  ERROR: {resp.get('error', 'No tools')}")
            tools = []

        # 3. Test each tool
        print("\n[3/4] Testing each tool...")
        tool_tests = {
            "lifeos_health": {},
            "lifeos_search": {"query": "test", "top_k": 1},
            "lifeos_ask": {"question": "test query"},
            "lifeos_calendar_upcoming": {"days": 1},
            "lifeos_calendar_search": {"q": "meeting"},
            "lifeos_gmail_search": {"q": "in:inbox"},
            "lifeos_drive_search": {"q": "test", "account": "personal"},
            "lifeos_people_search": {"q": "a"},
            "lifeos_conversations_list": {"limit": 1},
            "lifeos_memories_create": None,  # Skip - don't create test memories
            "lifeos_memories_search": {"query": "test"},
        }

        tool_results = {}
        for tool_name, args in tool_tests.items():
            if args is None:
                tool_results[tool_name] = "skipped"
                if VERBOSE:
                    print(f"  ⊘ {tool_name} (skipped)")
                continue

            resp = send_request(
                proc,
                "tools/call",
                params={"name": tool_name, "arguments": args},
                request_id=request_id
            )
            request_id += 1

            if "result" in resp:
                content = resp["result"].get("content", [])
                if content and content[0].get("type") == "text":
                    text = content[0].get("text", "")
                    if "Error" in text or "error" in text.lower():
                        tool_results[tool_name] = f"✗ {text[:50]}"
                    else:
                        tool_results[tool_name] = "✓"
                else:
                    tool_results[tool_name] = "✓ (empty)"
            else:
                error = resp.get("error", {}).get("message", "Unknown error")
                tool_results[tool_name] = f"✗ {error[:50]}"

        results["tool_tests"] = tool_results

        # 4. Summary
        print("\n[4/4] Results Summary")
        print("-" * 40)

        passed = 0
        failed = 0
        skipped = 0

        for tool, status in tool_results.items():
            if status == "✓" or status == "✓ (empty)":
                passed += 1
                print(f"  ✓ {tool}")
            elif status == "skipped":
                skipped += 1
                print(f"  ⊘ {tool} (skipped)")
            else:
                failed += 1
                print(f"  ✗ {tool}: {status[2:]}")

        print("-" * 40)
        print(f"  Passed: {passed}, Failed: {failed}, Skipped: {skipped}")

        if failed == 0:
            print("\n✅ All MCP tools working correctly!")
            return 0
        else:
            print(f"\n❌ {failed} tool(s) failing")
            return 1

    finally:
        proc.terminate()
        proc.wait()


if __name__ == "__main__":
    sys.exit(test_mcp_server())

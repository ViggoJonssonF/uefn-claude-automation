"""Minimal client for UEFN's native MCP server (http://127.0.0.1:8000/mcp, streamable HTTP).

Lets scripts call Epic's toolsets without an agent in the loop:

    from uefn_mcp_client import UefnMcp
    mcp = UefnMcp()
    mcp.call("ValkyrieToolset.SessionToolset", "GetSessionStatus")   # -> {"returnValue": "Connected"}

CLI:
    python uefn_mcp_client.py <toolset> <tool> ['{"json": "args"}']
"""

import json
import sys
import urllib.request

URL = "http://127.0.0.1:8000/mcp"
PROTOCOL = "2025-06-18"


class McpError(RuntimeError):
    pass


class UefnMcp:
    def __init__(self, url=URL, timeout=600):
        self.url = url
        self.timeout = timeout
        self.session_id = None
        self._next_id = 1
        self._initialize()

    def _post(self, payload, expect_reply=True):
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": PROTOCOL}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                self.session_id = sid
            body = resp.read().decode("utf-8", errors="replace")
            ctype = resp.headers.get("Content-Type", "")
        if not expect_reply or not body.strip():
            return None
        if "text/event-stream" in ctype:
            # Last JSON-RPC message carried in a `data:` line is the reply.
            messages = [json.loads(line[5:].strip()) for line in body.splitlines()
                        if line.startswith("data:") and line[5:].strip()]
            replies = [m for m in messages if m.get("id") == payload.get("id")]
            return replies[-1] if replies else (messages[-1] if messages else None)
        return json.loads(body)

    def _request(self, method, params=None):
        msg = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params or {}}
        self._next_id += 1
        reply = self._post(msg)
        if reply is None:
            raise McpError(f"no reply to {method}")
        if "error" in reply:
            raise McpError(f"{method}: {reply['error']}")
        return reply.get("result")

    def _initialize(self):
        self._request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                     "clientInfo": {"name": "uefn-tools", "version": "1.0"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_reply=False)

    def call(self, toolset, tool, arguments=None):
        """Call a toolset tool. Returns the decoded JSON result; raises McpError on tool errors."""
        result = self._request("tools/call", {"name": "call_tool", "arguments": {
            "toolset_name": toolset, "tool_name": tool, "arguments": arguments or {}}})
        text = "".join(c.get("text", "") for c in (result or {}).get("content", [])
                       if c.get("type") == "text")
        if (result or {}).get("isError"):
            raise McpError(f"{toolset}.{tool}: {text}")
        try:
            return json.loads(text) if text else None
        except json.JSONDecodeError:
            return text


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    print(json.dumps(UefnMcp().call(sys.argv[1], sys.argv[2], args), indent=1, ensure_ascii=False))

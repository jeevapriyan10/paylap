"""Model Context Protocol (MCP) Server for PayLap.

Exposes PayLap settlement capabilities as standardized tools to AI agents
(Claude, Gemini, Cursor, Antigravity, etc.) using JSON-RPC 2.0 over stdio.
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional

from paylap.client import PayLap
from paylap.exceptions import PayLapError


def get_tools_manifest() -> List[Dict[str, Any]]:
    """Return JSON Schema descriptions for all exposed MCP tools."""
    return [
        {
            "name": "paylap_create_contract",
            "description": "Create a new verified-delivery settlement contract with milestones.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Title of the contract"},
                    "milestones": {
                        "type": "array",
                        "description": "List of milestones with verification rules and tests",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "amount_usd": {"type": "string", "description": "Amount in USD (e.g. '25.00')"},
                                "public_tests": {"type": "string", "description": "Public test assertions"},
                                "hidden_tests": {
                                    "type": "string",
                                    "description": "Hidden test assertions for anti-cheat",
                                },
                                "verifier_type": {"type": "string", "default": "python_code"},
                            },
                            "required": ["title", "amount_usd", "public_tests"],
                        },
                    },
                    "worker_email": {"type": "string", "description": "Worker PayPal email for payout"},
                    "environment": {
                        "type": "string",
                        "enum": ["simulated", "sandbox", "live"],
                        "default": "simulated",
                        "description": "Settlement environment",
                    },
                    "deadline_days": {"type": "integer", "default": 14},
                },
                "required": ["title", "milestones"],
            },
        },
        {
            "name": "paylap_get_contract",
            "description": "Retrieve status, milestones, and metadata for a PayLap contract.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "contract_id": {"type": "string", "description": "Prefixed ID (ctr_...)"},
                },
                "required": ["contract_id"],
            },
        },
        {
            "name": "paylap_fund_contract",
            "description": "Authorize customer funds for a contract (moves status to FUNDED).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "contract_id": {"type": "string", "description": "Prefixed ID (ctr_...)"},
                },
                "required": ["contract_id"],
            },
        },
        {
            "name": "paylap_submit_milestone",
            "description": "Submit deliverable code/data for milestone verification and settlement.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "contract_id": {"type": "string", "description": "Prefixed ID (ctr_...)"},
                    "sequence": {"type": "integer", "description": "1-based milestone sequence number"},
                    "submission_code": {"type": "string", "description": "Source code or deliverable solution"},
                    "worker_id": {"type": "string", "description": "Worker identifier"},
                    "explanation": {"type": "string", "description": "Optional notes on implementation"},
                },
                "required": ["contract_id", "sequence", "submission_code"],
            },
        },
        {
            "name": "paylap_verify_receipt",
            "description": "Verify digital receipt signature offline or inspect a public receipt by share token.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "share_token": {"type": "string", "description": "Public share token (shr_...)"},
                    "receipt_data": {"type": "object", "description": "Complete receipt JSON for offline verification"},
                },
            },
        },
        {
            "name": "paylap_get_worker_stats",
            "description": "Retrieve completion rate and reputation stats for a worker.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "worker_id": {"type": "string", "description": "Worker ID"},
                },
                "required": ["worker_id"],
            },
        },
    ]


class MCPServer:
    """Standard JSON-RPC 2.0 MCP Server for PayLap."""

    def __init__(self, client: Optional[PayLap] = None):
        if client:
            self.client = client
        else:
            api_key = os.environ.get("PAYLAP_API_KEY")
            base_url = os.environ.get("PAYLAP_BASE_URL", "http://127.0.0.1:8000")
            self.client = PayLap(api_key=api_key, base_url=base_url)

    def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single JSON-RPC 2.0 request."""
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "paylap-mcp", "version": "0.3.0"},
                },
            }

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": get_tools_manifest()},
            }

        elif method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})
            try:
                tool_result = self.execute_tool(tool_name, args)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(tool_result, indent=2),
                            }
                        ]
                    },
                }
            except PayLapError as ple:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "isError": True,
                        "content": [{"type": "text", "text": f"PayLap Error: {ple.message}"}],
                    },
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "isError": True,
                        "content": [{"type": "text", "text": f"Execution error: {str(e)}"}],
                    },
                }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method '{method}' not found"},
        }

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        """Route tool call to the PayLap client."""
        if tool_name == "paylap_create_contract":
            return self.client.create_contract(
                title=args["title"],
                milestones=args["milestones"],
                worker_email=args.get("worker_email"),
                environment=args.get("environment", "simulated"),
                deadline_days=args.get("deadline_days", 14),
            )
        elif tool_name == "paylap_get_contract":
            return self.client.get_contract(args["contract_id"])
        elif tool_name == "paylap_fund_contract":
            return self.client.fund_contract(args["contract_id"])
        elif tool_name == "paylap_submit_milestone":
            return self.client.submit_milestone(
                contract_id=args["contract_id"],
                sequence=args["sequence"],
                submission_code=args["submission_code"],
                worker_id=args.get("worker_id"),
                explanation=args.get("explanation"),
            )
        elif tool_name == "paylap_verify_receipt":
            if "receipt_data" in args:
                valid = self.client.verify_receipt_offline(args["receipt_data"])
                return {"valid": valid, "verification_mode": "offline_ed25519"}
            elif "share_token" in args:
                return self.client.verify_public_receipt(args["share_token"])
            raise ValueError("Either 'share_token' or 'receipt_data' is required.")
        elif tool_name == "paylap_get_worker_stats":
            return self.client.get_worker_stats(args["worker_id"])
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

    def run_stdio(self) -> None:
        """Read newline-delimited JSON-RPC requests from sys.stdin and write responses to sys.stdout."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                resp = self.handle_request(req)
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
            except Exception as e:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {str(e)}"},
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()


def main() -> None:
    server = MCPServer()
    server.run_stdio()


if __name__ == "__main__":
    main()

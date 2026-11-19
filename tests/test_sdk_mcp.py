"""Unit and integration tests for PayLap Python SDK and MCP Server."""

import base64
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# Add sdk/python to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sdk", "python")))

from paylap.client import PayLap, canonicalize_json, verify_receipt_data
from paylap.exceptions import (
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    ReceiptVerificationError,
    SpendPolicyError,
)
from paylap.mcp import MCPServer, get_tools_manifest


def generate_valid_test_receipt():
    """Generate a cryptographically valid test receipt for testing verify_receipt_data."""
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_b64 = base64.b64encode(pub.public_bytes_raw()).decode("utf-8")

    payload = {
        "receipt_id": "rcpt_test1234567890",
        "version": "2.0",
        "contract_id": "ctr_test1234567890",
        "milestone_id": "mst_test1234567890",
        "amount_cents": 2500,
        "currency": "USD",
        "status": "COMPLETED",
        "signer_public_key": pub_b64,
    }
    canonical_bytes = canonicalize_json(payload)
    sig = priv.sign(canonical_bytes)
    sig_b64 = base64.b64encode(sig).decode("utf-8")

    payload["signature"] = sig_b64
    return payload


def test_offline_receipt_verification():
    receipt = generate_valid_test_receipt()
    assert verify_receipt_data(receipt) is True

    # Tamper with content
    tampered = dict(receipt)
    tampered["amount_cents"] = 999999
    with pytest.raises(ReceiptVerificationError):
        verify_receipt_data(tampered)

    # Tamper with signature
    tampered_sig = dict(receipt)
    tampered_sig["signature"] = base64.b64encode(b"invalid_signature_bytes_32_chars!32_chars!").decode("utf-8")
    with pytest.raises(ReceiptVerificationError):
        verify_receipt_data(tampered_sig)


def test_sdk_exception_mapping():
    client = PayLap(api_key="bad_key")
    with patch.object(client._client, "request") as mock_request:
        # 401 Unauthorized
        mock_resp = MagicMock()
        mock_resp.is_success = False
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"error": {"message": "Invalid API key"}}
        mock_request.return_value = mock_resp

        with pytest.raises(AuthenticationError, match="Invalid API key"):
            client.create_contract(title="Test", milestones=[])

        # 403 Forbidden
        mock_resp.status_code = 403
        mock_resp.json.return_value = {"error": {"message": "Scope missing"}}
        with pytest.raises(AuthorizationError, match="Scope missing"):
            client.create_contract(title="Test", milestones=[])

        # 404 Not Found
        mock_resp.status_code = 404
        mock_resp.json.return_value = {"error": {"message": "Contract not found"}}
        with pytest.raises(NotFoundError, match="Contract not found"):
            client.get_contract("ctr_missing")

        # 422 Spend Policy
        mock_resp.status_code = 422
        mock_resp.json.return_value = {"error": {"message": "Contract exceeds org spend policy budget"}}
        with pytest.raises(SpendPolicyError):
            client.create_contract(title="Test", milestones=[])


def test_mcp_tools_manifest():
    tools = get_tools_manifest()
    assert len(tools) >= 5
    names = [t["name"] for t in tools]
    assert "paylap_create_contract" in names
    assert "paylap_get_contract" in names
    assert "paylap_submit_milestone" in names
    assert "paylap_verify_receipt" in names


def test_mcp_server_initialize_and_tools():
    server = MCPServer(client=MagicMock())

    # initialize
    init_req = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    init_res = server.handle_request(init_req)
    assert init_res["result"]["serverInfo"]["name"] == "paylap-mcp"

    # tools/list
    list_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    list_res = server.handle_request(list_req)
    assert len(list_res["result"]["tools"]) >= 5

    # unknown method
    bad_req = {"jsonrpc": "2.0", "id": 3, "method": "unknown_method"}
    bad_res = server.handle_request(bad_req)
    assert bad_res["error"]["code"] == -32601


def test_mcp_server_tool_calls():
    mock_client = MagicMock()
    mock_client.create_contract.return_value = {"id": "ctr_123", "title": "MCP Contract"}
    mock_client.get_contract.return_value = {"id": "ctr_123", "status": "FUNDED"}
    mock_client.verify_receipt_offline.return_value = True

    server = MCPServer(client=mock_client)

    # Call create_contract
    call_req = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {
            "name": "paylap_create_contract",
            "arguments": {
                "title": "MCP Contract",
                "milestones": [{"title": "M1", "amount_usd": "10.00", "public_tests": "assert True"}],
            },
        },
    }
    call_res = server.handle_request(call_req)
    content = json.loads(call_res["result"]["content"][0]["text"])
    assert content["id"] == "ctr_123"
    mock_client.create_contract.assert_called_once()

    # Call verify_receipt
    receipt = generate_valid_test_receipt()
    verify_req = {
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {
            "name": "paylap_verify_receipt",
            "arguments": {"receipt_data": receipt},
        },
    }
    verify_res = server.handle_request(verify_req)
    v_content = json.loads(verify_res["result"]["content"][0]["text"])
    assert v_content["valid"] is True

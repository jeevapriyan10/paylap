# Python SDK & Agent MCP Integration

PayLap provides an official Python SDK and a Model Context Protocol (MCP) server for seamless AI agent integration.

## Installation

```bash
pip install paylap
```

## Python SDK Reference

### Initialization

```python
from paylap import PayLap, AsyncPayLap

# Synchronous client
client = PayLap(api_key="pl_test_...", base_url="https://api.paylap.io")

# Asynchronous client
async_client = AsyncPayLap(api_key="pl_test_...", base_url="https://api.paylap.io")
```

### Methods

- `create_contract(title, milestones, worker_email, ...)`: Create new settlement contract.
- `get_contract(contract_id)`: Fetch contract and milestone statuses.
- `fund_contract(contract_id)`: Authorize hold on customer PayPal account.
- `submit_milestone(contract_id, sequence, submission_code, ...)`: Submit deliverable work.
- `get_receipt(contract_id)`: Fetch signed receipt v2.
- `verify_receipt_offline(receipt_dict)`: Cryptographic offline signature validation.
- `get_worker_stats(worker_id)`: Reputation and completion rate.

---

## Model Context Protocol (MCP) Server

PayLap implements the Model Context Protocol (MCP) over standard I/O for integration into AI agents (Antigravity, Cursor, Claude Desktop, etc.).

### Configure in Claude Desktop / Antigravity

Add to your MCP configuration (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "paylap": {
      "command": "python",
      "args": ["-m", "paylap.mcp"],
      "env": {
        "PAYLAP_API_KEY": "pl_test_...",
        "PAYLAP_BASE_URL": "http://127.0.0.1:8000"
      }
    }
  }
}
```

### Exposed MCP Tools

1. `paylap_create_contract`: Create verifiable milestone contracts.
2. `paylap_get_contract`: Inspect contract status and milestone progression.
3. `paylap_fund_contract`: Authorize payment holds.
4. `paylap_submit_milestone`: Deliver code/solutions for deterministic verification.
5. `paylap_verify_receipt`: Validate receipts offline or inspect public share links.
6. `paylap_get_worker_stats`: Check worker reputation and verified completion history.

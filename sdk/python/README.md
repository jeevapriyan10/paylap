# PayLap Python SDK

Official Python SDK and Model Context Protocol (MCP) server for PayLap — multi-tenant settlement engine for verified-delivery payment holds.

## Installation

```bash
pip install paylap
```

## Quickstart

```python
from paylap import PayLap

client = PayLap(api_key="pl_test_...", base_url="http://127.0.0.1:8000")

# Create a contract with verifiable milestones
contract = client.create_contract(
    title="Data Extraction Algorithm",
    worker_email="alice@worker.org",
    milestones=[
        {
            "title": "Parser Implementation",
            "amount_usd": "25.00",
            "public_tests": "def test_parse(): assert parse('123') == 123",
            "hidden_tests": "def test_hidden(): assert parse('-1') == -1",
        }
    ],
)

print(f"Created contract: {contract['id']}")
```

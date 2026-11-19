# Quickstart Guide

This guide walks you through launching PayLap, authenticating, and creating your first settlement contract.

## 1. Prerequisites

- Python 3.10+
- Docker & Docker Compose (or local PostgreSQL 16)
- Node.js 18+ (for building the frontend)

## 2. Start PostgreSQL

```bash
docker compose up -d postgres
```

This creates the databases `paylap` and `paylap_test`, alongside the `paylap_owner` (migration) and `paylap_app` (runtime NOBYPASSRLS) roles.

## 3. Seed Development Database

```bash
python -m app.cli seed
```

This initializes the schema via Alembic migrations and creates a development organization with:
- **Email**: `dev@paylap.local`
- **Password**: `Development1234!`
- **API Key**: `pl_test_devkey00000000_1234567890abcdef1234567890abcdef`

## 4. Run the API Server

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Visit `http://127.0.0.1:8000` to interact with the web interface.

## 5. Create a Contract via SDK

```python
from paylap import PayLap

client = PayLap(
    api_key="pl_test_devkey00000000_1234567890abcdef1234567890abcdef",
    base_url="http://127.0.0.1:8000",
)

contract = client.create_contract(
    title="String Reversal Function",
    worker_email="worker@example.com",
    environment="simulated",
    milestones=[
        {
            "title": "Reverse ASCII",
            "amount_usd": "10.00",
            "public_tests": "def test_ascii(): assert reverse('abc') == 'cba'",
            "hidden_tests": "def test_unicode(): assert reverse('🚀 hello') == 'olleh 🚀'",
            "verifier_type": "python_code",
        }
    ],
)

print(f"Contract ID: {contract['id']}")
```

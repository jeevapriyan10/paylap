import pytest
from app.verifiers import get_verifier, list_available_verifiers
from app.verifiers.base import VerificationResult
from fastapi.testclient import TestClient
from app.db import get_db
from app.main import app


class DummyMilestone:
    def __init__(self, public_tests="", hidden_tests=None, verifier_type="python_code", verifier_config=None):
        self.public_tests = public_tests
        self.hidden_tests = hidden_tests
        self.verifier_type = verifier_type
        self.verifier_config = verifier_config or {}


def test_list_and_get_verifiers():
    avail = list_available_verifiers()
    assert "python_code" in avail
    assert "json_data" in avail
    assert "text_rules" in avail

    v = get_verifier("python_code")
    assert v is not None

    with pytest.raises(ValueError):
        get_verifier("unsupported_type")


def test_python_code_public_and_hidden_pass():
    v = get_verifier("python_code")
    m = DummyMilestone(
        public_tests="from solution import add\ndef test_add(): assert add(1, 2) == 3",
        hidden_tests="from solution import add\ndef test_add_hidden(): assert add(10, 20) == 30",
    )
    res = v.verify(m, "def add(a, b):\n    return a + b\n")
    assert res.passed is True
    assert len(res.checks) == 2
    assert res.checks[0]["passed"] is True
    assert res.checks[1]["passed"] is True


def test_python_code_public_fail():
    v = get_verifier("python_code")
    m = DummyMilestone(
        public_tests="from solution import add\ndef test_add(): assert add(1, 2) == 3",
        hidden_tests="def test_hidden(): pass",
    )
    res = v.verify(m, "def add(a, b):\n    return a * b\n")
    assert res.passed is False
    assert res.checks[0]["name"] == "public_tests"
    assert res.checks[0]["passed"] is False
    assert "assert 2 == 3" in res.public_summary or "FAILED" in res.public_summary
    assert res.private_detail is None


def test_python_code_hidden_only_fail_leaks_nothing():
    secret_marker = "SUPER_SECRET_ASSERTION_VALUE_987654"
    v = get_verifier("python_code")
    m = DummyMilestone(
        public_tests="from solution import f\ndef test_pub(): assert f(1) == 2",
        hidden_tests=f"from solution import f\ndef test_h1(): assert f(2) == 4\ndef test_h2(): assert f(3) == '{secret_marker}'",
    )
    # Solution passes public (1->2), but fails hidden test 2
    res = v.verify(m, "def f(x):\n    return x * 2\n")
    assert res.passed is False
    assert "1 of 2 hidden checks failed" in res.public_summary
    # Ensure confidential marker is NOT in public summary!
    assert secret_marker not in res.public_summary
    assert "test_h2" not in res.public_summary
    # But it is in private_detail
    assert res.private_detail is not None
    assert secret_marker in res.private_detail


def test_json_data_verifier_schema_pass_and_fail():
    v = get_verifier("json_data")
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "score": {"type": "integer", "minimum": 0},
        },
        "required": ["name", "score"],
    }
    m = DummyMilestone(verifier_config={"schema": schema})

    # 1. Invalid JSON syntax
    bad_syntax = "{name: 'alice'}"
    res1 = v.verify(m, bad_syntax)
    assert res1.passed is False
    assert "Invalid JSON" in res1.public_summary

    # 2. Schema violation
    bad_schema = '{"name": "Alice", "score": -5}'
    res2 = v.verify(m, bad_schema)
    assert res2.passed is False
    assert "Schema Validation Error" in res2.public_summary

    # 3. Valid JSON matching schema
    good_json = '{"name": "Alice", "score": 95}'
    res3 = v.verify(m, good_json)
    assert res3.passed is True


def test_json_data_verifier_hidden_tests():
    v = get_verifier("json_data")
    schema = {"type": "object", "properties": {"items": {"type": "array"}}}
    hidden = """
def test_hidden_count(data):
    assert len(data['items']) == 3

def test_hidden_sum(data):
    assert sum(data['items']) == 100
"""
    m = DummyMilestone(verifier_config={"schema": schema, "hidden_tests": hidden})

    # Passes schema, but sum is 99 (fails 1 hidden check)
    submission = '{"items": [33, 33, 33]}'
    res = v.verify(m, submission)
    assert res.passed is False
    assert "1 of 2 hidden checks failed" in res.public_summary
    assert res.private_detail is not None


def test_text_rules_verifier():
    v = get_verifier("text_rules")
    config = {
        "min_words": 5,
        "max_words": 15,
        "required_patterns": [r"AI", r"Escrow"],
        "forbidden_patterns": [r"hack", r"phish"],
    }
    m = DummyMilestone(verifier_config=config)

    # 1. Too short
    res1 = v.verify(m, "AI Escrow rules.")
    assert res1.passed is False
    assert "less than minimum" in res1.public_summary

    # 2. Missing required pattern
    res2 = v.verify(m, "This is a great payment escrow system with six words.")
    assert res2.passed is False
    assert "Required pattern 'AI' not found" in res2.public_summary

    # 3. Contains forbidden pattern
    res3 = v.verify(m, "PayLap is an AI Escrow service to hack things.")
    assert res3.passed is False
    assert "Forbidden pattern 'hack' was matched" in res3.public_summary

    # 4. Valid text passing all rules
    valid_text = "PayLap is a secure AI Escrow platform for autonomous agents."
    res4 = v.verify(m, valid_text)
    assert res4.passed is True


def test_hidden_test_sentinel_leak_scan(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        sentinel = "CONFIDENTIAL_SENTINEL_SECRET_TOKEN_42"
        payload = {
            "title": "Confidential Contract",
            "buyer_id": "b-secret",
            "worker_id": "w-secret",
            "worker_email": "w@example.com",
            "milestones": [
                {
                    "title": "M1",
                    "amount": "5.00",
                    "spec": "spec",
                    "public_tests": "def test_ok(): pass",
                    "hidden_tests": f"def test_secret(): assert 1 == 1, '{sentinel}'",
                }
            ],
        }

        # Contract creation
        create_res = client.post("/api/contracts", json=payload)
        assert create_res.status_code == 201
        assert sentinel not in create_res.text
        contract_id = create_res.json()["id"]

        # Detail endpoint
        detail_res = client.get(f"/api/contracts/{contract_id}")
        assert detail_res.status_code == 200
        assert sentinel not in detail_res.text

        # List endpoint
        list_res = client.get("/api/contracts")
        assert list_res.status_code == 200
        assert sentinel not in list_res.text

        # Events endpoint
        events_res = client.get("/api/events")
        assert events_res.status_code == 200
        assert sentinel not in events_res.text

        # Health endpoint
        health_res = client.get("/api/health")
        assert health_res.status_code == 200
        assert sentinel not in health_res.text
        assert "python_code" in health_res.json()["verifiers"]

    app.dependency_overrides.clear()

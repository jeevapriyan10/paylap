import time

import pytest

from app.arena import execute_scenario


def test_arena_scenarios_listing(client):
    res = client.get("/v1/arena/scenarios")
    assert res.status_code == 200
    scenarios = res.json()
    assert len(scenarios) == 6
    keys = {s["key"] for s in scenarios}
    assert keys == {"honest", "buggy", "cheater", "malicious", "injector", "overspender"}


@pytest.mark.parametrize("scenario_key", ["honest", "buggy", "cheater", "malicious", "injector", "overspender"])
def test_arena_individual_scenarios(client, scenario_key):
    outcome = execute_scenario(scenario_key, client=client)
    assert outcome["passed"] is True, f"Scenario '{scenario_key}' failed: {outcome}"


def test_arena_full_run_endpoint(client):
    res = client.post("/v1/arena/run", json={"scenario": "all", "sync": True})
    assert res.status_code == 200
    data = res.json()
    assert data["scenarios_count"] == 6
    assert data["scenarios_passed"] == 6
    assert data["all_passed"] is True
    assert data["ledger_chain_valid"] is True


def test_arena_async_run_and_status(client):
    # Launch async run
    res = client.post("/v1/arena/run", json={"scenario": "honest", "sync": False})
    assert res.status_code == 200
    data = res.json()
    run_id = data["run_id"]
    assert data["status"] == "running"

    # Poll status up to 15 seconds
    completed = False
    for _ in range(30):
        time.sleep(0.5)
        poll = client.get(f"/v1/arena/runs/{run_id}")
        assert poll.status_code == 200
        poll_data = poll.json()
        if poll_data["status"] == "completed":
            completed = True
            assert poll_data["scenarios_passed"] == 1
            break

    assert completed is True

#!/usr/bin/env python
"""
PayLap Red Team Arena CLI
Runs adversarial scenarios against PayLap defense-in-depth gates and verifies ledger integrity.
Usage:
    python scripts/arena_cli.py
    python scripts/arena_cli.py --scenario malicious
    python scripts/arena_cli.py --url http://127.0.0.1:8000
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from app.arena import SCENARIOS, run_arena


def format_table(rows: list, headers: list) -> str:
    col_widths = [len(h) for h in headers]
    for row in rows:
        for idx, val in enumerate(row):
            col_widths[idx] = max(col_widths[idx], len(str(val)))

    header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    separator = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
    row_lines = [
        " | ".join(str(val).ljust(col_widths[i]) for i, val in enumerate(row))
        for row in rows
    ]
    return f"\n{header_line}\n{separator}\n" + "\n".join(row_lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="PayLap Red Team Arena CLI")
    parser.add_argument("--scenario", "-s", default="all", help="Scenario to run: honest, buggy, cheater, malicious, injector, overspender, all")
    parser.add_argument("--url", "-u", default=None, help="PayLap base URL if testing remote/running server (e.g. http://localhost:8000)")
    parser.add_argument("--worker-source", default="canned", choices=["canned", "gemini", "auto"], help="Source for worker code submissions")
    parser.add_argument("--arbiter-mode", default="mock", choices=["mock", "gemini", "auto", "off"], help="Arbiter execution mode")
    args = parser.parse_args()

    from app.config import settings
    settings.ARENA_WORKER_SOURCE = args.worker_source
    settings.PAYLAP_ARBITER_MODE = args.arbiter_mode

    print("\n" + "=" * 70, flush=True)
    print("  PayLap Red Team Arena — Adversarial Gate & Invariant Verification", flush=True)
    print(f"  Worker Source: {args.worker_source} | Arbiter Mode: {args.arbiter_mode}", flush=True)
    print("=" * 70, flush=True)

    if args.url:
        print(f"Connecting to running server: {args.url}")
        target_scenario = None if args.scenario == "all" else args.scenario
        payload = {"scenario": target_scenario, "sync": True}
        try:
            with httpx.Client(timeout=30.0) as client:
                res = client.post(f"{args.url.rstrip('/')}/api/arena/run", json=payload)
                if res.status_code != 200:
                    print(f"Error: Server returned status {res.status_code}: {res.text}")
                    sys.exit(1)
                data = res.json()
        except Exception as exc:
            print(f"Error connecting to {args.url}: {exc}")
            sys.exit(1)
    else:
        print("Running in-process evaluation...")
        scenarios = None if args.scenario == "all" else [args.scenario]
        data = run_arena(scenarios=scenarios)

    headers = ["Scenario", "Title", "Expected", "Actual", "Defense", "Elapsed (ms)"]
    rows = []
    for s in data["scenarios"]:
        defense_status = "PASS (OK)" if s.get("passed") else "FAIL (BREACH)"
        rows.append([
            s.get("scenario"),
            s.get("title", ""),
            s.get("expected_outcome", ""),
            s.get("actual_outcome", ""),
            defense_status,
            f"{s.get('elapsed_ms', 0)}ms",
        ])

    print(format_table(rows, headers))

    passed_count = data.get("scenarios_passed", 0)
    total_count = data.get("scenarios_count", 0)
    ledger_valid = data.get("ledger_chain_valid", False)

    print("-" * 70)
    print(f"Result: {passed_count}/{total_count} attack scenarios verified.")
    print(f"Ledger Chain Integrity: {'VALID (Untampered)' if ledger_valid else 'INVALID / BROKEN'}")
    print("=" * 70 + "\n")

    if not data.get("all_passed"):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()

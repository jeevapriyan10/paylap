#!/usr/bin/env python3
"""
PayLap Live PayPal Verification & Smoke Test Script.

Exercises PayPal's live/sandbox money path directly through PayPalClient:
- OAuth2 token fetching
- AUTHORIZE order creation
- Buyer approval interaction
- Authorization capture (partial captures & final_capture flags)
- Payouts dispatch and status polling
- Authorization voiding

Usage:
  python scripts/smoke_paypal.py --scenario settle
  python scripts/smoke_paypal.py --scenario void
"""

import argparse
from datetime import datetime, timezone
import json
import os
import sys
import time

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings
from app.services.paypal_client import PayPalClient
from app.services.paypal_base import PayPalError


def print_step(name: str, passed: bool, detail: str = ""):
    status_tag = "\033[92m[PASS]\033[0m" if passed else "\033[91m[FAIL]\033[0m"
    detail_str = f" - {detail}" if detail else ""
    print(f" {status_tag} {name}{detail_str}")


def run_smoke_test(scenario: str):
    print("=" * 65)
    print(f" PayLap Live PayPal Smoke Test -- Scenario: {scenario.upper()}")
    print("=" * 65)

    if not settings.PAYPAL_CLIENT_ID or not settings.PAYPAL_CLIENT_SECRET:
        print("\n\033[91mERROR: PayPal credentials not configured.\033[0m")
        print("Please configure PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env\n")
        sys.exit(1)

    worker_email = settings.PAYPAL_WORKER_EMAIL or "worker-sandbox@example.com"
    print(f"PayPal Endpoint   : {settings.PAYPAL_BASE_URL}")
    print(f"PayPal Worker Email: {worker_email}\n")

    client = PayPalClient(
        client_id=settings.PAYPAL_CLIENT_ID,
        client_secret=settings.PAYPAL_CLIENT_SECRET,
        base_url=settings.PAYPAL_BASE_URL,
    )

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scenario": scenario,
        "base_url": settings.PAYPAL_BASE_URL,
        "worker_email": worker_email,
        "steps": [],
        "overall_status": "PENDING"
    }

    def record_step(name: str, passed: bool, data: dict = None, error: str = None):
        step_entry = {
            "name": name,
            "passed": passed,
            "data": data or {},
            "error": error
        }
        report["steps"].append(step_entry)
        detail_msg = json.dumps(data) if data else (error or "")
        print_step(name, passed, detail_msg)
        return passed

    all_passed = True

    try:
        # Step 1: OAuth2 Access Token
        print("\n1. Fetching OAuth2 Client Credentials Token...")
        try:
            token = client._get_access_token()
            record_step("OAuth2 Token", True, {"token_preview": token[:10] + "..."})
        except Exception as e:
            all_passed = False
            record_step("OAuth2 Token", False, error=str(e))
            raise

        if scenario == "settle":
            # Step 2: Create AUTHORIZE order for 5.00 USD
            print("\n2. Creating Escrow Order (intent=AUTHORIZE, 5.00 USD)...")
            contract_id = f"smoke-c-{int(time.time())}"
            try:
                order_res = client.create_escrow_order(
                    contract_id=contract_id,
                    amount_cents=500,
                    return_url=f"{settings.PAYLAP_PUBLIC_URL}/api/contracts/{contract_id}/funding/return",
                    cancel_url=f"{settings.PAYLAP_PUBLIC_URL}/api/contracts/{contract_id}/funding/cancel",
                    request_id=f"order-{contract_id}",
                )
                order_id = order_res["order_id"]
                approve_url = order_res["approve_url"]
                record_step("Create Order", True, {"order_id": order_id, "approve_url": approve_url})
            except Exception as e:
                all_passed = False
                record_step("Create Order", False, error=str(e))
                raise

            # Step 3: Interactive approval prompt
            print("\n" + "#" * 65)
            print(" ACTION REQUIRED: Buyer Approval")
            print(f" Please open this URL in your browser to approve the hold:\n {approve_url}")
            print("#" * 65)
            input("\nPress [Enter] after approving the authorization in sandbox PayPal...")

            # Step 4: Authorize the order
            print("\n3. Authorizing Order...")
            try:
                auth_res = client.authorize_order(order_id=order_id, request_id=f"auth-{contract_id}")
                auth_id = auth_res["authorization_id"]
                record_step("Authorize Order", True, {"authorization_id": auth_id, "status": auth_res["status"]})
            except Exception as e:
                all_passed = False
                record_step("Authorize Order", False, error=str(e))
                raise

            # Step 5: Partial-capture 2.00 USD (final_capture=False)
            print("\n4. Partial Capture #1: 2.00 USD (final_capture=False)...")
            try:
                cap1_res = client.capture(
                    authorization_id=auth_id,
                    amount_cents=200,
                    final_capture=False,
                    request_id=f"cap1-{contract_id}"
                )
                record_step("Capture #1 (2.00 USD)", True, {"capture_id": cap1_res["capture_id"], "status": cap1_res["status"]})
            except Exception as e:
                all_passed = False
                record_step("Capture #1 (2.00 USD)", False, error=str(e))
                print(f" Note: Capture failed: {e}")

            # Step 6: Send 2.00 USD payout and poll status
            print("\n5. Sending 2.00 USD Payout...")
            payout1_id = None
            try:
                payout1_res = client.send_payout(
                    recipient_email=worker_email,
                    amount_cents=200,
                    request_id=f"payout1-{contract_id}",
                    note="Smoke test milestone 1 payout"
                )
                payout1_id = payout1_res.get("payout_batch_id")
                record_step("Send Payout #1", True, {"payout_batch_id": payout1_id, "status": payout1_res.get("status")})
            except Exception as e:
                all_passed = False
                record_step("Send Payout #1", False, error=str(e))

            if payout1_id:
                print("   Polling payout status (up to 30s)...")
                for _ in range(10):
                    time.sleep(3)
                    try:
                        st = client.get_payout_status(payout1_id)
                        batch_st = st.get("status")
                        if batch_st in ("SUCCESS", "DENIED", "CANCELED"):
                            print(f"   Payout status reached: {batch_st}")
                            break
                    except Exception:
                        pass

            # Step 7: Partial-capture 1.00 USD (final_capture=False)
            print("\n6. Partial Capture #2: 1.00 USD (final_capture=False)...")
            try:
                cap2_res = client.capture(
                    authorization_id=auth_id,
                    amount_cents=100,
                    final_capture=False,
                    request_id=f"cap2-{contract_id}"
                )
                record_step("Capture #2 (1.00 USD)", True, {"capture_id": cap2_res["capture_id"], "status": cap2_res["status"]})
            except Exception as e:
                all_passed = False
                record_step("Capture #2 (1.00 USD)", False, error=str(e))

            # Step 8: Send 1.00 USD payout
            print("\n7. Sending 1.00 USD Payout...")
            try:
                payout2_res = client.send_payout(
                    recipient_email=worker_email,
                    amount_cents=100,
                    request_id=f"payout2-{contract_id}",
                    note="Smoke test milestone 2 payout"
                )
                record_step("Send Payout #2", True, {"payout_batch_id": payout2_res.get("payout_batch_id")})
            except Exception as e:
                all_passed = False
                record_step("Send Payout #2", False, error=str(e))

            # Step 9: Void remaining authorization hold
            print("\n8. Voiding Remaining Authorization...")
            try:
                void_res = client.void_authorization(
                    authorization_id=auth_id,
                    request_id=f"void-{contract_id}"
                )
                record_step("Void Remaining Authorization", True, {"status": void_res.get("status")})
            except Exception as e:
                all_passed = False
                record_step("Void Remaining Authorization", False, error=str(e))
                print(f" Note: Void after partial capture outcome: {e}")

        elif scenario == "void":
            # Void scenario: 3.00 USD order, authorize, void with no capture
            print("\n2. Creating Escrow Order (intent=AUTHORIZE, 3.00 USD)...")
            contract_id = f"smoke-void-{int(time.time())}"
            try:
                order_res = client.create_escrow_order(
                    contract_id=contract_id,
                    amount_cents=300,
                    return_url=f"{settings.PAYLAP_PUBLIC_URL}/api/contracts/{contract_id}/funding/return",
                    cancel_url=f"{settings.PAYLAP_PUBLIC_URL}/api/contracts/{contract_id}/funding/cancel",
                    request_id=f"order-{contract_id}",
                )
                order_id = order_res["order_id"]
                approve_url = order_res["approve_url"]
                record_step("Create Order", True, {"order_id": order_id, "approve_url": approve_url})
            except Exception as e:
                all_passed = False
                record_step("Create Order", False, error=str(e))
                raise

            print("\n" + "#" * 65)
            print(" ACTION REQUIRED: Buyer Approval")
            print(f" Please open this URL in your browser to approve the hold:\n {approve_url}")
            print("#" * 65)
            input("\nPress [Enter] after approving the authorization in sandbox PayPal...")

            print("\n3. Authorizing Order...")
            try:
                auth_res = client.authorize_order(order_id=order_id, request_id=f"auth-{contract_id}")
                auth_id = auth_res["authorization_id"]
                record_step("Authorize Order", True, {"authorization_id": auth_id, "status": auth_res["status"]})
            except Exception as e:
                all_passed = False
                record_step("Authorize Order", False, error=str(e))
                raise

            print("\n4. Voiding Full Authorization (no capture)...")
            try:
                void_res = client.void_authorization(
                    authorization_id=auth_id,
                    request_id=f"void-{contract_id}"
                )
                record_step("Void Full Authorization", True, {"status": void_res.get("status")})
            except Exception as e:
                all_passed = False
                record_step("Void Full Authorization", False, error=str(e))

    except Exception as exc:
        print(f"\n[!] Smoke test execution halted: {exc}")

    report["overall_status"] = "PASSED" if all_passed else "FAILED"

    # Write smoke_report.json (git-ignored)
    report_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "smoke_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 65)
    print(f" Smoke Test Report Written To: {report_path}")
    print(f" Overall Scenario Status     : {report['overall_status']}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PayLap Live PayPal Smoke Test")
    parser.add_argument(
        "--scenario",
        choices=["settle", "void"],
        default="settle",
        help="Test scenario: 'settle' (partial captures + payouts + void) or 'void' (pure void)",
    )
    args = parser.parse_args()
    run_smoke_test(args.scenario)

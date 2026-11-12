#!/usr/bin/env python3
"""
PayLap Gemini LLM Smoke Test Script.

Validates Gemini API key and model connectivity using the REST API:
- Verifies GEMINI_API_KEY is present
- Queries model with a tiny prompt and enforced JSON schema
- Prints PASS or FAIL with error details (never prints secrets)

Usage:
  python scripts/smoke_llm.py
"""

import os
import sys
import httpx

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings


def run_llm_smoke():
    print("=" * 60)
    print(" PayLap Gemini LLM Arbiter Smoke Test")
    print("=" * 60)

    api_key = settings.GEMINI_API_KEY
    model = settings.GEMINI_MODEL

    print(f"Model ID : {model}")
    print(f"Key Set  : {'YES (present)' if bool(api_key.strip()) else 'NO (empty)'}\n")

    if not api_key.strip():
        print("\033[91m[FAIL] GEMINI_API_KEY is missing or empty in .env\033[0m")
        print("Set GEMINI_API_KEY in your .env or environment to enable Gemini arbiter.")
        sys.exit(1)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json"
    }

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": "Ping test: respond with verdict ok and empty reasons."}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "verdict": {"type": "STRING", "enum": ["ok", "veto"]},
                    "reasons": {"type": "ARRAY", "items": {"type": "STRING"}}
                },
                "required": ["verdict", "reasons"]
            }
        }
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, json=payload, headers=headers)

        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get("candidates", [])
            text_out = candidates[0]["content"]["parts"][0]["text"]
            print(f"Gemini Response: {text_out.strip()}")
            print("\033[92m[PASS] Gemini API connection and model verified successfully!\033[0m")
        else:
            print(f"\033[91m[FAIL] Gemini API returned HTTP {resp.status_code}\033[0m")
            try:
                err_json = resp.json()
                print(f"Error Details: {err_json.get('error', {}).get('message', resp.text)}")
            except Exception:
                print(f"Raw Response: {resp.text}")
            sys.exit(1)

    except Exception as exc:
        print(f"\033[91m[FAIL] Connection Error: {type(exc).__name__}: {exc}\033[0m")
        sys.exit(1)


if __name__ == "__main__":
    run_llm_smoke()

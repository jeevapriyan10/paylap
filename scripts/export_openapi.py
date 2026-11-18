#!/usr/bin/env python3
"""
PayLap OpenAPI Specification Exporter and Validator.
Exports the OpenAPI specification from the FastAPI app and validates it using openapi-spec-validator.
"""

import json
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openapi_spec_validator import validate

from app.main import app

DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs")
OUTPUT_PATH = os.path.join(DOCS_DIR, "openapi.json")


def export_and_validate():
    print("Generating OpenAPI specification from app.main:app...")
    openapi_schema = app.openapi()

    print("Validating OpenAPI schema with openapi-spec-validator...")
    try:
        validate(openapi_schema)
        print("✓ OpenAPI schema is valid according to the OpenAPI specification.")
    except Exception as exc:
        print(f"✗ OpenAPI validation error: {exc}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, indent=2, ensure_ascii=False)

    paths_count = len(openapi_schema.get("paths", {}))
    schemas_count = len(openapi_schema.get("components", {}).get("schemas", {}))
    print(f"✓ Exported {paths_count} paths and {schemas_count} schemas to {OUTPUT_PATH}")


if __name__ == "__main__":
    export_and_validate()

import json
import re
import time
from typing import Any
import jsonschema
from app.services.sandbox import run_json_hidden_tests
from app.verifiers.base import VerifierBase, VerificationResult


class JsonDataVerifier(VerifierBase):
    """
    Deterministic verifier for JSON data deliverables.
    Validates against JSON Schema in verifier_config['schema'],
    then optionally runs buyer-trusted hidden pytest checks using a 'data' fixture.
    """

    def verify(self, milestone: Any, submission: str) -> VerificationResult:
        start_time = time.perf_counter()
        checks = []

        # 1. Parse JSON document
        try:
            parsed_data = json.loads(submission)
            checks.append({"name": "json_syntax", "passed": True})
        except Exception as err:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            checks.append({"name": "json_syntax", "passed": False})
            return VerificationResult(
                passed=False,
                public_summary=f"Invalid JSON format: {err}",
                private_detail=None,
                checks=checks,
                violations=[],
                duration_ms=round(duration_ms, 2),
                gate_type="deterministic"
            )

        # 2. Validate against JSON Schema in verifier_config
        config = milestone.verifier_config or {}
        schema = config.get("schema")
        if schema:
            try:
                jsonschema.validate(instance=parsed_data, schema=schema)
                checks.append({"name": "json_schema", "passed": True})
            except jsonschema.ValidationError as val_err:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                checks.append({"name": "json_schema", "passed": False})
                return VerificationResult(
                    passed=False,
                    public_summary=f"JSON Schema Validation Error: {val_err.message}",
                    private_detail=None,
                    checks=checks,
                    violations=[],
                    duration_ms=round(duration_ms, 2),
                    gate_type="deterministic"
                )

        # 3. Optional hidden pytest checks
        hidden_tests = milestone.hidden_tests or config.get("hidden_tests")
        if hidden_tests and hidden_tests.strip():
            hidden_res = run_json_hidden_tests(data_json_str=submission, tests=hidden_tests)

            test_funcs = re.findall(r"def\s+(test_\w+)", hidden_tests)
            total_hidden = len(test_funcs) if test_funcs else 1

            if not hidden_res.passed:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                failed_matches = re.findall(r"FAILED\s+test_data\.py::", hidden_res.output)
                failed_count = len(failed_matches) if failed_matches else 1
                failed_count = min(failed_count, total_hidden)

                checks.append({"name": "hidden_checks", "passed": False})
                return VerificationResult(
                    passed=False,
                    public_summary=f"{failed_count} of {total_hidden} hidden checks failed",
                    private_detail=hidden_res.output,
                    checks=checks,
                    violations=[],
                    duration_ms=round(duration_ms, 2),
                    gate_type="deterministic"
                )
            else:
                checks.append({"name": "hidden_checks", "passed": True})

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        return VerificationResult(
            passed=True,
            public_summary="JSON document passed schema validation and all checks.",
            private_detail=None,
            checks=checks,
            violations=[],
            duration_ms=round(duration_ms, 2),
            gate_type="deterministic"
        )

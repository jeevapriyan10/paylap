import re
import time
from typing import Any
from app.services.sandbox import run_python_tests
from app.verifiers.base import VerifierBase, VerificationResult


class PythonCodeVerifier(VerifierBase):
    """
    Deterministic verifier for Python code submissions.
    Runs public tests first, followed by hidden tests in a separate sandbox.
    Never leaks hidden test names, assertions, or values in public_summary.
    """

    def verify(self, milestone: Any, submission: str) -> VerificationResult:
        start_time = time.perf_counter()

        # Step 1: Run public tests
        public_tests = milestone.public_tests or ""
        public_res = run_python_tests(code=submission, tests=public_tests)

        if not public_res.passed:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return VerificationResult(
                passed=False,
                public_summary=public_res.output,
                private_detail=None,
                checks=[{"name": "public_tests", "passed": False}],
                violations=public_res.violations,
                duration_ms=round(duration_ms, 2),
                gate_type="deterministic"
            )

        checks = [{"name": "public_tests", "passed": True}]

        # Step 2: Run hidden tests in a separate sandbox run if present
        hidden_tests = milestone.hidden_tests
        if hidden_tests and hidden_tests.strip():
            hidden_res = run_python_tests(code=submission, tests=hidden_tests)

            # Count total hidden test functions
            test_funcs = re.findall(r"def\s+(test_\w+)", hidden_tests)
            total_hidden = len(test_funcs) if test_funcs else 1

            if not hidden_res.passed:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                failed_matches = re.findall(r"FAILED\s+test_solution\.py::", hidden_res.output)
                failed_count = len(failed_matches) if failed_matches else 1
                failed_count = min(failed_count, total_hidden)

                checks.append({"name": "hidden_tests", "passed": False})
                return VerificationResult(
                    passed=False,
                    # Strictly confidential: no test names, no assertions, no values
                    public_summary=f"{failed_count} of {total_hidden} hidden checks failed",
                    private_detail=hidden_res.output,
                    checks=checks,
                    violations=hidden_res.violations,
                    duration_ms=round(duration_ms, 2),
                    gate_type="deterministic"
                )
            else:
                checks.append({"name": "hidden_tests", "passed": True})

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        return VerificationResult(
            passed=True,
            public_summary="All public and hidden checks passed successfully.",
            private_detail=None,
            checks=checks,
            violations=[],
            duration_ms=round(duration_ms, 2),
            gate_type="deterministic"
        )

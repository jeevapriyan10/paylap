import re
import time
from typing import Any
from app.verifiers.base import VerifierBase, VerificationResult


class TextRulesVerifier(VerifierBase):
    """
    Deterministic verifier for text deliverables.
    Enforces min_words, max_words, required_patterns, and forbidden_patterns
    specified in verifier_config.
    """

    def verify(self, milestone: Any, submission: str) -> VerificationResult:
        start_time = time.perf_counter()
        config = milestone.verifier_config or {}

        checks = []
        failed_reasons = []

        # Count words by whitespace
        words = submission.strip().split()
        word_count = len(words)

        # 1. min_words
        min_words = config.get("min_words")
        if min_words is not None:
            passed = (word_count >= min_words)
            checks.append({"name": "min_words", "passed": passed, "expected": min_words, "actual": word_count})
            if not passed:
                failed_reasons.append(f"Word count {word_count} is less than minimum {min_words}")

        # 2. max_words
        max_words = config.get("max_words")
        if max_words is not None:
            passed = (word_count <= max_words)
            checks.append({"name": "max_words", "passed": passed, "expected": max_words, "actual": word_count})
            if not passed:
                failed_reasons.append(f"Word count {word_count} exceeds maximum {max_words}")

        # 3. required_patterns (regex list)
        required_patterns = config.get("required_patterns", [])
        for pattern in required_patterns:
            matched = bool(re.search(pattern, submission))
            checks.append({"name": f"required_pattern:{pattern}", "passed": matched})
            if not matched:
                failed_reasons.append(f"Required pattern '{pattern}' not found")

        # 4. forbidden_patterns (regex list)
        forbidden_patterns = config.get("forbidden_patterns", [])
        for pattern in forbidden_patterns:
            matched = bool(re.search(pattern, submission))
            checks.append({"name": f"forbidden_pattern:{pattern}", "passed": not matched})
            if matched:
                failed_reasons.append(f"Forbidden pattern '{pattern}' was matched")

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        passed = (len(failed_reasons) == 0)

        if passed:
            summary = f"All {len(checks)} text verification rules passed successfully ({word_count} words)."
        else:
            summary = f"Text verification failed: {'; '.join(failed_reasons)}."

        return VerificationResult(
            passed=passed,
            public_summary=summary,
            private_detail=None,
            checks=checks,
            violations=[],
            duration_ms=round(duration_ms, 2),
            gate_type="deterministic"
        )

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class VerificationResult:
    passed: bool
    public_summary: str
    private_detail: Optional[str] = None
    checks: List[Dict[str, Any]] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)
    duration_ms: float = 0.0
    gate_type: str = "deterministic"

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "public_summary": self.public_summary,
            "checks": self.checks,
            "violations": self.violations,
            "duration_ms": self.duration_ms,
            "gate_type": self.gate_type,
            # NOTE: private_detail is intentionally omitted from serialized public responses
        }


class VerifierBase(ABC):
    """Abstract base class for deterministic milestone verifiers."""

    @abstractmethod
    def verify(self, milestone: Any, submission: str) -> VerificationResult:
        """
        Verify submitted work against milestone specification and configuration.
        Returns VerificationResult.
        """
        pass

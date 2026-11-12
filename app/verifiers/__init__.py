from typing import Dict, List
from app.verifiers.base import VerifierBase, VerificationResult
from app.verifiers.python_code import PythonCodeVerifier
from app.verifiers.json_data import JsonDataVerifier
from app.verifiers.text_rules import TextRulesVerifier

_VERIFIERS: Dict[str, VerifierBase] = {
    "python_code": PythonCodeVerifier(),
    "json_data": JsonDataVerifier(),
    "text_rules": TextRulesVerifier(),
}


def get_verifier(verifier_type: str) -> VerifierBase:
    """Retrieve verifier instance by name; defaults to python_code."""
    key = (verifier_type or "python_code").lower()
    if key not in _VERIFIERS:
        raise ValueError(
            f"Unsupported verifier_type '{verifier_type}'. "
            f"Available verifiers: {list_available_verifiers()}"
        )
    return _VERIFIERS[key]


def list_available_verifiers() -> List[str]:
    """List registered verifier types."""
    return list(_VERIFIERS.keys())

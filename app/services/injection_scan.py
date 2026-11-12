import re
from typing import List

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|previous\s+|prior\s+)?instructions",
    r"disregard\s+(the\s+|all\s+|previous\s+)?rules",
    r"system\s*:",
    r"you\s+are\s+now",
    r"approve\s+this",
    r"pay\s+(the\s+)?maximum",
    r"mark\s+as\s+passed",
    r"override\s+(the\s+)?verification",
    r"release\s+(the\s+)?funds",
    r"bypass\s+(security|checks|sandbox)",
    r"payment\s+authorized",
    r"do\s+not\s+verify",
]


def scan_for_injections(content: str) -> List[str]:
    """
    Scans code, comments, docstrings, string literals, and text deliverables
    for adversarial prompt manipulation phrases.
    Does NOT reject by itself; returns risk_flags to be recorded in events
    and passed to the arbiter.
    """
    if not content:
        return []

    risk_flags = []
    content_lower = content.lower()

    for pattern in INJECTION_PATTERNS:
        match = re.search(pattern, content_lower, re.IGNORECASE)
        if match:
            risk_flags.append(f"Prompt manipulation phrase detected: '{match.group(0)}'")

    return risk_flags

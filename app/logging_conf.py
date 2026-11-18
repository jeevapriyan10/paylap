import json
import logging
import re
from typing import Any, Dict, Set

# Regex patterns for sensitive data redaction
REDACT_PATTERNS = [
    (re.compile(r"pl_(test|live)_[a-zA-Z0-9]{8,16}_[a-zA-Z0-9]{16,64}"), "[REDACTED_API_KEY]"),
    (re.compile(r'(?i)(password|secret|client_secret)["\']?\s*[:=]\s*["\']?([^"\'\s,}{]+)'), r'\1: "[REDACTED]"'),
    (re.compile(r"(?i)authorization:\s*bearer\s+[a-zA-Z0-9_\-\.]+"), "Authorization: Bearer [REDACTED]"),
    (re.compile(r"(?i)paylap_session=([^;\s]+)"), "paylap_session=[REDACTED]"),
    (re.compile(r"(?i)paylap_csrf=([^;\s]+)"), "paylap_csrf=[REDACTED]"),
]

# Planted sentinels and hidden-test keywords to scrub
HIDDEN_TEST_SENTINELS: Set[str] = set()


def register_hidden_test_sentinel(text: str) -> None:
    """Register hidden test content or sentinels to ensure they never appear in logs."""
    if text and len(text.strip()) > 5:
        HIDDEN_TEST_SENTINELS.add(text.strip())


class RedactingJsonFormatter(logging.Formatter):
    """
    Formatter that outputs JSON logs with mandatory redaction of:
    - Passwords
    - API keys
    - Session tokens
    - PayPal credentials
    - Authorization headers
    - Hidden test code and sentinels
    """

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()

        # 1. Apply regex redaction patterns
        for pattern, replacement in REDACT_PATTERNS:
            message = pattern.sub(replacement, message)

        # 2. Scrub registered hidden test strings and sentinels
        for sentinel in HIDDEN_TEST_SENTINELS:
            if sentinel in message:
                message = message.replace(sentinel, "[REDACTED_HIDDEN_TEST]")

        # 3. Scrub generic hidden-test assertions if present
        if "hidden_tests" in message.lower():
            message = re.sub(r'(?i)"hidden_tests"\s*:\s*"[^"]*"', '"hidden_tests": "[REDACTED]"', message)

        log_data: Dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        }

        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id

        if record.exc_info and not record.exc_text:
            # Mask exception text if it contains sensitive info
            exc_str = self.formatException(record.exc_info)
            for pattern, replacement in REDACT_PATTERNS:
                exc_str = pattern.sub(replacement, exc_str)
            for sentinel in HIDDEN_TEST_SENTINELS:
                if sentinel in exc_str:
                    exc_str = exc_str.replace(sentinel, "[REDACTED_HIDDEN_TEST]")
            log_data["exception"] = exc_str

        return json.dumps(log_data)


def configure_logging(level: int = logging.INFO) -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Avoid adding duplicate handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(RedactingJsonFormatter())
    root_logger.addHandler(handler)

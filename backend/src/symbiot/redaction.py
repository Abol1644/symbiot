"""Secret redaction layer for prompts, events, and API responses."""

import os
import re


SECRET_PATTERNS = [
    (r'(?i)(api[_-]?key|secret|token|password|passwd|pwd)\s*[=:]\s*\S+',
     r'\1=<REDACTED>'),
    (r'(?i)(bearer|authorization)\s*[:=]\s*\S+', r'\1: <REDACTED>'),
    (r'(?i)sk-[a-zA-Z0-9]{20,}', '<REDACTED_KEY>'),
    (r'(?i)sk-proj-[a-zA-Z0-9\-_]{20,}', '<REDACTED_KEY>'),
    (r'(?i)sk-ant-[a-zA-Z0-9\-_]{20,}', '<REDACTED_KEY>'),
    (r'(?i)sk-or-[a-zA-Z0-9\-_]{20,}', '<REDACTED_KEY>'),
    (r'(?i)ghp_[a-zA-Z0-9]{36}', '<REDACTED_KEY>'),
    (r'(?i)xox[bpars]-[a-zA-Z0-9\-]+', '<REDACTED_KEY>'),
    (r'(?i)AKIA[0-9A-Z]{16}', '<REDACTED_KEY>'),
    (r'-----BEGIN (RSA |EC |DSA )?PRIVATE KEY-----.*?-----END',
     '<REDACTED_PRIVATE_KEY>'),
    (r'(?i)(connection[_-]?string|database[_-]?url|db[_-]?url)\s*[=:]\s*\S+',
     r'\1=<REDACTED>'),
]


def _redaction_enabled() -> bool:
    return os.getenv("SYMBIOT_REDACTION_ENABLED", "true").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def redact_secrets(content: str) -> str:
    if not _redaction_enabled():
        return content
    for pattern, replacement in SECRET_PATTERNS:
        content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    return content


def redact_provider_config(config: dict) -> dict:
    """Redact key-like fields before API responses."""
    redacted = {}
    for k, v in config.items():
        if any(x in k.lower() for x in ('key', 'secret', 'token', 'password')):
            redacted[k] = '<REDACTED>'
        else:
            redacted[k] = v
    return redacted

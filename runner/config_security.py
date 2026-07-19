#!/usr/bin/env python3
"""
config_security.py - validation and masking for sensitive configuration values.

Enforces stricter handling of secrets, tokens, and API keys:
  - Classifies config keys as sensitive or not
  - Validates format and length before storage
  - Masks values for safe logging
  - Logs access to sensitive keys for audit

Usage:
    from config_security import validate_config_value, mask_sensitive

    result = validate_config_value("GITHUB_PAT", "ghp_abc123...")
    safe   = mask_sensitive("GITHUB_PAT", "ghp_abc123xyz")
    # => "ghp_***xyz"

Env vars:
    ORCH_CONFIG_SECURITY     "true" (default) to enable
    ORCH_AUDIT_SENSITIVE     "true" (default) to log sensitive key reads
"""
import os, re, sys, time
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("config_security")

ENABLED = os.environ.get("ORCH_CONFIG_SECURITY", "true").lower() in ("1", "true", "yes", "on")
AUDIT = os.environ.get("ORCH_AUDIT_SENSITIVE", "true").lower() in ("1", "true", "yes", "on")

# ---------------------------------------------------------------------------
# Sensitive key classification
# ---------------------------------------------------------------------------

# Exact keys always treated as sensitive
SENSITIVE_KEYS = frozenset({
    "GITHUB_PAT",
    "ANTHROPIC_API_KEY",
    "SUPABASE_SERVICE_KEY",
    "SUPABASE_ANON_KEY",
    "OPENAI_API_KEY",
    "SLACK_BOT_TOKEN",
    "SLACK_WEBHOOK_URL",
    "DATABASE_URL",
    "SENTRY_DSN",
})

# Patterns that mark any key as sensitive
_SENSITIVE_PATTERNS = re.compile(
    r"(SECRET|TOKEN|PASSWORD|PWD|CREDENTIAL|API_KEY|PAT|PRIVATE_KEY|AUTH)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Known token format prefixes and their constraints
# ---------------------------------------------------------------------------

_TOKEN_FORMATS = {
    "ghp_": {"label": "GitHub PAT (fine-grained)", "min_len": 36, "max_len": 255},
    "github_pat_": {"label": "GitHub PAT (classic)", "min_len": 40, "max_len": 255},
    "gho_": {"label": "GitHub OAuth token", "min_len": 36, "max_len": 255},
    "sk-": {"label": "OpenAI / Anthropic API key", "min_len": 30, "max_len": 200},
    "xoxb-": {"label": "Slack bot token", "min_len": 40, "max_len": 255},
    "xoxp-": {"label": "Slack user token", "min_len": 40, "max_len": 255},
    "eyJhbGciOi": {"label": "JWT", "min_len": 50, "max_len": 8192},
}

# General limits for values we don't recognize by prefix
_DEFAULT_MIN_LEN = 8
_DEFAULT_MAX_LEN = 4096


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    ok: bool
    reason: str = ""
    key: str = ""
    is_sensitive: bool = False


def is_sensitive_key(key: str) -> bool:
    """Return True if *key* should be treated as a sensitive config key."""
    if key in SENSITIVE_KEYS:
        return True
    return bool(_SENSITIVE_PATTERNS.search(key))


def validate_config_value(key: str, value) -> ValidationResult:
    """Validate a config value before storage.

    Checks:
      - value must be a non-empty string (for sensitive keys)
      - must not contain obvious placeholder text
      - must satisfy length constraints for known token formats
      - must not contain whitespace or control characters
    """
    sensitive = is_sensitive_key(key)

    if not ENABLED:
        return ValidationResult(ok=True, key=key, is_sensitive=sensitive)

    if not isinstance(value, str):
        return ValidationResult(
            ok=False, reason=f"expected string value, got {type(value).__name__}",
            key=key, is_sensitive=sensitive,
        )

    if sensitive and not value:
        return ValidationResult(
            ok=False, reason="sensitive key must not be empty",
            key=key, is_sensitive=sensitive,
        )

    # Reject obvious placeholders
    placeholders = ("changeme", "replace_me", "your_token_here", "xxx", "todo")
    if value.lower().strip() in placeholders:
        return ValidationResult(
            ok=False, reason="value appears to be a placeholder",
            key=key, is_sensitive=sensitive,
        )

    # Whitespace / control-character check
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value):
        return ValidationResult(
            ok=False, reason="value contains control characters",
            key=key, is_sensitive=sensitive,
        )
    if value != value.strip():
        return ValidationResult(
            ok=False, reason="value has leading/trailing whitespace",
            key=key, is_sensitive=sensitive,
        )

    # Format-specific length checks
    for prefix, spec in _TOKEN_FORMATS.items():
        if value.startswith(prefix):
            if len(value) < spec["min_len"]:
                return ValidationResult(
                    ok=False,
                    reason=f"{spec['label']} too short (got {len(value)}, min {spec['min_len']})",
                    key=key, is_sensitive=sensitive,
                )
            if len(value) > spec["max_len"]:
                return ValidationResult(
                    ok=False,
                    reason=f"{spec['label']} too long (got {len(value)}, max {spec['max_len']})",
                    key=key, is_sensitive=sensitive,
                )
            return ValidationResult(ok=True, key=key, is_sensitive=sensitive)

    # General length bounds for sensitive values
    if sensitive:
        if len(value) < _DEFAULT_MIN_LEN:
            return ValidationResult(
                ok=False, reason=f"sensitive value too short (min {_DEFAULT_MIN_LEN})",
                key=key, is_sensitive=sensitive,
            )
        if len(value) > _DEFAULT_MAX_LEN:
            return ValidationResult(
                ok=False, reason=f"value too long (max {_DEFAULT_MAX_LEN})",
                key=key, is_sensitive=sensitive,
            )

    return ValidationResult(ok=True, key=key, is_sensitive=sensitive)


# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------

def mask_sensitive(key: str, value: str) -> str:
    """Return a masked version of *value* safe for logging.

    For sensitive keys: preserves a recognisable prefix and the last 3 chars,
    replacing the middle with '***'.
    For non-sensitive keys: returns the value unchanged.

    Examples:
        mask_sensitive("GITHUB_PAT", "ghp_abc123xyz")  -> "ghp_***xyz"
        mask_sensitive("MAX_PARALLEL", "4")             -> "4"
    """
    if not is_sensitive_key(key):
        return value
    return mask_value(value)


def mask_value(value: str) -> str:
    """Mask a single secret value regardless of key classification.

    Strategy:
      - Keep a recognisable prefix (up to first _ or first 4 chars)
      - Keep the last 3 characters
      - Replace everything in between with ***
      - Very short values (<=6 chars) become '***'
    """
    if not isinstance(value, str) or len(value) <= 6:
        return "***"

    # Find a prefix boundary (e.g., "ghp_", "xoxb-", "sk-")
    prefix_end = 0
    for i, ch in enumerate(value):
        if ch in ("_", "-") and i < 12:
            prefix_end = i + 1
            break
    if prefix_end == 0:
        prefix_end = min(4, len(value) // 3)

    tail = value[-3:]
    return f"{value[:prefix_end]}***{tail}"


# ---------------------------------------------------------------------------
# Access audit logging
# ---------------------------------------------------------------------------

def log_sensitive_access(key: str, *, caller: Optional[str] = None) -> None:
    """Record that a sensitive key was read, for audit purposes."""
    if not AUDIT or not is_sensitive_key(key):
        return
    extra = f" by {caller}" if caller else ""
    _log.info("AUDIT: sensitive key %r accessed%s at %s",
              key, extra, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

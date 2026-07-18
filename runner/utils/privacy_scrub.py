"""privacy_scrub.py — Scrub PII from completion outputs. Env gate: ORCH_PRIVACY_SCRUB_ENABLED (default OFF)."""
import os, re
ENABLED = os.environ.get("ORCH_PRIVACY_SCRUB_ENABLED", "").lower() == "true"
def scrub(text):
    if not ENABLED or not text: return text or ""
    return re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}", "[REDACTED_EMAIL]", text)

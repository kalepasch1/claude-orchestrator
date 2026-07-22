"""failsoft_integration.py — Fail-soft integration layer. Env gate: ORCH_FAILSOFT_INTEGRATION_ENABLED (default OFF)."""
import os
ENABLED = os.environ.get("ORCH_FAILSOFT_INTEGRATION_ENABLED", "").lower() == "true"
def safe_call(fn, *args, default=None):
    if not ENABLED: return fn(*args)
    try: return fn(*args)
    except Exception: return default

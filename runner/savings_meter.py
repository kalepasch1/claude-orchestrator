#!/usr/bin/env python3
"""Record avoided token/minute telemetry from reuse, cache, and templates."""
import os


def estimate_tokens(text):
    return max(1, int(len(str(text or "")) / 4))


def estimate_minutes(tokens):
    # Conservative: avoided model/context setup + review time. Tunable without schema changes.
    return round(tokens / float(os.environ.get("ORCH_SAVINGS_TOKENS_PER_MIN", "1800")), 2)


def record(kind, prompt="", result_text="", tokens=None, minutes=None, detail=""):
    tokens = int(tokens if tokens is not None else estimate_tokens(prompt) + estimate_tokens(result_text))
    minutes = float(minutes if minutes is not None else estimate_minutes(tokens))
    try:
        import db
        db.insert("resource_events", {
            "kind": "savings",
            "value": tokens,
            "detail": f"{kind}: {tokens} tokens avoided, {minutes:.2f} minutes avoided; {detail}"[:500],
            "action": f"{kind}|minutes={minutes:.2f}",
        })
    except Exception:
        pass
    return {"tokens": tokens, "minutes": minutes}

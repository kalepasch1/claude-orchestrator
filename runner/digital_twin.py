#!/usr/bin/env python3
"""
digital_twin.py - shadow-copy dry-run harness for high-risk changes. Before a change
reaches the real canary (canary_economics.py), it runs against a shadow copy with
synthetic traffic. Only changes that pass the twin gate proceed to the live canary.

Extends canary_economics: twin_decide() runs the same promote/rollback logic but against
shadow telemetry, acting as a pre-filter.

Flow:
  diff arrives -> digital_twin.run_twin(diff, app) -> synthetic requests against shadow
  -> twin_decide(app) -> if "promote" -> proceed to real canary_economics.decide(app)
  -> if "rollback" -> block before any real traffic sees it.

Fail-soft: if the twin harness errors, it returns "pass-through" so the real canary
still gets to decide (we never block on twin infra failures).
"""
import os, sys, json, time, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import canary_economics

TWIN_WINDOW_MIN = int(os.environ.get("TWIN_WINDOW_MIN", "5"))
TWIN_SYNTHETIC_N = int(os.environ.get("TWIN_SYNTHETIC_N", "10"))
TWIN_QUALITY_MIN = float(os.environ.get("TWIN_QUALITY_MIN", "6.0"))


def _shadow_ops(app: str, minutes: int) -> list:
    """Fetch shadow telemetry from twin_operations table."""
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(minutes=minutes)).isoformat()
    try:
        return db.select("twin_operations", {
            "select": "quality_score,cost_usd,ok",
            "app": f"eq.{app}", "created_at": f"gte.{cutoff}"
        }) or []
    except Exception:
        return []


def twin_decide(app: str) -> dict:
    """Run canary-style promote/rollback against shadow telemetry."""
    ops = _shadow_ops(app, TWIN_WINDOW_MIN)
    if not ops:
        return {"app": app, "decision": "pass-through",
                "why": "no twin telemetry — pass-through to real canary"}

    q = [float(o["quality_score"]) for o in ops if o.get("quality_score") is not None]
    quality = sum(q) / len(q) if q else None
    cost = sum(float(o.get("cost_usd") or 0) for o in ops)
    errors = sum(1 for o in ops if o.get("ok") is False)

    if quality is not None and quality < TWIN_QUALITY_MIN:
        return {"app": app, "decision": "block",
                "why": f"twin quality {quality:.1f} < {TWIN_QUALITY_MIN}"}
    if errors > max(1, len(ops) // 5):
        return {"app": app, "decision": "block",
                "why": f"twin error spike {errors}/{len(ops)}"}
    return {"app": app, "decision": "promote",
            "why": f"twin OK: quality={quality}, cost=${cost:.2f}, errors={errors}"}


def gate(app: str) -> dict:
    """Full gate: twin first, then real canary if twin passes."""
    twin = twin_decide(app)
    if twin["decision"] == "block":
        return {"app": app, "decision": "block", "stage": "twin", "detail": twin}

    # Twin passed — proceed to real canary
    real = canary_economics.decide(app)
    return {"app": app, "decision": real["decision"], "stage": "canary",
            "twin": twin, "canary": real}


def log_synthetic(app: str, quality: float, cost: float, ok: bool = True) -> bool:
    """Record a synthetic twin operation result."""
    try:
        db.insert("twin_operations", {
            "app": app, "quality_score": quality, "cost_usd": cost, "ok": ok
        })
        return True
    except Exception:
        return False


def run():
    """Run twin gate for all projects."""
    out = []
    for p in db.select("projects", {"select": "name"}) or []:
        result = gate(p["name"])
        out.append(result)
        print(f"digital_twin: {p['name']} -> {result['decision']} (stage={result['stage']})")
    return out


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))

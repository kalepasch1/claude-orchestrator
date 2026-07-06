#!/usr/bin/env python3
"""
budget.py - per-project spend telemetry/guardrails.

Owner policy: caps should inform routing and spend dashboards, not create manual task
backlogs. The runner therefore does NOT block by default when a project crosses its cap;
subscription/fixed-price coders can keep moving, and paid-API coders enforce their own
small caps at the provider route. Set ORCH_BUDGET_BLOCKS_TASKS=true only for a deliberate
hard stop.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

def _block_on_cap():
    # Evaluate at CALL time (not import) so flipping ORCH_EMERGENCY_BUDGET_STOP via fleet_config +
    # reload takes effect immediately, without waiting for a full runner restart. This is the
    # emergency brake ONLY — in subscription mode real spend is $0, so it must stay OFF or it blocks
    # every over-(phantom)-cap project and starves integrate of inputs (the "ships nothing" bug).
    return os.environ.get("ORCH_EMERGENCY_BUDGET_STOP", "false").lower() in ("true", "1", "yes")


# back-compat module constant (some callers import it); prefer _block_on_cap() for live evaluation
BLOCK_ON_CAP = _block_on_cap()
FILE_BUDGET_CARDS = os.environ.get("ORCH_FILE_BUDGET_CARDS", "false").lower() in ("true", "1", "yes")

# Model-name fragments that are REAL paid providers (billed per token). Everything else — Claude Max
# and Codex subscriptions — is $0 and must NOT count toward spend. This is the calibration point: the
# budget reflects money actually spent on paid APIs, per source.
_PAID_FRAGMENTS = ("deepseek", "gemini", "gpt", "openai", "mistral", "groq")


def _real_spent(project=None):
    """Real month-to-date billable $ from PAID providers only (subscription = $0, excluded). Immune to
    the phantom subscription 'spend' that polluted v_spend_mtd. Sums outcomes.usd for paid-model rows."""
    import datetime
    month_start = datetime.date.today().replace(day=1).isoformat()
    q = {"select": "usd,model", "created_at": f"gte.{month_start}"}
    if project:
        q["project"] = f"eq.{project}"
    total = 0.0
    try:
        for r in (db.select("outcomes", q) or []):
            m = str(r.get("model") or "").lower()
            if "claude" in m or "codex" in m:      # subscription -> $0
                continue
            if any(f in m for f in _PAID_FRAGMENTS):
                total += float(r.get("usd") or 0)
    except Exception:
        pass
    return round(total, 2)


def status(project):
    """Return {cap, spent, hard_pause, over} for a project. `spent` is REAL paid-provider $ only."""
    cap, hard = None, True
    try:
        b = db.select("budgets", {"select": "*", "project": f"eq.{project}"}) or []
        if b:
            cap = float(b[0]["monthly_usd_cap"]); hard = bool(b[0]["hard_pause"])
    except Exception:
        pass
    spent = _real_spent(project)
    over = cap is not None and spent >= cap
    return {"cap": cap, "spent": spent, "hard_pause": hard, "over": over}


def _global_real_cap():
    # Hard ceiling on TOTAL real billable $ across ALL projects/providers before human approval is
    # required. Subscription work is $0 (see claude_cli), so this only counts money actually spent on
    # paid APIs (deepseek/gemini/gpt via aider + key_broker). Call-time read so it's tunable fleet-wide.
    try:
        return float(os.environ.get("ORCH_REAL_USD_MONTH_CAP", "200"))
    except ValueError:
        return 200.0


def global_real_spent():
    """Total real month-to-date billable $ across ALL projects (paid providers only; subscription $0)."""
    return _real_spent(None)


def global_status():
    spent = global_real_spent()
    cap = _global_real_cap()
    return {"real_spent": spent, "cap": cap, "over": spent >= cap, "left": round(max(0.0, cap - spent), 2)}


_PAID_CARD_ONCE = {"filed": False}


def paid_allowed():
    """True while total real spend is under the global ceiling. Gates ONLY paid-API providers
    (deepseek/gemini/gpt/key_broker) — subscription + free/local work is $0 and always allowed, so the
    fleet keeps running costlessly even after the ceiling; only real spending pauses for approval."""
    g = global_status()
    if g["over"] and FILE_BUDGET_CARDS and not _PAID_CARD_ONCE["filed"]:
        try:
            db.insert("approvals", {"project": "global", "kind": "material",
                "title": f"Real-spend ceiling reached (${g['real_spent']}/${g['cap']})",
                "why": "Total REAL billable spend across all paid providers hit the approval ceiling.",
                "value": "Approve to raise ORCH_REAL_USD_MONTH_CAP and resume paid-API coders.",
                "risk": "Paid-API work is paused; subscription + free/local work continues at $0.",
                "command": ""})
            _PAID_CARD_ONCE["filed"] = True
        except Exception:
            pass
    return not g["over"]


def allow(project):
    """True if a new task may run. Task execution itself is never blocked by the $-ceiling (subscription
    work is free); only the legacy per-project emergency stop can halt it. The real-$ ceiling is enforced
    at the PAID-provider layer via paid_allowed()."""
    s = status(project)
    if s["over"] and s["hard_pause"]:
        if FILE_BUDGET_CARDS:
            try:
                db.insert("approvals", {"project": project, "kind": "self",
                    "title": f"Budget cap reached for {project} (${s['spent']}/{s['cap']})",
                    "why": "Month-to-date spend hit the cap; continuing via subscription/failover routes.",
                    "value": "Keeps visibility without blocking queued improvements.",
                    "risk": "Paid API coders remain separately capped by their provider route.",
                    "command": ""})
            except Exception:
                pass
        return not _block_on_cap()
    return True

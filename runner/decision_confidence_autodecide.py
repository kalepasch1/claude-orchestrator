#!/usr/bin/env python3
"""
decision_confidence_autodecide.py — auto-decide high-confidence low-stakes approvals.

When the decision_engine produces a brief with high confidence and low stakes,
this module can auto-decide without human intervention.  Criteria:

  1. confidence >= threshold (env ORCH_AUTODECIDE_CONFIDENCE_THRESHOLD, default 85)
  2. stakes are not "high"
  3. brief does not flag counsel_needed
  4. category is not in the denylist (legal, financial, security, personnel, compliance)
  5. decision is not flagged as irreversible

Usage:
    import decision_confidence_autodecide as autodecide
    summary = autodecide.run()          # poll-loop: evaluate & auto-decide eligible
    ok      = autodecide.should_autodecide(approval, brief)
    record  = autodecide.autodecide(approval, brief)
"""
import os, sys, json, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

CONFIDENCE_THRESHOLD = int(os.environ.get("ORCH_AUTODECIDE_CONFIDENCE_THRESHOLD", "85"))
DECIDED_BY = "autodecide"

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
_stats = {"evaluated": 0, "auto_decided": 0, "manual_required": 0, "confidence_sum": 0.0}
_audit_log = []  # in-memory fallback; also persisted to DB when available


# ---------------------------------------------------------------------------
# Denylist & stake heuristics
# ---------------------------------------------------------------------------

def category_denylist() -> set:
    """Return set of approval categories that must never be auto-decided."""
    base = {"legal", "financial", "security", "personnel", "compliance"}
    extra = os.environ.get("ORCH_AUTODECIDE_DENYLIST_EXTRA", "")
    if extra:
        base |= {c.strip().lower() for c in extra.split(",") if c.strip()}
    return base


_HIGH_DOLLAR_RX = re.compile(r"\$\s*[\d,]+(?:\.\d+)?[MBmb]|\$\s*(?:\d{1,3},)*\d{3,}(?:\.\d+)?")
_EXTERNAL_PARTY_RX = re.compile(r"(?:vendor|partner|client|customer|regulator|government|court)", re.I)


def stake_level(brief: dict) -> str:
    """Determine stake level from brief content: 'low', 'medium', or 'high'.

    Uses heuristics on dollar amounts, reversibility of options, and whether
    external parties are involved.
    """
    if not brief:
        return "medium"  # unknown = cautious

    text = json.dumps(brief, default=str).lower()

    # High-dollar amounts -> high stakes
    if _HIGH_DOLLAR_RX.search(text):
        return "high"

    # Explicit stakes field
    stakes_str = str(brief.get("stakes", "")).lower()
    if any(w in stakes_str for w in ("critical", "catastrophic", "existential", "bankruptcy")):
        return "high"

    # Check reversibility of options
    options = brief.get("options", [])
    irreversible_count = sum(
        1 for o in options
        if isinstance(o, dict) and str(o.get("reversibility", "")).lower() in ("low", "none", "irreversible")
    )
    if irreversible_count > len(options) / 2 and options:
        return "high"

    # External parties raise stakes
    if _EXTERNAL_PARTY_RX.search(text):
        return "medium"

    return "low"


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def should_autodecide(approval: dict, brief: dict) -> bool:
    """Evaluate whether a decision can be auto-decided.

    Criteria:
      - confidence >= CONFIDENCE_THRESHOLD
      - stakes are not 'high'
      - counsel_needed is not set
      - not a financial/legal/irreversible decision
      - category not in denylist
    """
    if not brief:
        return False

    confidence = brief.get("confidence", 0)
    if not isinstance(confidence, (int, float)):
        try:
            confidence = float(confidence)
        except (ValueError, TypeError):
            return False

    if confidence < CONFIDENCE_THRESHOLD:
        return False

    if brief.get("counsel_needed"):
        return False

    # Category denylist
    kind = str(approval.get("kind", "") or "").lower()
    category = str(approval.get("category", "") or "").lower()
    tags = {kind, category} - {""}
    if tags & category_denylist():
        return False

    # Stake level
    if stake_level(brief) == "high":
        return False

    # All options irreversible = never auto-decide
    options = brief.get("options", [])
    if options and all(
        isinstance(o, dict) and str(o.get("reversibility", "")).lower() in ("low", "none", "irreversible")
        for o in options
    ):
        return False

    return True


def autodecide(approval: dict, brief: dict) -> dict:
    """Execute an auto-decision: pick the recommended option, record it, log rationale.

    Returns the decision record dict.
    """
    rec = brief.get("recommendation", "approve")
    confidence = brief.get("confidence", 0)
    approval_id = approval.get("id", "unknown")

    record = {
        "approval_id": approval_id,
        "decided_by": DECIDED_BY,
        "decision": rec,
        "confidence": confidence,
        "stake_level": stake_level(brief),
        "rationale": f"Auto-decided: confidence {confidence}% >= {CONFIDENCE_THRESHOLD}% threshold, "
                     f"stakes={stake_level(brief)}, no counsel needed.",
        "ts": time.time(),
    }

    # Persist to DB
    try:
        db.update("approvals", {"id": approval_id}, {
            "status": "decided",
            "decided_by": DECIDED_BY,
            "decision_text": rec,
            "decided_at": record["ts"],
        })
    except Exception:
        pass  # fail-soft

    # Audit log
    _audit_log.append(record)
    try:
        db.insert("autodecide_log", record)
    except Exception:
        pass  # fail-soft: in-memory log is the fallback

    # Update stats
    _stats["auto_decided"] += 1
    _stats["confidence_sum"] += confidence

    return record


def audit_trail(approval_id: str) -> list:
    """Return the audit trail of auto-decisions for a given approval.

    Checks DB first, falls back to in-memory log.
    """
    try:
        rows = db.select("autodecide_log", {"approval_id": f"eq.{approval_id}"})
        if rows:
            return rows
    except Exception:
        pass
    return [r for r in _audit_log if r.get("approval_id") == approval_id]


def stats() -> dict:
    """Module statistics: total evaluated, auto-decided, manual-required, avg confidence."""
    avg = 0.0
    if _stats["auto_decided"] > 0:
        avg = _stats["confidence_sum"] / _stats["auto_decided"]
    return {
        "evaluated": _stats["evaluated"],
        "auto_decided": _stats["auto_decided"],
        "manual_required": _stats["manual_required"],
        "avg_confidence_auto": round(avg, 1),
    }


def run() -> dict:
    """Poll loop: fetch pending approvals with briefs, evaluate each, auto-decide eligible.

    Returns a summary dict with counts and any errors.
    """
    summary = {"evaluated": 0, "auto_decided": 0, "manual_required": 0, "errors": []}
    try:
        pending = db.select("approvals", {
            "status": "eq.pending",
            "brief_status": "eq.ready",
            "select": "*,brief_json",
        }) or []
    except Exception as e:
        summary["errors"].append(f"fetch failed: {e}")
        return summary

    for approval in pending:
        brief = approval.get("brief_json")
        if isinstance(brief, str):
            try:
                brief = json.loads(brief)
            except Exception:
                brief = {}
        if not isinstance(brief, dict):
            brief = {}

        _stats["evaluated"] += 1
        summary["evaluated"] += 1

        try:
            if should_autodecide(approval, brief):
                autodecide(approval, brief)
                summary["auto_decided"] += 1
            else:
                _stats["manual_required"] += 1
                summary["manual_required"] += 1
        except Exception as e:
            _stats["manual_required"] += 1
            summary["manual_required"] += 1
            summary["errors"].append(f"{approval.get('id')}: {e}")

    return summary

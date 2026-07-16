#!/usr/bin/env python3
"""
legitimacy_gauntlet.py - sequential verifier pipeline with immutable receipts.

Runs an artifact through a sequence of INJECTED verifiers (citation-verifier,
source-authenticator, precedent-integrity, logic/entailment, adversary-league
survival, peer cross-examination, independent reproduction).  Aggregates to a
confidence score in [0,1].  Any unresolved citation / source / precedent failure
hard-caps confidence low.  Produces an immutable receipt with per-round verdicts
and a tamper-evident hash.
"""
import os, sys, hashlib, json, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# ── env knobs ────────────────────────────────────────────────────────────────
HARD_CAP = float(os.environ.get("ORCH_LEGIT_HARD_CAP", "0.25"))
DEFAULT_PASS_WEIGHT = float(os.environ.get("ORCH_LEGIT_PASS_WEIGHT", "1.0"))

# Verifier kinds that hard-cap confidence on failure
_HARD_CAP_KINDS = frozenset([
    "citation-verifier",
    "source-authenticator",
    "precedent-integrity",
])

# ── data classes (plain dicts) ───────────────────────────────────────────────

def _make_round(verifier_name, kind, passed, detail=""):
    return {
        "verifier": verifier_name,
        "kind": kind,
        "passed": bool(passed),
        "detail": str(detail),
        "ts": datetime.datetime.utcnow().isoformat(),
    }


def _hash_receipt(rounds, confidence):
    """Deterministic SHA-256 over the round list + final confidence."""
    blob = json.dumps({"rounds": rounds, "confidence": confidence},
                      sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


# ── core pipeline ────────────────────────────────────────────────────────────

def run_gauntlet(artifact, verifiers):
    """Run *artifact* through each verifier in order.

    Each verifier is a callable: ``verifier(artifact) -> dict`` returning at
    minimum ``{"passed": bool}``.  Optional keys: ``"detail"`` (str),
    ``"kind"`` (str, defaults to verifier.__name__), ``"weight"`` (float).
    Returns a ``GauntletResult`` dict.
    """
    rounds = []
    weights_total = 0.0
    weighted_pass = 0.0
    hard_cap_triggered = False

    for v in verifiers:
        try:
            result = v(artifact)
        except Exception as exc:
            result = {"passed": False, "detail": f"verifier raised: {exc}"}

        passed = bool(result.get("passed", False))
        kind = result.get("kind", getattr(v, "__name__", "unknown"))
        detail = result.get("detail", "")
        weight = float(result.get("weight", DEFAULT_PASS_WEIGHT))

        rnd = _make_round(getattr(v, "__name__", str(v)), kind, passed, detail)
        rounds.append(rnd)

        weights_total += weight
        if passed:
            weighted_pass += weight

        if not passed and kind in _HARD_CAP_KINDS:
            hard_cap_triggered = True
    # aggregate confidence
    if weights_total > 0:
        confidence = weighted_pass / weights_total
    else:
        confidence = 0.0

    if hard_cap_triggered:
        confidence = min(confidence, HARD_CAP)

    confidence = max(0.0, min(1.0, confidence))

    receipt_hash = _hash_receipt(rounds, confidence)

    receipt = {
        "rounds": rounds,
        "challenges": len(rounds),
        "verdicts": [r["passed"] for r in rounds],
        "confidence": confidence,
        "hard_cap_triggered": hard_cap_triggered,
        "hash": receipt_hash,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }

    # persist (fail-soft)
    try:
        db.insert("legitimacy_gauntlet_runs", {
            "artifact_id": artifact.get("id", ""),
            "confidence": confidence,
            "rounds": len(rounds),
            "passed_rounds": sum(1 for r in rounds if r["passed"]),
            "hard_cap_triggered": hard_cap_triggered,
            "receipt_hash": receipt_hash,
        })
    except Exception:
        pass

    return {
        "confidence": confidence,
        "rounds": rounds,
        "receipt": receipt,
        "hard_cap_triggered": hard_cap_triggered,
    }


# ── stats ────────────────────────────────────────────────────────────────────

def stats():
    """Return aggregate statistics from past gauntlet runs."""
    try:
        rows = db.select("legitimacy_gauntlet_runs", {"select": "*"}) or []
    except Exception:
        rows = []
    if not rows:
        return {"total_runs": 0, "avg_confidence": 0.0, "hard_cap_rate": 0.0}
    total = len(rows)
    avg_conf = sum(r.get("confidence", 0) for r in rows) / total
    hard_caps = sum(1 for r in rows if r.get("hard_cap_triggered"))
    return {
        "total_runs": total,
        "avg_confidence": round(avg_conf, 4),
        "hard_cap_rate": round(hard_caps / total, 4),
    }
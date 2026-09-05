#!/usr/bin/env python3
"""
signed_plan_execution_router.py — signed plans + economic execution routing.

The expensive frontier council owns PLANNING. Cheap, available models own
IMPLEMENTATION of small, non-overlapping worktree slices. This module is the
contract between the two halves:

  1. A plan is *signed* (content digest over its normative fields) before it is
     handed to executors. Executors may not silently move a contract boundary —
     any change to slice scope, file_scope, tests or reviewer requirements
     invalidates the signature and is refused (`ContractViolation`).
  2. Slices must be non-overlapping in file scope, so parallel worktrees cannot
     collide. `validate_slices` is the gate.
  3. Routing is economic: the cheapest *available* capable provider wins; when a
     provider disappears the router fails over rather than stalling; when a
     slice needs an independent reviewer family the implementing family is
     excluded from review.
  4. Evidence-driven uncertainty escalates to targeted replanning instead of the
     executor guessing (`should_escalate` / `escalation_request`).
  5. Every execution records planned-vs-actual files, provider/model/cost,
     tests run, and deviations — which is what makes
     `cost_per_deployed_and_verified` meaningful.

Pure functions with no I/O so the whole surface is unit-testable; callers
(plan_stage, tier_router, agentic_coders, QA) wire it in fail-soft.
"""
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Signature scheme version. Bumping it invalidates every previously signed plan,
# which is the intended behaviour when the contract's meaning changes.
SIGNATURE_VERSION = "spv1"

# Fields that define the contract. Anything outside this set (prose, rationale,
# telemetry hints) may drift without breaking the signature.
NORMATIVE_SLICE_FIELDS = ("slice_id", "file_scope", "tests", "reviewer_family_excluded", "max_cost_usd")
NORMATIVE_PLAN_FIELDS = ("plan_id", "task_slug", "task_class")

# Task classes that may never be reviewed by the family that implemented them.
INDEPENDENT_REVIEW_CLASSES = frozenset({"broad", "security", "legal", "material"})

# Confidence at or below which the executor must stop and ask for replanning
# rather than improvise.
ESCALATION_CONFIDENCE = float(os.environ.get("ORCH_SPR_ESCALATE_CONFIDENCE", "0.45"))


class ContractViolation(Exception):
    """Raised when an executor's work diverges from the signed contract."""


class NoRouteAvailable(Exception):
    """Raised when no available provider can implement a slice within budget."""


# --------------------------------------------------------------------------
# signing
# --------------------------------------------------------------------------

def _normative_view(plan):
    """The subset of a plan the signature covers, in a canonical, ordered form."""
    view = {f: plan.get(f) for f in NORMATIVE_PLAN_FIELDS}
    slices = []
    for sl in plan.get("slices") or []:
        norm = {}
        for f in NORMATIVE_SLICE_FIELDS:
            val = sl.get(f)
            # file_scope / tests are sets-in-spirit: order must not change the digest
            if isinstance(val, (list, tuple, set)):
                val = sorted(str(v) for v in val)
            norm[f] = val
        slices.append(norm)
    # slice order is not normative — only the set of slices is
    view["slices"] = sorted(slices, key=lambda s: str(s.get("slice_id")))
    view["signature_version"] = SIGNATURE_VERSION
    return view


def plan_digest(plan):
    """Stable hex digest over the normative fields of `plan`."""
    blob = json.dumps(_normative_view(plan), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def sign_plan(plan):
    """Return a copy of `plan` carrying its digest. Idempotent."""
    signed = dict(plan)
    signed["signature_version"] = SIGNATURE_VERSION
    signed["digest"] = plan_digest(plan)
    signed.setdefault("signed_at", time.time())
    return signed


def verify_plan(plan):
    """True when `plan` still matches the digest it was signed with."""
    if not plan or not plan.get("digest"):
        return False
    if plan.get("signature_version") != SIGNATURE_VERSION:
        return False
    return plan_digest(plan) == plan["digest"]


def assert_signed(plan):
    """verify_plan(), but raises ContractViolation naming what changed."""
    if not plan or not plan.get("digest"):
        raise ContractViolation("plan is unsigned — executors may not run an unsigned plan")
    if plan.get("signature_version") != SIGNATURE_VERSION:
        raise ContractViolation(
            "plan signature version %r is not %r" % (plan.get("signature_version"), SIGNATURE_VERSION))
    if plan_digest(plan) != plan["digest"]:
        raise ContractViolation("plan contract boundary changed after signing (digest mismatch)")
    return True


# --------------------------------------------------------------------------
# slice scope
# --------------------------------------------------------------------------

def _scope(sl):
    return {str(p).strip().lstrip("./") for p in (sl.get("file_scope") or []) if str(p).strip()}


def overlapping_slices(slices):
    """List of (slice_id_a, slice_id_b, sorted_shared_paths) for every collision."""
    out = []
    items = list(slices or [])
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            shared = _scope(items[i]) & _scope(items[j])
            if shared:
                out.append((items[i].get("slice_id"), items[j].get("slice_id"), sorted(shared)))
    return out


def validate_slices(slices):
    """Raise ContractViolation on empty scopes, duplicate ids, or overlaps."""
    items = list(slices or [])
    if not items:
        raise ContractViolation("plan has no slices")
    seen = set()
    for sl in items:
        sid = sl.get("slice_id")
        if not sid:
            raise ContractViolation("slice is missing slice_id")
        if sid in seen:
            raise ContractViolation("duplicate slice_id %r" % (sid,))
        seen.add(sid)
        if not _scope(sl):
            raise ContractViolation("slice %r has an empty file_scope" % (sid,))
    collisions = overlapping_slices(items)
    if collisions:
        a, b, shared = collisions[0]
        raise ContractViolation(
            "slices %r and %r overlap on %s" % (a, b, ", ".join(shared)))
    return True


# --------------------------------------------------------------------------
# economic routing
# --------------------------------------------------------------------------

def _family(provider):
    """Reviewer *family* — independence is per-vendor, not per-model."""
    return str(provider or "").split(":", 1)[0].lower()


def select_route(slc, catalog, available, exclude_families=()):
    """Cheapest available capable provider for `slc`.

    catalog: [{provider, model, cost_per_slice, capability}] — capability is the
             0..10 scale already used by model_policy tranches.
    available: iterable of provider names currently reachable.
    Returns the chosen catalog entry. Raises NoRouteAvailable when nothing fits.
    """
    avail = {str(p) for p in (available or [])}
    excluded = {_family(f) for f in (exclude_families or ())}
    need = int(slc.get("min_capability") or 0)
    budget = slc.get("max_cost_usd")
    cands = [
        e for e in (catalog or [])
        if e.get("provider") in avail
        and _family(e.get("provider")) not in excluded
        and int(e.get("capability") or 0) >= need
        and (budget is None or float(e.get("cost_per_slice") or 0.0) <= float(budget))
    ]
    if not cands:
        raise NoRouteAvailable(
            "no available provider for slice %r (need capability>=%d, budget=%s, available=%s)"
            % (slc.get("slice_id"), need, budget, sorted(avail)))
    # cheapest first; ties broken toward the more capable model, then by name for determinism
    cands.sort(key=lambda e: (float(e.get("cost_per_slice") or 0.0),
                              -int(e.get("capability") or 0),
                              str(e.get("provider"))))
    return cands[0]


def select_reviewer(slc, catalog, available, implementer_provider, task_class=None):
    """Pick a reviewer. For independence-required classes the implementing family
    is excluded; otherwise a same-family reviewer is acceptable."""
    tclass = str(task_class or slc.get("task_class") or "").lower()
    exclude = (implementer_provider,) if tclass in INDEPENDENT_REVIEW_CLASSES else ()
    return select_route(slc, catalog, available, exclude_families=exclude)


def requires_independent_reviewer(task_class):
    return str(task_class or "").lower() in INDEPENDENT_REVIEW_CLASSES


# --------------------------------------------------------------------------
# deviation + escalation
# --------------------------------------------------------------------------

def plan_deviation(slc, actual_files):
    """{'unplanned': [...], 'unwritten': [...], 'within_scope': bool}."""
    planned = _scope(slc)
    actual = {str(p).strip().lstrip("./") for p in (actual_files or []) if str(p).strip()}
    unplanned = sorted(actual - planned)
    unwritten = sorted(planned - actual)
    return {"unplanned": unplanned, "unwritten": unwritten, "within_scope": not unplanned}


def assert_within_scope(slc, actual_files):
    """Executors may not silently widen scope — this is the enforcement point."""
    dev = plan_deviation(slc, actual_files)
    if not dev["within_scope"]:
        raise ContractViolation(
            "slice %r touched files outside its signed scope: %s"
            % (slc.get("slice_id"), ", ".join(dev["unplanned"])))
    return dev


def should_escalate(evidence):
    """Evidence-driven: low confidence, a contract violation, missing context, or
    a failing proof all mean 'replan', not 'improvise'."""
    ev = evidence or {}
    if ev.get("contract_violation"):
        return True
    if ev.get("missing_context"):
        return True
    if ev.get("tests_failed"):
        return True
    conf = ev.get("confidence")
    if conf is not None and float(conf) <= ESCALATION_CONFIDENCE:
        return True
    return False


def escalation_request(slc, evidence, note=None):
    """A *targeted* replanning ask — names the slice and the reason, so the
    council replans one slice instead of the whole plan."""
    ev = evidence or {}
    reasons = []
    if ev.get("contract_violation"):
        reasons.append("contract_violation")
    if ev.get("missing_context"):
        reasons.append("missing_context")
    if ev.get("tests_failed"):
        reasons.append("tests_failed")
    if ev.get("confidence") is not None and float(ev["confidence"]) <= ESCALATION_CONFIDENCE:
        reasons.append("low_confidence")
    return {
        "slice_id": slc.get("slice_id"),
        "scope": "slice",
        "reasons": reasons,
        "confidence": ev.get("confidence"),
        "note": str(note or "")[:2000],
    }


# --------------------------------------------------------------------------
# execution receipts + cost accounting
# --------------------------------------------------------------------------

def execution_receipt(plan, slc, provider, model, actual_files, cost_usd=0.0,
                      latency_s=0.0, tests=None, tests_passed=None, state=None,
                      reviewer_provider=None):
    """Planned-vs-actual receipt. Never raises — deviations are recorded, and
    enforcement is the caller's decision via assert_within_scope()."""
    dev = plan_deviation(slc, actual_files)
    return {
        "plan_id": plan.get("plan_id"),
        "plan_digest": plan.get("digest"),
        "plan_verified": verify_plan(plan),
        "slice_id": slc.get("slice_id"),
        "provider": provider,
        "model": model,
        "reviewer_provider": reviewer_provider,
        "reviewer_independent": (
            _family(reviewer_provider) != _family(provider) if reviewer_provider else None),
        "planned_files": sorted(_scope(slc)),
        "actual_files": sorted({str(p).strip().lstrip("./") for p in (actual_files or []) if str(p).strip()}),
        "deviation": dev,
        "cost_usd": round(float(cost_usd or 0.0), 6),
        "latency_s": round(float(latency_s or 0.0), 3),
        "tests": list(tests or []),
        "tests_passed": tests_passed,
        "state": state,
        "recorded_at": time.time(),
    }


def cost_per_deployed_and_verified(receipts):
    """Total spend divided by receipts that actually reached DEPLOYED_AND_VERIFIED.

    Spend on abandoned work is counted in the numerator on purpose: the fleet's
    real unit economics include everything it paid for and did not ship.
    """
    rows = list(receipts or [])
    total = sum(float(r.get("cost_usd") or 0.0) for r in rows)
    verified = sum(1 for r in rows if str(r.get("state") or "").upper() == "DEPLOYED_AND_VERIFIED")
    return {
        "receipts": len(rows),
        "verified": verified,
        "total_cost_usd": round(total, 6),
        "cost_per_verified_usd": (round(total / verified, 6) if verified else None),
        "wasted_cost_usd": round(
            sum(float(r.get("cost_usd") or 0.0) for r in rows
                if str(r.get("state") or "").upper() != "DEPLOYED_AND_VERIFIED"), 6),
    }

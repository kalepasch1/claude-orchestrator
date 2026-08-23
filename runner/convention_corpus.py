#!/usr/bin/env python3
"""
convention_corpus.py — the circular hivemind: cross-tenant learning with the
privacy gates that make it safe to switch on.

WHAT CROSSES AND WHAT NEVER DOES
--------------------------------
CONVENTIONS cross. Code does not. A distilled rule like "public functions return
sensible defaults rather than raising" is portable and carries no customer
information; a diff hunk carries both. So `contribute()` accepts a distilled
convention and stores no code, and `_strip_provenance()` removes the identifying
residue that survives distillation anyway — repo names, paths, hostnames,
emails, URLs, ticket ids, and the tenant's own name.

THREE GATES, ALL OF WHICH MUST PASS
-----------------------------------
1. OPT-IN. A tenant contributes only if it explicitly said yes. The default is
   no, and an absent config is a no rather than an unset that resolves to yes.
2. K-ANONYMITY FLOOR. A pattern is surfaced across tenants only once at least
   K_FLOOR (3) DISTINCT tenants have independently contributed it. One tenant
   repeating itself ten times is still one tenant — the floor counts distinct
   contributors, not rows, and that distinction is the whole guarantee.
3. PROVENANCE STRIPPING, applied before storage, not before reading. Data that
   arrives identifying is already a leak; no downstream care fixes it.

Own patterns are ALWAYS available to their own tenant, opt-in or not: a tenant
consulting its own conventions is not cross-tenant learning.

Fail-soft per repo convention: every public function returns a sensible default
rather than raising, and a storage outage degrades retrieval to "own patterns
only" rather than wedging the planner.
"""
import hashlib
import os
import re
import sys
import threading
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

#: Distinct tenants required before a pattern may be surfaced cross-tenant.
K_FLOOR = int(os.environ.get("ORCH_CORPUS_K_FLOOR", "3"))

#: Salt for the cohort key. Without a stable secret the key is still non-
#: reversible, but rotating it re-partitions cohorts, so it lives in env.
COHORT_SALT = os.environ.get("ORCH_CORPUS_COHORT_SALT", "madeus-corpus")

MAX_TEXT = 2000


# ── Provenance stripping ────────────────────────────────────────────────────

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_URL = re.compile(r"https?://\S+")
_PATH = re.compile(r"(?:/[\w.-]+){2,}/?")
_GH_REPO = re.compile(r"\b[\w-]+/[\w.-]+\b(?=\s|$|[.,;:])")
_TICKET = re.compile(r"\b[A-Z]{2,10}-\d{1,6}\b")
_SHA = re.compile(r"\b[0-9a-f]{7,40}\b")


def _strip_provenance(text: Optional[str], tenant_id: Optional[str] = None) -> str:
    """Remove the identifying residue that survives distillation.

    Order matters: URLs before paths (a URL contains slashes), and the tenant's
    own name last so a tenant literally called "https" cannot break the earlier
    patterns.
    """
    if not text or not isinstance(text, str):
        return ""
    out = text
    out = _EMAIL.sub("<email>", out)
    out = _URL.sub("<url>", out)
    out = _PATH.sub("<path>", out)
    out = _TICKET.sub("<ticket>", out)
    out = _SHA.sub("<sha>", out)
    out = _GH_REPO.sub("<repo>", out)
    if tenant_id:
        out = re.sub(re.escape(tenant_id), "<tenant>", out, flags=re.IGNORECASE)
    return out.strip()[:MAX_TEXT]


def cohort_key(tenant_id: str, salt: str = COHORT_SALT) -> str:
    """Opaque, non-reversible grouping key for a tenant."""
    return hashlib.sha256(f"{salt}:{tenant_id}".encode("utf-8")).hexdigest()[:32]


def pattern_key(convention: str) -> str:
    """Stable identity of a convention, independent of wording noise.

    Case, punctuation and whitespace are normalised so "DO fail soft." and
    "do fail soft" count as the SAME pattern across tenants — otherwise the
    k-floor never trips and the corpus never surfaces anything.
    """
    norm = re.sub(r"[^a-z0-9 ]+", " ", (convention or "").lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]


# ── Storage seam ────────────────────────────────────────────────────────────

class _Store:
    """In-process store with a DB seam.

    Tests drive the in-memory path; production points `backend` at the
    convention_corpus table. Kept behind a lock because the runner is threaded.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: List[Dict[str, Any]] = []

    def add(self, row: Dict[str, Any]) -> None:
        with self._lock:
            self._rows.append(row)

    def all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._rows)

    def clear(self) -> None:
        with self._lock:
            self._rows = []


_store = _Store()


# ── Opt-in ──────────────────────────────────────────────────────────────────

def _opted_in(tenant_id: str, config: Optional[Dict[str, Any]]) -> bool:
    """Explicit yes only. Absent config is NO, not unset-means-yes."""
    if not isinstance(config, dict):
        return False
    return config.get("corpus_opt_in") is True


# ── Contribution ────────────────────────────────────────────────────────────

def contribute(tenant_id: str, convention: str, category: str = "general",
               config: Optional[Dict[str, Any]] = None,
               outcome_score: float = 0.0) -> Dict[str, Any]:
    """Store one distilled convention. Returns {'stored': bool, 'reason': str}.

    Never raises. A refusal is reported so an operator can see WHY a tenant is
    not contributing rather than assuming the corpus is empty.
    """
    if not tenant_id or not isinstance(convention, str) or not convention.strip():
        return {"stored": False, "reason": "tenant_id and convention are required"}
    if not _opted_in(tenant_id, config):
        return {"stored": False, "reason": "tenant has not opted in to the corpus"}

    cleaned = _strip_provenance(convention, tenant_id)
    if not cleaned:
        return {"stored": False, "reason": "convention was empty after provenance stripping"}

    try:
        score = float(outcome_score)
    except (TypeError, ValueError):
        score = 0.0

    _store.add({
        "pattern_key": pattern_key(cleaned),
        "cohort_key": cohort_key(tenant_id),
        # The tenant id is kept for OWN-tenant retrieval only and never leaves
        # this process in a cross-tenant result — see retrieve().
        "tenant_id": tenant_id,
        "category": str(category or "general")[:64],
        "convention": cleaned,
        "outcome_score": max(0.0, min(1.0, score)),
    })
    return {"stored": True, "reason": ""}


# ── Retrieval ───────────────────────────────────────────────────────────────

def _distinct_tenants(rows: List[Dict[str, Any]], key: str) -> int:
    return len({r.get("tenant_id") for r in rows if r.get("pattern_key") == key})


def retrieve(tenant_id: str, category: Optional[str] = None,
             config: Optional[Dict[str, Any]] = None,
             limit: int = 20) -> List[Dict[str, Any]]:
    """Conventions available to `tenant_id`, ranked by outcome then breadth.

    OWN patterns always. CROSS-TENANT patterns only when the tenant opted in AND
    the pattern clears the k-anonymity floor. Results never carry another
    tenant's identity — cross-tenant rows expose `tenant_count`, not who.
    """
    if not tenant_id:
        return []
    try:
        rows = _store.all()
    except Exception:  # noqa: BLE001 — degrade to nothing rather than wedge
        return []

    if category:
        rows = [r for r in rows if r.get("category") == category]

    own = [r for r in rows if r.get("tenant_id") == tenant_id]
    own_keys = {r["pattern_key"] for r in own}
    out: Dict[str, Dict[str, Any]] = {}
    for r in own:
        out[r["pattern_key"]] = {
            "convention": r["convention"], "category": r["category"],
            "source": "own", "tenant_count": 1,
            "outcome_score": r.get("outcome_score", 0.0),
        }

    if _opted_in(tenant_id, config):
        for r in rows:
            key = r["pattern_key"]
            if key in out:
                # Only OUR OWN pattern can be "corroborated" by others. A
                # cross-tenant pattern seen twice is still cross-tenant — the
                # earlier version of this branch relabelled it and quietly
                # implied we had contributed it ourselves.
                count = _distinct_tenants(rows, key)
                if count >= K_FLOOR:
                    out[key]["tenant_count"] = count
                    if key in own_keys:
                        out[key]["source"] = "corroborated"
                continue
            count = _distinct_tenants(rows, key)
            if count < K_FLOOR:
                continue  # k-floor: not enough distinct tenants to be anonymous
            out[key] = {
                "convention": r["convention"], "category": r["category"],
                "source": "cross_tenant", "tenant_count": count,
                "outcome_score": r.get("outcome_score", 0.0),
            }

    ranked = sorted(out.values(),
                    key=lambda x: (x["outcome_score"], x["tenant_count"]), reverse=True)
    return ranked[: max(0, int(limit or 0))]


# ── steering_events -> planner hints ────────────────────────────────────────

def steering_hints(events: Optional[List[Dict[str, Any]]], min_observations: int = 3) -> List[Dict[str, Any]]:
    """Which kinds of human steering correlate with first-pass merge success.

    Correlation, not causation, and labelled as such: this ranks event types by
    observed first-pass merge rate so the planner can PREFER the ones that have
    historically preceded clean merges. Anything below `min_observations` is
    dropped rather than shown with a confident-looking rate computed from two
    data points.
    """
    if not isinstance(events, list):
        return []
    agg: Dict[str, Dict[str, int]] = {}
    for e in events:
        if not isinstance(e, dict):
            continue
        et = e.get("event_type")
        if not et:
            continue
        bucket = agg.setdefault(et, {"n": 0, "merged": 0})
        bucket["n"] += 1
        if e.get("first_pass_merged") is True:
            bucket["merged"] += 1

    hints = []
    for et, b in agg.items():
        if b["n"] < min_observations:
            continue
        hints.append({
            "event_type": et,
            "observations": b["n"],
            "first_pass_merge_rate": round(b["merged"] / b["n"], 4),
            "basis": "observed correlation, not causation",
        })
    return sorted(hints, key=lambda h: h["first_pass_merge_rate"], reverse=True)


# ── Flywheel KPI ────────────────────────────────────────────────────────────

def flywheel_kpi(tenant_id: str, history: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Pattern-reuse rate and first-pass merge rate over time.

    `history` is a list of per-period dicts:
        {period, tasks, tasks_reusing_pattern, first_pass_merges}

    Returns per-period rates plus a `trend` of the last period vs the first.
    Division by zero yields 0.0, not NaN: a dashboard that renders NaN is a
    dashboard nobody trusts again.
    """
    periods = []
    if isinstance(history, list):
        for h in history:
            if not isinstance(h, dict):
                continue
            tasks = max(0, int(h.get("tasks") or 0))
            reuse = max(0, int(h.get("tasks_reusing_pattern") or 0))
            merges = max(0, int(h.get("first_pass_merges") or 0))
            periods.append({
                "period": h.get("period"),
                "tasks": tasks,
                "pattern_reuse_rate": round(reuse / tasks, 4) if tasks else 0.0,
                "first_pass_merge_rate": round(merges / tasks, 4) if tasks else 0.0,
            })

    trend = {"pattern_reuse_delta": 0.0, "first_pass_merge_delta": 0.0}
    if len(periods) >= 2:
        trend = {
            "pattern_reuse_delta": round(
                periods[-1]["pattern_reuse_rate"] - periods[0]["pattern_reuse_rate"], 4),
            "first_pass_merge_delta": round(
                periods[-1]["first_pass_merge_rate"] - periods[0]["first_pass_merge_rate"], 4),
        }

    return {"tenant_id": tenant_id, "periods": periods, "trend": trend,
            "getting_smarter": trend["first_pass_merge_delta"] > 0 or trend["pattern_reuse_delta"] > 0}


# ── Test/ops seams ──────────────────────────────────────────────────────────

def _reset() -> None:
    """Clear the in-process store. Tests only."""
    _store.clear()


def stats() -> Dict[str, Any]:
    rows = _store.all()
    return {"rows": len(rows), "patterns": len({r["pattern_key"] for r in rows}),
            "tenants": len({r["tenant_id"] for r in rows}), "k_floor": K_FLOOR}

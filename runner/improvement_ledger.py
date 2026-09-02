#!/usr/bin/env python3
"""improvement_ledger.py — REQUIREMENTS A(emit), F(honest scoring), G(semantic dedupe).

WHAT CHANGED AND WHY
--------------------
F. HONEST SCORING. The old score was `impact x feasibility x (1+log10(1+mrr)) x surf_boost`
   where impact and feasibility were self-reported by the same model that invented the idea
   and the two trailing factors had been a constant 1.0 since inception (surface_returns and
   merge_revenue have always had ZERO rows). 713 of 934 proposals shared three score values.
   Here scoring is REALIZED-DELTA-ONLY: rank by the measured multipliers that comparable past
   proposals actually achieved. When there is no realized history, `score()` REFUSES — it
   returns score=None with score_basis='refused' and a reason, instead of silently
   multiplying by 1.0 and producing a fake ordering. Ranking then falls back to measured
   HEADROOM, which is arithmetic on telemetry, not an opinion.

G. SEMANTIC DEDUPE. Title-equality let 26.1% duplicates through. Dedupe is now against
   shipped AND regressed history on a normalised token signature of title+proposal+metric,
   with a Jaccard threshold — so a re-worded restatement of something already tried (and
   especially something already REGRESSED) is blocked.

B. SLUGS. Full-length, collision-free, uniqueness-checked against the DB before insert.
   The old `"improve-" + title[:40]` produced 48-char slugs and 40.6% collisions, silently
   merging distinct proposals onto one task.
"""
import hashlib
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import gate_liveness

DEDUPE_GATE = "improvement_dedupe_gate"
DEDUPE_THRESHOLD = float(os.environ.get("ORCH_IMPROVE_DEDUPE_JACCARD", "0.6"))
MIN_CALIBRATION_N = int(os.environ.get("ORCH_IMPROVE_MIN_CALIBRATION_N", "3"))
WINDOW_HOURS = int(os.environ.get("ORCH_IMPROVE_WINDOW_HOURS", "72"))

_STOP = {"the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "by", "with", "at",
         "is", "are", "be", "that", "this", "it", "as", "from", "into", "via", "per",
         "improve", "improvement", "better", "faster", "reduce", "increase", "add", "make",
         "system", "orchestrator", "pipeline", "task", "tasks"}


# ------------------------------------------------------------------ G: semantic dedupe
def signature(text):
    """Normalised token set: lowercase, alphanumeric, stopword- and stem-ish-stripped."""
    toks = re.findall(r"[a-z0-9]+", (text or "").lower())
    out = set()
    for t in toks:
        if len(t) < 3 or t in _STOP:
            continue
        for suf in ("ing", "ed", "es", "s"):
            if len(t) > 5 and t.endswith(suf):
                t = t[: -len(suf)]
                break
        out.add(t)
    return out


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedupe_key(app, surface, metric_name, title):
    raw = "|".join(str(x or "") for x in (app, surface, metric_name, " ".join(sorted(signature(title)))))
    return hashlib.sha1(raw.encode()).hexdigest()[:32]


#: Statuses that mean "nobody ever acted on this". They are an intake queue, not a
#: result -- unlike merged / shipped / validated / regressed / SUPERSEDED, which are
#: evidence about what happens when you try the idea.
_INERT_STATUSES = frozenset({"proposed", "for_review", "", "none"})


def stale_proposal_days():
    """How long an unacted proposal keeps blocking a fresh one. 0 disables the expiry."""
    try:
        return max(0, int(os.environ.get("ORCH_IMPROVE_STALE_PROPOSAL_DAYS", "21")))
    except (TypeError, ValueError):
        return 21


def _age_days(row):
    """Days since this proposal was created, or None when that cannot be read."""
    raw = str((row or {}).get("created_at") or "").strip()
    if not raw:
        return None
    text = raw.replace("Z", "+00:00")
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        try:
            when = datetime.fromisoformat(text[:19])
        except ValueError:
            return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return (now - when).total_seconds() / 86400.0


def is_inert(row, max_age_days=None):
    """True when this proposal is an unacted note old enough to stop blocking new work.

    A proposal that REACHED AN OUTCOME blocks forever, and should: merged, shipped,
    validated, regressed and SUPERSEDED are all evidence about what happens when the idea
    is tried, and re-proposing it would be re-doing settled work.

    A proposal still sitting in `proposed` or `for_review` is not evidence of anything.
    Nobody acted on it. Blocking on it means the bottleneck it describes can never be
    raised again, however bad it gets.

    Measured 2026-09-02 across 1,004 proposals:

        merged        395   (all of them older than 21 days)
        proposed      315   oldest 2026-07-13, 314 older than 21 days
        SUPERSEDED    197
        for_review     65   64 older than 21 days
        shipped        21
        reviewed       10
        validated       1   -- one, ever

    So 378 proposals that never reached an outcome were permanently suppressing the
    fleet's ability to re-raise the problems they describe, while exactly one proposal in
    the table's history was ever validated.
    """
    max_age_days = stale_proposal_days() if max_age_days is None else max_age_days
    if not max_age_days:
        return False
    if str((row or {}).get("status") or "").strip().lower() not in _INERT_STATUSES:
        return False
    age = _age_days(row)
    return age is not None and age > max_age_days


def _history(app, limit=3000):
    """Everything already tried for this app — INCLUDING regressed, so failures aren't retried."""
    return db.select("improvement_proposals", {
        "select": ("id,app,surface,title,proposal,metric_name,status,dedupe_key,"
                   "realized_multiplier,created_at"),
        "app": f"eq.{app}", "limit": str(limit)}) or []


def is_duplicate(cand, history=None, threshold=DEDUPE_THRESHOLD):
    """True when `cand` semantically restates something already proposed/shipped/regressed."""
    history = _history(cand.get("app")) if history is None else history
    key = cand.get("dedupe_key") or dedupe_key(
        cand.get("app"), cand.get("surface"), cand.get("metric_name"), cand.get("title"))
    csig = signature(f"{cand.get('title','')} {cand.get('proposal','')} {cand.get('metric_name','')}")
    for h in history:
        # An unacted proposal past its expiry is a note, not a result. See is_inert.
        if is_inert(h):
            continue
        if h.get("dedupe_key") and h["dedupe_key"] == key:
            gate_liveness.record(DEDUPE_GATE, "duplicate_key", cand.get("title"), h.get("status"))
            return {"duplicate": True, "why": "identical dedupe_key",
                    "of": h.get("title"), "status": h.get("status")}
        hsig = signature(f"{h.get('title','')} {h.get('proposal','')} {h.get('metric_name','')}")
        j = jaccard(csig, hsig)
        if j >= threshold:
            gate_liveness.record(DEDUPE_GATE, "duplicate_semantic", cand.get("title"),
                                 f"j={j:.2f} vs {h.get('status')}")
            return {"duplicate": True, "why": f"semantic overlap {j:.2f} >= {threshold}",
                    "of": h.get("title"), "status": h.get("status")}
    gate_liveness.record(DEDUPE_GATE, "novel", cand.get("title"))
    return {"duplicate": False}


# ------------------------------------------------------------------- B: collision-free slug
def make_slug(title, bottleneck_key, existing=None):
    """Full-length, deterministic, uniqueness-checked. Never truncated to a colliding prefix."""
    body = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    base = f"improve-{bottleneck_key}-{body}".strip("-")
    # A short content hash guarantees distinctness even for identical prose, and is
    # appended AFTER the full body so nothing is lost to truncation.
    h = hashlib.sha1(f"{bottleneck_key}|{title}".encode()).hexdigest()[:8]
    slug = f"{base}-{h}"
    if existing is None:
        existing = {r["task_slug"] for r in (db.select("improvement_proposals", {
            "select": "task_slug", "task_slug": "not.is.null", "limit": "5000"}) or [])
            if r.get("task_slug")}
    if slug not in existing:
        return slug
    for i in range(2, 100):
        alt = f"{slug}-{i}"
        if alt not in existing:
            return alt
    raise RuntimeError(f"could not allocate a unique slug for {title!r}")


# -------------------------------------------------------------------- F: honest scoring
def realized_returns(surface=None, metric_name=None):
    """Realized multipliers from the calibration ledger — the ONLY legitimate ranking signal."""
    params = {"select": "surface,metric_name,realized_multiplier,outcome", "limit": "5000"}
    if surface:
        params["surface"] = f"eq.{surface}"
    rows = db.select("improvement_calibration", params) or []
    vals = [float(r["realized_multiplier"]) for r in rows
            if r.get("realized_multiplier") is not None
            and (not metric_name or r.get("metric_name") == metric_name)]
    return vals


def score(cand, min_n=MIN_CALIBRATION_N):
    """Rank by REALIZED deltas. Refuse — loudly — when there is no realized history.

    Returns {'score', 'basis', 'reason'}. `score` is None when basis == 'refused'.
    Self-reported impact/feasibility are NOT accepted here and are not read at all.
    """
    vals = realized_returns(cand.get("surface"), cand.get("metric_name"))
    if len(vals) < min_n:
        vals = realized_returns(cand.get("surface"))
    if len(vals) < min_n:
        return {"score": None, "basis": "refused",
                "reason": (f"only {len(vals)} realized outcome(s) for surface="
                           f"{cand.get('surface')}; need {min_n}. REFUSING to score: the "
                           "returns table is empty, so any number here would be fabricated. "
                           "Ranking falls back to measured headroom.")}
    avg = sum(vals) / len(vals)
    return {"score": round(avg * float(cand.get("headroom_multiplier") or 1.0), 3),
            "basis": "realized_delta",
            "reason": f"mean realized {avg:.2f}x over n={len(vals)} x measured headroom"}


def rank(cands):
    """Order candidates. Realized-delta scores first; otherwise measured headroom.

    Ordering by headroom is the "aim at order-of-magnitude gains" rule made concrete:
    a bottleneck with 143x of measured headroom outranks one with 2.2x, because the
    arithmetic says so — not because a model typed "500x".
    """
    scored = []
    for c in cands:
        s = score(c)
        c = dict(c, score=s["score"], score_basis=s["basis"], score_reason=s["reason"])
        scored.append(c)
    refused = [c for c in scored if c["score"] is None]
    if refused:
        print(f"[improvement_ledger] REFUSED to score {len(refused)}/{len(scored)} candidates: "
              f"{refused[0]['score_reason']}")
    scored.sort(key=lambda c: (c["score"] if c["score"] is not None else -1,
                               float(c.get("headroom_multiplier") or 0)), reverse=True)
    return scored


# ---------------------------------------------------- A: emit a proposal from a bottleneck
def build_proposal(b, app, title=None, proposal_text=None, predicted_multiplier=None,
                   window_hours=WINDOW_HOURS, required_margin=None):
    """Turn a MEASURED bottleneck into a proposal row carrying its own falsification test."""
    key = b["bottleneck_key"]
    headroom = float(b["headroom_multiplier"])
    title = title or f"Cut {b['metric_name']} ({b['value']} -> target) at the {key} bottleneck"
    # A prediction may not exceed the measured headroom — that is the whole anti-"100x" rule.
    pred = min(float(predicted_multiplier or min(headroom, 10.0)), headroom)
    comparator = b["comparator"]
    baseline = float(b["value"])
    target = (round(baseline / pred, 4) if comparator == "lt" else round(baseline * pred, 4))
    now = datetime.now(timezone.utc)
    row = {
        "app": app, "surface": b["surface"], "title": title[:200],
        "current_state": b["detail"][:600],
        "proposal": (proposal_text or
                     f"Reduce the {key} bottleneck. Ship behind flag "
                     f"ORCH_FLAG_{key.upper()} and hold the change to its target.")[:1500],
        "rationale": (f"Originates from a measured bottleneck, not a template. "
                      f"{b['metric_name']} = {baseline} over n={b['sample_n']}; ideal "
                      f"{b['ideal_value']} implies {headroom}x of headroom.")[:800],
        "status": "proposed", "divergent": False,
        "bottleneck_key": key, "metric_name": b["metric_name"],
        "metric_collector": b["metric_collector"], "metric_query": b["metric_query"],
        "baseline_value": baseline, "target_value": target, "comparator": comparator,
        "required_margin": float(required_margin or max(1.10, pred * 0.5)),
        "predicted_multiplier": pred, "expected_multiplier": f"{pred:g}x",
        "headroom_multiplier": headroom,
        "evaluate_after": (now + timedelta(hours=window_hours)).isoformat(),
        "feature_flag": f"ORCH_FLAG_{key.upper()}",
        "dedupe_key": dedupe_key(app, b["surface"], b["metric_name"], title),
        "slug_v2": True,
    }
    s = score(dict(row, headroom_multiplier=headroom))
    row["score"] = s["score"]
    row["score_basis"] = s["basis"]
    row["rationale"] = (row["rationale"] + f" Scoring: {s['reason']}")[:800]
    return row


REQUIRE_PREDICTION = os.environ.get(
    "ORCH_IMPROVE_REQUIRE_PREDICTION", "true").strip().lower() in ("1", "true", "yes", "on")


def is_falsifiable(row):
    """True if this proposal can later be proved wrong.

    improvement_verify.evaluate() re-runs `metric_query` after the window and compares
    the result to `baseline_value` using `comparator` and `required_margin`. Without all
    four, there is no verdict to reach -- the proposal is unfalsifiable by construction
    and 'did it add value?' can never be answered for it.
    """
    if not str(row.get("metric_query") or "").strip():
        return False
    if not str(row.get("comparator") or "").strip():
        return False
    return row.get("baseline_value") is not None and row.get("required_margin") is not None


def queue(row, existing_slugs=None):
    """Dedupe (G), allocate a collision-free slug (B), insert. Returns the row or None."""
    # 2026-09-01: of 1003 proposals, 814 (all of July) carried NO metric_query, baseline,
    # comparator or margin. Their code merged; whether any of it helped is permanently
    # unknowable. Exactly one proposal in the table has ever been 'validated'. An
    # improvement that cannot be measured is not an improvement, it is a change -- refuse
    # to queue it. Set ORCH_IMPROVE_REQUIRE_PREDICTION=false to restore the old behaviour.
    if REQUIRE_PREDICTION and not is_falsifiable(row):
        missing = [f for f, ok in (
            ("metric_query", str(row.get("metric_query") or "").strip()),
            ("comparator", str(row.get("comparator") or "").strip()),
            ("baseline_value", row.get("baseline_value") is not None),
            ("required_margin", row.get("required_margin") is not None)) if not ok]
        print(f"[improvement_ledger] REFUSED (unfalsifiable): {str(row.get('title'))[:60]!r} "
              f"— missing {', '.join(missing)}. Nothing could ever prove this helped, so it "
              f"is not queued. This is the correct outcome, not a failure.")
        return None
    dup = is_duplicate(row)
    if dup["duplicate"]:
        print(f"[improvement_ledger] dedupe: skipping {row['title'][:60]!r} — "
              f"{dup['why']} with {dup['status']!r} proposal {str(dup['of'])[:60]!r}")
        return None
    row = dict(row)
    row["task_slug"] = make_slug(row["title"], row["bottleneck_key"], existing_slugs)
    db.insert("improvement_proposals", row)
    return row


if __name__ == "__main__":
    import bottleneck_detector, json
    found = bottleneck_detector.detect(persist=False)
    print(json.dumps(rank([dict(b, app="beethoven") for b in found])[:3], indent=2, default=str))

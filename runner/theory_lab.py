#!/usr/bin/env python3
"""theory_lab.py — TEST THE THEORIES: resolve staked forecasts and verify doctrine claims.

THE DEFECT (2026-09-11). The corps had staked 1,000 dated positions (expert_positions) and not
one had ever been resolved; brier_n was 0 on all 155 experts. Elo (who argues well) had 6,422
bouts of signal; Brier (who is RIGHT) had none. The module docstrings say both are needed —
"an expert can win arguments for years while being consistently wrong, and only the Brier
column catches it" — and the column was empty. Likewise expert_memory held 1,000+ "research"
claims with zero source URLs: theories nobody had tested.

TWO LOOPS, BOTH BOUNDED AND WEB-GROUNDED (frontier.py, Opus tier with WebSearch/WebFetch):

  1. POSITION RESOLUTION. For a docket question with unresolved staked theses, ask: is this
     question presently SETTLED by authority a regulator or court has actually issued (statute,
     rule, controlling opinion, formal guidance)? If yes — with the URL — each thesis resolves
     true/false and expert_corps.resolve_position() scores it (Brier), which is what puts
     miscalibrated experts on probation. If not settled, record the next check date. The
     resolver is told that "not settled" is the honest default: it must not manufacture a
     resolution to look productive.

  2. CLAIM VERIFICATION. Take the highest-salience unsourced research claims and try to OPEN a
     primary source for each. Verified -> source_url + quote written back (this is what evolve()
     now requires to advance a generation). Refuted -> kind='refuted', salience floored, so the
     claim stops feeding seat prompts. Unverifiable -> salience halved.

Every outcome is a row a human can audit; nothing here changes a card, a docket status or a
publication state. Fail-soft throughout.
"""
from __future__ import annotations
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import common_utils
import expert_corps as corps
import frontier

_s = common_utils.safe_string_coerce
GROUPS_PER_RUN = int(os.environ.get("ORCH_THEORY_LAB_GROUPS", "4"))
CLAIMS_PER_RUN = int(os.environ.get("ORCH_THEORY_LAB_CLAIMS", "8"))

RESOLVE_SCHEMA = {"type": "object", "properties": {
    "settled": {"type": "boolean"}, "basis": {"type": "string"}, "url": {"type": "string"},
    "quote": {"type": "string"},
    "resolutions": {"type": "array", "items": {"type": "object", "properties": {
        "position_id": {"type": "string"}, "outcome": {"type": "string"}, "why": {"type": "string"}},
        "required": ["position_id", "outcome", "why"]}},
    "next_check_days": {"type": "integer"}},
    "required": ["settled", "basis", "url", "quote", "resolutions", "next_check_days"]}

RESOLVE = """You are the RESOLVER for a calibration ledger. Experts staked dated theses on the question below.
Decide, using WebSearch/WebFetch to OPEN primary authority, whether the question is presently
SETTLED — i.e. a statute, regulation, controlling court opinion, or formal agency guidance/order
now answers it for the stated jurisdiction(s). "Not settled" is the honest default; do NOT
manufacture a resolution. A thesis resolves TRUE only if the settled authority says what the
thesis says; FALSE only if it contradicts it; otherwise "indeterminate".

QUESTION: {question}
TODAY: {today}
THESES:
{theses}

Return ONLY JSON: {{"settled":bool,"basis":"the authority that settles it, or why it is not settled",
"url":"URL you opened (or \\"\\")","quote":"<=40 words verbatim (or \\"\\")",
"resolutions":[{{"position_id":"...","outcome":"true|false|indeterminate","why":"..."}}],
"next_check_days":int}}"""

VERIFY_SCHEMA = {"type": "object", "properties": {
    "results": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "status": {"type": "string"}, "url": {"type": "string"},
        "quote": {"type": "string"}, "note": {"type": "string"}},
        "required": ["id", "status", "url", "quote", "note"]}}},
    "required": ["results"]}

VERIFY = """You are a cite-checker. For each claim below, try to OPEN a primary source (statute, rule, court
opinion, agency guidance, official dataset) with WebSearch/WebFetch that VERIFIES or REFUTES it.
Status is "verified" only if you opened a page that supports the claim (give the URL and a <=30 word
verbatim quote); "refuted" only if an opened source contradicts it; else "unverifiable". Do not
guess URLs; do not mark verified from memory.

TODAY: {today}
CLAIMS:
{claims}

Return ONLY JSON: {{"results":[{{"id":"...","status":"verified|refuted|unverifiable","url":"...","quote":"...","note":"..."}}]}}"""


def _unresolved_groups(limit_groups):
    rows = db.select("expert_positions", {
        "select": "id,expert_id,docket_id,question,thesis,probability,created_at,resolves_by",
        "resolved": "eq.false", "order": "created_at.asc", "limit": "400"}) or []
    groups, order = {}, []
    for r in rows:
        key = r.get("docket_id") or (r.get("question") or "")[:160]
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(r)
    # Prefer groups with real disagreement — that is where a resolution teaches the most.
    def spread(g):
        ps = [float(x.get("probability") or 0.5) for x in g]
        return (max(ps) - min(ps)) if ps else 0
    keys = sorted(order, key=lambda k: (-spread(groups[k]), k))
    return [(k, groups[k]) for k in keys[:limit_groups]]


def resolve_positions(limit_groups=GROUPS_PER_RUN):
    out = {"groups": 0, "settled": 0, "resolved": 0, "indeterminate": 0, "skipped": 0}
    if not frontier.available(min_tokens=15000):
        out["skipped"] = "frontier unavailable"
        return out
    for key, group in _unresolved_groups(limit_groups):
        q = group[0].get("question") or ""
        theses = "\n".join(f"- position_id={g['id']} (p={g.get('probability')}): {_s(g.get('thesis'))[:400]}"
                           for g in group[:8])
        r = frontier.complete(RESOLVE.format(question=q[:2000], today=datetime.date.today().isoformat(),
                                             theses=theses),
                              need=8, tools=frontier.WEB_TOOLS, max_turns=10, json_schema=RESOLVE_SCHEMA,
                              tag="theory_lab.resolve")
        j = r.get("json")
        out["groups"] += 1
        if r.get("error") or not isinstance(j, dict):
            continue
        if not j.get("settled"):
            out["indeterminate"] += 1
            continue
        out["settled"] += 1
        by_id = {g["id"]: g for g in group}
        for res in (j.get("resolutions") or []):
            pid = str(res.get("position_id") or "")
            oc = str(res.get("outcome") or "").lower()
            if pid not in by_id or oc not in ("true", "false"):
                continue
            brier = corps.resolve_position(pid, oc == "true")
            if brier is not None:
                out["resolved"] += 1
                try:
                    db.insert("expert_memory", {
                        "expert_id": by_id[pid]["expert_id"], "kind": "resolution",
                        "claim": (f"Resolved {oc.upper()} on '{q[:120]}': {_s(j.get('basis'))[:300]} "
                                  f"— {_s(res.get('why'))[:200]}")[:2000],
                        "source": _s(j.get("basis"))[:500] or None,
                        "source_url": (_s(j.get("url"))[:500] or None),
                        "salience": 0.9, "generation": 1})
                except Exception:
                    pass
        print(f"theory_lab: '{q[:70]}' settled={j.get('settled')} basis={_s(j.get('basis'))[:90]}", flush=True)
    return out


def verify_claims(limit=CLAIMS_PER_RUN):
    out = {"checked": 0, "verified": 0, "refuted": 0, "unverifiable": 0, "skipped": 0}
    if not frontier.available(min_tokens=15000):
        out["skipped"] = "frontier unavailable"
        return out
    rows = db.select("expert_memory", {
        "select": "id,expert_id,claim,source,salience", "kind": "eq.research",
        "source_url": "is.null", "salience": "gte.0.5", "order": "salience.desc,created_at.desc",
        "limit": str(limit)}) or []
    if not rows:
        return out
    claims = "\n".join(f"- id={r['id']}: {_s(r.get('claim'))[:300]} (claimed source: {_s(r.get('source'))[:120]})"
                       for r in rows)
    r = frontier.complete(VERIFY.format(today=datetime.date.today().isoformat(), claims=claims),
                          need=8, tools=frontier.WEB_TOOLS, max_turns=14, json_schema=VERIFY_SCHEMA,
                          tag="theory_lab.verify")
    j = r.get("json")
    if r.get("error") or not isinstance(j, dict):
        return out
    by_id = {str(x["id"]): x for x in rows}
    for res in (j.get("results") or []):
        rid = str(res.get("id") or "")
        if rid not in by_id:
            continue
        st = str(res.get("status") or "").lower()
        url = _s(res.get("url")).strip()
        patch = None
        if st == "verified" and url.lower().startswith(("http://", "https://")):
            patch = {"source_url": url[:500],
                     "salience": min(1.0, float(by_id[rid].get("salience") or 0.5) + 0.1)}
            out["verified"] += 1
        elif st == "refuted":
            patch = {"kind": "refuted", "salience": 0.05, "source_url": url[:500] or None}
            out["refuted"] += 1
        else:
            patch = {"salience": round(float(by_id[rid].get("salience") or 0.5) * 0.5, 3)}
            out["unverifiable"] += 1
        try:
            db.update("expert_memory", {"id": rid}, patch)
            out["checked"] += 1
        except Exception:
            pass
    return out


def run():
    res = {"positions": resolve_positions(), "claims": verify_claims(),
           "at": datetime.datetime.utcnow().isoformat()}
    try:
        db.upsert("controls", {"key": "theory_lab_stats", "value": json.dumps(res, default=str)})
    except Exception:
        pass
    print("theory_lab: " + json.dumps(res, default=str), flush=True)
    return res


if __name__ == "__main__":
    import single_instance
    _owned, _deadline = single_instance.guard("theory_lab", interval_s=10800)
    if not _owned:
        print(json.dumps({"skipped": "theory_lab already running"}))
        raise SystemExit(0)
    try:
        run()
    finally:
        if _deadline is not None:
            _deadline.cancel()

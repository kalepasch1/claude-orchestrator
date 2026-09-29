#!/usr/bin/env python3
"""docket_triage.py — make the tribunal debate questions worth debating.

THE FINDING (quality review, 2026-09-28). 833 questions were pending; most were written by small
local models filling a (business model x regulation x AI pattern) grid. A sample showed false
premises and misattributed law — a "dispute resolution rule" at 17 CFR 4.45, "suitability
requirements" in the USA PATRIOT Act, an NTSB that regulates data culture — and 515 of 1,000
stamped "high" by their own generators. A frontier tournament costs 100K+ budget tokens; spending
it to discover that a question's premise is wrong is the most expensive way to learn it.

ONE BATCHED PASS. The frontier model reads the pending docket in batches and, per question:
  keep     the premise holds and the answer would change a decision
  rewrite  there is a real question inside a malformed one — restate it correctly
  retire   false premise, duplicate, or no decision turns on it
and assigns a calibrated priority and a LENS (what kind of answer is wanted): answer | pathway |
weakness | arbitrage | opportunity. Only a minority may be `high`.

REVERSIBLE. Nothing is deleted. Retired questions get status 'retired'; rewrites update the text
in place; every change appends the original row to a local ledger
(<home>/consilium/docket_triage.jsonl) so any decision can be undone. Unsure means keep.
"""
from __future__ import annotations
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import common_utils
import frontier

_s = common_utils.safe_string_coerce
HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
LEDGER = os.path.join(HOME, "consilium", "docket_triage.jsonl")
BATCH = int(os.environ.get("ORCH_TRIAGE_BATCH", "30"))
MAX_BATCHES = int(os.environ.get("ORCH_TRIAGE_MAX_BATCHES", "40"))
MIN_TOKENS = int(os.environ.get("ORCH_TRIAGE_MIN_TOKENS", "40000"))
HIGH_SHARE = float(os.environ.get("ORCH_TRIAGE_HIGH_SHARE", "0.25"))
LENSES = ("answer", "pathway", "weakness", "arbitrage", "opportunity")
LENS_TO_DB = {"answer": "regulatory_gap", "pathway": "innovation_pathway", "weakness": "red_team",
              "arbitrage": "cross_industry_analog", "opportunity": "opportunity"}

SCHEMA = {"type": "object", "properties": {"decisions": {"type": "array", "items": {"type": "object", "properties": {
    "n": {"type": "integer"}, "decision": {"type": "string"}, "priority": {"type": "string"},
    "lens": {"type": "string"}, "decision_value": {"type": "number"}, "premise_ok": {"type": "boolean"},
    "premise_error": {"type": "string"}, "rewritten_question": {"type": "string"},
    "duplicate_of": {"type": "integer"}},
    "required": ["n", "decision", "priority", "lens", "decision_value", "premise_ok", "premise_error",
                 "rewritten_question", "duplicate_of"]}}},
    "required": ["decisions"]}

SYSTEM = """You are the docket clerk for a regulatory tribunal serving gaming and sweepstakes operators, prediction
markets and regulated finance, and AI/data companies. Each question below may be convened for an
expensive adversarial tournament. Decide which deserve it.

For each numbered question return:
  decision        keep | rewrite | retire
  priority        high | medium | low. At most one quarter may be high. High means a real operator would
                  change a launch, a structure, a licence or a product this quarter on the answer.
  lens            answer (what does the law require) | pathway (how can this lawfully be done) |
                  weakness (where is the rule ambiguous or under-enforced) | arbitrage (how do
                  jurisdictions differ) | opportunity (what should we sell or file)
  decision_value  0.0-1.0
  premise_ok      false if the question misstates the law, cites a provision that does not say what is
                  claimed, names the wrong regulator, or bolts "AI-generated" onto a rule that does not
                  care how the content was made
  premise_error   one sentence naming the error, or ""
  rewritten_question  for `rewrite`: the real question, stated correctly, one or two sentences, naming
                  the jurisdiction and the actual governing authority if you know it; otherwise ""
  duplicate_of    the number of an earlier question in THIS batch that asks the same thing, else 0

Retire a question when its premise is false and nothing salvageable remains, when it duplicates another,
or when no decision turns on the answer. Rewrite when a real question hides inside a malformed one —
prefer rewriting toward the pathway, weakness, arbitrage or opportunity lens where the underlying issue
supports it, because those are the answers the operator uses. If you are unsure whether a premise is
wrong, keep the question. Return ONLY the JSON object."""


def _ledger(rec):
    try:
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        with open(LEDGER, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass


def _triaged_ids():
    ids = set()
    try:
        with open(LEDGER) as f:
            for line in f:
                try:
                    ids.add(json.loads(line).get("id"))
                except Exception:
                    pass
    except OSError:
        pass
    return ids


def _pending(priorities=None):
    p = {"select": "id,vertical,question,priority,lens,risk_band,origin,created_at",
         "status": "eq.pending", "order": "vertical.asc,created_at.asc", "limit": "2000"}
    if priorities:
        p["priority"] = f"in.({','.join(priorities)})"
    rows = db.select("legal_docket", p) or []
    seen = _triaged_ids()
    return [r for r in rows if r.get("id") not in seen]


def decide(batch):
    lines = "\n".join("%d. [%s] %s" % (i, r.get("vertical"), re.sub(r"\s+", " ", _s(r.get("question")))[:520])
                      for i, r in enumerate(batch, 1))
    r = frontier.complete(f"TODAY: {datetime.date.today().isoformat()}\n\nQUESTIONS:\n{lines}",
                          system=SYSTEM, need=9, json_schema=SCHEMA, timeout=900, tag="docket.triage")
    j = r.get("json")
    if r.get("error") or not isinstance(j, dict):
        return None, r.get("error") or "malformed output"
    return [d for d in j.get("decisions") or [] if isinstance(d, dict)], ""


def apply(batch, decisions, dry_run=False):
    out = {"keep": 0, "rewrite": 0, "retire": 0, "high": 0, "errors": 0}
    max_high = max(1, int(len(batch) * HIGH_SHARE))
    ranked = sorted(decisions, key=lambda d: -float(d.get("decision_value") or 0))
    high_ok = {int(d.get("n") or 0) for d in [x for x in ranked if str(x.get("priority")).lower() == "high"][:max_high]}
    for d in decisions:
        try:
            n = int(d.get("n") or 0)
        except Exception:
            continue
        if not (1 <= n <= len(batch)):
            continue
        row = batch[n - 1]
        decision = str(d.get("decision") or "keep").lower()
        if decision not in ("keep", "rewrite", "retire"):
            decision = "keep"
        pr = str(d.get("priority") or "medium").lower()
        pr = pr if pr in ("high", "medium", "low") else "medium"
        if pr == "high" and n not in high_ok:
            pr = "medium"
        lens = str(d.get("lens") or "answer").lower()
        lens = lens if lens in LENSES else "answer"
        patch = {}
        if decision == "retire":
            patch = {"status": "retired"}
        else:
            patch = {"priority": pr, "lens": LENS_TO_DB[lens]}
            new_q = re.sub(r"\s+", " ", _s(d.get("rewritten_question"))).strip()
            if decision == "rewrite" and len(new_q) >= 40:
                patch["question"] = new_q[:2000]
            elif decision == "rewrite":
                decision = "keep"
        _ledger({"at": datetime.datetime.utcnow().isoformat(), "id": row.get("id"), "decision": decision,
                 "original": {k: row.get(k) for k in ("vertical", "question", "priority", "lens", "status")},
                 "patch": patch, "premise_ok": d.get("premise_ok"), "premise_error": _s(d.get("premise_error"))[:300],
                 "decision_value": d.get("decision_value"), "lens": lens, "dry_run": dry_run})
        if not dry_run:
            try:
                db.update("legal_docket", {"id": row["id"]}, patch)
            except Exception:
                # A rewrite can collide with unique (vertical, question): the rewritten question is
                # already on the docket, so this row is a duplicate of it.
                try:
                    db.update("legal_docket", {"id": row["id"]}, {"status": "retired"})
                    decision = "retire"
                except Exception:
                    out["errors"] += 1
                    continue
        out[decision] += 1
        if decision != "retire" and pr == "high":
            out["high"] += 1
    return out


def run(priorities=None, max_batches=MAX_BATCHES, dry_run=False):
    rows = _pending(priorities)
    tally = {"pending_untriaged": len(rows), "batches": 0, "keep": 0, "rewrite": 0, "retire": 0,
             "high": 0, "errors": 0, "stopped": None}
    for i in range(0, len(rows), BATCH):
        if tally["batches"] >= max_batches:
            tally["stopped"] = "max_batches"
            break
        if not frontier.available(min_tokens=MIN_TOKENS):
            tally["stopped"] = "frontier unavailable or out of budget"
            break
        batch = rows[i:i + BATCH]
        decisions, err = decide(batch)
        if decisions is None:
            tally["errors"] += 1
            print(f"docket_triage: batch {tally['batches'] + 1} failed: {err[:160]}", flush=True)
            if tally["errors"] >= 3:
                tally["stopped"] = "repeated failures"
                break
            continue
        r = apply(batch, decisions, dry_run=dry_run)
        tally["batches"] += 1
        for k in ("keep", "rewrite", "retire", "high", "errors"):
            tally[k] += r[k]
        print(f"docket_triage: batch {tally['batches']}: {json.dumps(r)}", flush=True)
    print("docket_triage: " + json.dumps(tally), flush=True)
    return tally


if __name__ == "__main__":
    import single_instance
    _owned, _deadline = single_instance.guard("docket_triage", interval_s=86400)
    if not _owned:
        print(json.dumps({"skipped": "docket_triage already running"}))
        raise SystemExit(0)
    try:
        args = sys.argv[1:]
        run(priorities=(["high"] if "--high-only" in args else None),
            max_batches=int(next((a.split("=", 1)[1] for a in args if a.startswith("--max-batches=")), MAX_BATCHES)),
            dry_run="--dry-run" in args)
    finally:
        if _deadline is not None:
            _deadline.cancel()

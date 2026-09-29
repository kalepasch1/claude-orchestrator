#!/usr/bin/env python3
"""local_benchmark.py — measure the local tribunal against the frontier tier, scored by the commission.

A claim that the local tier is "as good as the frontier" is worth nothing unless someone other
than the local tier says so. This harness takes questions the FRONTIER tier has already answered
(and the independent commission has already scored), runs the local tribunal on the same
questions, and has the same commission score the local memo. Same questions, same reviewers, same
gate. The number that matters is the gap.

Nothing is written to the docket, the cards or the reviews: results go to
<home>/consilium/benchmarks/<date>.jsonl and a summary is printed.

    python3 local_benchmark.py            # 3 questions
    python3 local_benchmark.py 5 --force  # 5 questions; let a sub-20B model write the memo
    python3 local_benchmark.py --no-score # run the pipeline only (no frontier tokens)

Scoring costs frontier tokens (five reviewers per memo, the evidence reviewer opens the cited
URLs); running the local tribunal costs none.
"""
from __future__ import annotations
import datetime
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
OUT = os.path.join(HOME, "consilium", "benchmarks")
#: what the first local tier scored with the same commission (quality review, 2026-09-28)
BASELINE_LOCAL_V2 = {"composite": 0.29, "evidence": 0.18, "rigor": 0.20, "novelty": 0.10, "utility": 0.65, "risk": 0.34}


def _loads(v, default):
    try:
        return json.loads(v) if isinstance(v, str) else (v if v is not None else default)
    except Exception:
        return default


def questions(n):
    """Frontier cards with a commission review, spread across verticals, best-reviewed first."""
    cards = db.select("verdict_cards", {
        "select": "id,docket_id,vertical,question,process,publication_state,minted_at",
        "status": "eq.fresh", "publication_state": "in.(attorney_review,published)",
        "order": "minted_at.desc", "limit": "120"}) or []
    revs = {r["artifact_id"]: r for r in (db.select("publication_reviews", {
        "select": "artifact_id,composite,decision,detail", "artifact_type": "eq.verdict_card", "limit": "2000"}) or [])}
    pool = []
    for c in cards:
        proc = _loads(c.get("process"), {})
        rv = revs.get(c["id"])
        if not rv or not str(proc.get("model") or "").startswith("claude"):
            continue
        scores = (_loads(rv.get("detail"), {}) or {}).get("scores") or {}
        if len(scores) < 5:
            continue
        pool.append({"card_id": c["id"], "vertical": c["vertical"], "question": c["question"],
                     "frontier": {"composite": float(rv["composite"]), "decision": rv["decision"], **scores}})
    pool.sort(key=lambda x: -x["frontier"]["composite"])
    picked, per = [], {}
    for p in pool:                     # round-robin over verticals
        if per.get(p["vertical"], 0) < max(1, n // 3 + 1):
            picked.append(p)
            per[p["vertical"]] = per.get(p["vertical"], 0) + 1
        if len(picked) >= n:
            break
    return picked


def _artifact(card_id, question, memo, pen):
    return {"id": f"bench-{pen}-{card_id}", "type": "verdict_card", "title": question, "verdict": memo.get("verdict"),
            "content": (f"POSITION:\n{memo.get('memo')}\n\nDISSENT: {memo.get('dissent')}\nFLIPS IF: {memo.get('flips_if')}\n"
                        f"CONDITIONS: {memo.get('conditions')}\nUNSETTLED: {memo.get('unsettled')}\n"
                        f"ASSUMPTIONS: {memo.get('assumptions')}\nOPTIONS: {json.dumps(memo.get('options') or [])[:1500]}"),
            "citations": memo.get("citations") or []}


def run(n=3, force=True, score=True, pens=("local", "sonnet"), decide=True):
    """Prepare the evidence ONCE per question, write the memo with each pen, score each memo with the
    commission, and (when `decide`) record the better pen in pen_policy.json."""
    import consilium_v2
    import local_tribunal as lt
    import publication_commission as pc
    import frontier
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, datetime.date.today().isoformat() + ".jsonl")
    rows = []
    # The comparison is only meaningful when a local model at or above the debate floor can run.
    try:
        import local_llm
        strong = [m for m in lt.strong_models() if local_llm.fits(*m.partition(":")[::2])[0]]
    except Exception:
        strong = []
    if not strong and "local" in pens:
        out = {"questions": 0, "rows": 0, "status": "noop", "skipped": "no local model at or above "
               f"{lt.MIN_DEBATE_B:g}B fits in free RAM right now; benchmark stays due"}
        print("local_benchmark summary: " + json.dumps(out), flush=True)
        return out
    for q in questions(n):
        t0 = time.time()
        state = lt.prepare(q["question"], context="PRIORITY: medium", vertical=q["vertical"], priority="medium",
                           panel=consilium_v2._seat_pool(q["vertical"], lt.SEATS))
        base = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "card_id": q["card_id"],
                "vertical": q["vertical"], "question": q["question"][:400], "frontier": q["frontier"],
                "prepare_seconds": round(time.time() - t0, 1), "research_model": (state["calls"].models or ["?"])[0],
                "findings": len(state.get("findings") or []), "phases": state["meta"].get("phases")}
        if state.get("abstain"):
            row = {**base, "pen": None, "abstain": True, "reason": state["abstain"], "scored": False}
            rows.append(row)
            with open(path, "a") as f:
                f.write(json.dumps(row, default=str) + "\n")
            print("local_benchmark: " + json.dumps({"q": q["question"][:70], "abstain": state["abstain"]}), flush=True)
            continue
        for pen in pens:
            t1 = time.time()
            res = lt.write(state, pen=pen, force=force)
            meta, memo = res.get("meta") or {}, (res.get("j") or {}).get("memo")
            row = {**base, "pen": pen, "write_seconds": round(time.time() - t1, 1), "scored": False,
                   "local": {k: meta.get(k) for k in ("model", "pen_models", "pen_tokens", "calls", "calls_failed", "citations",
                                                      "options", "confidence", "confidence_parts", "grounding",
                                                      "adversary_severity", "revised", "abstain", "reason")}}
            if memo:
                row["verdict"] = (memo.get("verdict") or "")[:500]
                row["memo_chars"] = len(memo.get("memo") or "")
                if score:
                    rec = pc.review_artifact(_artifact(q["card_id"], q["question"], memo, pen))
                    if rec.get("decision") != "deferred":
                        row.update(scored=True, commission={
                            "decision": rec.get("decision"), "composite": rec.get("composite"),
                            "steer_composite": rec.get("steer_composite"), "veto": rec.get("veto"),
                            "posture": rec.get("posture"), **(rec.get("scores") or {}), "rationales": rec.get("rationales")})
                    else:
                        row["score_skipped"] = rec.get("reason")
            rows.append(row)
            with open(path, "a") as f:
                f.write(json.dumps(row, default=str) + "\n")
            print("local_benchmark: " + json.dumps({
                "q": q["question"][:60], "pen": pen, "writer": meta.get("model"), "gate": meta.get("reason"),
                "citations": meta.get("citations"), "confidence": meta.get("confidence"),
                "grounding": (meta.get("grounding") or {}).get("ratio"),
                "commission": (row.get("commission") or {}).get("composite"),
                "steer": (row.get("commission") or {}).get("steer_composite"),
                "decision": (row.get("commission") or {}).get("decision"),
                "frontier_card": q["frontier"]["composite"], "secs": row["write_seconds"]}), flush=True)
    summary = {"questions": n, "rows": len(rows), "path": path, "baseline_local_v2": BASELINE_LOCAL_V2, "pens": {}}
    for pen in pens:
        scored = [r for r in rows if r.get("pen") == pen and r.get("scored")]
        if not scored:
            continue
        agg = {}
        for k in ("composite", "steer_composite", "evidence", "rigor", "novelty", "utility", "risk"):
            vals = [float(r["commission"][k]) for r in scored if r["commission"].get(k) is not None]
            if vals:
                agg[k] = round(statistics.median(vals), 3)
        agg["n"] = len(scored)
        agg["decisions"] = [r["commission"]["decision"] for r in scored]
        agg["writers"] = sorted({str((r["local"] or {}).get("model")) for r in scored})
        agg["pen_tokens_median"] = int(statistics.median([int((r["local"] or {}).get("pen_tokens") or 0) for r in scored]))
        summary["pens"][pen] = agg
    fr = [r["frontier"] for r in rows if r.get("scored")]
    if fr:
        summary["frontier_same_questions"] = {k: round(statistics.median([float(x[k]) for x in fr if x.get(k) is not None]), 3)
                                              for k in ("composite", "evidence", "rigor", "novelty", "utility", "risk")}
    if decide and len(summary["pens"]) >= 2:
        # Steering quality decides. A local writer within 0.03 of the frontier writer wins the tie:
        # it costs nothing and does not depend on a login or a rate limit.
        loc, son = summary["pens"].get("local", {}), summary["pens"].get("sonnet", {})
        if loc.get("steer_composite") is not None and son.get("steer_composite") is not None:
            pen = "local" if loc["steer_composite"] >= son["steer_composite"] - 0.03 else "sonnet"
            policy = {"pen": pen, "decided_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      "evidence": {"local": loc, "sonnet": son}, "rule": "steer_composite, local wins within 0.03",
                      "benchmark": path}
            os.makedirs(os.path.dirname(lt.PEN_POLICY), exist_ok=True)
            with open(lt.PEN_POLICY, "w") as f:
                json.dump(policy, f, indent=1)
            summary["policy"] = {"pen": pen, "path": lt.PEN_POLICY}
    print("local_benchmark summary: " + json.dumps(summary), flush=True)
    return summary


if __name__ == "__main__":
    args = sys.argv[1:]
    n = next((int(a) for a in args if a.isdigit()), 3)
    pens = next((tuple(a.split("=", 1)[1].split(",")) for a in args if a.startswith("--pens=")), ("local", "sonnet"))
    run(n, force="--no-force" not in args, score="--no-score" not in args, pens=pens, decide="--no-decide" not in args)

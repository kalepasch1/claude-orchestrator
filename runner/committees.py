#!/usr/bin/env python3
"""
committees.py - standing EXPERT COMMITTEES that weigh in on business-model choices and 20-500X growth
concepts. Each committee is a distinct expert persona (Legal, BizDev/Marketing, Finance, Product,
Security, Growth, Devil's Advocate). Given a proposal/decision, each committee returns a verdict +
conviction + the specific opportunity/risk it sees + a recommendation; the aggregate (weighted) picks
the optimal path. This turns a single yes/no into a board-style deliberation.

Costless-first + cross-model: committees are spread across providers so it's a genuine multi-perspective
panel, not one model wearing hats. Used by improvement_miner (business-model proposals) + decision_engine.

  review(subject_type, subject_id, title, body) -> {aggregate, recommendation, panel:[...]}
"""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

PROMPT = """You are the {name} committee. Mandate: {mandate}. Review this proposal STRICTLY from your
lens only. Return ONE JSON object:
{"verdict":"support|oppose|conditional|needs-info","score":0-10,
 "opportunity":"the biggest upside YOU see (1 sentence)","risk":"the biggest risk YOU see (1 sentence)",
 "recommendation":"your concrete recommendation (1 sentence)"}
PROPOSAL: {title}
DETAIL: {body}"""


def active_committees():
    return db.select("committees", {"select": "*", "active": "eq.true"}) or []


def _ask(committee, title, body):
    prompt = (PROMPT.replace("{name}", committee["name"]).replace("{mandate}", committee.get("mandate", ""))
              .replace("{title}", (title or "")[:300]).replace("{body}", (body or "")[:1500]))
    try:
        import model_policy, model_gateway
        # spread committees across providers for genuine diversity of perspective
        prov, model, _ = model_policy.choose("review", agentic=False)
        r = model_gateway.complete(prov, model, prompt)
        m = re.search(r"\{.*\}", r.get("text") or "", re.S)
        return json.loads(m.group(0)) if m else {}
    except Exception:
        return {}


def _cal_weight(name):
    """CALIBRATION: accurate committees (past prediction vs. realized outcome) count more."""
    try:
        r = db.select("committee_calibration", {"select": "weight", "committee": f"eq.{name}"}) or []
        return float(r[0]["weight"]) if r else 1.0
    except Exception:
        return 1.0


def review(subject_type, subject_id, title, body):
    panel = []
    for c in active_committees():
        d = _ask(c, title, body)
        if not d:
            continue
        panel.append({"committee": c["name"], "base_w": float(c.get("weight") or 1.0),
                      "verdict": d.get("verdict"), "score": float(d.get("score", 5) or 5),
                      "opportunity": d.get("opportunity"), "risk": d.get("risk"), "rec": d.get("recommendation")})
    if not panel:
        return {"aggregate": None, "recommendation": "HOLD", "opposed_by": [], "panel": []}

    # DEBATE ROUND: if the panel is split, let each member see the strongest counterpoints and revise once.
    verdicts = {p["verdict"] for p in panel}
    if "support" in verdicts and "oppose" in verdicts:
        opp = " | ".join(f"{p['committee']}: {p['risk']}" for p in panel if p["verdict"] == "oppose")[:600]
        pro = " | ".join(f"{p['committee']}: {p['opportunity']}" for p in panel if p["verdict"] == "support")[:600]
        for p in panel:
            c = next((x for x in active_committees() if x["name"] == p["committee"]), None)
            if not c:
                continue
            d2 = _ask(c, title, f"{body}\n\nOPPOSING VIEWS: {opp}\nSUPPORTING VIEWS: {pro}\n"
                                f"Reconsider and give your FINAL verdict addressing the strongest counterpoint.")
            if d2:
                p.update({"verdict": d2.get("verdict", p["verdict"]), "score": float(d2.get("score", p["score"]) or p["score"]),
                          "rec": d2.get("recommendation", p["rec"]), "debated": True})

    total_w = weighted = 0.0
    for p in panel:
        w = p["base_w"] * _cal_weight(p["committee"])
        total_w += w; weighted += w * p["score"]
        db.insert("committee_reviews", {"subject_type": subject_type, "subject_id": subject_id,
                  "subject_title": (title or "")[:200], "committee": p["committee"],
                  "verdict": p["verdict"], "score": p["score"], "opportunity": (p.get("opportunity") or "")[:300],
                  "risk": (p.get("risk") or "")[:300], "recommendation": (p.get("rec") or "")[:300]})
    agg = round(weighted / total_w, 1) if total_w else None
    opposed = [p["committee"] for p in panel if p["verdict"] == "oppose"]
    rec = ("GO" if (agg or 0) >= 7 and not opposed else "REVISE" if (agg or 0) >= 5 else "HOLD")
    if any(p["committee"] == "Legal & Compliance" and p["verdict"] == "oppose" for p in panel):
        rec = "HOLD (legal veto)"
    return {"aggregate": agg, "recommendation": rec, "opposed_by": opposed, "panel": panel}


def compose_spec(title, body, panel):
    """COMMITTEE-AUTHORED SPEC: on GO, fold each committee's constraints into the build spec so the
    implementation inherits their expertise (Legal's compliance guardrails, Finance's pricing bounds…)."""
    constraints = "\n".join(f"- [{p['committee']}] {p.get('rec') or ''} (guard: {p.get('risk') or ''})"
                            for p in panel if p.get("rec"))
    return (f"BUILD SPEC (committee-authored): {title}\n{body}\n\nCONSTRAINTS the implementation MUST honor:\n"
            f"{constraints}\nBuild with tests; keep the prod build green.")


def calibrate():
    """COMMITTEE MEMORY: reweight each committee by how well its past verdicts predicted the realized
    outcome (committee_reviews.outcome). Accurate committees count more; consistently-wrong ones less."""
    rows = db.select("committee_reviews", {"select": "committee,verdict,score,outcome",
                                           "outcome": "not.is.null", "limit": "3000"}) or []
    agg = {}
    for r in rows:
        # predicted-good if score>=6/support; realized-good if outcome>0
        pred_good = (r.get("verdict") == "support") or float(r.get("score") or 0) >= 6
        real_good = float(r.get("outcome") or 0) > 0
        a = agg.setdefault(r["committee"], [0, 0]); a[1] += 1
        if pred_good == real_good:
            a[0] += 1
    n = 0
    for name, (hits, tot) in agg.items():
        if tot < 5:
            continue
        acc = hits / tot
        weight = round(0.5 + acc, 2)   # 0.5..1.5
        db.insert("committee_calibration", {"committee": name, "n": tot, "accuracy": round(acc, 3),
                  "weight": weight, "updated_at": "now()"}, upsert=True)
        n += 1
    print(f"committees.calibrate: reweighted {n} committees")
    return n


def run(limit=8):
    """Convene the committees on pending business-model proposals + legal/strategic decisions."""
    reviewed = {r["subject_id"] for r in (db.select("committee_reviews", {"select": "subject_id"}) or [])}
    n = 0
    # 20-500X business-model proposals awaiting the owner
    for p in db.select("improvement_proposals", {"select": "id,title,proposal,rationale",
                        "status": "eq.for_review", "limit": str(limit)}) or []:
        if p["id"] in reviewed:
            continue
        agg = review("proposal", p["id"], p.get("title"),
                     (p.get("proposal") or "") + "\n" + (p.get("rationale") or ""))
        # write the committee verdict onto the proposal so the cockpit presentation shows it
        db.update("improvement_proposals", {"id": p["id"]},
                  {"rationale": (p.get("rationale") or "")[:500] +
                   f"\n\nCommittee panel: {agg['recommendation']} (avg {agg['aggregate']}). "
                   f"Opposed by: {', '.join(agg['opposed_by']) or 'none'}."})
        n += 1
    # legal/strategic decision cards
    for a in db.select("approvals", {"select": "id,title,why", "status": "eq.pending",
                       "kind": "in.(legal,material)", "limit": str(limit)}) or []:
        if a["id"] in reviewed:
            continue
        review("decision", a["id"], a.get("title"), a.get("why"))
        n += 1
    print(f"committees: convened on {n} proposal(s)/decision(s)")
    return n


if __name__ == "__main__":
    print(json.dumps(review("proposal", None, "Add usage-based pricing tier",
                            "Introduce metered pricing on top of the flat plan."), indent=2, default=str))

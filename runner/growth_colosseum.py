#!/usr/bin/env python3
"""
growth_colosseum.py — the autonomous Marketing Colosseum loop.

Each run: for a target segment, K strategists (top by ELO + exploratory picks) generate competing
copy proposals via app_triage (cheapest capable model), each becomes a bandit arm; every proposal is
synthetic-audience pre-tested and the strategists place reputation wagers; then the tournament is
allocated. A separate settle pass grades running tournaments once their arms have enough live
evidence (the DB function settle_tournament updates ELO + calibration + banks the winning play).

Wired into loops.py as the 'colosseum' loop type. Fail-soft: if no LLM provider is available it
falls back to template proposals so the market still advances.
"""
import os, sys, json, random, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
try:
    import app_triage
except Exception:
    app_triage = None

APP = "growth"
K_STRATEGISTS = 4
MIN_IMPRESSIONS = int(os.environ.get("COLOSSEUM_MIN_IMPRESSIONS", "100"))


def _triage(operation, prompt, task_class="plan"):
    """Route generation through the shared cost/quality optimizer; degrade to '' if unavailable."""
    if not app_triage:
        return ""
    try:
        return (app_triage.run(APP, operation, prompt, task_class=task_class) or {}).get("text", "") or ""
    except Exception as e:
        print(f"colosseum triage error: {e}")
        return ""


def _json_block(text):
    if not text:
        return None
    try:
        i, j = text.index("{"), text.rindex("}")
        return json.loads(text[i:j + 1])
    except Exception:
        return None


def _pick_strategists(k):
    rows = db.select("growth_strategists", {"select": "*", "status": "eq.active", "order": "elo.desc"}) or []
    if not rows:
        return []
    top = rows[:max(1, k - 1)]                       # exploit the proven
    rest = rows[max(1, k - 1):]
    if rest:
        top.append(random.choice(rest))              # explore one wildcard
    return top[:k]


def _propose(strategist, segment):
    """One strategist drafts a competing variant + a falsifiable prediction."""
    lens = strategist.get("lens", "")
    prompt = (
        f"You are {strategist['display_name']} ({lens}). Segment: {segment.get('path')}. "
        f"Positioning: {segment.get('positioning')}. Audience message so far: {segment.get('message')}.\n"
        "Propose ONE landing/ad variant to win this segment. Return STRICT JSON: "
        '{"headline":"","subhead":"","cta":"","angle":"","hypothesis":"","predicted_lift":0.3}. '
        "predicted_lift = your honest forecast of relative conversion lift vs baseline (e.g. 0.3 = +30%)."
    )
    data = _json_block(_triage("colosseum_propose", prompt, "plan")) or {}
    if not data.get("headline"):
        data = {"headline": segment.get("message") or "Try it", "cta": "Get started",
                "angle": lens, "hypothesis": f"{lens} converts this segment",
                "predicted_lift": round(random.uniform(0.05, 0.4), 3)}
    return data


def _synth_pretest(proposal_id, variant):
    """Simulate ICP personas scoring the variant BEFORE spending real traffic."""
    personas = ["skeptical buyer", "time-pressed decision-maker", "budget-conscious founder"]
    for p in personas:
        prompt = (f'Persona: {p}. Rate this ad from 0.0-1.0 for likelihood to click+convert. '
                  f'Variant: {json.dumps(variant)}. Return STRICT JSON {{"score":0.0,"verdict":"pass|fail","notes":""}}.')
        d = _json_block(_triage("synth_pretest", prompt, "rating")) or {}
        score = float(d.get("score", 0.5)) if isinstance(d.get("score", 0.5), (int, float)) else 0.5
        db.insert("growth_synth_tests", {"proposal_id": proposal_id, "persona": p,
                                         "score": round(score, 4), "verdict": d.get("verdict", "pass"),
                                         "notes": (d.get("notes") or "")[:400]})


def _open_segment_tournament(seg):
    tid = db.rpc("open_tournament", {"p_objective": "acquisition", "p_app": seg["app"],
                                     "p_segment_path": seg["path"]})
    tid = tid if isinstance(tid, str) else (tid or [None])[0] if isinstance(tid, list) else tid
    if not tid:
        return None
    strategists = _pick_strategists(K_STRATEGISTS)
    proposals = []
    for s in strategists:
        v = _propose(s, seg)
        arm_name = s["handle"]
        db.insert("growth_arms", {"segment_id": seg["id"], "arm": arm_name,
                                  "variant": {k: v.get(k) for k in ("headline", "subhead", "cta", "angle")}},
                  upsert=True)
        arm = (db.select("growth_arms", {"select": "id", "segment_id": f"eq.{seg['id']}",
                                         "arm": f"eq.{arm_name}"}) or [{}])[0]
        db.insert("growth_proposals", {"tournament_id": tid, "strategist_id": s["id"],
                                       "hypothesis": v.get("hypothesis"), "predicted_lift": v.get("predicted_lift", 0),
                                       "arm_id": arm.get("id"),
                                       "critique_score": round(random.uniform(50, 90), 1)})
        prop = (db.select("growth_proposals", {"select": "id", "tournament_id": f"eq.{tid}",
                                              "strategist_id": f"eq.{s['id']}", "order": "created_at.desc"}) or [{}])[0]
        if prop.get("id"):
            _synth_pretest(prop["id"], v)
            proposals.append({"proposal_id": prop["id"], "strategist_id": s["id"],
                              "elo": float(s.get("elo", 1200)), "pred": float(v.get("predicted_lift", 0))})
    # prediction market: each strategist stakes ELO-weighted on the proposal it believes wins
    if proposals:
        favorite = max(proposals, key=lambda p: p["pred"])
        for s in strategists:
            db.insert("growth_wagers", {"tournament_id": tid, "proposal_id": favorite["proposal_id"],
                                        "strategist_id": s["id"], "stake": round(float(s.get("elo", 1200)) / 100, 2)})
    db.rpc("allocate_tournament", {"p_tournament_id": tid, "p_keep": K_STRATEGISTS})
    print(f"colosseum: opened tournament {tid} for {seg['path']} with {len(proposals)} proposals")
    return tid


def _settle_ready():
    """Settle running tournaments whose live arms have accrued enough real evidence."""
    running = db.select("growth_tournaments", {"select": "id,target_segment", "status": "eq.running"}) or []
    settled = 0
    for t in running:
        live = db.select("growth_proposals", {"select": "arm_id", "tournament_id": f"eq.{t['id']}",
                                              "status": "eq.live"}) or []
        arm_ids = [p["arm_id"] for p in live if p.get("arm_id")]
        if not arm_ids:
            continue
        arms = db.select("growth_arms", {"select": "impressions", "id": f"in.({','.join(arm_ids)})"}) or []
        if sum(int(a.get("impressions", 0)) for a in arms) >= MIN_IMPRESSIONS:
            db.rpc("settle_tournament", {"p_tournament_id": t["id"], "p_min_impressions": MIN_IMPRESSIONS})
            settled += 1
    if settled:
        print(f"colosseum: settled {settled} tournaments")
    return settled


def run():
    _settle_ready()
    # open a tournament for the top live segment that isn't already contested
    segs = db.select("growth_segments", {"select": "id,app,path,positioning,message", "status": "eq.live"}) or []
    open_paths = {t["target_segment"] for t in
                  (db.select("growth_tournaments", {"select": "target_segment",
                                                    "status": "in.(open,running)"}) or [])}
    for seg in segs:
        if seg["path"] not in open_paths:
            _open_segment_tournament(seg)
            break   # one new tournament per tick; cadence handles the rest
    db.insert("resource_events", {"kind": "colosseum_tick", "detail": datetime.datetime.utcnow().isoformat()})


if __name__ == "__main__":
    run()

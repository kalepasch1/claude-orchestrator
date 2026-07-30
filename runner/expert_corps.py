#!/usr/bin/env python3
"""expert_corps.py — a PERSISTENT, MEASURED, continuously-evolving corps of expert agents.

WHAT THIS REPLACES (2026-07-30). committees.py seated experts as *strings* — "Risk-focused
specialist" — freshly instantiated on every panel with no memory, no track record, and no way to
improve. Two panels a month apart were literally the same agent. Volume looked like intelligence;
nothing was accumulating.

THE DESIGN RULE THAT MAKES THIS REAL: evolution must be EARNED, not asserted. It is trivial to
increment a `generation` column every minute and call the corps superintelligent. That is theater.
An expert here advances only when BOTH hold:
    (1) it survived adversarial challenge — Elo at/above the corps median over its recent bouts, and
    (2) it learned something citable since its last generation — >=1 new sourced memory.
An expert whose forecasts decay (rising Brier) is put on probation and then retired regardless of
how loud it is. The corps therefore gets smarter in a sense you can audit: doctrine text changes,
Elo separates, Brier falls. If those three do not move, nothing is happening, and the dashboard
will say so rather than flatter us.

SPAWNING — TWO-PHASE SELECTIVE GROWTH (operator revision 2026-07-30). The corps GROWS, but
selectively — spawn is gated on anticipated value and uniqueness of position, and the gate
tightens once the corps reaches critical mass of intellectual diversity.

  PHASE A (growth, coverage < ORCH_EXPERT_DIVERSITY_TARGET): the objective is to occupy the space
  of schools of thought. Spawn targets the emptiest (vertical x method) niche first; the novelty
  gate is light (a candidate must merely be distinguishable from what exists). Population may grow
  to ORCH_EXPERT_POP_CAP.

  PHASE B (mature, coverage >= target): growth continues but every spawn must EARN its seat —
  strict novelty (doctrine measurably distant from every incumbent in its vertical) AND a
  demonstrated gap (an under-covered niche, a vertical whose incumbents are miscalibrated, or a
  domain the docket is asking about that nobody covers). No gap, no seat.

In both phases the anti-mob invariants hold: candidates too similar to an incumbent are REJECTED at
spawn (an undifferentiated crowd regresses to the mean and drowns the calibrated few), and the
bottom is culled above the cap. The corps grows where thought is missing, never where it is
redundant.

PUBLICATION SAFETY — BIFURCATED (operator revision 2026-07-30). Three persona classes, keyed by
`persona_class`, because the names/schools ARE marketing and legitimacy assets and the ban only
needs to cover what actually creates exposure:
  * historical_public_domain — long-deceased figures whose persona/works are public domain
    (Holmes, Brandeis, Coase, Hand...): publishable BY NAME with a real public-domain portrait,
    always labeled "agentic interpretation in the tradition of X — not X, not an endorsement".
  * school — named schools/groups/institutions ("2026 U.S. Supreme Court", "Chicago School of
    Economics", "Enforcement-era CFPB"): publishable by school name (`school_label`) with a
    REPRESENTATIVE COMPOSITE face evoking the school — never a face identifiable as any LIVING
    member (a composite engineered to look like a sitting justice is a likeness use; the school
    label carries the legitimacy, the face only has to carry the aesthetic).
  * archetype — everything else ("Enforcement-Realist Gaming Counsel"): composite face, seat-name.
What stays prohibited in ALL classes: naming a living person, or any face identifiable as one
(right of publicity + Lanham Act s.43(a) false endorsement). `publication_view()` is still the only
accessor publication paths may use; it returns name/school/portrait policy per class and never the
raw internal `lens`.
"""
from __future__ import annotations
import json
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

POP_CAP        = int(os.environ.get("ORCH_EXPERT_POP_CAP", "240"))
SPAWN_PER_TICK = int(os.environ.get("ORCH_EXPERT_SPAWN_PER_TICK", "2"))
# Critical mass = fraction of (vertical x method) niches occupied. Below it: growth phase.
DIVERSITY_TARGET   = float(os.environ.get("ORCH_EXPERT_DIVERSITY_TARGET", "0.70"))
# Novelty = 1 - max doctrine similarity vs incumbents in the same vertical.
NOVELTY_MIN_GROWTH = float(os.environ.get("ORCH_EXPERT_NOVELTY_MIN_GROWTH", "0.25"))
NOVELTY_MIN_MATURE = float(os.environ.get("ORCH_EXPERT_NOVELTY_MIN_MATURE", "0.45"))
RESEARCH_PER_TICK = int(os.environ.get("ORCH_EXPERT_RESEARCH_PER_TICK", "6"))
K_FACTOR       = float(os.environ.get("ORCH_EXPERT_ELO_K", "24"))
PROBATION_BRIER = float(os.environ.get("ORCH_EXPERT_PROBATION_BRIER", "0.30"))

VERTICALS = {
    "gaming":  ["sweepstakes & promotions", "licensing & suitability", "tribal & compact",
                "responsible gaming", "advertising & UDAP"],
    "finserv": ["money transmission", "AML/BSA", "derivatives & event contracts",
                "bank partnership & BaaS", "consumer credit"],
    "aidata":  ["AI governance", "privacy & data protection", "model risk & validation",
                "IP & training data", "automated decisioning"],
    "corp":    ["securities & capital formation", "M&A and change of control",
                "professional responsibility", "commercial contracting"],
}
# Analytic METHODS — the real source of disagreement in expert panels. A textualist and a
# consequentialist reading the same statute reach different places, and that gap is the signal.
METHODS = ["textualist", "purposivist", "consequentialist", "empirical/quantitative",
           "comparative/cross-jurisdictional", "law-and-economics", "enforcement-realist",
           "practitioner-operational", "academic-doctrinal", "regulator's-eye"]
ERAS    = ["contemporary", "post-2008 regulatory", "deregulatory era", "administrative-state",
           "common-law foundational", "emerging/unsettled"]
STANCES = ["conservative/protective", "aggressive/expansionist", "adversarial red-team",
           "synthesist", "first-principles contrarian"]


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────
# SUBSCRIPTION-FIRST (2026-07-30): the corps is the highest-VOLUME consumer in the fleet, and volume
# belongs on capacity already paid for (the Claude Max plans; Codex rides the ChatGPT plan via the
# agentic path). So: research/spawn/maintenance calls route subscription/free-first
# (model_policy.choose, non-agentic — free/cheap/sub tranches before any mid-tier paid API).
# Gauntlet SEATS stay on choose_diverse — cross-model disagreement is the product there, and that
# bounded slice is what the paid-provider budget is FOR. Subscription usage records $0 real in
# outcomes.usd (claude_cli), so none of this volume touches ORCH_PAID_AGENTIC_DAILY_USD.
_DIVERSE_KINDS = {"seat", "judge"}


def _complete(prompt, kind="review", need=None):
    try:
        import model_policy, model_gateway
        if need in _DIVERSE_KINDS:
            prov, model, _ = model_policy.choose_diverse(kind, need=None)
        else:
            prov, model, _ = model_policy.choose(kind, agentic=False, prefer_free=True)
        r = model_gateway.complete(prov, model, prompt)
        return r.get("text") or ""
    except Exception:
        return ""


def _json(prompt, kind="review", need=None, arr=False):
    txt = _complete(prompt, kind, need)
    m = re.search(r"\[.*\]" if arr else r"\{.*\}", txt, re.S)
    try:
        return json.loads(m.group(0)) if m else ([] if arr else {})
    except Exception:
        return [] if arr else {}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def roster(vertical=None, limit=40, status="active"):
    p = {"select": "id,handle,public_label,lens,vertical,domain,method,era,doctrine,generation,"
                   "elo,bouts,wins,brier_sum,brier_n,status,persona_class,school_label",
         "status": f"eq.{status}", "order": "elo.desc", "limit": str(limit)}
    if vertical:
        p["vertical"] = f"eq.{vertical}"
    try:
        return db.select("experts", p) or []
    except Exception:
        return []


def publication_view(expert):
    """The ONLY shape an expert may take in published material. Never exposes raw `lens`.
    Bifurcated by persona_class (2026-07-30): public-domain historicals publish by name with a real
    portrait + tradition disclaimer; schools publish by school_label with a representative composite;
    archetypes publish as seat names. No living person's name or identifiable face, ever."""
    cls = expert.get("persona_class") or "archetype"
    v = {"persona_class": cls,
         "domain": expert.get("domain"),
         "method": expert.get("method"),
         "generation": expert.get("generation"),
         "calibration": calibration(expert)}
    if cls == "historical_public_domain":
        v["label"] = expert.get("public_label")
        v["portrait"] = "public_domain_portrait"
        v["disclaimer"] = (f"Agentic interpretation in the tradition of {expert.get('public_label')} — "
                           f"not the person, not an endorsement.")
    elif cls == "school":
        v["label"] = expert.get("school_label") or expert.get("public_label")
        v["portrait"] = "school_representative_composite"
        v["disclaimer"] = (f"Agentic panel reasoning in the tradition of {v['label']}. "
                           f"Composite representation; no affiliation or endorsement.")
    else:
        v["label"] = expert.get("public_label")
        v["portrait"] = "archetype_composite"
    return v


def calibration(e):
    n = int(e.get("brier_n") or 0)
    if not n:
        return None
    return round(1.0 - (float(e.get("brier_sum") or 0) / n), 4)   # 1.0 = perfect


def _median_elo():
    rows = roster(limit=POP_CAP)
    if not rows:
        return 1500.0
    v = sorted(float(r.get("elo") or 1500) for r in rows)
    return v[len(v) // 2]


# ── diversity + novelty: the machinery that makes growth selective ───────────────────────────────
def _tokens(text):
    return set(re.findall(r"[a-z]{4,}", (text or "").lower()))


def _doctrine_novelty(doctrine, vertical, pool=None):
    """1 - max Jaccard similarity vs incumbents in the vertical. 1.0 = nothing like it exists."""
    cand = _tokens(doctrine)
    if not cand:
        return 0.0
    pool = pool if pool is not None else roster(vertical=vertical, limit=POP_CAP)
    worst = 0.0
    for e in pool:
        inc = _tokens(e.get("doctrine"))
        if not inc:
            continue
        sim = len(cand & inc) / max(1, len(cand | inc))
        worst = max(worst, sim)
    return round(1.0 - worst, 3)


def diversity_coverage(pool=None):
    """Occupied (vertical x method) niches / all niches. This is the critical-mass gauge."""
    pool = pool if pool is not None else roster(limit=POP_CAP)
    occupied = {(e.get("vertical"), (e.get("method") or "").lower()) for e in pool}
    total = len(VERTICALS) * len(METHODS)
    return round(len(occupied) / max(1, total), 3), occupied


def _emptiest_niches(occupied, k=6):
    """Unoccupied (vertical, method) cells — where growth should aim first."""
    gaps = [(v, m) for v in VERTICALS for m in METHODS if (v, m.lower()) not in occupied]
    random.shuffle(gaps)
    return gaps[:k]


def _demonstrated_gaps(pool):
    """Phase-B gaps: an under-covered niche, a miscalibrated vertical, or docket demand nobody covers."""
    gaps = []
    _, occupied = diversity_coverage(pool)
    for v, m in _emptiest_niches(occupied, k=3):
        gaps.append({"vertical": v, "method": m, "reason": f"unoccupied niche: {v} x {m}"})
    by_v = {}
    for e in pool:
        c = calibration(e)
        if c is not None:
            by_v.setdefault(e.get("vertical"), []).append(c)
    for v, cals in by_v.items():
        mean = sum(cals) / len(cals)
        if mean < (1.0 - PROBATION_BRIER):
            gaps.append({"vertical": v, "method": None,
                         "reason": f"incumbents miscalibrated (mean {round(mean, 3)}) — seat a corrective school"})
    try:
        pend = db.select("legal_docket", {"select": "vertical", "status": "eq.pending", "limit": "50"}) or []
        have = {e.get("vertical") for e in pool}
        for v in {p.get("vertical") for p in pend} - have:
            if v:
                gaps.append({"vertical": v, "method": None, "reason": f"docket demand with zero coverage: {v}"})
    except Exception:
        pass
    return gaps


def spawn_phase(pool=None):
    cov, _ = diversity_coverage(pool)
    return ("growth" if cov < DIVERSITY_TARGET else "mature"), cov


# ── spawn ────────────────────────────────────────────────────────────────────────────────────────
SPAWN_PROMPT = """Design ONE expert seat for a legal/regulatory analysis corps. It must be genuinely
DIFFERENT from its parent — a seat that would reach a different conclusion on some real question,
not a synonym. Disagreement is the product; a corps of agreeable experts is worthless.

PARENT: {parent}
FORCED MUTATION (must be honoured): {mutation}
VERTICAL: {vertical}   DOMAIN: {domain}

`public_label` is an ARCHETYPE used in published work. It must NOT name, evoke, or be a thin
pseudonym for any real identifiable person, living or dead. Describe the SEAT, e.g.
"Enforcement-Realist Gaming Counsel" or "Quantitative Model-Risk Examiner".
`lens` is internal: the school of thought / analytic tradition the seat reasons from.
`doctrine` is this seat's opening thesis about its domain — a falsifiable claim it will defend and
revise, not a description of its job.

Return ONE JSON object:
{{"public_label":"archetype seat name","lens":"internal analytic tradition","method":"{method}",
  "era":"{era}","domain":"{domain}",
  "doctrine":"a falsifiable opening thesis about this domain (2-3 sentences)"}}"""


def spawn(parent=None, vertical=None, method=None, reason=None):
    vertical = vertical or (parent or {}).get("vertical") or random.choice(list(VERTICALS))
    domain   = random.choice(VERTICALS.get(vertical, ["general"]))
    mutation = (f"targeted seat: {reason}" if reason else random.choice([
        f"method -> {method or random.choice(METHODS)}",
        f"era/frame -> {random.choice(ERAS)}",
        f"stance -> {random.choice(STANCES)}",
        f"adjacent domain -> {random.choice(VERTICALS.get(vertical, ['general']))}",
    ]))
    spec = _json(SPAWN_PROMPT.format(
        parent=json.dumps({k: (parent or {}).get(k) for k in ("public_label", "lens", "method", "era", "doctrine")}),
        mutation=mutation, vertical=vertical, domain=domain,
        method=method or random.choice(METHODS), era=random.choice(ERAS)), kind="review")
    if not spec.get("public_label"):
        return None
    # NOVELTY GATE: a candidate indistinguishable from an incumbent is rejected at the door,
    # in BOTH phases — the threshold is what tightens, not the principle.
    phase, _ = spawn_phase()
    floor = NOVELTY_MIN_GROWTH if phase == "growth" else NOVELTY_MIN_MATURE
    nov = _doctrine_novelty(spec.get("doctrine"), vertical)
    if nov < floor:
        print(f"expert_corps: spawn rejected — novelty {nov} < {floor} ({phase}) for '{spec.get('public_label')}'")
        return None
    label = str(spec["public_label"])[:120]
    handle = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:60] + "-" + str(int(time.time() * 1000))[-6:]
    # Inherit the parent's Elo minus a rookie discount: lineage is a prior, not a free pass.
    seed_elo = max(1200.0, float((parent or {}).get("elo") or 1500) - 60)
    row = {"handle": handle, "public_label": label,
           "lens": str(spec.get("lens") or "unspecified")[:200],
           "vertical": vertical, "domain": str(spec.get("domain") or domain)[:120],
           "method": str(spec.get("method") or "doctrinal")[:60],
           "era": str(spec.get("era") or "contemporary")[:60],
           "doctrine": str(spec.get("doctrine") or "")[:4000],
           "elo": seed_elo, "parent_id": (parent or {}).get("id"), "mutation": mutation[:200]}
    try:
        db.insert("experts", row)
        return row
    except Exception as e:
        print(f"expert_corps: spawn failed: {type(e).__name__}: {str(e)[:120]}")
        return None


def _population():
    try:
        return db.count("experts", {"status": "eq.active"}) or 0
    except Exception:
        return 0


def cull():
    """Retire the weakest so headcount stays constant and the floor rises. A corps, not a mob."""
    over = _population() - POP_CAP
    if over <= 0:
        return 0
    try:
        weak = db.select("experts", {"select": "id,elo,bouts", "status": "eq.active",
                                     "order": "elo.asc", "limit": str(over + 4)}) or []
    except Exception:
        return 0
    n = 0
    for w in weak:
        # Never retire an expert that has not yet been tested — that would select for luck.
        if int(w.get("bouts") or 0) < 3:
            continue
        try:
            db.update("experts", {"id": w["id"]}, {"status": "retired", "retired_at": _now()})
            n += 1
        except Exception:
            pass
        if n >= over:
            break
    return n


# ── research: the intake that makes positions ADVANCE ────────────────────────────────────────────
RESEARCH_PROMPT = """You are {label} ({method} method, {domain}). Advance your own thesis.

YOUR CURRENT DOCTRINE: {doctrine}
WHAT YOU ALREADY KNOW (do not repeat): {known}

Identify what you would need to learn NEXT to make your doctrine sharper or to find out you are
wrong. Then state what you believe the current state of that authority is. Be specific and
falsifiable — name the statute, rule, docket, agency guidance, case, or dataset. A vague gesture at
"recent developments" is a failure.

Return ONE JSON object:
{{"claims":[{{"claim":"a specific, checkable proposition","source":"the authority or dataset",
   "salience":0.0-1.0,"changes_doctrine":true|false}}],
  "revised_doctrine":"your doctrine restated if anything above changes it, else repeat it verbatim",
  "open_question":"the single question whose answer would most change your view"}}"""


def _known(expert_id, k=8):
    try:
        rows = db.select("expert_memory", {"select": "claim", "expert_id": f"eq.{expert_id}",
                                           "order": "salience.desc", "limit": str(k)}) or []
    except Exception:
        rows = []
    return "; ".join((r.get("claim") or "")[:120] for r in rows) or "(nothing yet)"


def research(expert):
    """One research cycle for one expert. Writes sourced memory and may revise doctrine."""
    out = _json(RESEARCH_PROMPT.format(
        label=expert.get("public_label"), method=expert.get("method"),
        domain=expert.get("domain"), doctrine=(expert.get("doctrine") or "(none yet)")[:1500],
        known=_known(expert["id"])), kind="review", need="research")
    claims = out.get("claims") or []
    wrote = 0
    for c in claims[:6]:
        if not isinstance(c, dict) or not c.get("claim"):
            continue
        try:
            db.insert("expert_memory", {
                "expert_id": expert["id"], "kind": "research",
                "claim": str(c["claim"])[:2000],
                "source": str(c.get("source") or "")[:500] or None,
                "salience": max(0.0, min(1.0, float(c.get("salience") or 0.5))),
                "generation": int(expert.get("generation") or 1)})
            wrote += 1
        except Exception:
            pass
    rd = (out.get("revised_doctrine") or "").strip()
    if rd and rd[:200] != (expert.get("doctrine") or "")[:200]:
        try:
            db.update("experts", {"id": expert["id"]}, {"doctrine": rd[:4000]})
        except Exception:
            pass
    return wrote


# ── Elo + calibration: the only ways an expert's standing can change ─────────────────────────────
def record_bout(question, a, b, winner_id, margin=0.5, grounds="", docket_id=None, judge_model=None):
    ea = 1.0 / (1.0 + 10 ** ((float(b.get("elo") or 1500) - float(a.get("elo") or 1500)) / 400.0))
    sa = 1.0 if winner_id == a["id"] else (0.0 if winner_id == b["id"] else 0.5)
    k = K_FACTOR * (0.5 + float(margin or 0.5))      # decisive wins move more than narrow ones
    na = float(a.get("elo") or 1500) + k * (sa - ea)
    nb = float(b.get("elo") or 1500) + k * ((1 - sa) - (1 - ea))
    try:
        db.insert("expert_bouts", {"question": (question or "")[:2000], "docket_id": docket_id,
                                   "a_id": a["id"], "b_id": b["id"], "winner_id": winner_id,
                                   "margin": float(margin or 0.5), "grounds": (grounds or "")[:2000],
                                   "judge_model": judge_model})
        for e, new, won in ((a, na, winner_id == a["id"]), (b, nb, winner_id == b["id"])):
            db.update("experts", {"id": e["id"]}, {
                "elo": round(new, 2), "bouts": int(e.get("bouts") or 0) + 1,
                "wins": int(e.get("wins") or 0) + (1 if won else 0)})
            db.insert("expert_memory", {
                "expert_id": e["id"], "kind": "bout_win" if won else "bout_loss",
                "claim": f"On '{(question or '')[:120]}': {grounds[:400]}",
                "salience": 0.8 if not won else 0.6,     # losses teach more than wins
                "generation": int(e.get("generation") or 1)})
    except Exception as ex:
        print(f"expert_corps: bout persist failed: {type(ex).__name__}: {str(ex)[:120]}")
    return round(na, 2), round(nb, 2)


def resolve_position(position_id, outcome: bool):
    """Score a dated forecast. Brier is what stops confident nonsense from compounding."""
    try:
        rows = db.select("expert_positions", {"select": "id,expert_id,probability,resolved",
                                              "id": f"eq.{position_id}"}) or []
        if not rows or rows[0].get("resolved"):
            return None
        pos = rows[0]
        p = float(pos.get("probability") or 0.5)
        brier = (p - (1.0 if outcome else 0.0)) ** 2
        db.update("expert_positions", {"id": position_id},
                  {"resolved": True, "outcome": outcome, "brier": round(brier, 4)})
        ex = (db.select("experts", {"select": "id,brier_sum,brier_n,status",
                                    "id": f"eq.{pos['expert_id']}"}) or [{}])[0]
        bs = float(ex.get("brier_sum") or 0) + brier
        bn = int(ex.get("brier_n") or 0) + 1
        patch = {"brier_sum": round(bs, 6), "brier_n": bn}
        # Miscalibration is disqualifying, and it should bite before the expert is influential.
        if bn >= 5 and (bs / bn) > PROBATION_BRIER and ex.get("status") == "active":
            patch["status"] = "probation"
        db.update("experts", {"id": pos["expert_id"]}, patch)
        return brier
    except Exception:
        return None


# ── promotion: the earned-evolution gate ─────────────────────────────────────────────────────────
def evolve(expert):
    """Advance a generation ONLY if the expert both survived challenge and learned something."""
    med = _median_elo()
    if float(expert.get("elo") or 1500) < med:
        return False
    if int(expert.get("bouts") or 0) < 3:
        return False
    gen = int(expert.get("generation") or 1)
    try:
        fresh = db.count("expert_memory", {"expert_id": f"eq.{expert['id']}",
                                           "generation": f"eq.{gen}", "source": "not.is.null"}) or 0
    except Exception:
        fresh = 0
    if fresh < 2:
        return False
    cal = calibration(expert)
    if cal is not None and cal < (1.0 - PROBATION_BRIER):
        return False
    try:
        db.update("experts", {"id": expert["id"]}, {"generation": gen + 1, "evolved_at": _now()})
        return True
    except Exception:
        return False


# ── the tick ─────────────────────────────────────────────────────────────────────────────────────
def tick():
    """One cycle: research the strongest, promote the earned, spawn from the top, retire the bottom."""
    out = {"researched": 0, "claims": 0, "evolved": 0, "spawned": 0, "retired": 0}
    pool = roster(limit=POP_CAP)
    if not pool:
        for v in VERTICALS:                     # cold start: one seat per vertical
            if spawn(vertical=v):
                out["spawned"] += 1
        return out

    for e in pool[:RESEARCH_PER_TICK]:
        n = research(e)
        out["claims"] += n
        out["researched"] += 1
        if evolve(e):
            out["evolved"] += 1

    phase, cov = spawn_phase(pool)
    out["phase"], out["coverage"] = phase, cov
    top = pool[:max(3, len(pool) // 5)]
    if phase == "growth":
        # Growth: aim at the emptiest niches first so headcount buys DIVERSITY, not redundancy.
        _, occupied = diversity_coverage(pool)
        niches = _emptiest_niches(occupied, k=SPAWN_PER_TICK)
        for i in range(SPAWN_PER_TICK):
            if _population() >= POP_CAP:
                break
            v, m = niches[i] if i < len(niches) else (None, None)
            if spawn(parent=random.choice(top), vertical=v, method=m,
                     reason=(f"growth-phase niche fill: {v} x {m}" if v else None)):
                out["spawned"] += 1
    else:
        # Mature: no gap, no seat. Growth continues only where a gap is demonstrated.
        gaps = _demonstrated_gaps(pool)
        for g in gaps[:SPAWN_PER_TICK]:
            if _population() >= POP_CAP:
                break
            if spawn(parent=random.choice(top), vertical=g.get("vertical"),
                     method=g.get("method"), reason=g.get("reason")):
                out["spawned"] += 1
    out["retired"] = cull()
    return out


def stats():
    pool = roster(limit=POP_CAP)
    cals = [c for c in (calibration(e) for e in pool) if c is not None]
    phase, cov = spawn_phase(pool)
    return {"population": len(pool),
            "phase": phase, "diversity_coverage": cov, "diversity_target": DIVERSITY_TARGET,
            "generations": {"max": max([int(e.get("generation") or 1) for e in pool] or [0]),
                            "mean": round(sum(int(e.get("generation") or 1) for e in pool) / max(1, len(pool)), 2)},
            "elo": {"top": max([float(e.get("elo") or 0) for e in pool] or [0]),
                    "median": _median_elo()},
            "calibration": {"n": len(cals),
                            "mean": round(sum(cals) / len(cals), 4) if cals else None},
            "verticals": sorted({e.get("vertical") for e in pool if e.get("vertical")})}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tick"
    if cmd == "stats":
        print(json.dumps(stats(), indent=2))
    elif cmd == "roster":
        print(json.dumps([publication_view(e) for e in roster(limit=30)], indent=2))
    else:
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        agg = {"researched": 0, "claims": 0, "evolved": 0, "spawned": 0, "retired": 0}
        for _ in range(n):
            r = tick()
            for k in agg:
                agg[k] += r.get(k, 0)
        print(json.dumps({"ticks": n, **agg, "stats": stats()}, indent=2))

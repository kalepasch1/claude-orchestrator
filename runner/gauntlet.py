#!/usr/bin/env python3
"""gauntlet.py — the adversarial gauntlet that replaces one-shot committee voting.

WHAT WAS WRONG WITH THE OLD TOURNAMENT. committees.deliberate() ran opening positions, a couple of
coordination rounds, then a chair synthesis. Every seat saw every other seat immediately, which is
the textbook setup for anchoring cascade: the first confident answer sets the frame and the rest
converge on it. Measured output was ~300 characters of hedged agreement. A tournament that produces
consensus quickly is not rigorous; it is correlated.

WHAT THE GAUNTLET DOES DIFFERENTLY — five rounds, each removing a specific failure mode:

  R1 BLIND     Experts answer independently, seeing NOTHING from the others. Kills anchoring. Any
               agreement that survives from here is real agreement, not echo.
  R2 STEELMAN  Each expert is handed the position that most opposes its own and must argue it AT
               ITS STRONGEST before responding. You cannot rebut what you cannot restate. This is
               the single highest-yield round: it routinely flips positions, which R1-only never does.
  R3 REBUTTAL  Now, with the opposition steelmanned, each expert either holds with new grounds or
               concedes. Concession is scored POSITIVELY — an expert that updates on evidence is
               more valuable than one that never moves, and the Brier ledger proves it later.
  R4 RED TEAM  A dedicated adversary attacks the leading position only: what fact pattern breaks it,
               what authority was missed, what would a regulator/opposing counsel say first.
  R5 SYNTHESIS The chair writes the memo. Dissent is preserved verbatim with its reasoning. A
               smoothed consensus that erases the strongest objection is a failing output.

SCORING. Pairwise bouts are judged on GROUNDING (did the position cite operative authority and
apply it to these facts), not on eloquence — the failure mode of LLM judging is rewarding fluent
prose. Winners move Elo (expert_corps.record_bout). Every expert also stakes a dated probability,
which is scored later against the real outcome. Elo says who argues well; Brier says who is right.
Both are needed: an expert can win arguments for years while being consistently wrong, and only the
Brier column catches it.

CONSENSUS IS NOT THE GOAL. The output records the position, its strongest surviving objection, and
the conditions under which it flips. A memo that says "here is the answer, here is what would change
it, here is who disagrees and why" is worth more to a GC than a confident one-liner, and it is the
only honest thing to publish.
"""
from __future__ import annotations
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import expert_corps as corps

SEATS       = int(os.environ.get("ORCH_GAUNTLET_SEATS", "5"))
MAX_BOUTS   = int(os.environ.get("ORCH_GAUNTLET_BOUTS", "4"))
ENABLED     = os.environ.get("ORCH_GAUNTLET_ENABLED", "true").lower() != "false"


def _json(prompt, kind="review", need=None, arr=False):
    return corps._json(prompt, kind=kind, need=need, arr=arr)


# ── R1 ───────────────────────────────────────────────────────────────────────────────────────────
R1 = """You are {label}. Method: {method}. Domain: {domain}. Your standing doctrine: {doctrine}
What you have learned (your own prior research): {memory}

Answer the question below INDEPENDENTLY. You have not seen anyone else's answer and must not
speculate about it. Reason from authority to facts to conclusion.

Every material assertion carries a citation — statute, regulation, case, agency guidance, no-action
letter, or an explicit dataset. If you cannot cite it, put it in `assumptions`. An uncited assertion
dressed as a holding is the single worst thing you can produce here.

Also stake a PROBABILITY: if a regulator or court reached this question in the next 24 months, how
likely is it they land where you just did? You will be scored against the real outcome, so an
honest 0.55 beats a performative 0.95.

QUESTION: {question}
CONTEXT: {context}

Return ONE JSON object:
{{"position":"your holding in one sentence",
  "analysis":"operative rule -> application to these facts -> conclusion. Cite inline.",
  "citations":[{{"source":"authority","proposition":"what it establishes","confidence":0.0-1.0}}],
  "assumptions":["anything you could not cite"],
  "probability":0.0-1.0,
  "flips_if":"the specific fact or authority that would reverse your conclusion"}}"""


# ── R2 ───────────────────────────────────────────────────────────────────────────────────────────
R2 = """You are {label}. Below is the position that most OPPOSES yours on this question.

YOUR POSITION: {mine}
OPPOSING POSITION: {theirs}

Before you may respond, argue THEIR case at its strongest. Add the best authority and the best
factual framing they did not think to use. Do not caricature it, do not hedge it, do not smuggle in
your rebuttal. If your steelman is weaker than their original, you have failed this round.

Then, honestly: does the steelman change your view?

Return ONE JSON object:
{{"steelman":"their case at its strongest, with authority they should have cited",
  "strongest_point":"the single best thing about their position",
  "updates_me":true|false,
  "why":"what specifically moved you, or why it did not"}}"""


# ── R3 ───────────────────────────────────────────────────────────────────────────────────────────
R3 = """You are {label}. You steelmanned the opposition and said: {steel}

Now settle it. HOLD with new grounds, or CONCEDE — in whole or in part. Conceding to a better
argument is a strength here and is scored as one; refusing to move when the evidence moved is the
failure. Restate your probability now that you have seen the strongest opposing case.

YOUR ORIGINAL: {mine}
THE OPPOSITION: {theirs}

Return ONE JSON object:
{{"outcome":"hold|concede|partial",
  "position":"your position now, in one sentence",
  "grounds":"the authority that decides it, applied to these facts",
  "citations":[{{"source":"authority","proposition":"what it establishes","confidence":0.0-1.0}}],
  "probability":0.0-1.0,
  "conceded":"what you gave up, or 'nothing'"}}"""


# ── R4 ───────────────────────────────────────────────────────────────────────────────────────────
R4 = """You are the RED TEAM. Your only job is to break the position below. You are not balanced and
you are not trying to be fair; you are the opposing counsel, the examiner, and the enforcement
division at once.

POSITION UNDER ATTACK: {position}
ITS GROUNDS: {grounds}

Find: the fact pattern where it fails; the authority it missed or read too generously; the
jurisdiction where it is simply wrong; the step where it assumed rather than established. If after
genuine effort you cannot break it, say so plainly and state what makes it durable — a red team that
manufactures a weak objection to look useful is worse than one that concedes.

Return ONE JSON object:
{{"breaks":true|false,
  "attack":"the strongest attack you have",
  "failing_fact_pattern":"the specific scenario where this position loses",
  "missed_authority":"authority the position did not address, or 'none found'",
  "severity":"fatal|material|marginal|none",
  "durable_because":"if you could not break it, what holds it up"}}"""


# ── R5 ───────────────────────────────────────────────────────────────────────────────────────────
R5 = """You are the chair. Write the memo a General Counsel will act on this week.

You are NOT averaging opinions. You are deciding, on the record, with the dissent preserved. The
reader needs three things and will not forgive their absence: what the answer is, what would change
it, and who disagrees and on what grounds.

QUESTION: {question}
POSITIONS AFTER THE GAUNTLET: {positions}
RED TEAM FINDINGS: {red}

Rules:
  * Lead with the answer. A memo that builds to a conclusion wastes the reader's first thirty seconds.
  * Every material assertion carries a citation. Uncited claims go in `assumptions`, explicitly.
  * Preserve the strongest surviving objection VERBATIM with its reasoning, even where you reject it.
  * State the conditions that bound the conclusion and the trigger that would reverse it.
  * If the honest answer is that the question is unsettled, say that and give the decision rule for
    acting under that uncertainty. "Unsettled" is a real answer; hedged mush is not.
  * Length follows substance. Do not pad. Do not truncate real analysis to seem crisp.

Return ONE JSON object:
{{"verdict":"the holding in one sentence",
  "memo":"the full analysis: answer -> operative authority -> application -> limits",
  "citations":[{{"source":"authority","proposition":"what it establishes","confidence":0.0-1.0}}],
  "assumptions":["asserted without citable source"],
  "confidence":0.0-1.0,
  "dissent":"the strongest surviving objection, verbatim, with reasoning, or 'none'",
  "flips_if":"the trigger that reverses this",
  "conditions":"what the reader must do for this to hold",
  "unsettled":true|false}}"""


JUDGE = """Judge which of these two positions is better GROUNDED on the question. Judge grounding,
not style: does it name the operative authority, apply it to THESE facts, and acknowledge its own
limits? Fluent prose with no authority loses to a plain answer that cites correctly. Length is not
quality.

QUESTION: {question}
A ({a_label}): {a}
B ({b_label}): {b}

Return ONE JSON object:
{{"winner":"A|B|tie","margin":0.0-1.0,"grounds":"why, in one sentence, naming the deciding factor"}}"""


def _seat_pool(vertical, n):
    pool = corps.roster(vertical=vertical, limit=n * 3)
    if len(pool) < n:
        pool += [e for e in corps.roster(limit=n * 3) if e not in pool]
    if not pool:
        return []
    # Take the strongest, but force METHOD diversity — five textualists is one expert with five
    # voices, and it will produce five copies of the same blind spot.
    picked, methods = [], set()
    for e in pool:
        m = (e.get("method") or "").lower()
        if m in methods and len(picked) < n:
            continue
        picked.append(e)
        methods.add(m)
        if len(picked) >= n:
            break
    for e in pool:                                   # backfill if diversity starved us
        if len(picked) >= n:
            break
        if e not in picked:
            picked.append(e)
    return picked[:n]


def _memory(expert_id, k=6):
    try:
        rows = db.select("expert_memory", {"select": "claim,source", "expert_id": f"eq.{expert_id}",
                                           "order": "salience.desc", "limit": str(k)}) or []
    except Exception:
        rows = []
    return "; ".join(f"{(r.get('claim') or '')[:110]}" + (f" [{r['source'][:40]}]" if r.get("source") else "")
                     for r in rows) or "(no prior research)"


def _most_opposed(i, r1):
    """Pick the position least like mine. Distance by citation + holding overlap, not by vibe."""
    mine = set(re.findall(r"[a-z]{4,}", (r1[i].get("position") or "").lower()))
    best, bd = None, -1
    for j, o in enumerate(r1):
        if j == i or not o:
            continue
        theirs = set(re.findall(r"[a-z]{4,}", (o.get("position") or "").lower()))
        d = len(mine ^ theirs) - len(mine & theirs)
        # a genuinely opposite probability is the strongest signal of real disagreement
        d += int(abs(float(r1[i].get("probability") or 0.5) - float(o.get("probability") or 0.5)) * 10)
        if d > bd:
            best, bd = j, d
    return best


def run(question, context="", vertical=None, docket_id=None, seats=SEATS):
    """Run the full gauntlet. Returns a memo-grade result with dissent and calibration preserved."""
    if not ENABLED:
        return None
    panel = _seat_pool(vertical, seats)
    if len(panel) < 2:
        return {"error": "expert corps too small; run expert_corps.py tick first"}

    # R1 — blind
    r1 = []
    for e in panel:
        r1.append(_json(R1.format(label=e.get("public_label"), method=e.get("method"),
                                  domain=e.get("domain"), doctrine=(e.get("doctrine") or "")[:800],
                                  memory=_memory(e["id"]), question=question,
                                  context=(context or "")[:3000]), kind="review") or {})

    # R2 — forced steelman of the most opposed position
    r2 = []
    for i, e in enumerate(panel):
        j = _most_opposed(i, r1)
        if j is None:
            r2.append({})
            continue
        r2.append(_json(R2.format(label=e.get("public_label"),
                                  mine=json.dumps(r1[i])[:2500],
                                  theirs=json.dumps(r1[j])[:2500]), kind="review") or {})

    # R3 — hold or concede
    r3 = []
    for i, e in enumerate(panel):
        j = _most_opposed(i, r1)
        r3.append(_json(R3.format(label=e.get("public_label"),
                                  steel=(r2[i].get("steelman") or "")[:1500],
                                  mine=json.dumps(r1[i])[:2000],
                                  theirs=json.dumps(r1[j] if j is not None else {})[:2000]),
                        kind="review") or {})

    # Stake each expert's dated forecast, then judge pairwise bouts on grounding.
    for i, e in enumerate(panel):
        p = r3[i].get("probability", r1[i].get("probability"))
        try:
            db.insert("expert_positions", {
                "expert_id": e["id"], "docket_id": docket_id, "question": (question or "")[:2000],
                "thesis": (r3[i].get("position") or r1[i].get("position") or "")[:2000],
                "probability": max(0.0, min(1.0, float(p))) if p is not None else None,
                "generation": int(e.get("generation") or 1)})
        except Exception:
            pass

    pairs = [(a, b) for a in range(len(panel)) for b in range(a + 1, len(panel))]
    random.shuffle(pairs)
    for a, b in pairs[:MAX_BOUTS]:
        v = _json(JUDGE.format(question=question,
                               a_label=panel[a].get("public_label"), a=json.dumps(r3[a])[:2500],
                               b_label=panel[b].get("public_label"), b=json.dumps(r3[b])[:2500]),
                  kind="review", need="judge") or {}
        w = v.get("winner")
        wid = panel[a]["id"] if w == "A" else (panel[b]["id"] if w == "B" else None)
        corps.record_bout(question, panel[a], panel[b], wid,
                          margin=float(v.get("margin") or 0.5),
                          grounds=str(v.get("grounds") or "")[:1000], docket_id=docket_id)

    # R4 — red team the leading position (the one carried by the highest-Elo holder)
    lead_i = max(range(len(panel)), key=lambda i: float(panel[i].get("elo") or 1500))
    red = _json(R4.format(position=(r3[lead_i].get("position") or "")[:1500],
                          grounds=(r3[lead_i].get("grounds") or "")[:2500]), kind="review") or {}

    # R5 — chair
    positions = [{"seat": panel[i].get("public_label"), "method": panel[i].get("method"),
                  "calibration": corps.calibration(panel[i]),
                  "opened": r1[i].get("position"), "steelman_moved": r2[i].get("updates_me"),
                  "final": r3[i].get("position"), "outcome": r3[i].get("outcome"),
                  "grounds": r3[i].get("grounds"), "probability": r3[i].get("probability"),
                  "citations": r3[i].get("citations") or r1[i].get("citations") or []}
                 for i in range(len(panel))]
    memo = _json(R5.format(question=question, positions=json.dumps(positions)[:12000],
                           red=json.dumps(red)[:3000]), kind="review", need="chair") or {}

    cites = memo.get("citations") or []
    flipped = sum(1 for x in r2 if x.get("updates_me"))
    conceded = sum(1 for x in r3 if x.get("outcome") in ("concede", "partial"))
    return {
        "question": question,
        "verdict": memo.get("verdict"),
        "opinion": memo.get("memo") or memo.get("opinion") or "",
        "citations": cites,
        "assumptions": memo.get("assumptions") or [],
        "conviction": round(float(memo.get("confidence") or 0.5) * 10, 1),
        "dissent": memo.get("dissent") or "none",
        "flips_if": memo.get("flips_if"),
        "conditions": memo.get("conditions"),
        "unsettled": bool(memo.get("unsettled")),
        "red_team": red,
        # The process record is what makes this auditable — and it is what a marketing artifact can
        # honestly show: seats, methods, how many were moved by the steelman, how many conceded.
        "process": {"seats": [corps.publication_view(e) for e in panel],
                    "rounds": 5, "positions_flipped_by_steelman": flipped,
                    "concessions": conceded, "bouts_judged": min(MAX_BOUTS, len(pairs)),
                    "red_team_severity": red.get("severity"),
                    "citation_count": len(cites)},
    }


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "Is a dual-currency sweepstakes model lawful in Nevada today?"
    v = sys.argv[2] if len(sys.argv) > 2 else "gaming"
    print(json.dumps(run(q, vertical=v), indent=2))

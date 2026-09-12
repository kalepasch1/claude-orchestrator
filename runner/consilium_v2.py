#!/usr/bin/env python3
"""consilium_v2.py — the COMPACT adversarial tournament: one frontier call hosts the whole gauntlet.

WHY ONE CALL (2026-09-11). gauntlet.py runs the five rounds as ~21 separate model calls per
question (5 blind seats, 5 steelmen, 5 rebuttals, 4 judged bouts, 1 red team, 1 chair). Under
the default CLI each of those carried 30-60K tokens of Claude Code preamble, so a frontier-model
gauntlet cost ~1M tokens per question and the fleet quietly routed the seats to an 8B local
model instead — which is where the "5 citations, 0.95 confidence, generic prose" cards came from.

A frontier model holding ALL five seats in one context does the debate BETTER than five small
models passing JSON: the steelman round actually sees the position it must restate, the judge
sees both bouts side by side, the chair remembers every concession. And it costs 15-30K tokens
with lean calls (see frontier.py) — a 40-60x reduction — which is what makes it affordable to
run Fable 5.1 on every docket question instead of on none.

WHAT IS PRESERVED FROM THE GAUNTLET, DELIBERATELY:
  * The five rounds and their failure-mode logic (blind -> steelman -> hold/concede -> red team
    -> chair), spelled out as procedure the model must follow IN ORDER inside the response.
  * The persistent corps: seats are real `experts` rows (doctrine, method, Elo, calibration),
    method-diverse, and the in-context bouts are written back through expert_corps.record_bout
    so Elo keeps moving; every seat stakes a dated probability into expert_positions so Brier
    can finally be scored (theory_lab.py resolves them).
  * Preserved dissent, flips_if, conditions, unsettled — the memo shape legal_docket.mint_card
    already persists. This module returns the same aggregate dict gauntlet.run() returns.

WHAT IS NEW:
  * GROUNDING. With research on, the model is given WebSearch/WebFetch and told that every
    citation must carry a URL it actually opened plus a short verbatim quote. Unopened sources
    are demoted to assumptions. Cards stop asserting authorities that do not exist.
  * CROSS-VENDOR RED TEAM. For high-priority questions, GPT-5.5 (via the ChatGPT subscription)
    independently attacks the memo; a material hit triggers one bounded revision pass. Two
    model families disagreeing is the one signal a single model's self-debate cannot produce.
  * AN AUDIT TRANSCRIPT. The full tournament JSON is appended to a local JSONL so a proof pack
    can show the seats, the flips, the concessions and the red-team hit for any card.

FAIL-SOFT. Frontier unavailable / budget exhausted / malformed output -> returns None and the
legacy gauntlet path runs on local models. It never raises into legal_docket.
"""
from __future__ import annotations
import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import common_utils
import expert_corps as corps
import frontier

_s = common_utils.safe_string_coerce

ENABLED = os.environ.get("ORCH_CONSILIUM_V2", "true").lower() not in ("0", "false", "no", "off")
RESEARCH = os.environ.get("ORCH_CONSILIUM_RESEARCH", "true").lower() not in ("0", "false", "no", "off")
CROSS_VENDOR = os.environ.get("ORCH_CONSILIUM_CROSS_VENDOR", "true").lower() not in ("0", "false", "no", "off")
SEATS = int(os.environ.get("ORCH_CONSILIUM_SEATS", "5"))
MAX_TURNS = int(os.environ.get("ORCH_CONSILIUM_MAX_TURNS", "18"))
MIN_TOKENS = int(os.environ.get("ORCH_CONSILIUM_MIN_TOKENS", "30000"))
HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
TRANSCRIPTS = os.path.join(HOME, "consilium", "tournaments.jsonl")

CITATION = {"type": "object", "properties": {
    "source": {"type": "string"}, "proposition": {"type": "string"},
    "confidence": {"type": "number"}, "url": {"type": "string"},
    "verified": {"type": "boolean"}, "quote": {"type": "string"}},
    "required": ["source", "proposition", "confidence", "url", "verified", "quote"]}

MEMO = {"type": "object", "properties": {
    "verdict": {"type": "string"}, "memo": {"type": "string"},
    "citations": {"type": "array", "items": CITATION},
    "assumptions": {"type": "array", "items": {"type": "string"}},
    "confidence": {"type": "number"}, "dissent": {"type": "string"},
    "flips_if": {"type": "string"}, "conditions": {"type": "string"},
    "unsettled": {"type": "boolean"}},
    "required": ["verdict", "memo", "citations", "assumptions", "confidence", "dissent",
                 "flips_if", "conditions", "unsettled"]}

SCHEMA = {"type": "object", "properties": {
    "seats": {"type": "array", "items": {"type": "object", "properties": {
        "seat": {"type": "string"},
        "r1_position": {"type": "string"}, "r1_analysis": {"type": "string"},
        "r1_probability": {"type": "number"},
        "steelman_of": {"type": "string"}, "steelman": {"type": "string"},
        "moved": {"type": "boolean"},
        "r3_outcome": {"type": "string"}, "r3_position": {"type": "string"},
        "r3_grounds": {"type": "string"}, "r3_probability": {"type": "number"},
        "conceded": {"type": "string"}},
        "required": ["seat", "r1_position", "r1_analysis", "r1_probability", "steelman_of",
                     "steelman", "moved", "r3_outcome", "r3_position", "r3_grounds",
                     "r3_probability", "conceded"]}},
    "bouts": {"type": "array", "items": {"type": "object", "properties": {
        "a": {"type": "string"}, "b": {"type": "string"}, "winner": {"type": "string"},
        "margin": {"type": "number"}, "grounds": {"type": "string"}},
        "required": ["a", "b", "winner", "margin", "grounds"]}},
    "red_team": {"type": "object", "properties": {
        "breaks": {"type": "boolean"}, "attack": {"type": "string"},
        "failing_fact_pattern": {"type": "string"}, "missed_authority": {"type": "string"},
        "severity": {"type": "string"}, "durable_because": {"type": "string"}},
        "required": ["breaks", "attack", "failing_fact_pattern", "missed_authority",
                     "severity", "durable_because"]},
    "memo": MEMO,
    "research": {"type": "object", "properties": {
        "queries": {"type": "array", "items": {"type": "string"}},
        "sources_opened": {"type": "array", "items": {"type": "string"}}},
        "required": ["queries", "sources_opened"]}},
    "required": ["seats", "bouts", "red_team", "memo", "research"]}

ATTACK_SCHEMA = {"type": "object", "properties": {
    "breaks": {"type": "boolean"}, "attack": {"type": "string"},
    "missed_authority": {"type": "string"}, "failing_fact_pattern": {"type": "string"},
    "severity": {"type": "string"}, "what_would_fix_it": {"type": "string"}},
    "required": ["breaks", "attack", "missed_authority", "failing_fact_pattern", "severity",
                 "what_would_fix_it"]}

SYSTEM = """You are the CONSILIUM — an adversarial legal/regulatory tribunal engine. You will run a
FIVE-ROUND GAUNTLET among the expert seats given to you, IN FULL, inside this single response, and
return ONLY the JSON object matching the schema you were given.

PROCEDURE (order is mandatory; each round exists to remove a specific failure mode):
 R1 BLIND     Write every seat's independent position BEFORE writing any R2 content. Each seat
              reasons ONLY from its own doctrine/method and the authority. No seat may reference
              another seat in R1. Agreement that survives this round is real; agreement produced by
              anchoring is not.
 R2 STEELMAN  For each seat, identify the seat whose R1 position most opposes it (by holding and by
              probability), and argue THAT position at its strongest — adding the best authority
              and framing the opponent did not use. A steelman weaker than the original is a failure.
              Then say honestly whether it moved the seat.
 R3 SETTLE    Each seat HOLDS with new grounds, CONCEDES, or PARTIALLY concedes. Conceding to a
              better argument is scored as a strength; refusing to move when the evidence moved is
              the failure. Restate the probability.
 BOUTS        Judge 4 pairwise bouts (distinct pairs) on GROUNDING ONLY: did the seat name the
              operative authority, apply it to THESE facts, and acknowledge its limits? Fluent
              prose with no authority loses to a plain answer that cites correctly.
 R4 RED TEAM  Attack the leading position (the strongest-grounded R3 holding): the fact pattern
              where it fails, the authority it missed or read too generously, the jurisdiction
              where it is simply wrong, the step it assumed rather than established. If it holds,
              say so and say why — a manufactured objection is worse than a concession.
 R5 CHAIR     Write the memo a General Counsel will act on this week. Lead with the answer. Then
              the operative authority, the application, the limits, what would flip it, and the
              strongest surviving objection VERBATIM with its reasoning. If the honest answer is
              unsettled, say so and give the decision rule for acting under that uncertainty.

GROUNDING RULES (these are the product):
 * Use WebSearch/WebFetch when they are available: BEFORE R1, open the operative primary
   authority for this question — statute text, regulation, the controlling opinion, the agency
   guidance or no-action letter. Prefer official sources (legislature and agency sites, eCFR,
   Federal Register, court opinions) over secondary commentary.
 * EVERY citation in the memo carries: the URL you actually opened, a verbatim quote of at most
   40 words that supports the proposition, and verified=true. If you could not open it, set
   verified=false, lower its confidence, and list the point under assumptions. Do not invent
   section numbers, docket numbers, or holdings. A citation you did not read is an assumption.
 * Citation depth floor: at least 10 citations overall on a contested question and 5+ per
   contested issue; for a genuinely novel issue cite by analogy and label it analogical.
 * Probabilities are forecasts of where a regulator or court lands within 24 months. They will be
   scored (Brier) against real outcomes. An honest 0.55 beats a performative 0.95.
 * Seats are DISTINCT schools of thought. Do not homogenize them into one voice.

Return ONLY the JSON object. No prose outside it."""

USER = """QUESTION: {question}
CONTEXT: {context}
VERTICAL: {vertical}
PRIORITY: {priority}
TODAY: {today}

SEATS (argue each faithfully from its own doctrine and method):
{seats}

Run the full gauntlet now and return the JSON object."""

ATTACK = """You are opposing counsel, the examiner, and the enforcement division at once — an independent
adversary from a different model family. Your ONLY job is to break the memo below. Find the fact
pattern where it fails, the authority it missed or read too generously, the jurisdiction where it
is simply wrong, the step it assumed rather than established. If after genuine effort you cannot
break it, say so plainly — a manufactured objection is worse than a concession.

QUESTION: {question}
MEMO VERDICT: {verdict}
MEMO: {memo}
CITATIONS: {citations}

Return ONLY a JSON object: {{"breaks":bool,"attack":str,"missed_authority":str,
"failing_fact_pattern":str,"severity":"fatal|material|marginal|none","what_would_fix_it":str}}"""

REVISE = """An INDEPENDENT adversary (a different model family) attacked the memo you chaired. Either
rebut the attack on the record or revise the memo to absorb it. Keep every grounding rule: URLs you
opened, verbatim quotes, verified flags, assumptions for anything unopened. Preserve dissent.

QUESTION: {question}
CURRENT MEMO (JSON): {memo}
ADVERSARY ATTACK (JSON): {attack}

Return ONLY the revised memo JSON object (same shape as the memo you were given). If you rebut
rather than revise, put the rebuttal in `dissent` handling and keep the verdict."""


# ── seats ────────────────────────────────────────────────────────────────────────────────────────
def _seat_pool(vertical, n):
    pool = corps.roster(vertical=vertical, limit=n * 3)
    if len(pool) < n:
        pool += [e for e in corps.roster(limit=n * 3) if e not in pool]
    picked, methods = [], set()
    for e in pool:
        m = (e.get("method") or "").lower()
        if m in methods and len(picked) < n:
            continue
        picked.append(e)
        methods.add(m)
        if len(picked) >= n:
            break
    for e in pool:
        if len(picked) >= n:
            break
        if e not in picked:
            picked.append(e)
    return picked[:n]


def _sourced_memory(expert_id, k=4):
    try:
        rows = db.select("expert_memory", {"select": "claim,source_url", "expert_id": f"eq.{expert_id}",
                                           "source_url": "not.is.null", "order": "salience.desc",
                                           "limit": str(k)}) or []
    except Exception:
        rows = []
    return "; ".join(f"{(r.get('claim') or '')[:140]} [{(r.get('source_url') or '')[:60]}]" for r in rows) \
        or "(no sourced research yet)"


def _seat_block(e):
    return (f"- SEAT \"{e.get('public_label')}\" | method: {e.get('method')} | domain: {e.get('domain')} | "
            f"vertical: {e.get('vertical')} | calibration: {corps.calibration(e)}\n"
            f"  doctrine: {_s(e.get('doctrine'))[:700]}\n"
            f"  sourced research: {_sourced_memory(e['id'])[:600]}")


def _priority_from(context, default="medium"):
    m = re.search(r"PRIORITY:\s*(high|medium|low)", context or "", re.I)
    return m.group(1).lower() if m else default


def _match_seat(label, panel):
    lab = (label or "").strip().lower()
    for e in panel:
        if (e.get("public_label") or "").strip().lower() == lab:
            return e
    for e in panel:
        if lab and lab in (e.get("public_label") or "").lower():
            return e
    return None


def _append_transcript(rec):
    try:
        os.makedirs(os.path.dirname(TRANSCRIPTS), exist_ok=True)
        with open(TRANSCRIPTS, "a") as f:
            f.write(json.dumps(rec, default=str)[:200000] + "\n")
    except Exception:
        pass


# ── the tournament ───────────────────────────────────────────────────────────────────────────────
def run(question, context="", vertical=None, docket_id=None, seats=SEATS, priority=None):
    """Return the memo-grade aggregate (gauntlet.run() shape) or None to let the legacy path run."""
    if not ENABLED or not frontier.available(min_tokens=MIN_TOKENS):
        return None
    panel = _seat_pool(vertical, seats)
    if len(panel) < 2:
        return None
    priority = (priority or _priority_from(context)).lower()
    tools = frontier.WEB_TOOLS if RESEARCH else None
    user = USER.format(question=(question or "")[:3000], context=(context or "")[:3000],
                       vertical=vertical or "n/a", priority=priority,
                       today=datetime.date.today().isoformat(),
                       seats="\n".join(_seat_block(e) for e in panel))
    t0 = time.time()
    r = frontier.complete(user, system=SYSTEM, need=9, tools=tools,
                          max_turns=MAX_TURNS if tools else 1, json_schema=SCHEMA,
                          timeout=int(os.environ.get("ORCH_CONSILIUM_TIMEOUT_S", "1500")),
                          tag="consilium.tournament")
    j = r.get("json")
    if r.get("error") or not isinstance(j, dict) or not isinstance(j.get("memo"), dict):
        print(f"consilium_v2: tournament unusable ({r.get('error') or 'malformed output'}); "
              f"legacy gauntlet will run", flush=True)
        return None
    memo = j["memo"]
    seats_out = [s for s in (j.get("seats") or []) if isinstance(s, dict)]
    bouts = [b for b in (j.get("bouts") or []) if isinstance(b, dict)]
    red = j.get("red_team") if isinstance(j.get("red_team"), dict) else {}

    # Elo writeback — the in-context judge's bouts move the persistent corps exactly as before.
    judged = 0
    for b in bouts[:6]:
        a, bb = _match_seat(b.get("a"), panel), _match_seat(b.get("b"), panel)
        if not a or not bb or a is bb:
            continue
        w = str(b.get("winner") or "").strip().upper()
        wid = a["id"] if w == "A" else (bb["id"] if w == "B" else None)
        try:
            corps.record_bout(question, a, bb, wid, margin=float(b.get("margin") or 0.5),
                              grounds=_s(b.get("grounds"))[:1000], docket_id=docket_id,
                              judge_model=r.get("model"))
            judged += 1
        except Exception:
            pass

    # Stake every seat's dated forecast so Brier can be scored later (theory_lab.py).
    resolves_by = (datetime.date.today() + datetime.timedelta(days=730)).isoformat()
    staked = 0
    for s in seats_out:
        e = _match_seat(s.get("seat"), panel)
        if not e:
            continue
        p = s.get("r3_probability", s.get("r1_probability"))
        try:
            db.insert("expert_positions", {
                "expert_id": e["id"], "docket_id": docket_id, "question": (question or "")[:2000],
                "thesis": _s(s.get("r3_position") or s.get("r1_position"))[:2000],
                "probability": max(0.0, min(1.0, float(p))) if p is not None else None,
                "generation": int(e.get("generation") or 1), "resolves_by": resolves_by})
            staked += 1
        except Exception:
            pass

    # Cross-vendor adversary for the questions that matter most.
    cross = {"ran": False}
    if CROSS_VENDOR and priority == "high" and frontier.codex_available():
        att = frontier.codex_complete(ATTACK.format(
            question=(question or "")[:1500], verdict=_s(memo.get("verdict"))[:600],
            memo=_s(memo.get("memo"))[:9000],
            citations=json.dumps(memo.get("citations") or [])[:5000]),
            json_schema=ATTACK_SCHEMA, tag="consilium.crossvendor")
        aj = att.get("json") if isinstance(att.get("json"), dict) else None
        cross = {"ran": not att.get("error"), "model": att.get("model"), "error": att.get("error") or "",
                 "severity": (aj or {}).get("severity"), "breaks": (aj or {}).get("breaks"),
                 "attack": _s((aj or {}).get("attack"))[:1500]}
        if aj and str(aj.get("severity", "")).lower() in ("fatal", "material") and frontier.available(min_tokens=15000):
            rev = frontier.complete(REVISE.format(question=(question or "")[:1500],
                                                  memo=json.dumps(memo)[:14000],
                                                  attack=json.dumps(aj)[:4000]),
                                    system=SYSTEM, need=9, tools=tools, max_turns=10 if tools else 1,
                                    json_schema=MEMO, tag="consilium.revise")
            rj = rev.get("json")
            if isinstance(rj, dict) and rj.get("memo") and not rev.get("error"):
                memo = rj
                cross["revised"] = True

    cites = [c for c in (memo.get("citations") or []) if isinstance(c, dict)]
    verified = [c for c in cites if c.get("verified") and c.get("url")]
    flipped = sum(1 for s in seats_out if s.get("moved"))
    conceded = sum(1 for s in seats_out if str(s.get("r3_outcome", "")).lower() in ("concede", "partial"))
    process = {"engine": "consilium_v2", "model": r.get("model"), "research": bool(tools),
               "seats": [corps.publication_view(e) for e in panel], "rounds": 5,
               "positions_flipped_by_steelman": flipped, "concessions": conceded,
               "bouts_judged": judged, "positions_staked": staked,
               "red_team_severity": red.get("severity"),
               "citation_count": len(cites), "verified_citations": len(verified),
               "sources_opened": ((j.get("research") or {}).get("sources_opened") or [])[:25],
               "tokens_in": r.get("tokens_in"), "tokens_out": r.get("tokens_out"),
               "turns": r.get("turns"), "latency_s": round(time.time() - t0, 1),
               "cross_vendor": cross}
    agg = {"question": question,
           "verdict": _s(memo.get("verdict")),
           "opinion": _s(memo.get("memo")),
           "citations": cites,
           "assumptions": memo.get("assumptions") or [],
           "conviction": round(max(0.0, min(1.0, float(memo.get("confidence") or 0.5))) * 10, 1),
           "dissent": _s(memo.get("dissent")) or "none",
           "flips_if": _s(memo.get("flips_if")),
           "conditions": _s(memo.get("conditions")),
           "unsettled": bool(memo.get("unsettled")),
           "red_team": red,
           "process": process}
    _append_transcript({"at": datetime.datetime.utcnow().isoformat(), "docket_id": docket_id,
                        "vertical": vertical, "priority": priority, "question": question,
                        "tournament": j, "final_memo": memo, "process": process})
    print(f"consilium_v2: {r.get('model')} tournament on '{(question or '')[:70]}' -> "
          f"{len(cites)} citations ({len(verified)} verified), red={red.get('severity')}, "
          f"flipped={flipped}, conceded={conceded}, tokens={r.get('tokens_in')}+{r.get('tokens_out')}, "
          f"{process['latency_s']}s", flush=True)
    return agg


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "Is a dual-currency sweepstakes model lawful in Nevada today?"
    v = sys.argv[2] if len(sys.argv) > 2 else "gaming"
    out = run(q, context="PRIORITY: high", vertical=v)
    print(json.dumps(out, indent=2, default=str)[:6000] if out else "consilium_v2: no result (frontier unavailable?)")

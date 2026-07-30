#!/usr/bin/env python3
"""corpus_forecaster.py — build the decisioning corpus BEFORE the customer arrives.

THE OPERATOR'S THESIS (2026-07-30): our users will disproportionately be AI-native gaming/fintech
startups pushing into interpretations and structures that were not possible or considered until
recently — often invented BY the same class of models doing their coding. So the corpus cannot wait
for questions to be asked. It must anticipate: enumerate the business models, the regulations they
collide with, the grey areas, the creative structures agentic coding will produce, and the
profitability pressure points — and pre-debate ALL of it, so that the first time a founder (or
their coding agent) reaches a decision point, the verdict card already exists.

THE ENGINE, three feeds into one docket:

  1. COMBINATORIAL ANTICIPATION — expand (business model x regulatory axis x AI-usage pattern) into
     concrete, docketable questions. The grid is seeded below and self-extends: each cycle asks the
     model to name model/axis/pattern entries the grid is missing, so the frontier keeps moving.
  2. MISS-DRIVEN DEMAND — Foulkon logs every gradient cache-miss (novel_gradient_queries). Misses
     are literal evidence of what real decision flow needs pre-debated. Highest-signal feed.
     (Pulled via ORCH_FOULKON_NOVEL_URL when set; fail-soft absent.)
  3. RED-TEAM-AS-FOUNDER — the inversion that finds what enumeration misses: prompt the model AS an
     aggressive AI-native founder ("design the most profitable structure that arguably threads
     these rules") and docket whatever it invents. Our customers' coding agents WILL think of these
     structures, because we just demonstrated that a model does. Pre-debating the exploit space
     before customers enter it is how we advise them past traps we've already mapped — and how the
     Consilium can "predict their futures": the anticipated-question set for a business model IS
     the regulatory trajectory forecast for every company running that model.

BOUNDED: MAX_NEW_PER_RUN caps insertion per cycle, dedupe is by (vertical, question) unique key,
and the docket's own gauntlet loop (legal_docket) does the actual pre-debating at its own pace.
Anticipation generates the queue; it never burns gauntlet budget itself.
"""
from __future__ import annotations
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import expert_corps as corps

MAX_NEW_PER_RUN = int(os.environ.get("ORCH_CORPUS_FORECAST_MAX_NEW", "12"))

# The anticipation grid — seed axes. Self-extending (see EXTEND_PROMPT).
BUSINESS_MODELS = [
    "dual-currency sweepstakes casino", "skill-based real-money tournament platform",
    "prediction market / event contracts", "social casino with premium currency",
    "iGaming B2B supplier (RGS/aggregator)", "esports wagering", "daily fantasy",
    "crypto-native gaming with tokenized rewards", "AI-personalized betting recommendations",
    "white-label sportsbook", "lottery courier", "AI-driven odds/pricing engine vendor",
    "gaming-adjacent payments/wallet provider", "affiliate/streamer network with rev-share",
]
REG_AXES = [
    "licensing & suitability (incl. key persons, change of control)",
    "consideration/prize/chance characterization", "AML/BSA and SAR obligations",
    "money transmission (state MTL / federal MSB)", "advertising & UDAP/dark patterns",
    "responsible gaming & self-exclusion", "data privacy & minors", "CEA/CFTC jurisdiction",
    "tax & withholding (W-2G, excise)", "tribal compacts & IGRA", "payment-network rules",
    "AI-specific duties (disclosure, model governance, automated decisioning)",
]
AI_PATTERNS = [
    "fully agentic customer support making binding promises", "AI-generated game content and odds",
    "personalization engines that could target vulnerable players",
    "autonomous marketing/campaign generation", "AI-drafted compliance filings",
    "vibe-coded features shipping without legal review", "LLM-based KYC/affordability decisions",
]

QUESTION_PROMPT = """Generate {n} SPECIFIC, docketable legal/regulatory questions a General Counsel
would pay to have answered, for companies at this intersection:

BUSINESS MODEL: {model}
REGULATORY AXIS: {axis}
AI-USAGE PATTERN: {pattern}

Rules: each question must be concrete enough to answer with operative authority (name the trigger,
the actor, the jurisdiction class), non-duplicative, and phrased as the GC would ask it. Prefer the
grey areas — the questions where reasonable counsel disagree are the ones worth pre-debating.
Return a JSON array: [{{"question":"...","priority":"high|medium|low",
"why":"one sentence on who pays for this answer"}}]"""

FOUNDER_PROMPT = """You are an extremely aggressive, extremely capable AI-native founder in the
{vertical} space. Your coding agents ship daily. Design {n} novel product structures or mechanics
that maximize profitability while ARGUABLY staying within current law — the kind of structure a
creative team with autonomous coding actually ships before any lawyer sees it. For each, state the
legal theory you'd rely on and where it is weakest.

Return a JSON array: [{{"structure":"what you'd build","legal_theory":"why it's arguably lawful",
"weakest_point":"where the theory is most vulnerable",
"docket_question":"the question a regulator or court would eventually ask about this"}}]"""

EXTEND_PROMPT = """Here is the anticipation grid we pre-debate regulatory questions from. Name up to
3 entries PER AXIS that are missing and rising — things appearing in startup launches, enforcement
chatter, or agentic-coding capability that the grid does not cover yet. Only genuinely distinct,
emerging entries; return empty arrays if the grid is adequate.
GRID: {grid}
Return ONE JSON object: {{"business_models":[],"reg_axes":[],"ai_patterns":[]}}"""


def _insert_question(vertical, question, priority="medium", source="forecast"):
    q = re.sub(r"\s+", " ", (question or "")).strip()
    if len(q) < 40:
        return False
    try:
        db.insert("legal_docket", {"vertical": vertical, "question": q[:2000],
                                   "priority": priority if priority in ("high", "medium", "low") else "medium",
                                   "status": "pending"}, upsert=True)
        return True
    except Exception:
        return False


def _pull_foulkon_misses(limit=10):
    """Feed 2: real cache-misses from Foulkon's gradient endpoint. Fail-soft without the URL."""
    url = os.environ.get("ORCH_FOULKON_NOVEL_URL", "")
    if not url:
        return []
    try:
        import urllib.request
        req = urllib.request.Request(url + ("&" if "?" in url else "?") + f"limit={limit}",
                                     headers={"User-Agent": "corpus-forecaster"})
        with urllib.request.urlopen(req, timeout=10) as r:
            rows = json.loads(r.read().decode("utf-8", "replace"))
        return rows if isinstance(rows, list) else rows.get("queries") or []
    except Exception:
        return []


def run():
    import random
    added = 0
    out = {"combinatorial": 0, "founder_redteam": 0, "foulkon_misses": 0, "grid_extended": 0}

    # Feed 2 first — real demand outranks anticipation.
    for m in _pull_foulkon_misses():
        if added >= MAX_NEW_PER_RUN:
            break
        if _insert_question(m.get("vertical") or "gaming", m.get("question"), "high", "foulkon_miss"):
            added += 1
            out["foulkon_misses"] += 1

    # Feed 1 — one random grid cell per run (the docket loop drains at its own pace; coverage
    # accumulates across runs, which at 1/hr = ~9K cell-visits/year against a ~1.2K-cell grid).
    model = random.choice(BUSINESS_MODELS)
    axis = random.choice(REG_AXES)
    pattern = random.choice(AI_PATTERNS)
    vertical = "finserv" if any(k in axis for k in ("AML", "money transmission", "CEA", "payment")) else \
               "aidata" if "AI-specific" in axis or "privacy" in axis else "gaming"
    qs = corps._json(QUESTION_PROMPT.format(n=min(5, MAX_NEW_PER_RUN - added) or 1, model=model,
                                            axis=axis, pattern=pattern), kind="review", arr=True) or []
    for q in qs:
        if added >= MAX_NEW_PER_RUN:
            break
        if isinstance(q, dict) and _insert_question(vertical, q.get("question"), q.get("priority", "medium")):
            added += 1
            out["combinatorial"] += 1

    # Feed 3 — red-team-as-founder (every third run keeps it cheap; deterministic-ish via day parity)
    import time as _t
    if int(_t.time() // 3600) % 3 == 0 and added < MAX_NEW_PER_RUN:
        inv = corps._json(FOUNDER_PROMPT.format(vertical=vertical, n=3), kind="review", arr=True) or []
        for s in inv:
            if added >= MAX_NEW_PER_RUN:
                break
            if isinstance(s, dict) and _insert_question(vertical, s.get("docket_question"), "high"):
                added += 1
                out["founder_redteam"] += 1

    # Self-extension — daily-ish (hour 4), bounded, in-memory only this run; persisted additions go
    # through the docket as questions, so the grid file itself never mutates silently.
    if int(_t.time() // 3600) % 24 == 4:
        ext = corps._json(EXTEND_PROMPT.format(grid=json.dumps({
            "business_models": BUSINESS_MODELS, "reg_axes": REG_AXES,
            "ai_patterns": AI_PATTERNS})[:6000]), kind="review") or {}
        for bm in (ext.get("business_models") or [])[:3]:
            BUSINESS_MODELS.append(str(bm)[:120])
            out["grid_extended"] += 1

    out["added"] = added
    print("corpus_forecaster: " + json.dumps(out))
    return out


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))

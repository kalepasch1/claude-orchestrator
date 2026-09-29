#!/usr/bin/env python3
"""pathway_lab.py — the STRUCTURING TRIBUNAL: ranked lawful pathways, regime weak points,
jurisdiction comparisons and kill criteria, each attacked before it is ranked.

WHY (quality review, 2026-09-28). The tribunal was built to answer "is X lawful?" and defend the
answer. Across the 33 frontier-grade cards it had minted, 0 discussed how jurisdictions differ and
1 presented alternatives; the commission's novelty reviewer scored them 0.2-0.4 ("settled and
familiar to any practitioner"). That is a good defensive memo engine and it is not what the
operator uses the tribunal FOR — pathways, weaknesses, arbitrage, opportunities, creative
structures. A verdict card says where the line is. This module asks what to build given the line.

THE RUN (three calls, two model families):
  1. STRUCTURE   Fable 5.1 with WebSearch/WebFetch. Maps the regime (each trigger, cited), names
                 where it is WEAKEST (undefined terms, thresholds, enforcement gaps, preemption
                 conflicts, stale rules), compares how other jurisdictions treat the same activity,
                 and proposes 4-7 distinct pathways — each a real change to product, entity,
                 licensing, partner or sequencing, with its legal theory, what is retained and
                 lost, time, cost, and an honest risk posture.
  2. ATTACK      GPT-5.5 (cross-vendor; Opus 5 when Codex is unavailable) plays the examiner, the
                 enforcement division and the plaintiffs' bar against EVERY pathway: the
                 regulator's first move, the authority missed, the fact pattern where it fails,
                 and how the structure fares under substance-over-form.
  3. ADJUDICATE  Fable 5.1, no tools: keeps, revises or kills each pathway in light of the attack,
                 sets durability and enforcement probability, writes kill criteria, ranks.

GROUNDING IS MECHANICAL. After the model returns, every citation URL is fetched by us and the
quote is checked against the page text. The model's own `verified` flag is discarded. A pathway
whose legal theory rests on citations we could not confirm is kept but marked, and its score is
discounted — the reviewing attorney sees exactly which support is unconfirmed.

CREATIVE RISK IS LABELLED, NOT SUPPRESSED (operator direction 2026-09-28). A pathway may be
`aggressive_arguable`: untested, defensible on the text, with a real chance a regulator
disagrees. It is ranked alongside the conservative routes with its durability and enforcement
probability stated, so the operator can choose the risk instead of never seeing the option.

THE LINE THAT IS NOT CROSSED. A pathway changes the FACTS so that a rule is satisfied or does not
apply: different product mechanics, a licensed partner, a different entity or jurisdiction, an
exemption whose conditions are actually met, a no-action or comment request. It is never
concealment, misstatement to a regulator, bank or partner, a sham lacking economic substance,
or structuring to defeat a reporting threshold. Those are not aggressive pathways; they are
violations, and the adversary is told to flag any pathway that drifts toward them as fatal.

REVIEW-ONLY. Rows land in pathway_runs / verdict_pathways with status 'proposed', a packet goes
to the approvals queue, markdown goes under docs/consilium/pathways/. Nothing is adopted,
published or acted on without a human.
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
import frontier

_s = common_utils.safe_string_coerce

ENABLED = os.environ.get("ORCH_PATHWAY_LAB", "true").lower() not in ("0", "false", "no", "off")
RUNS_PER_TICK = int(os.environ.get("ORCH_PATHWAY_RUNS", "1"))
MIN_TOKENS = int(os.environ.get("ORCH_PATHWAY_MIN_TOKENS", "200000"))
MAX_TURNS = int(os.environ.get("ORCH_PATHWAY_MAX_TURNS", "16"))
PROJECT = os.environ.get("ORCH_PATHWAY_PROJECT", "apparently-law")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "consilium", "pathways")

KINDS = ("licensing_pathway", "structural_redesign", "jurisdictional_sequencing", "partner_or_sponsor",
         "exemption_or_safe_harbor", "regulatory_engagement", "product_boundary", "other")
POSTURES = ("conservative", "defensible", "aggressive_arguable")
KIND_HINTS = (("partner_or_sponsor", ("partner", "sponsor", "b2b", "supply", "white_label", "vendor")),
              ("licensing_pathway", ("licen", "registr", "authoris", "authoriz")),
              ("jurisdictional_sequencing", ("jurisdiction", "sequenc", "market_entry", "phased")),
              ("exemption_or_safe_harbor", ("exempt", "safe_harbo", "carve")),
              ("regulatory_engagement", ("engage", "no_action", "interpretive", "comment", "sandbox")),
              ("product_boundary", ("product", "boundary", "feature", "mechanic")),
              ("structural_redesign", ("structur", "redesign", "entity", "reorgan")))

CITE = {"type": "object", "properties": {
    "source": {"type": "string"}, "url": {"type": "string"}, "quote": {"type": "string"},
    "proposition": {"type": "string"}},
    "required": ["source", "url", "quote", "proposition"]}

STRUCTURE_SCHEMA = {"type": "object", "properties": {
    "objective_restated": {"type": "string"},
    "regime_map": {"type": "array", "items": {"type": "object", "properties": {
        "element": {"type": "string"}, "trigger": {"type": "string"}, "authority": {"type": "string"},
        "url": {"type": "string"}, "quote": {"type": "string"}},
        "required": ["element", "trigger", "authority", "url", "quote"]}},
    "weak_points": {"type": "array", "items": {"type": "object", "properties": {
        "point": {"type": "string"}, "kind": {"type": "string"}, "authority": {"type": "string"},
        "url": {"type": "string"}, "quote": {"type": "string"}, "how_it_matters": {"type": "string"},
        "confidence": {"type": "number"}},
        "required": ["point", "kind", "authority", "url", "quote", "how_it_matters", "confidence"]}},
    "jurisdiction_matrix": {"type": "array", "items": {"type": "object", "properties": {
        "jurisdiction": {"type": "string"}, "treatment": {"type": "string"}, "authority": {"type": "string"},
        "url": {"type": "string"}, "quote": {"type": "string"}, "friction": {"type": "string"},
        "note": {"type": "string"}},
        "required": ["jurisdiction", "treatment", "authority", "url", "quote", "friction", "note"]}},
    "pathways": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "title": {"type": "string"}, "kind": {"type": "string"},
        "structure": {"type": "string"}, "legal_theory": {"type": "string"},
        "jurisdictions": {"type": "array", "items": {"type": "string"}},
        "citations": {"type": "array", "items": CITE},
        "retained": {"type": "array", "items": {"type": "string"}},
        "lost": {"type": "array", "items": {"type": "string"}},
        "time_to_market_days": {"type": "integer"},
        "cost_band": {"type": "string"}, "value_band": {"type": "string"},
        "risk_posture": {"type": "string"},
        "durability": {"type": "number"}, "enforcement_probability": {"type": "number"},
        "substance_over_form": {"type": "string"}, "kill_criteria": {"type": "string"},
        "first_steps": {"type": "array", "items": {"type": "string"}}},
        "required": ["id", "title", "kind", "structure", "legal_theory", "jurisdictions", "citations",
                     "retained", "lost", "time_to_market_days", "cost_band", "value_band", "risk_posture",
                     "durability", "enforcement_probability", "substance_over_form", "kill_criteria",
                     "first_steps"]}},
    "opportunities": {"type": "array", "items": {"type": "object", "properties": {
        "title": {"type": "string"}, "why_now": {"type": "string"}, "what_to_do": {"type": "string"},
        "url": {"type": "string"}},
        "required": ["title", "why_now", "what_to_do", "url"]}},
    "summary": {"type": "string"}},
    "required": ["objective_restated", "regime_map", "weak_points", "jurisdiction_matrix", "pathways",
                 "opportunities", "summary"]}

ATTACK_SCHEMA = {"type": "object", "properties": {
    "attacks": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "attack": {"type": "string"},
        "regulator_first_move": {"type": "string"}, "missed_authority": {"type": "string"},
        "failing_fact_pattern": {"type": "string"}, "substance_over_form": {"type": "string"},
        "severity": {"type": "string"}, "fixable_by": {"type": "string"}},
        "required": ["id", "attack", "regulator_first_move", "missed_authority", "failing_fact_pattern",
                     "substance_over_form", "severity", "fixable_by"]}},
    "overall": {"type": "string"}},
    "required": ["attacks", "overall"]}

ADJUDICATE_SCHEMA = {"type": "object", "properties": {
    "pathways": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "keep": {"type": "boolean"},
        "revised_structure": {"type": "string"}, "risk_posture": {"type": "string"},
        "durability": {"type": "number"}, "enforcement_probability": {"type": "number"},
        "kill_criteria": {"type": "string"}, "response_to_attack": {"type": "string"}},
        "required": ["id", "keep", "revised_structure", "risk_posture", "durability",
                     "enforcement_probability", "kill_criteria", "response_to_attack"]}},
    "ranking": {"type": "array", "items": {"type": "string"}},
    "recommendation": {"type": "string"}},
    "required": ["pathways", "ranking", "recommendation"]}

LINE = """THE LINE. A pathway changes the FACTS so that a rule is satisfied or genuinely does not apply: different
product mechanics, a licensed partner or sponsor, a different entity or jurisdiction, an exemption whose
conditions are actually met, a sequenced market entry, a no-action, interpretive or comment request. It is
never concealment, a misstatement to a regulator, bank, processor or partner, a sham lacking economic
substance, or structuring to defeat a reporting or licensing threshold. Do not propose those; if a
candidate drifts toward them, drop it and say why."""

STRUCTURE_SYSTEM = """You are the CONSILIUM convened as a STRUCTURING TRIBUNAL for Apparently Law (AI-native regulatory counsel
for gaming and sweepstakes, prediction markets and regulated finance, and AI/data regulation). A verdict
card has already said where the legal line is. Your job is the next question a founder and a General
Counsel actually ask: GIVEN THE LINE, WHAT ARE THE LAWFUL ROUTES TO THE OBJECTIVE, and which is best?

Work in this order and return ONLY the JSON object matching the schema:
 1. REGIME MAP. Break the governing rule into its operative elements and triggers. One row per element,
    each with the authority, the URL you opened, and a verbatim quote of at most 40 words.
 2. WEAK POINTS. Where is this regime weakest or least certain? Undefined or circular terms, numeric
    thresholds, exemptions with loose conditions, gaps between the text and how it is enforced,
    federal/state or cross-border conflicts, rules that predate the technology. Cite each. Say how it
    matters commercially. These are observations about the law, stated with confidence levels.
 3. JURISDICTION MATRIX. How do 4-8 relevant jurisdictions treat the SAME activity? Include at least one
    materially more permissive and one materially stricter regime where they exist. Cite each.
 4. PATHWAYS. Propose 4 to 7 DISTINCT routes. Distinct means a different mechanism, not a variation in
    wording. Cover the range: at least one conservative route, at least one that a careful firm would
    call defensible, and — where the text honestly supports it — one aggressive-but-arguable route that
    is untested and clearly labelled. For each: the concrete structure (what changes), the legal theory
    (rule to application), what capability is retained and lost, days to market, cost band ($, $$,
    $$$), value band, risk posture (conservative | defensible | aggressive_arguable), durability (the
    probability it survives a regulator or court challenge within 24 months), enforcement probability
    (the probability a regulator acts against it within 24 months), how it fares under
    substance-over-form, the kill criteria (the observable event that means abandon this route), and
    the first three steps.
 5. OPPORTUNITIES. Anything the analysis surfaced that is worth doing regardless: a comment window, a
    pending rule, an enforcement pattern that creates demand, a licensable role.

GROUNDING. Use WebSearch/WebFetch. Open primary sources: legislature and agency sites, eCFR, Federal
Register, court opinions, regulator guidance and enforcement releases. Every citation carries the URL you
opened and a verbatim quote of at most 40 words. Our system re-fetches every URL and checks every quote
mechanically; an unconfirmed quote discounts the pathway that relies on it. Do not invent section
numbers, docket numbers or holdings. Probabilities are forecasts and will be scored.

""" + LINE

STRUCTURE_USER = """OBJECTIVE: {objective}
VERTICAL: {vertical}
TODAY: {today}

WHAT THE TRIBUNAL ALREADY HELD (verdict card {card_id}):
VERDICT: {verdict}
POSITION (excerpt): {position}
CONDITIONS: {conditions}
FLIPS IF: {flips_if}
PRESERVED DISSENT: {dissent}
AUTHORITIES ALREADY OPENED (reuse; open more for other jurisdictions): {citations}

Build the structuring analysis now."""

ATTACK_SYSTEM = """You are an independent adversary from a different model family: at once the examiner, the enforcement
division, a state attorney general, and the plaintiffs' bar. You are reviewing proposed regulatory
pathways. Attack EVERY pathway by id. For each: the strongest attack; the regulator's likely FIRST move;
the authority the proposal missed or read too generously; the specific fact pattern where it fails; how
it fares under substance-over-form and anti-evasion doctrine; severity (fatal | material | marginal |
none); and what change would fix it. Mark as fatal any pathway that depends on concealment, a
misstatement to a regulator, bank or partner, a sham without economic substance, or structuring to
defeat a threshold. If a pathway genuinely holds, say so plainly — a manufactured objection is worse
than a concession. Return ONLY the JSON object."""

ADJUDICATE_SYSTEM = """You chaired the structuring tribunal. An independent adversary has attacked each pathway. Decide, on the
record, for each pathway id: keep it as is, keep it with a revised structure that absorbs the attack, or
kill it (keep=false). Do not defend a pathway out of loyalty; do not kill one because an attack sounds
confident. Restate risk posture, durability and enforcement probability after the attack, write the kill
criteria as an observable event, and answer the attack in two or three sentences. Then rank the
surviving pathways best first by risk-adjusted value to a founder who wants to launch lawfully and
quickly, and give a one-paragraph recommendation that names the first choice, the fallback, and what
would make you switch. Creative risk is allowed when it is labelled and priced.

""" + LINE + "\n\nReturn ONLY the JSON object."


# ── mechanical citation verification ─────────────────────────────────────────────────────────────
def _norm(t):
    t = (t or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = t.replace(" ", " ").replace("—", "-").replace("–", "-")
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def check_quote(quote, page_text):
    """-> 'exact' | 'near' | 'absent' | 'no_quote'. Near = at least 60% of 6-word shingles present."""
    nq, nt = _norm(quote), _norm(page_text)
    if len(nq.split()) < 4:
        return "no_quote"
    if nq in nt:
        return "exact"
    w = nq.split()
    sh = [" ".join(w[i:i + 6]) for i in range(0, max(1, len(w) - 5))]
    hit = sum(1 for s in sh if s in nt) / len(sh)
    return "near" if hit >= 0.6 else "absent"


def verify_citation(c, fetcher=None):
    """Mutates and returns the citation with `verified` and `check` set by US, not by the model."""
    url = _s(c.get("url")).strip()
    c["verified"] = False
    if not url.lower().startswith(("http://", "https://")):
        c["check"] = "no_url"
        return c
    try:
        if fetcher is None:
            import local_research
            fetcher = local_research.fetch
        page = fetcher(url) or ""
    except Exception:
        page = ""
    if len(page) < 200:
        c["check"] = "unreachable"
        return c
    c["check"] = check_quote(c.get("quote"), page)
    c["verified"] = c["check"] in ("exact", "near")
    return c


def verify_all(j, fetcher=None):
    """Verify every cited row in the structure. Returns (total, verified)."""
    total = ok = 0
    rows = list(j.get("regime_map") or []) + list(j.get("weak_points") or []) + list(j.get("jurisdiction_matrix") or [])
    for p in j.get("pathways") or []:
        rows += list(p.get("citations") or [])
    cache = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        key = (_s(r.get("url")), _s(r.get("quote")))
        if key not in cache:
            cache[key] = dict(verify_citation(dict(r), fetcher))
        r["verified"], r["check"] = cache[key]["verified"], cache[key]["check"]
        total += 1
        ok += 1 if r["verified"] else 0
    return total, ok


# ── scoring ──────────────────────────────────────────────────────────────────────────────────────
def norm_severity(s):
    t = str(s or "").strip().lower()
    if "fatal" in t:
        return "fatal"
    if any(k in t for k in ("material", "high", "major", "severe", "serious", "significant", "medium", "moderate")):
        return "material"
    if any(k in t for k in ("marginal", "minor", "low")):
        return "marginal"
    return "none"


def _band(v, default=2):
    t = str(v or "")
    n = t.count("$")
    if n:
        return max(1, min(3, n))
    t = t.lower()
    return 3 if "high" in t else 1 if "low" in t else default


def _clamp(v, default=0.5):
    try:
        return max(0.0, min(1.0, float(v)))
    except Exception:
        return default


def score(p):
    """Risk-adjusted value in [0,1]. Durable, fast, valuable, well-grounded routes rank first; an
    aggressive route is not penalised for being aggressive, only for the durability and
    enforcement numbers it actually carries."""
    durability = _clamp(p.get("durability"))
    enforcement = _clamp(p.get("enforcement_probability"), 0.3)
    value = _band(p.get("value_band")) / 3.0
    try:
        days = max(0, int(p.get("time_to_market_days") or 180))
    except Exception:
        days = 180
    speed = 1.0 / (1.0 + days / 180.0)
    cites = [c for c in (p.get("citations") or []) if isinstance(c, dict)]
    grounded = (sum(1 for c in cites if c.get("verified")) / len(cites)) if cites else 0.0
    base = durability * (1.0 - 0.6 * enforcement) * (0.5 + 0.5 * value) * (0.7 + 0.3 * speed)
    return round(base * (0.5 + 0.5 * grounded), 4)


# ── candidates ───────────────────────────────────────────────────────────────────────────────────
def _loads(v, default):
    try:
        return json.loads(v) if isinstance(v, str) else (v if v is not None else default)
    except Exception:
        return default


def _candidates(limit):
    """Frontier-grade cards accepted for steering that have no pathway run yet, best first."""
    cards = db.select("verdict_cards", {
        "select": "id,docket_id,vertical,question,verdict,position,conditions,flips_if,dissent,citations,process,publication_state,minted_at",
        "status": "eq.fresh", "publication_state": "in.(attorney_review,published)",
        "order": "minted_at.desc", "limit": "120"}) or []
    done = {r.get("card_id") for r in (db.select("pathway_runs", {"select": "card_id", "limit": "2000"}) or [])}
    revs = {r.get("artifact_id"): r for r in (db.select("publication_reviews", {
        "select": "artifact_id,composite,detail", "artifact_type": "eq.verdict_card", "limit": "2000"}) or [])}
    out = []
    for c in cards:
        if c.get("id") in done:
            continue
        proc = _loads(c.get("process"), {})
        if not str(proc.get("model") or "").startswith("claude"):
            continue
        out.append((float((revs.get(c["id"]) or {}).get("composite") or 0), c))
    out.sort(key=lambda x: -x[0])
    return [c for _, c in out[:limit]]


def objective_for(card):
    return (f"Find the lawful routes for a company in this position to do what the question contemplates, "
            f"at the lowest regulatory friction and fastest time to market. QUESTION: {_s(card.get('question'))[:1200]}")


# ── the run ──────────────────────────────────────────────────────────────────────────────────────
def structure(objective, vertical, card=None):
    card = card or {}
    cites = _loads(card.get("citations"), [])
    lead = [{"source": c.get("source"), "url": c.get("url")} for c in cites if isinstance(c, dict) and c.get("url")][:20]
    return frontier.complete(STRUCTURE_USER.format(
        objective=objective[:2000], vertical=vertical or "n/a", today=datetime.date.today().isoformat(),
        card_id=card.get("id") or "none", verdict=_s(card.get("verdict"))[:900] or "(no prior card)",
        position=_s(card.get("position"))[:6000] or "(none)", conditions=_s(card.get("conditions"))[:900],
        flips_if=_s(card.get("flips_if"))[:900], dissent=_s(card.get("dissent"))[:900],
        citations=json.dumps(lead)[:3500]),
        system=STRUCTURE_SYSTEM, need=9, tools=frontier.WEB_TOOLS, max_turns=MAX_TURNS,
        json_schema=STRUCTURE_SCHEMA, timeout=1800, tag="pathway.structure")


def attack(objective, j):
    brief = [{k: p.get(k) for k in ("id", "title", "kind", "structure", "legal_theory", "jurisdictions",
                                    "risk_posture", "durability", "enforcement_probability",
                                    "substance_over_form")} for p in j.get("pathways") or []]
    prompt = (f"OBJECTIVE: {objective[:1200]}\n\nREGIME MAP: {json.dumps(j.get('regime_map') or [])[:5000]}\n\n"
              f"PATHWAYS: {json.dumps(brief)[:14000]}")
    if frontier.codex_available():
        r = frontier.codex_complete(prompt, system=ATTACK_SYSTEM, json_schema=ATTACK_SCHEMA, tag="pathway.attack")
        if isinstance(r.get("json"), dict) and not r.get("error"):
            return r
    return frontier.complete(prompt, system=ATTACK_SYSTEM, model=frontier.OPUS, json_schema=ATTACK_SCHEMA,
                             timeout=900, tag="pathway.attack")


def adjudicate(objective, j, attacks):
    brief = [{k: p.get(k) for k in ("id", "title", "kind", "structure", "legal_theory", "risk_posture",
                                    "durability", "enforcement_probability", "kill_criteria")}
             for p in j.get("pathways") or []]
    prompt = (f"OBJECTIVE: {objective[:1200]}\n\nPATHWAYS: {json.dumps(brief)[:14000]}\n\n"
              f"ADVERSARY ATTACKS: {json.dumps(attacks)[:12000]}")
    return frontier.complete(prompt, system=ADJUDICATE_SYSTEM, need=9, json_schema=ADJUDICATE_SCHEMA,
                             timeout=900, tag="pathway.adjudicate")


def assemble(j, attacks, adj):
    """Merge structure + attack + adjudication into the final ranked pathway list."""
    att = {str(a.get("id")): a for a in (attacks or {}).get("attacks") or [] if isinstance(a, dict)}
    dec = {str(d.get("id")): d for d in (adj or {}).get("pathways") or [] if isinstance(d, dict)}
    final, killed = [], []
    for p in j.get("pathways") or []:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id"))
        a, d = att.get(pid) or {}, dec.get(pid) or {}
        sev = norm_severity(a.get("severity"))
        p["red_team"] = {"attack": _s(a.get("attack"))[:2000], "regulator_first_move": _s(a.get("regulator_first_move"))[:800],
                         "missed_authority": _s(a.get("missed_authority"))[:800],
                         "failing_fact_pattern": _s(a.get("failing_fact_pattern"))[:800],
                         "substance_over_form": _s(a.get("substance_over_form"))[:800],
                         "severity": sev, "fixable_by": _s(a.get("fixable_by"))[:800],
                         "response": _s(d.get("response_to_attack"))[:1200]}
        if d:
            if _s(d.get("revised_structure")).strip() and _s(d.get("revised_structure")).strip().lower() not in ("none", "n/a", "unchanged"):
                p["structure_original"] = p.get("structure")
                p["structure"] = _s(d.get("revised_structure"))
            p["risk_posture"] = d.get("risk_posture") or p.get("risk_posture")
            p["durability"] = _clamp(d.get("durability"), _clamp(p.get("durability")))
            p["enforcement_probability"] = _clamp(d.get("enforcement_probability"), _clamp(p.get("enforcement_probability"), 0.3))
            p["kill_criteria"] = _s(d.get("kill_criteria")) or p.get("kill_criteria")
        kind = str(p.get("kind") or "other").strip().lower().replace("-", "_").replace(" ", "_")
        if kind not in KINDS:
            kind = next((k for k, words in KIND_HINTS if any(w in kind for w in words)), "other")
        p["kind"] = kind
        posture = str(p.get("risk_posture") or "defensible").strip().lower().replace("-", "_").replace(" ", "_")
        p["risk_posture"] = posture if posture in POSTURES else "defensible"
        p["score"] = score(p)
        if d and d.get("keep") is False:
            killed.append(p)
        else:
            final.append(p)
    order = [str(x) for x in (adj or {}).get("ranking") or []]
    pos = {pid: i for i, pid in enumerate(order)}
    final.sort(key=lambda p: (pos.get(str(p.get("id")), 999), -p["score"]))
    return final, killed


def _markdown(objective, vertical, card, j, final, killed, adj, process):
    today = datetime.date.today().isoformat()
    L = [f"# Pathways — {_s(j.get('objective_restated'))[:140] or objective[:140]}", "",
         f"> Structuring tribunal, {today}. Structure and adjudication by {process.get('model')}; adversary "
         f"{process.get('adversary_model')}. {process.get('citations_verified')}/{process.get('citations_total')} "
         f"citations confirmed by our own fetch. REVIEW-ONLY: nothing here has been adopted or acted on; an "
         f"attorney decides. Vertical: {vertical}. Source card: {(card or {}).get('id') or 'none'}.", "",
         "## Recommendation", "", _s((adj or {}).get("recommendation")) or _s(j.get("summary")), "",
         "## Ranked pathways", ""]
    for i, p in enumerate(final, 1):
        rt = p.get("red_team") or {}
        cites = [c for c in p.get("citations") or [] if isinstance(c, dict)]
        L += [f"### {i}. {p.get('title')}", "",
              f"- **Kind:** {p.get('kind')} · **Risk posture:** {p.get('risk_posture')} · **Durability:** {p.get('durability')} · "
              f"**Enforcement probability:** {p.get('enforcement_probability')} · **Score:** {p.get('score')}",
              f"- **Time to market:** {p.get('time_to_market_days')} days · **Cost:** {p.get('cost_band')} · **Value:** {p.get('value_band')}",
              f"- **Jurisdictions:** {', '.join(p.get('jurisdictions') or [])}", "",
              f"**Structure.** {_s(p.get('structure'))}", "", f"**Legal theory.** {_s(p.get('legal_theory'))}", "",
              f"**Retained:** {'; '.join(p.get('retained') or [])}", "", f"**Lost:** {'; '.join(p.get('lost') or [])}", "",
              f"**Substance over form.** {_s(p.get('substance_over_form'))}", "",
              f"**Adversary ({rt.get('severity')}).** {rt.get('attack')}", "",
              f"**Regulator's first move.** {rt.get('regulator_first_move')}", "",
              f"**Tribunal's answer.** {rt.get('response')}", "",
              f"**Kill criteria.** {_s(p.get('kill_criteria'))}", "", "**First steps.**"]
        L += [f"  {n}. {s}" for n, s in enumerate(p.get("first_steps") or [], 1)]
        L += ["", "**Authorities.**"]
        L += [f"  - [{'confirmed' if c.get('verified') else 'UNCONFIRMED: ' + str(c.get('check'))}] {c.get('source')} — {c.get('url')} — \"{_s(c.get('quote'))[:180]}\"" for c in cites]
        L.append("")
    if killed:
        L += ["## Pathways the tribunal killed", ""]
        L += [f"- **{p.get('title')}** ({(p.get('red_team') or {}).get('severity')}): {(p.get('red_team') or {}).get('response') or (p.get('red_team') or {}).get('attack')}" for p in killed]
        L.append("")
    L += ["## Where the regime is weakest", ""]
    for w in j.get("weak_points") or []:
        L.append(f"- **{w.get('point')}** ({w.get('kind')}, confidence {w.get('confidence')}; "
                 f"{'confirmed' if w.get('verified') else 'UNCONFIRMED'}) — {w.get('how_it_matters')} — {w.get('authority')} {w.get('url')}")
    L += ["", "## Jurisdiction comparison", "", "| Jurisdiction | Treatment | Friction | Authority | Confirmed |", "|---|---|---|---|---|"]
    for m in j.get("jurisdiction_matrix") or []:
        L.append(f"| {m.get('jurisdiction')} | {_s(m.get('treatment'))[:220].replace('|', '/')} | {m.get('friction')} | "
                 f"[{_s(m.get('authority'))[:60]}]({m.get('url')}) | {'yes' if m.get('verified') else 'no'} |")
    if j.get("opportunities"):
        L += ["", "## Opportunities surfaced", ""]
        L += [f"- **{o.get('title')}** — {o.get('why_now')} — {o.get('what_to_do')} {o.get('url')}" for o in j["opportunities"]]
    L += ["", "_Analysis of public law for internal structuring decisions; not legal advice and not a "
              "substitute for attorney review._"]
    return "\n".join(L)


def run_one(objective, vertical, card=None, docket_id=None, fetcher=None):
    """One structuring run. Returns a summary dict, or {'error': ...}."""
    t0 = time.time()
    if not frontier.available(min_tokens=MIN_TOKENS):
        return {"error": "frontier unavailable or budget below the pathway envelope"}
    s = structure(objective, vertical, card)
    j = s.get("json")
    if s.get("error") or not isinstance(j, dict) or not j.get("pathways"):
        return {"error": f"structure failed: {s.get('error') or 'malformed output'}"[:300]}
    total, ok = verify_all(j, fetcher)
    a = attack(objective, j)
    attacks = a.get("json") if isinstance(a.get("json"), dict) and not a.get("error") else {"attacks": []}
    d = adjudicate(objective, j, attacks) if attacks.get("attacks") else {"json": None}
    adj = d.get("json") if isinstance(d.get("json"), dict) and not d.get("error") else {}
    final, killed = assemble(j, attacks, adj)
    process = {"engine": "pathway_lab", "model": s.get("model"), "adversary_model": a.get("model"),
               "adversary_error": a.get("error") or "", "adjudicated": bool(adj),
               "citations_total": total, "citations_verified": ok,
               "tokens": {"structure": [s.get("tokens_in"), s.get("tokens_out")],
                          "attack": [a.get("tokens_in"), a.get("tokens_out")],
                          "adjudicate": [d.get("tokens_in"), d.get("tokens_out")]},
               "turns": s.get("turns"), "latency_s": round(time.time() - t0, 1),
               "pathways_proposed": len(j.get("pathways") or []), "pathways_killed": len(killed),
               "severities": [((p.get("red_team") or {}).get("severity")) for p in final + killed]}
    run_row = None
    try:
        run_row = db.insert("pathway_runs", {
            "card_id": (card or {}).get("id"), "docket_id": docket_id or (card or {}).get("docket_id"),
            "vertical": vertical or "gaming", "objective": objective[:4000],
            "regime_map": j.get("regime_map") or [], "weak_points": j.get("weak_points") or [],
            "jurisdiction_matrix": j.get("jurisdiction_matrix") or [], "opportunities": j.get("opportunities") or [],
            "summary": (_s(adj.get("recommendation")) or _s(j.get("summary")))[:8000],
            "citations_total": total, "citations_verified": ok, "process": process})
    except Exception as e:
        print(f"pathway_lab: run persist failed: {type(e).__name__}: {str(e)[:200]}", flush=True)
    run_id = (run_row[0] if isinstance(run_row, list) and run_row else run_row or {}).get("id") if run_row else None
    saved = 0
    if run_id:
        for i, p in enumerate(final, 1):
            try:
                db.insert("verdict_pathways", {
                    "run_id": run_id, "card_id": (card or {}).get("id"), "vertical": vertical or "gaming", "rank": i,
                    "title": _s(p.get("title"))[:300], "kind": p["kind"], "structure": _s(p.get("structure"))[:8000],
                    "legal_theory": _s(p.get("legal_theory"))[:8000], "jurisdictions": p.get("jurisdictions") or [],
                    "citations": p.get("citations") or [], "retained": p.get("retained") or [], "lost": p.get("lost") or [],
                    "time_to_market_days": int(p.get("time_to_market_days") or 0) or None,
                    "cost_band": _s(p.get("cost_band"))[:60], "value_band": _s(p.get("value_band"))[:60],
                    "risk_posture": p["risk_posture"], "durability": round(_clamp(p.get("durability")), 3),
                    "enforcement_probability": round(_clamp(p.get("enforcement_probability"), 0.3), 3),
                    "substance_over_form": _s(p.get("substance_over_form"))[:3000], "red_team": p.get("red_team") or {},
                    "kill_criteria": _s(p.get("kill_criteria"))[:3000], "first_steps": p.get("first_steps") or [],
                    "score": p["score"], "status": "proposed"})
                saved += 1
            except Exception as e:
                print(f"pathway_lab: pathway persist failed: {type(e).__name__}: {str(e)[:200]}", flush=True)
    md = _markdown(objective, vertical, card, j, final, killed, adj, process)
    os.makedirs(OUT_DIR, exist_ok=True)
    slugtxt = re.sub(r"[^a-z0-9]+", "-", (_s(j.get("objective_restated")) or objective).lower()).strip("-")[:70]
    path = os.path.join(OUT_DIR, f"{datetime.date.today().isoformat()}-{slugtxt}.md")
    try:
        with open(path, "w") as f:
            f.write(md)
    except Exception as e:
        print(f"pathway_lab: write failed: {e}", flush=True)
    slug = f"pathway:{run_id or slugtxt}"
    try:
        top = final[0] if final else {}
        db.insert("approvals", {
            "project": PROJECT, "slug": slug[:200], "kind": "material",
            "title": f"Regulatory pathways — {(_s(j.get('objective_restated')) or objective)[:110]}",
            "why": (_s(adj.get("recommendation")) or _s(j.get("summary")))[:900],
            "value": (f"{len(final)} ranked lawful routes ({len(killed)} killed by the adversary). Top: "
                      f"{_s(top.get('title'))[:120]} [{top.get('risk_posture')}, durability {top.get('durability')}]."),
            "risk": (f"REVIEW-ONLY. {ok}/{total} citations confirmed by our own fetch; unconfirmed support is marked. "
                     f"Aggressive routes are labelled and priced, not recommended by default."),
            "detail": json.dumps({"run_id": run_id, "card_id": (card or {}).get("id"),
                                  "path": os.path.relpath(path, os.path.join(OUT_DIR, "..", "..", "..")),
                                  "ranking": [p.get("title") for p in final], "process": process,
                                  "markdown": md[:60000]}),
            "alternatives": [
                {"label": "Adopt the top route", "recommended": True, "description": "Counsel confirms and the route becomes the working plan."},
                {"label": "Adopt a different route", "description": "Pick another ranked pathway, including a labelled aggressive one."},
                {"label": "Send back", "description": "Re-run with a sharper objective or more jurisdictions."}],
        })
    except Exception as e:
        print(f"pathway_lab: approvals insert failed: {type(e).__name__}: {str(e)[:160]}", flush=True)
    out = {"run_id": run_id, "pathways": len(final), "killed": len(killed), "saved": saved,
           "citations": [ok, total], "postures": [p.get("risk_posture") for p in final],
           "top": _s((final[0] if final else {}).get("title"))[:120], "path": path,
           "latency_s": process["latency_s"], "adversary": process["adversary_model"]}
    print("pathway_lab: " + json.dumps(out), flush=True)
    return out


def run(limit=RUNS_PER_TICK):
    out = {"candidates": 0, "runs": 0, "pathways": 0, "skipped": None}
    if not ENABLED:
        out["skipped"] = "disabled"
    elif not frontier.available(min_tokens=MIN_TOKENS):
        out["skipped"] = "frontier unavailable or budget below the pathway envelope"
    else:
        for card in _candidates(limit):
            out["candidates"] += 1
            r = run_one(objective_for(card), card.get("vertical"), card=card)
            if r.get("error"):
                print(f"pathway_lab: {card.get('id')} -> {r['error']}", flush=True)
                continue
            out["runs"] += 1
            out["pathways"] += r.get("pathways") or 0
    print("pathway_lab: " + json.dumps(out), flush=True)
    return out


if __name__ == "__main__":
    import single_instance
    _owned, _deadline = single_instance.guard("pathway_lab", interval_s=10800)
    if not _owned:
        print(json.dumps({"skipped": "pathway_lab already running"}))
        raise SystemExit(0)
    try:
        if len(sys.argv) > 2 and sys.argv[1] == "--objective":
            print(json.dumps(run_one(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "gaming"), default=str))
        else:
            run(int(sys.argv[1]) if len(sys.argv) > 1 else RUNS_PER_TICK)
    finally:
        if _deadline is not None:
            _deadline.cancel()

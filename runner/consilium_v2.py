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
# TWO-PHASE (2026-09-12). The single-call tournament measured 220–310K budget-weighted tokens: a
# 30–40 turn research loop inside the Fable call re-reads its growing context every turn and the
# tool calls themselves are output tokens (weighted x5). Splitting the work — a research clerk on
# the mid tier builds an AUTHORITY DOSSIER (opened URLs + verbatim quotes), then ONE no-tool Fable
# call debates on that record — keeps the grounding contract (every citation is an opened URL) and
# takes the research loop out of the frontier call. Dossiers are cached per question and every
# opened source goes into an authority cache that later questions on the same vertical reuse.
MODE = os.environ.get("ORCH_CONSILIUM_MODE", "two_phase").strip().lower()
# Research clerk on Sonnet 5 by default (need 6): the dossier is verified mechanically by URL and the
# debate runs on Fable, so the clerk's job is retrieval, and Sonnet is weighted 0.2 in the ledger.
# Measured 2026-09-12 afternoon: Opus at 12 turns died on the turn cap 9 times out of 9.
RESEARCH_NEED = int(os.environ.get("ORCH_CONSILIUM_RESEARCH_NEED", "6"))
RESEARCH_TURNS = int(os.environ.get("ORCH_CONSILIUM_RESEARCH_TURNS", "16"))
RESEARCH_TOOL_BUDGET = int(os.environ.get("ORCH_CONSILIUM_RESEARCH_TOOL_BUDGET", str(max(4, RESEARCH_TURNS - 4))))
# A question whose tournament failed twice in 24h is skipped until the window passes: a retry loop
# on a question the models cannot finish (refusals, turn-cap deaths) is the fastest way to burn a day.
FAIL_LIMIT = int(os.environ.get("ORCH_CONSILIUM_FAIL_LIMIT", "2"))
COMPACT = os.environ.get("ORCH_CONSILIUM_COMPACT", "true").lower() not in ("0", "false", "no", "off")
CORPUS_K = int(os.environ.get("ORCH_CONSILIUM_CORPUS_K", "8"))
DOSSIER_TTL_S = int(os.environ.get("ORCH_CONSILIUM_DOSSIER_TTL_S", str(7 * 86400)))
# What a tournament costs in budget-weighted tokens (measured), so a call is only started when the
# hour can fund it instead of overshooting the cap mid-tournament.
ENVELOPE = {"two_phase": 120000, "single": 250000}
MIN_TOKENS = int(os.environ.get("ORCH_CONSILIUM_MIN_TOKENS", str(ENVELOPE.get(MODE, 250000))))
HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
TRANSCRIPTS = os.path.join(HOME, "consilium", "tournaments.jsonl")
DOSSIER_DIR = os.path.join(HOME, "consilium", "dossiers")
AUTHORITY_CACHE = os.path.join(HOME, "consilium", "authority_cache.jsonl")
FAILURES = os.path.join(HOME, "consilium", "failures.json")

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

SOURCE = {"type": "object", "properties": {
    "url": {"type": "string"}, "title": {"type": "string"}, "authority": {"type": "string"},
    "jurisdiction": {"type": "string"}, "quote": {"type": "string"}, "proposition": {"type": "string"},
    "verified": {"type": "boolean"}},
    "required": ["url", "title", "authority", "jurisdiction", "quote", "proposition", "verified"]}

DOSSIER = {"type": "object", "properties": {
    "issues": {"type": "array", "items": {"type": "string"}},
    "sources": {"type": "array", "items": SOURCE},
    "unresolved": {"type": "array", "items": {"type": "string"}},
    "queries": {"type": "array", "items": {"type": "string"}}},
    "required": ["issues", "sources", "unresolved", "queries"]}

RESEARCH_SYSTEM = """You are the CONSILIUM's research clerk. Build the AUTHORITY DOSSIER a tribunal will debate
on — the operative primary authority for the question, opened and quoted, with the strongest authority
on EACH side of every contested issue.

RULES
 * Open sources with WebFetch (search with WebSearch only to locate them). Prefer official text:
   legislature and agency sites, eCFR, Federal Register, court opinions, no-action letters.
 * For every source record: the URL you actually opened; the citation string (e.g. "31 CFR 1022.380(a)",
   "NY Banking Law § 641(1)", "Loper Bright v. Raimondo, 603 U.S. 369 (2024)"); the jurisdiction; a
   VERBATIM quote of at most 40 words that bears on the question; the proposition it supports; and
   verified=true ONLY if you opened the page and the quote is verbatim. An unopened or paraphrased
   source is verified=false.
 * PREVIOUSLY OPENED SOURCES and CORPUS PASSAGES given below are already on the record: reuse them
   (copy url/quote, verified=true) when they supply what is needed; re-open only when a different
   passage is required. This saves the tribunal's budget.
 * At most 14 sources; name at most 6 issues; list what you could not resolve. Do not argue the
   question — that is the tribunal's job. Return ONLY the JSON object.
 * TOOL BUDGET: at most {tool_budget} tool calls in total (WebSearch + WebFetch). Count them. When the
   budget is spent — or earlier, once the operative authority is on the record — STOP and write the
   JSON. A dossier with 6 opened sources beats a dead session with 14 half-read ones."""

RESEARCH_USER = """QUESTION: {question}
CONTEXT: {context}
VERTICAL: {vertical}
TODAY: {today}

PREVIOUSLY OPENED SOURCES (authority cache; reuse when apt):
{prior}

CORPUS PASSAGES (the firm's verified corpus; treat as opened):
{corpus}

Build the dossier now and return the JSON object."""

DOSSIER_RULES = """

NO TOOLS IN THIS CALL. The AUTHORITY DOSSIER in the user message is the record. Cite ONLY dossier
sources: each citation's url must be a dossier URL and its quote must be that source's quote (or a
sub-span of it); copy the dossier's verified flag. Authority you believe exists but is not in the
dossier goes under `assumptions` (verified=false, confidence <= 0.5) — never as a citation.
`research.sources_opened` = the dossier URLs you relied on; `research.queries` = []."""

LENGTH_RULES = """

LENGTH DISCIPLINE (output tokens are the scarce resource; say each thing once, precisely):
 * r1_analysis <= 90 words; steelman <= 80 words; r3_grounds <= 60 words; bout grounds <= 40 words;
   red_team.attack <= 150 words; memo.memo 700-1100 words; each citation quote <= 30 words.
 * Never restate another seat's text — refer to it by seat name. Never repeat a quote already given."""

DEBATE_USER = """QUESTION: {question}
CONTEXT: {context}
VERTICAL: {vertical}
PRIORITY: {priority}
TODAY: {today}

SEATS (argue each faithfully from its own doctrine and method):
{seats}

AUTHORITY DOSSIER (the only citable record; [n] url | authority | jurisdiction | verified):
{dossier}

Run the full gauntlet now and return the JSON object."""

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


# ── research phase: dossier + authority cache + corpus ──────────────────────────────────────────
_STOP = set("""the a an and or of to in for on by with from as at is are be was were that this these those
its it their they them which who whom what when where how does do did can could would should must may
shall any all our your his her we you under over into onto about between among than then there here
such other same also not non per via use used using make makes made company business activities
regarding whether question""".split())


def _keywords(text):
    toks = re.findall(r"[A-Za-z][A-Za-z\-]{3,}|\d+(?:\.\d+)+|§\s*\d+[\w().-]*", (text or "").lower())
    return {t.strip() for t in toks if t.strip() and t.strip() not in _STOP}


def _norm_url(u):
    u = str(u or "").strip().lower().split("#")[0]
    return u[:-1] if u.endswith("/") else u


def _dossier_key(question, docket_id):
    import hashlib
    return hashlib.sha1(f"{docket_id or ''}|{(question or '').strip().lower()}".encode()).hexdigest()[:16]


def _load_dossier(key):
    try:
        path = os.path.join(DOSSIER_DIR, key + ".json")
        if time.time() - os.path.getmtime(path) > DOSSIER_TTL_S:
            return None
        with open(path) as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get("sources") else None
    except Exception:
        return None


def _save_dossier(key, dossier):
    try:
        os.makedirs(DOSSIER_DIR, exist_ok=True)
        with open(os.path.join(DOSSIER_DIR, key + ".json"), "w") as f:
            json.dump(dossier, f)
    except Exception:
        pass


def _append_authority_cache(sources, vertical, key):
    try:
        os.makedirs(os.path.dirname(AUTHORITY_CACHE), exist_ok=True)
        at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(AUTHORITY_CACHE, "a") as f:
            for src in sources:
                if not src.get("verified") or not src.get("url"):
                    continue
                rec = {k: _s(src.get(k))[:600] for k in ("url", "title", "authority", "jurisdiction", "quote", "proposition")}
                rec.update(vertical=vertical or "", key=key, at=at)
                f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def _cache_hits(question, vertical, k=8, min_score=2):
    """Previously opened, verified sources whose authority/title/proposition overlap this question."""
    qk = _keywords(question)
    if not qk:
        return []
    best = {}
    try:
        with open(AUTHORITY_CACHE) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                url = _norm_url(rec.get("url"))
                if not url:
                    continue
                score = len(qk & _keywords(" ".join([rec.get("authority", ""), rec.get("title", ""),
                                                     rec.get("proposition", "")])))
                if vertical and rec.get("vertical") == vertical:
                    score += 1
                if score >= min_score and score > best.get(url, (0, None))[0]:
                    best[url] = (score, rec)
    except Exception:
        return []
    ranked = sorted(best.values(), key=lambda x: -x[0])[:k]
    return [r for _, r in ranked]


def _corpus_block(question):
    try:
        import corpus_retrieval
        return corpus_retrieval.dossier_block(question, k=CORPUS_K, max_chars=5000) or ""
    except Exception:
        return ""


def _render_prior(hits):
    return "\n".join(f"- {h.get('url')} | {h.get('authority')} | {h.get('jurisdiction')}\n"
                     f"  quote: \"{_s(h.get('quote'))[:300]}\" — {_s(h.get('proposition'))[:200]}" for h in hits)


def _render_dossier(dossier):
    lines = []
    if dossier.get("issues"):
        lines.append("ISSUES: " + "; ".join(_s(i)[:160] for i in dossier["issues"][:6]))
    for n, src in enumerate(dossier.get("sources") or [], 1):
        lines.append(f"[{n}] {src.get('url')} | {_s(src.get('authority'))[:120]} | "
                     f"{_s(src.get('jurisdiction'))[:40]} | {'verified' if src.get('verified') else 'UNVERIFIED'}")
        lines.append(f"    quote: \"{_s(src.get('quote'))[:320]}\" — {_s(src.get('proposition'))[:240]}")
    if dossier.get("unresolved"):
        lines.append("UNRESOLVED: " + "; ".join(_s(u)[:160] for u in dossier["unresolved"][:6]))
    return "\n".join(lines)


def _research_phase(question, context, vertical, docket_id):
    """Return (dossier or None, info). The dossier is cached per question for DOSSIER_TTL_S."""
    key = _dossier_key(question, docket_id)
    cached = _load_dossier(key)
    if cached:
        return cached, {"cached": True, "sources": len(cached.get("sources") or []),
                        "verified_sources": sum(1 for x in cached["sources"] if x.get("verified"))}
    prior = _cache_hits(question, vertical)
    corpus = _corpus_block(question)
    prompt = RESEARCH_USER.format(question=(question or "")[:3000], context=(context or "")[:2000],
                                  vertical=vertical or "n/a", today=datetime.date.today().isoformat(),
                                  prior=_render_prior(prior) or "(none yet)", corpus=corpus or "(none available)")
    r = frontier.complete(prompt, system=RESEARCH_SYSTEM.format(tool_budget=RESEARCH_TOOL_BUDGET),
                          need=RESEARCH_NEED, tools=frontier.WEB_TOOLS,
                          max_turns=RESEARCH_TURNS, json_schema=DOSSIER,
                          timeout=int(os.environ.get("ORCH_CONSILIUM_RESEARCH_TIMEOUT_S", "900")),
                          tag="consilium.research")
    info = {"cached": False, "model": r.get("model"), "tokens_in": r.get("tokens_in"), "tokens_out": r.get("tokens_out"),
            "turns": r.get("turns"), "latency_s": r.get("latency_s"), "error": r.get("error") or "",
            "salvaged": bool(r.get("salvaged")),
            "corpus_passages": corpus.count("\n[") if corpus else 0, "prior_hits": len(prior)}
    j = r.get("json")
    if r.get("error") or not isinstance(j, dict) or not isinstance(j.get("sources"), list):
        return None, info
    srcs = [x for x in j["sources"] if isinstance(x, dict) and _s(x.get("url")).strip()][:16]
    for x in srcs:
        x["verified"] = bool(x.get("verified")) and bool(_s(x.get("quote")).strip())
    if not srcs:
        info["error"] = info["error"] or "dossier had no sources"
        return None, info
    j["sources"] = srcs
    info["sources"] = len(srcs)
    info["verified_sources"] = sum(1 for x in srcs if x.get("verified"))
    _save_dossier(key, j)
    _append_authority_cache(srcs, vertical, key)
    return j, info


def _failures_load():
    try:
        with open(FAILURES) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _recent_failures(key, horizon=86400):
    cut = time.time() - horizon
    return [t for t in (_failures_load().get(key) or []) if isinstance(t, (int, float)) and t >= cut]


def _note_failure(key, reason=""):
    try:
        os.makedirs(os.path.dirname(FAILURES), exist_ok=True)
        d = _failures_load()
        d[key] = _recent_failures(key) + [time.time()]
        d["_last"] = {"key": key, "reason": str(reason)[:200], "at": time.time()}
        tmp = FAILURES + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, FAILURES)
    except Exception:
        pass


def _enforce_dossier(cites, dossier):
    """A citation is verified only if its URL is a verified dossier source — the model's flag is not
    trusted. Returns the kept citations (unknown URLs are demoted, not dropped)."""
    ok = {_norm_url(x.get("url")) for x in (dossier.get("sources") or []) if x.get("verified")}
    known = {_norm_url(x.get("url")) for x in (dossier.get("sources") or [])}
    demoted = 0
    for c in cites:
        u = _norm_url(c.get("url"))
        v = bool(u) and u in ok
        if c.get("verified") and not v:
            demoted += 1
        c["verified"] = v
        if u and u not in known:
            c["confidence"] = min(float(c.get("confidence") or 0.5), 0.5)
    return demoted


# ── the tournament ───────────────────────────────────────────────────────────────────────────────
def _system(tools):
    return SYSTEM + ("" if tools else DOSSIER_RULES) + (LENGTH_RULES if COMPACT else "")


def _tournament_call(user, tools, model=None, system=None):
    return frontier.complete(user, system=system or _system(tools), need=9, model=model, tools=tools,
                             max_turns=MAX_TURNS if tools else 1, json_schema=SCHEMA,
                             timeout=int(os.environ.get("ORCH_CONSILIUM_TIMEOUT_S", "1500")),
                             tag="consilium.tournament")


def _usable(r):
    j = r.get("json") if isinstance(r, dict) else None
    return bool(r) and not r.get("error") and isinstance(j, dict) and isinstance(j.get("memo"), dict)


def _retryable(r):
    """A second frontier call is worth its tokens only when the first one actually ran and was
    refused or came back malformed — not when the budget, the kill switch or a timeout stopped it."""
    err = str((r or {}).get("error") or "").lower()
    if not err:
        return True  # ran, returned, but not the schema we asked for
    return not any(k in err for k in ("unavailable", "timeout", "timed out", "skipped", "circuitopen",
                                       "usage limit", "rate limit", "cooldown"))


def run(question, context="", vertical=None, docket_id=None, seats=SEATS, priority=None):
    """Return the memo-grade aggregate (gauntlet.run() shape) or None to let the legacy path run."""
    if not ENABLED or not frontier.available(min_tokens=MIN_TOKENS):
        return None
    panel = _seat_pool(vertical, seats)
    if len(panel) < 2:
        return None
    priority = (priority or _priority_from(context)).lower()
    fkey = _dossier_key(question, docket_id)
    if len(_recent_failures(fkey)) >= FAIL_LIMIT:
        print(f"consilium_v2: '{(question or '')[:60]}' failed {FAIL_LIMIT}x in 24h; skipping until the window passes", flush=True)
        return None
    t0 = time.time()
    fmt = dict(question=(question or "")[:3000], context=(context or "")[:3000], vertical=vertical or "n/a",
               priority=priority, today=datetime.date.today().isoformat(),
               seats="\n".join(_seat_block(e) for e in panel))
    mode = MODE if RESEARCH else "single"
    dossier, phases, fallback = None, {}, None
    tools = frontier.WEB_TOOLS if RESEARCH else None
    if mode == "two_phase":
        dossier, phases["research"] = _research_phase(question, context, vertical, docket_id)
        if dossier:
            tools = None
            user = DEBATE_USER.format(dossier=_render_dossier(dossier), **fmt)
        else:
            mode = "single"
            print(f"consilium_v2: research phase unusable ({phases['research'].get('error') or 'no dossier'}); "
                  f"single-call tournament instead", flush=True)
            if not frontier.available(min_tokens=ENVELOPE["single"]):
                print("consilium_v2: budget cannot fund a single-call tournament; legacy gauntlet will run", flush=True)
                _note_failure(fkey, phases["research"].get("error") or "research unusable")
                return None
    if mode == "single":
        user = USER.format(**fmt)
    r = _tournament_call(user, tools)
    if not _usable(r):
        # MID-TIER RETRY (2026-09-12). The third live tournament (a prediction-market wagering
        # question, gaming vertical) died after 7 minutes and 199K weighted tokens with "API Error:
        # Fable's safeguards flagged this message" — a content classifier on the frontier tier, not
        # a rate limit, so no cooldown applied and the question fell to the 21-call local path on a
        # 27B model. Wagering, AML and enforcement questions are the docket's core, so one retry on
        # the mid tier (Opus 5) keeps the frontier-grade path; budget and timeouts still gate it.
        reason = r.get("error") or "malformed output"
        if _retryable(r) and frontier.available(min_tokens=MIN_TOKENS):
            print(f"consilium_v2: {r.get('model')} tournament failed ({reason[:160]}); "
                  f"retrying once on {frontier.OPUS}", flush=True)
            r2 = _tournament_call(user, tools, model=frontier.OPUS)
            if _usable(r2):
                fallback = {"from": r.get("model"), "to": frontier.OPUS, "reason": reason[:200],
                            "wasted_tokens_in": r.get("tokens_in"), "wasted_tokens_out": r.get("tokens_out")}
                r = r2
            else:
                reason = f"{reason[:120]} | retry on {frontier.OPUS}: {r2.get('error') or 'malformed output'}"
    if not _usable(r):
        print(f"consilium_v2: tournament unusable ({reason}); legacy gauntlet will run", flush=True)
        _note_failure(fkey, reason)
        return None
    phases["debate"] = {"model": r.get("model"), "tokens_in": r.get("tokens_in"), "tokens_out": r.get("tokens_out"),
                        "turns": r.get("turns"), "latency_s": r.get("latency_s")}
    j = r["json"]
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
    demoted = _enforce_dossier(cites, dossier) if dossier else 0
    verified = [c for c in cites if c.get("verified") and c.get("url")]
    rin = int((phases.get("research") or {}).get("tokens_in") or 0)
    rout = int((phases.get("research") or {}).get("tokens_out") or 0)
    flipped = sum(1 for s in seats_out if s.get("moved"))
    conceded = sum(1 for s in seats_out if str(s.get("r3_outcome", "")).lower() in ("concede", "partial"))
    process = {"engine": "consilium_v2", "model": r.get("model"), "research": bool(tools),
               "seats": [corps.publication_view(e) for e in panel], "rounds": 5,
               "positions_flipped_by_steelman": flipped, "concessions": conceded,
               "bouts_judged": judged, "positions_staked": staked,
               "red_team_severity": red.get("severity"),
               "citation_count": len(cites), "verified_citations": len(verified),
               "sources_opened": ((j.get("research") or {}).get("sources_opened") or [])[:25],
               "tokens_in": int(r.get("tokens_in") or 0) + rin, "tokens_out": int(r.get("tokens_out") or 0) + rout,
               "turns": int(r.get("turns") or 0) + int((phases.get("research") or {}).get("turns") or 0),
               "latency_s": round(time.time() - t0, 1),
               "mode": mode, "phases": phases,
               "dossier_sources": len((dossier or {}).get("sources") or []), "citations_demoted": demoted,
               "fallback": fallback, "cross_vendor": cross}
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
                        "tournament": j, "final_memo": memo, "process": process, "dossier": dossier})
    print(f"consilium_v2[{mode}]: {r.get('model')} tournament on '{(question or '')[:70]}' -> "
          f"{len(cites)} citations ({len(verified)} verified, {demoted} demoted), red={red.get('severity')}, "
          f"flipped={flipped}, conceded={conceded}, tokens={process['tokens_in']}+{process['tokens_out']} "
          f"(research {rin}+{rout}), {process['latency_s']}s", flush=True)
    return agg


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "Is a dual-currency sweepstakes model lawful in Nevada today?"
    v = sys.argv[2] if len(sys.argv) > 2 else "gaming"
    out = run(q, context="PRIORITY: high", vertical=v)
    print(json.dumps(out, indent=2, default=str)[:6000] if out else "consilium_v2: no result (frontier unavailable?)")


# ── steering for code (docs/consilium-v2.md §7.6) ───────────────────────────────────────────────
# The same tribunal, pointed at a diff. committees.review() and illuminati_cothink's pre-merge pass
# route material coding decisions here: five fixed engineering seats argue the change in one
# no-tool frontier call, every finding must quote the diff verbatim (the code analogue of the
# opened-URL rule — a finding that cannot point at a line is demoted to unverified), and the result
# comes back in the committees.review() aggregate shape so callers need no new contract.
CODE_SEATS = [
    ("Correctness & Regression", "Does the change do what its title claims on every path the diff touches? "
     "Find the input, state or ordering where it breaks, and the behaviour that silently changed."),
    ("Security & Abuse", "Trust boundaries, injection, secrets, authz, unsafe defaults, new attack surface; "
     "what a hostile caller or hostile data does to this code."),
    ("Operability & Rollback", "Failure modes in production: partial deploys, retries, timeouts, migrations, "
     "observability; can it be rolled back without data loss?"),
    ("Intent Fidelity & Scope", "Does the diff do exactly the task — no quiet narrowing, widening or unrelated "
     "edits? Are tests real tests of the change?"),
    ("Compatibility & Data", "Schema, API and contract compatibility with every other caller in the fleet; "
     "double-encoded fields, truncations, type drift."),
]

CODE_FINDING = {"type": "object", "properties": {
    "severity": {"type": "string"}, "file": {"type": "string"}, "where": {"type": "string"},
    "claim": {"type": "string"}, "evidence": {"type": "string"}, "fix": {"type": "string"},
    "seat": {"type": "string"}},
    "required": ["severity", "file", "where", "claim", "evidence", "fix", "seat"]}

CODE_SCHEMA = {"type": "object", "properties": {
    "seats": {"type": "array", "items": {"type": "object", "properties": {
        "seat": {"type": "string"}, "r1_position": {"type": "string"}, "r1_analysis": {"type": "string"},
        "steelman": {"type": "string"}, "moved": {"type": "boolean"},
        "r3_outcome": {"type": "string"}, "r3_position": {"type": "string"}, "r3_probability": {"type": "number"}},
        "required": ["seat", "r1_position", "r1_analysis", "steelman", "moved", "r3_outcome", "r3_position", "r3_probability"]}},
    "findings": {"type": "array", "items": CODE_FINDING},
    "red_team": {"type": "object", "properties": {
        "attack": {"type": "string"}, "severity": {"type": "string"}, "failing_scenario": {"type": "string"}},
        "required": ["attack", "severity", "failing_scenario"]},
    "memo": {"type": "object", "properties": {
        "verdict": {"type": "string"}, "summary": {"type": "string"}, "risk": {"type": "number"},
        "conditions": {"type": "string"}, "dissent": {"type": "string"}, "rollout": {"type": "string"}},
        "required": ["verdict", "summary", "risk", "conditions", "dissent", "rollout"]}},
    "required": ["seats", "findings", "red_team", "memo"]}

CODE_SYSTEM = """You are the CONSILIUM convened as an ENGINEERING TRIBUNAL on one code change. Run the five-round
gauntlet among the seats below, in full, inside this single response, and return ONLY the JSON object.

 R1 BLIND     each seat's independent verdict on the diff (approve / revise / block) with its strongest
              concrete reason, reasoning only from the diff and the task. No seat references another.
 R2 STEELMAN  each seat argues the most opposed seat's position at its strongest; say if it moved you.
 R3 SETTLE    hold / concede / partial, with the probability (0-1) that this change ships without a
              production incident or a revert in 30 days.
 R4 RED TEAM  the single most plausible failing scenario for the leading position.
 R5 CHAIR     memo: verdict approve|revise|block; risk 0-1; conditions to ship; rollout full|canary|hold;
              the strongest surviving objection verbatim as dissent.

GROUNDING RULES: every finding quotes the diff VERBATIM in `evidence` (a line or fragment, <= 200
characters, exactly as it appears after the +/- marker). A finding without a verbatim quote is an
opinion, not a finding — do not emit it. severity is blocker|major|minor|nit. `where` is the hunk
or function. Do not invent files or lines not in the diff. Be specific and short: r1_analysis <= 80
words, steelman <= 60 words, memo.summary <= 150 words."""

CODE_USER = """TASK: {title}
CONTEXT: {body}
PROJECT: {project}   BLAST RADIUS: {blast}

SEATS:
{seats}

DIFF (the record; quote it verbatim in findings):
{diff}

Run the gauntlet now and return the JSON object."""

CODE_MAX_DIFF = int(os.environ.get("ORCH_CONSILIUM_CODE_MAX_DIFF", "60000"))


def has_diff(text):
    t = str(text or "")
    return ("diff --git" in t) or ("\n@@ " in t) or ("\n+++ " in t and "\n--- " in t)


def _squash(t):
    return re.sub(r"\s+", " ", str(t or "")).strip()


def verify_findings(findings, diff):
    """Findings whose evidence is not a verbatim fragment of the diff are demoted to 'unverified'."""
    flat = _squash(diff)
    out = []
    for f in findings or []:
        if not isinstance(f, dict):
            continue
        ev = _squash(f.get("evidence"))
        f = dict(f)
        f["verified"] = bool(ev) and len(ev) >= 8 and ev in flat
        sev = str(f.get("severity") or "minor").lower()
        f["severity"] = sev if sev in ("blocker", "major", "minor", "nit") else "minor"
        if not f["verified"]:
            f["severity_claimed"] = f["severity"]
            f["severity"] = "unverified"
        out.append(f)
    return out


def run_code(title, body="", diff="", *, project=None, blast_radius=0.0, need=None, tag="consilium.code"):
    """Tribunal over a diff. Returns a committees.review()-shaped aggregate, or None when no frontier
    call was possible (callers fall back to their existing panels)."""
    if not ENABLED or not has_diff(diff or body):
        return None
    diff = diff or body
    need = need or (9 if float(blast_radius or 0) >= 0.7 else 8)
    if not frontier.available(min_tokens=int(os.environ.get("ORCH_CONSILIUM_CODE_MIN_TOKENS", "40000"))):
        return None
    t0 = time.time()
    seats_txt = "\n".join(f"- SEAT \"{n}\": {d}" for n, d in CODE_SEATS)
    user = CODE_USER.format(title=(title or "")[:500], body=(body if body is not diff else "")[:4000],
                            project=project or "n/a", blast=blast_radius, seats=seats_txt,
                            diff=diff[:CODE_MAX_DIFF])
    r = frontier.complete(user, system=CODE_SYSTEM + (LENGTH_RULES if COMPACT else ""), need=need, tools=None,
                          max_turns=1, json_schema=CODE_SCHEMA, timeout=900, tag=tag)
    j = r.get("json")
    if r.get("error") or not isinstance(j, dict) or not isinstance(j.get("memo"), dict):
        print(f"consilium_v2.code: unusable ({r.get('error') or 'malformed output'})", flush=True)
        return None
    memo = j["memo"]
    findings = verify_findings(j.get("findings"), diff)
    verdict = str(memo.get("verdict") or "revise").strip().lower()
    verdict = verdict if verdict in ("approve", "revise", "block") else "revise"
    blockers = [f for f in findings if f["severity"] == "blocker"]
    majors = [f for f in findings if f["severity"] == "major"]
    if blockers and verdict == "approve":
        verdict = "revise"
    try:
        risk = max(0.0, min(1.0, float(memo.get("risk") or 0.5)))
    except Exception:
        risk = 0.5
    seats = [s for s in (j.get("seats") or []) if isinstance(s, dict)]
    opposed = [s.get("seat") for s in seats if str(s.get("r3_position") or s.get("r1_position") or "").lower().startswith("block")]
    probs = [float(s.get("r3_probability")) for s in seats if isinstance(s.get("r3_probability"), (int, float))]
    score = round(10 * (sum(probs) / len(probs) if probs else (1 - risk)), 1)
    rec = {"approve": "GO", "revise": "REVISE", "block": "HOLD"}[verdict]
    if verdict == "approve" and str(memo.get("rollout") or "").lower() == "canary":
        rec = "GO (canary)"
    process = {"engine": "consilium_v2.code", "model": r.get("model"), "seats": [n for n, _ in CODE_SEATS],
               "findings": len(findings), "verified_findings": sum(1 for f in findings if f["verified"]),
               "blockers": len(blockers), "majors": len(majors),
               "positions_flipped_by_steelman": sum(1 for s in seats if s.get("moved")),
               "red_team_severity": (j.get("red_team") or {}).get("severity"),
               "tokens_in": r.get("tokens_in"), "tokens_out": r.get("tokens_out"),
               "latency_s": round(time.time() - t0, 1)}
    agg = {"aggregate": score, "recommendation": rec, "verdict": verdict, "risk": risk,
           "opposed_by": [o for o in opposed if o], "dissents": [memo.get("dissent")] if _s(memo.get("dissent")) else [],
           "conditions": _s(memo.get("conditions")), "summary": _s(memo.get("summary")),
           "rollout": _s(memo.get("rollout")) or ("full" if verdict == "approve" else "hold"),
           "critical": verdict == "block" or bool(blockers),
           "auto_ok": verdict == "approve" and not blockers and not majors and risk < 0.3,
           "escalate": verdict == "block", "findings": findings,
           "red_team": j.get("red_team") or {}, "title": title, "body": body,
           "panel": [{"committee": s.get("seat"), "verdict": ("oppose" if str(s.get("r3_position") or "").lower().startswith("block")
                                                               else "support" if str(s.get("r3_position") or "").lower().startswith("approve")
                                                               else "needs-info"),
                      "conviction": round(float(s.get("r3_probability") or 0.5) * 10, 1),
                      "opinion": _s(s.get("r3_position") or s.get("r1_position"))[:400]} for s in seats],
           "process": process}
    _append_transcript({"at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "kind": "code",
                        "title": title, "project": project, "tournament": j, "process": process})
    print(f"consilium_v2.code: {r.get('model')} on '{(title or '')[:60]}' -> {verdict} risk={risk} "
          f"findings={len(findings)} ({process['verified_findings']} verified), tokens={r.get('tokens_in')}+{r.get('tokens_out')}",
          flush=True)
    return agg

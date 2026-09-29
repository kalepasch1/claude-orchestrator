#!/usr/bin/env python3
"""escalation.py — the FIRM: associate -> counsel -> partner, each escalation earned.

THE MODEL (operator direction, 2026-09-29). A law firm does not send every question to a partner.
An associate researches, builds the record and drafts. Counsel reviews the draft against the record
and decides whether a partner is needed. A partner sees only what is genuinely contested, in a short
brief, and rules on it. Simple matters never leave the associate's desk; hard ones reach the partner
with the research already done.

    ASSOCIATE  local_tribunal.prepare + write, on a local model. Research, evidence ledger,
               verified claims, draft, computed confidence. Free.
    ROUTE      mechanical. The associate's result is FINAL when the priority allows it (low or
               medium), its evidence gate passed, every issue is covered, the seats agree, the
               adversary did not land a fatal blow, no authority outside the record was named, and
               its confidence clears this vertical's EARNED threshold (see trust below).
    COUNSEL    reviews the associate's packet — ledger, draft, metrics, the adversary's attack — and
               agrees, amends or redoes the memo from the ledger, classifying every issue as settled,
               contested or open. Strongest local model that is stronger than the associate and fits
               in memory; otherwise Sonnet; otherwise GPT-5.5. No web research: the packet is the
               record. Needs a partner? It says so, and says exactly what for.
    PARTNER    Fable (GPT-5.5 when Claude is down). Receives a brief: settled issues with counsel's
               rulings, the contested issues, the ledger, the question counsel could not answer. It
               rules on the contested issues and signs the memo. When it names a gap, the associate
               researches the gap locally first (free); only if that finds nothing does the partner
               get web tools, for those gaps alone.

EVERY TIER CITES THE SAME LEDGER. Counsel and partner write with finding ids ([F3]); citations are
built from the findings, and a partner's web authority becomes a finding only after the system has
fetched the page and found the quote on it. No tier writes a citation from memory.

TRUST IS EARNED PER VERTICAL. Counsel re-reviews a fixed 25% of the matters the associate finished
alone (operator choice), plus every matter the associate escalated with a passing draft. Each review
is recorded as agree / amend / redo. The vertical's local-final threshold rises when counsel keeps
amending the associate and falls when it keeps agreeing. The ledger is
<home>/consilium/escalation_ledger.jsonl.

PRECEDENT FIRST. Before any tier works, a question that is the same as one the tribunal has already
answered (content-word overlap >= ORCH_PRECEDENT_SIMILARITY, same vertical, fresh card) is resolved
by precedent: retired from the docket with the card it duplicates recorded. Zero model calls.
"""
from __future__ import annotations
import datetime
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common_utils

_s = common_utils.safe_string_coerce

ENABLED = os.environ.get("ORCH_CONSILIUM_FIRM", "true").lower() not in ("0", "false", "no", "off")
LOCAL_FINAL_PRIORITIES = {p.strip().lower() for p in os.environ.get("ORCH_LOCAL_FINAL_PRIORITIES", "low,medium").split(",") if p.strip()}
SPOT_CHECK_RATE = float(os.environ.get("ORCH_SPOT_CHECK_RATE", "0.25"))
BASE_THRESHOLD = float(os.environ.get("ORCH_LOCAL_FINAL_THRESHOLD", "0.58"))
MAX_SEAT_SPREAD = float(os.environ.get("ORCH_LOCAL_FINAL_MAX_SPREAD", "0.25"))
TRUST_WINDOW = int(os.environ.get("ORCH_TRUST_WINDOW", "12"))
PRECEDENT_SIMILARITY = float(os.environ.get("ORCH_PRECEDENT_SIMILARITY", "0.72"))
HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
LEDGER = os.path.join(HOME, "consilium", "escalation_ledger.jsonl")
# FIRM MEMORY. Every issue counsel or a partner settles becomes a HOLDING (issue, ruling, the verbatim
# authority it rests on), and every time counsel corrects the associate the correction is kept. The
# associate reads the nearest holdings and recent corrections on every new matter, and opens the
# holdings' authorities first — so an issue that once needed a partner is, the next time, settled at
# the associate's desk. This is how the escalation rate is meant to fall.
MEMORY = os.path.join(HOME, "consilium", "firm_memory.jsonl")
MEMORY_K = int(os.environ.get("ORCH_FIRM_MEMORY_K", "4"))

COUNSEL_SCHEMA = {"type": "object", "properties": {
    "assessment": {"type": "string"},
    "issues": {"type": "array", "items": {"type": "object", "properties": {
        "issue": {"type": "string"}, "status": {"type": "string"}, "ruling": {"type": "string"},
        "findings": {"type": "array", "items": {"type": "string"}}},
        "required": ["issue", "status", "ruling", "findings"]}},
    "verdict": {"type": "string"}, "memo": {"type": "string"},
    "needs_partner": {"type": "boolean"}, "partner_question": {"type": "string"},
    "gaps": {"type": "array", "items": {"type": "string"}},
    "dissent": {"type": "string"}, "flips_if": {"type": "string"}, "conditions": {"type": "string"},
    "unsettled": {"type": "boolean"},
    "options": {"type": "array", "items": {"type": "object", "properties": {
        "option": {"type": "string"}, "posture": {"type": "string"},
        "findings": {"type": "array", "items": {"type": "string"}}, "abandon_if": {"type": "string"}},
        "required": ["option", "posture", "findings", "abandon_if"]}}},
    "required": ["assessment", "issues", "verdict", "memo", "needs_partner", "partner_question", "gaps",
                 "dissent", "flips_if", "conditions", "unsettled", "options"]}

PARTNER_SCHEMA = {"type": "object", "properties": {
    "rulings": {"type": "array", "items": {"type": "object", "properties": {
        "issue": {"type": "string"}, "ruling": {"type": "string"},
        "findings": {"type": "array", "items": {"type": "string"}}},
        "required": ["issue", "ruling", "findings"]}},
    "verdict": {"type": "string"}, "memo": {"type": "string"},
    "gaps": {"type": "array", "items": {"type": "string"}},
    "new_authorities": {"type": "array", "items": {"type": "object", "properties": {
        "source": {"type": "string"}, "url": {"type": "string"}, "quote": {"type": "string"},
        "proposition": {"type": "string"}}, "required": ["source", "url", "quote", "proposition"]}},
    "dissent": {"type": "string"}, "flips_if": {"type": "string"}, "conditions": {"type": "string"},
    "unsettled": {"type": "boolean"},
    "options": {"type": "array", "items": {"type": "object", "properties": {
        "option": {"type": "string"}, "posture": {"type": "string"},
        "findings": {"type": "array", "items": {"type": "string"}}, "abandon_if": {"type": "string"}},
        "required": ["option", "posture", "findings", "abandon_if"]}}},
    "required": ["rulings", "verdict", "memo", "gaps", "new_authorities", "dissent", "flips_if", "conditions",
                 "unsettled", "options"]}

COUNSEL_SYSTEM = """You are COUNSEL reviewing an associate's work before it goes out. You have the associate's
evidence ledger (every entry is a verbatim quote from an official source the system fetched), the associate's
draft memo, and the associate's own quality signals. You do no research of your own: the ledger is the record.

 1. For EACH issue: settled (the ledger answers it and the draft gets it right), contested (the ledger
    supports more than one reading, or the draft's reading is doubtful), or open (the ledger does not answer
    it). Give your ruling in one or two sentences with the finding ids it rests on.
 2. assessment: `agree` (the draft is right and adequately grounded; memo may be ""), `amend` (right in
    substance, needs corrections — write the corrected memo), or `redo` (wrong or missing — write the memo).
    When there is no draft, assessment is `redo`.
 3. Every sentence of your memo that states what the law is or requires ends with finding ids like [F3].
    A legal statement without one is not allowed; list it under gaps instead. Refer to authorities by the
    labels shown in the ledger and name no rule that is not in it.
 4. needs_partner is true ONLY when a contested or open issue materially changes the answer and a senior
    judgement could resolve it. Then state the precise question for the partner. Do not escalate what the
    ledger already answers.
 5. options: 2-4 lawful ways to proceed (changes to product, partner, entity, licence or jurisdiction —
    never concealment or a misstatement to anyone), each with a posture (conservative | defensible |
    aggressive_arguable), its finding ids, and the event that means abandon it.
Return ONLY the JSON object."""

PARTNER_SYSTEM = """You are the PARTNER. Counsel has already reviewed the matter; you are asked only what counsel
could not resolve. The settled issues are listed with counsel's rulings — do not relitigate them unless you see
a clear error. Rule on the contested and open issues, then sign the final memo a General Counsel will act on
this week: the answer first, the operative authority, the application, the limits, what would flip it, and the
strongest surviving objection.

 * Cite the ledger with finding ids like [F3]. Every legal statement carries one.
 * If a ruling needs an authority that is NOT in the ledger, name it under `gaps` (precise citation or search
   phrase) and do not state it as law. If you have web tools in this call, you may open it: put it in
   `new_authorities` with the URL you opened and a verbatim quote of at most 40 words, and cite it in the memo
   as [W1], [W2]... in the order listed. The system re-fetches every URL and checks every quote.
 * options: 2-4 lawful paths with posture, finding ids and an abandon-if event. Never concealment or a
   misstatement to anyone.
Return ONLY the JSON object."""


# ── ledger + trust ───────────────────────────────────────────────────────────────────────────────
def _append(rec):
    try:
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        with open(LEDGER, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass


def _records():
    out = []
    try:
        with open(LEDGER) as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except OSError:
        pass
    return out


def trust(vertical, records=None):
    """Counsel's agreement with associate work that PASSED the associate's own gate, recent first.
    -> {n, agree, amend, redo, rate, threshold}. rate counts agree as 1 and amend as 0.5."""
    recs = [r for r in (records if records is not None else _records())
            if r.get("vertical") == vertical and r.get("associate_resolvable") and r.get("counsel_assessment")]
    recent = recs[-TRUST_WINDOW:]
    n = len(recent)
    agree = sum(1 for r in recent if r["counsel_assessment"] == "agree")
    amend = sum(1 for r in recent if r["counsel_assessment"] == "amend")
    redo = n - agree - amend
    rate = (agree + 0.5 * amend) / n if n else None
    th = BASE_THRESHOLD
    if rate is not None and n >= 4:
        if rate < 0.70:
            th += 0.15
        elif rate < 0.85:
            th += 0.07
        elif rate >= 0.95 and n >= TRUST_WINDOW:
            th -= 0.05
    return {"n": n, "agree": agree, "amend": amend, "redo": redo,
            "rate": round(rate, 3) if rate is not None else None, "threshold": round(min(0.85, th), 3)}


def remember(state, vertical, route, counsel=None, partner=None, associate_verdict=""):
    """Store settled issues as holdings and counsel's corrections of the associate."""
    by_id = {f["id"]: f for f in state.get("findings") or []}
    rows, now = [], datetime.datetime.now(datetime.timezone.utc).isoformat()

    def holding(issue, ruling, fids, tier):
        auth = [{"authority": by_id[f]["authority"], "url": by_id[f]["url"], "quote": by_id[f]["quote"]}
                for f in fids if f in by_id][:4]
        if auth and len(_s(ruling)) >= 15:
            rows.append({"kind": "holding", "at": now, "vertical": vertical, "tier": tier, "route": route,
                         "question": _s(state.get("question"))[:400],
                         "issue": _s(issue)[:300], "ruling": _s(ruling)[:600], "authorities": auth})
    for i in (counsel or {}).get("issues") or []:
        if _s(i.get("status")).lower().startswith("settled"):
            import local_tribunal as lt
            holding(i.get("issue"), i.get("ruling"), lt._fids(i.get("findings"), set(by_id)), "counsel")
    for r in (partner or {}).get("rulings") or []:
        import local_tribunal as lt
        holding(r.get("issue"), r.get("ruling"), lt._fids(r.get("findings"), set(by_id)), "partner")
    a = _s((counsel or {}).get("assessment")).lower()
    if counsel and (a.startswith("amend") or a.startswith("redo")) and associate_verdict:
        rows.append({"kind": "correction", "at": now, "vertical": vertical, "tier": "counsel",
                     "associate_said": _s(associate_verdict)[:400], "counsel_said": _s(counsel.get("verdict"))[:400],
                     "issues": [f"{_s(i.get('issue'))[:120]}: {_s(i.get('ruling'))[:200]}" for i in counsel.get("issues") or []
                                if not _s(i.get("status")).lower().startswith("settled")][:3]})
    try:
        os.makedirs(os.path.dirname(MEMORY), exist_ok=True)
        with open(MEMORY, "a") as f:
            for r in rows:
                f.write(json.dumps(r, default=str) + "\n")
    except Exception:
        pass
    return len(rows)


def memory(vertical, question, k=MEMORY_K, path=None):
    """-> {"holdings": [...], "corrections": [...], "block": str, "urls": [...]} for the associate."""
    try:
        import docket_matrix
        want = docket_matrix.content_words(question)
    except Exception:
        want = set(re.findall(r"[a-z]{4,}", _s(question).lower()))
    holdings, corrections = [], []
    try:
        with open(path or MEMORY) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("vertical") != vertical:
                    continue
                if r.get("kind") == "holding":
                    text = " ".join([r.get("issue", ""), r.get("ruling", ""), r.get("question", "")]
                                    + [a.get("authority", "") for a in r.get("authorities") or []])
                    words = set(re.findall(r"[a-z][a-z0-9\-]{3,}", text.lower()))
                    s = len(want & words)
                    if s >= 3:
                        holdings.append((s + (1 if r.get("tier") == "partner" else 0), r))
                elif r.get("kind") == "correction":
                    corrections.append(r)
    except OSError:
        pass
    holdings.sort(key=lambda x: -x[0])
    seen, top = set(), []
    for _, h in holdings:
        key = h["issue"][:80]
        if key not in seen:
            seen.add(key)
            top.append(h)
        if len(top) >= k:
            break
    corrections = corrections[-3:]
    lines = []
    for h in top:
        lines.append(f"PRIOR RULING ({h['tier']}): {h['issue']} -> {h['ruling']}")
        lines += [f"   rests on {a['authority']} <{a['url']}>: \"{a['quote'][:160]}\"" for a in h["authorities"][:2]]
    for c in corrections:
        lines.append(f"RECENT CORRECTION BY COUNSEL: the associate concluded \"{c['associate_said'][:200]}\"; counsel held "
                     f"\"{c['counsel_said'][:200]}\"" + (f" (because: {'; '.join(c['issues'])[:300]})" if c.get("issues") else ""))
    block = ("FIRM MEMORY (rulings counsel and partners made on similar issues, and recent corrections of associate "
             "work; the authorities are leads to open, not citations until they appear in your ledger):\n" + "\n".join(lines)) if lines else ""
    urls = []
    for h in top:
        for a in h["authorities"]:
            if a.get("url") and a["url"] not in urls:
                urls.append({"url": a["url"], "authority": a.get("authority")})
    return {"holdings": top, "corrections": corrections, "block": block[:3500], "urls": urls[:8]}


def spot_checked(key, rate=None):
    """Deterministic sample: the same matter is always in or out, so a rerun does not re-roll."""
    r = SPOT_CHECK_RATE if rate is None else rate
    h = int(hashlib.sha256(str(key).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return h < r


# ── precedent ────────────────────────────────────────────────────────────────────────────────────
def precedent(question, vertical, cards=None):
    """-> (card, similarity) for a fresh card answering the same question, else (None, best)."""
    try:
        import docket_matrix
        if cards is None:
            import db
            cards = db.select("verdict_cards", {"select": "id,docket_id,question,vertical,status,publication_state",
                                                "vertical": f"eq.{vertical}", "status": "eq.fresh",
                                                "publication_state": "neq.withdrawn", "limit": "1000"}) or []
        mine = docket_matrix.content_words(question)
        best, score = None, 0.0
        for c in cards:
            s = docket_matrix.similarity(mine, c.get("question") or "")
            if s > score:
                best, score = c, s
        return (best, round(score, 3)) if score >= PRECEDENT_SIMILARITY else (None, round(score, 3))
    except Exception:
        return None, 0.0


# ── the packet ───────────────────────────────────────────────────────────────────────────────────
def issue_map(state):
    """Per issue: which verified claims and findings cover it."""
    import local_tribunal as lt
    by_id = {f["id"]: f for f in state.get("findings") or []}
    out = []
    for i, issue in enumerate((state.get("plan") or {}).get("issues") or []):
        claims = []
        for s in state.get("seats") or []:
            for c in lt.grounded(s):
                if any(by_id.get(fid, {}).get("issue") == i for fid in c["findings"]):
                    claims.append({"seat": s["seat"], "claim": c["claim"], "findings": c["findings"]})
        out.append({"n": i, "issue": issue, "covered": bool(claims), "claims": claims[:6]})
    return out


def to_fids(memo_text, citations):
    """Turn the finalized memo's [1, 2] back into finding ids for the next tier."""
    num = {str(i): c.get("finding") for i, c in enumerate(citations or [], 1) if c.get("finding")}

    def sub(m):
        ids = [num.get(x.strip()) for x in m.group(1).split(",")]
        return "[" + ", ".join(i for i in ids if i) + "]" if all(ids) else m.group(0)
    return re.sub(r"\[(\d+(?:\s*,\s*\d+)*)\]", sub, _s(memo_text))


def spread(state):
    ps = [s.get("final_probability", s.get("probability", 0.5)) for s in state.get("seats") or []]
    return round(max(ps) - min(ps), 3) if len(ps) > 1 else 0.0


def assess(state, res, priority, vertical, th):
    """Is the associate's result FINAL? -> (final, reasons_against, signals)."""
    meta = res.get("meta") or {}
    memo = ((res.get("j") or {}).get("memo")) or {}
    parts = meta.get("confidence_parts") or {}
    g = meta.get("grounding") or {}
    imap = issue_map(state)
    sig = {"priority": priority, "gate": meta.get("reason"), "confidence": meta.get("confidence"),
           "threshold": th, "issue_coverage": parts.get("issue_coverage"), "open_issues": [x["issue"] for x in imap if not x["covered"]],
           "seat_spread": spread(state), "adversary": meta.get("adversary_severity"), "revised": meta.get("revised"),
           "unknown_authorities": g.get("unknown_authorities") or [], "unsettled": bool(memo.get("unsettled")),
           "premise_ok": meta.get("premise_ok"), "model": meta.get("model"), "model_b": meta.get("model_b")}
    why = []
    if priority not in LOCAL_FINAL_PRIORITIES:
        why.append(f"priority {priority} requires review")
    if res.get("abstain") or not res.get("j"):
        why.append(f"associate did not mint: {res.get('reason')}")
    if sig["open_issues"]:
        why.append(f"{len(sig['open_issues'])} issue(s) not covered by verified evidence")
    if sig["seat_spread"] > MAX_SEAT_SPREAD:
        why.append(f"seats disagree (spread {sig['seat_spread']})")
    if sig["adversary"] == "fatal" or (sig["adversary"] == "material" and not sig["revised"]):
        why.append(f"adversary landed a {sig['adversary']} attack")
    if sig["unknown_authorities"]:
        why.append("memo names authority outside the record")
    if sig["unsettled"]:
        why.append("associate found the question unsettled")
    if (sig["confidence"] or 0) < th:
        why.append(f"confidence {sig['confidence']} < earned threshold {th}")
    return (not why), why, sig


# ── counsel and partner calls ────────────────────────────────────────────────────────────────────
def counsel_rung(associate_model):
    """The strongest local model that is stronger than the associate and fits right now, or None."""
    try:
        import local_llm
        import local_tribunal as lt
        floor = max(lt.MIN_DEBATE_B, lt.size_b(associate_model or "") + 1)
        for spec in local_llm.MODELS:                   # ladder is ordered strongest first
            p, _, m = spec.partition(":")
            if lt.size_b(m) >= floor and local_llm.fits(p, m)[0]:
                return spec
    except Exception:
        pass
    return None


def _call(prompt, schema, system, *, role, rung=None, tools=None, chat=None, cloud=None):
    """-> (json, info). A counsel call goes to `rung` (local) or up the cloud chain; a partner call is
    cloud-only (min_tier codex): a partner judgement from a smaller model is not a partner judgement."""
    t0 = time.time()
    if rung and not tools:
        try:
            chat = chat or __import__("local_llm").chat
            r = chat(prompt, system=system, json_schema=schema, max_tokens=5000, temperature=0.2, timeout=1500,
                     models=[rung], tag=f"firm.{role}")
            if isinstance(r.get("json"), dict) and not r.get("error"):
                return r["json"], {"tier": "local", "model": r.get("model") or rung, "latency_s": round(time.time() - t0, 1),
                                   "tokens_in": r.get("tokens_in") or 0, "tokens_out": r.get("tokens_out") or 0}
        except Exception:
            pass
    try:
        import frontier
        cloud = cloud or frontier.complete
        model = frontier.FABLE if role == "partner" else frontier.SONNET
        r = cloud(prompt, system=system, model=model, need=9 if role == "partner" else 7, json_schema=schema,
                  tools=tools, max_turns=(8 if tools else None), timeout=1500, tag=f"firm.{role}", min_tier="codex")
    except Exception as e:
        r = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
    info = {"tier": r.get("tier"), "model": r.get("model"), "latency_s": round(time.time() - t0, 1),
            "tokens_in": r.get("tokens_in") or 0, "tokens_out": r.get("tokens_out") or 0,
            "tokens_weighted": r.get("tokens_weighted"), "error": r.get("error") or ""}
    j = r.get("json") if isinstance(r.get("json"), dict) and not r.get("error") else None
    return j, info


def _counsel_prompt(question, state, res, sig):
    import local_tribunal as lt
    memo = ((res.get("j") or {}).get("memo")) or {}
    draft = to_fids(memo.get("memo"), memo.get("citations")) if memo else ""
    imap = issue_map(state)
    attack = ((res.get("j") or {}).get("red_team") or {})
    return (f"QUESTION: {question[:1500]}\n"
            + (f"PREMISE PROBLEM FOUND BY THE ASSOCIATE: {(state.get('plan') or {}).get('premise_problem')}\n"
               f"RESTATED: {(state.get('plan') or {}).get('restated_question')}\n" if not sig.get("premise_ok", True) else "")
            + f"TODAY: {datetime.date.today().isoformat()}\n\nISSUES AND THE VERIFIED CLAIMS THAT COVER THEM:\n"
            + "\n".join(f"{x['n'] + 1}. {x['issue']}\n   " + ("; ".join(f"({c['seat']}) {c['claim'][:180]} [{', '.join(c['findings'])}]"
                                                              for c in x["claims"][:4]) or "NOT COVERED BY ANY VERIFIED CLAIM")
                        for x in imap)
            + f"\n\nEVIDENCE LEDGER:\n{lt.render_ledger(state.get('findings') or [], 9000)}\n\n"
            + (f"ASSOCIATE'S DRAFT (verdict: {memo.get('verdict')}):\n{draft[:7000]}\n\n" if draft else "ASSOCIATE'S DRAFT: none (it did not clear the associate's own gate)\n\n")
            + f"ADVERSARY'S ATTACK ON THE DRAFT ({attack.get('severity')}): {_s(attack.get('attack'))[:1200]}\n"
            + f"ASSOCIATE'S SIGNALS: {json.dumps({k: sig.get(k) for k in ('confidence', 'seat_spread', 'open_issues', 'unknown_authorities', 'unsettled', 'model')}, default=str)[:1500]}\n")


def _partner_prompt(question, state, counsel, extra_findings_note=""):
    import local_tribunal as lt
    settled = [i for i in counsel.get("issues") or [] if _s(i.get("status")).lower().startswith("settled")]
    hard = [i for i in counsel.get("issues") or [] if not _s(i.get("status")).lower().startswith("settled")]
    return (f"QUESTION: {question[:1500]}\nTODAY: {datetime.date.today().isoformat()}\n\n"
            f"COUNSEL'S QUESTION FOR YOU: {_s(counsel.get('partner_question'))[:1200]}\n\n"
            "SETTLED (counsel's rulings — do not relitigate without a clear error):\n"
            + ("\n".join(f"- {_s(i.get('issue'))[:200]}: {_s(i.get('ruling'))[:400]} [{', '.join(i.get('findings') or [])}]" for i in settled) or "- none")
            + "\n\nCONTESTED OR OPEN (rule on these):\n"
            + ("\n".join(f"- [{_s(i.get('status'))}] {_s(i.get('issue'))[:200]}: counsel's view: {_s(i.get('ruling'))[:400]}" for i in hard) or "- see counsel's question")
            + f"\n\nCOUNSEL'S MEMO:\n{_s(counsel.get('memo'))[:6000]}\n\nGAPS COUNSEL NAMED: {json.dumps(counsel.get('gaps') or [])[:800]}\n"
            + extra_findings_note
            + f"\n\nEVIDENCE LEDGER:\n{lt.render_ledger(state.get('findings') or [], 10000)}\n")


def _fill_gaps(state, gaps, question, vertical, fetcher=None, searcher=None):
    """Associate researches the partner's named gaps locally. -> number of new findings."""
    import local_tribunal as lt
    if not gaps or not state.get("d"):
        return 0
    before = {p["id"] for p in state["d"]["passages"]}
    n0 = len(state["findings"])
    try:
        import authority_search
        import local_research
        d = lt.research(question, state.get("context") or "", vertical, state["plan"],
                        fetcher=fetcher or local_research.fetch, searcher=searcher or authority_search.search,
                        extra_queries=[{"backend": "", "query": _s(g)[:140]} for g in gaps[:4]], have=state["d"])
        state["d"] = d
        new = {p["id"] for p in d["passages"]} - before
        if new:
            lt.extract(state["calls"], question, d, state["findings"], only_passages=new)
            lt.backfill(d, state["findings"], question)
    except Exception:
        pass
    return len(state["findings"]) - n0


def _adopt_web(state, authorities, fetcher=None):
    """A partner's web authority joins the ledger only if we fetch the page and find the quote.
    Returns {"W1": "F12", ...} for the ones that verified."""
    import pathway_lab
    import authority_search
    mapping = {}
    for i, a in enumerate(authorities or [], 1):
        if not isinstance(a, dict):
            continue
        c = pathway_lab.verify_citation({"url": a.get("url"), "quote": a.get("quote")}, fetcher)
        if not c.get("verified"):
            continue
        fid = f"F{len(state['findings']) + 1}"
        url = _s(a.get("url"))
        try:
            import local_research
            page = (fetcher or local_research.fetch)(url) or ""
        except Exception:
            page = ""
        if page:
            state["d"]["_pages"][url] = page
        state["findings"].append({"id": fid, "passage": "web", "source": "web", "url": url,
                                  "authority": authority_search.label_for(url, _s(a.get("source"))[:160]),
                                  "issue": 0, "quote": " ".join(_s(a.get("quote")).split()[:45]),
                                  "says": _s(a.get("proposition"))[:400], "bears_on": "opened by the partner", "web": True})
        mapping[f"W{i}"] = fid
    return mapping


def _finish(state, chair, writer_b, severity, revised):
    """Ground, finalize, compute confidence and gate a memo written by counsel or partner."""
    import local_tribunal as lt
    chair, gp = lt.ground_pass(state["calls"], chair, state["findings"], verifier_models=state.get("verifier"))
    memo, stats = lt.finalize(chair, state["findings"])
    conf, parts = lt.confidence(state["seats"], state["findings"], stats, state["plan"]["issues"], severity, revised,
                                writer_b, memo["unsettled"])
    memo["confidence"] = conf
    mint, why = lt.gate(state["seats"], state["findings"], stats, parts, severity, revised, writer_b, force=False)
    return memo, stats, conf, parts, mint, why, gp


def _chair_from(j, fallback_memo=None):
    fb = fallback_memo or {}
    return {"verdict": _s(j.get("verdict")) or fb.get("verdict", ""), "memo": _s(j.get("memo")),
            "assumptions": fb.get("assumptions") or [], "dissent": _s(j.get("dissent")) or fb.get("dissent", ""),
            "flips_if": _s(j.get("flips_if")) or fb.get("flips_if", ""), "conditions": _s(j.get("conditions")) or fb.get("conditions", ""),
            "unsettled": bool(j.get("unsettled")), "options": j.get("options") or fb.get("options") or []}


def _package(state, res, memo, route, route_meta):
    """The single-call tournament shape consilium_v2 expects, with the firm's record attached."""
    import local_tribunal as lt
    j = dict(res.get("j") or {})
    if not j:
        seats = state.get("seats") or []
        j = {"seats": [{"seat": s["seat"], "r1_position": s["answer"], "r1_analysis": "", "r1_probability": s["probability"],
                        "steelman_of": s.get("steelman_of", ""), "steelman": s.get("steelman", ""), "moved": bool(s.get("moved")),
                        "r3_outcome": s.get("outcome", "hold"), "r3_position": s.get("final_answer") or s["answer"],
                        "r3_grounds": "; ".join(c["claim"][:140] for c in lt.grounded(s)[:3]),
                        "r3_probability": s.get("final_probability", s["probability"]), "conceded": "",
                        "claims_total": len(s["claims"]), "claims_verified": len(lt.grounded(s))} for s in seats],
             "bouts": state.get("bouts") or [], "red_team": {"severity": "none"},
             "research": {"queries": state["d"]["queries"][:10], "sources_opened": [s["url"] for s in state["d"]["sources"]]},
             "adversary_done": {"ran": False, "local": True}}
    j["memo"] = memo
    j["firm"] = {"route": route, **route_meta}
    used = {c.get("finding") for c in memo.get("citations") or []}
    by_id = {f["id"]: f for f in state["findings"]}
    sources = [dict(s) for s in state["d"]["sources"]]
    have = {s["url"] for s in sources}
    for fid in used:
        f = by_id.get(fid) or {}
        if f.get("url") and f["url"] not in have:
            sources.append({"id": f"S{len(sources) + 1}", "url": f["url"], "authority": f.get("authority"), "quote": f.get("quote"),
                            "verified": True, "proposition": f.get("says"), "origin": "web" if f.get("web") else "firm"})
            have.add(f["url"])
    for s in sources:
        fs = [f for f in state["findings"] if f["url"] == s["url"] and f["id"] in used]
        if fs:
            s.update(quote=fs[0]["quote"], proposition=fs[0]["says"], verified=True)
    dossier = {"issues": state["plan"]["issues"], "sources": sources, "unresolved": state["d"]["unresolved"][:10],
               "queries": state["d"]["queries"][:10], "_pages": state["d"]["_pages"], "leads": state["d"]["leads"][:10]}
    return j, dossier


# ── the matter ───────────────────────────────────────────────────────────────────────────────────
def run(question, context="", vertical=None, priority="medium", panel=None, docket_id=None, *,
        chat=None, fetcher=None, searcher=None, cloud=None, counsel_chat=None, records=None):
    """-> {"route", "j", "dossier", "meta", "abstain", "reason", "escalate_full"}."""
    import local_tribunal as lt
    t0 = time.time()
    priority = (priority or "medium").lower()
    key = docket_id or hashlib.sha1(_s(question).encode()).hexdigest()[:16]
    rec = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "docket_id": docket_id, "vertical": vertical,
           "priority": priority, "question": _s(question)[:300]}

    def out(route, j=None, dossier=None, abstain=False, reason="", escalate_full=False, **meta):
        rec.update(route=route, abstain=abstain, reason=reason, latency_s=round(time.time() - t0, 1),
                   **{k: v for k, v in meta.items() if k in ("counsel_assessment", "associate_resolvable", "spot_check",
                                                             "counsel", "partner", "signals", "tokens", "trust")})
        _append(rec)
        return {"route": route, "j": j, "dossier": dossier, "abstain": abstain, "reason": reason,
                "escalate_full": escalate_full, "meta": {**meta, "route": route, "latency_s": rec["latency_s"]}}

    # ASSOCIATE
    state = lt.prepare(question, context, vertical, priority, panel, docket_id, chat=chat, fetcher=fetcher, searcher=searcher)
    if state.get("abstain"):
        # No usable record. A high-priority matter goes to the partner with full research; the rest wait.
        return out("none", abstain=True, reason=f"associate: {state['abstain']}", escalate_full=(priority == "high"))
    res = lt.write(state, pen="local")
    tr = trust(vertical, records)
    final, why, sig = assess(state, res, priority, vertical, tr["threshold"])
    resolvable = not [w for w in why if not w.startswith("priority")] and bool(res.get("j"))
    spot = final and spot_checked(key)
    tokens = {"associate_cloud_steps": (res.get("meta") or {}).get("cloud_steps", 0)}
    if final and not spot:
        return out("associate", j=_package(state, res, res["j"]["memo"], "associate",
                                             {"signals": sig, "trust": tr, "spot_check": False})[0],
                   dossier=res.get("dossier"), associate_resolvable=True, spot_check=False, signals=sig, trust=tr, tokens=tokens)

    # COUNSEL
    rung = counsel_rung((res.get("meta") or {}).get("model"))
    cj, cinfo = _call(_counsel_prompt(question, state, res, sig), COUNSEL_SCHEMA, COUNSEL_SYSTEM, role="counsel",
                      rung=rung, chat=counsel_chat, cloud=cloud)
    tokens["counsel"] = {k: cinfo.get(k) for k in ("tier", "model", "tokens_in", "tokens_out", "tokens_weighted")}
    if cj is None:
        # Counsel unavailable on every tier. A locally final result stands (the spot check is owed);
        # anything else stays pending rather than going out unreviewed.
        if final:
            return out("associate", j=_package(state, res, res["j"]["memo"], "associate",
                                                 {"signals": sig, "trust": tr, "spot_check": "owed"})[0],
                       dossier=res.get("dossier"), associate_resolvable=True, spot_check="owed", signals=sig, trust=tr, tokens=tokens)
        return out("none", abstain=True, reason=f"counsel unavailable: {cinfo.get('error')}", escalate_full=False,
                   signals=sig, tokens=tokens)
    assessment = _s(cj.get("assessment")).lower()
    assessment = "agree" if assessment.startswith("agree") else ("amend" if assessment.startswith("amend") else "redo")
    if not res.get("j"):
        assessment = "redo"
    severity = (res.get("meta") or {}).get("adversary_severity") or "none"
    revised = bool((res.get("meta") or {}).get("revised"))
    counsel_b = lt.size_b(cinfo.get("model") or "") if cinfo.get("tier") == "local" else 100.0
    if assessment == "agree":
        memo, conf, mint, gwhy = res["j"]["memo"], (res.get("meta") or {}).get("confidence"), True, "counsel agreed"
        stats = (res.get("meta") or {}).get("grounding") or {}
    else:
        memo, stats, conf, parts, mint, gwhy, _ = _finish(state, _chair_from(cj, (res.get("j") or {}).get("memo")),
                                                          counsel_b, severity if assessment == "amend" else "none", revised)
    common = {"associate_resolvable": resolvable, "counsel_assessment": assessment if res.get("j") else None,
              "spot_check": spot, "signals": sig, "trust": tr,
              "counsel": {"tier": cinfo.get("tier"), "model": cinfo.get("model"), "rung": rung,
                          "issues": [{"issue": _s(i.get("issue"))[:160], "status": _s(i.get("status"))} for i in cj.get("issues") or []],
                          "needs_partner": bool(cj.get("needs_partner")), "gate": gwhy}}
    remember(state, vertical, "counsel", counsel=cj, associate_verdict=((res.get("j") or {}).get("memo") or {}).get("verdict", ""))
    need_partner = bool(cj.get("needs_partner")) or (priority == "high" and any(
        not _s(i.get("status")).lower().startswith("settled") for i in cj.get("issues") or []))
    if not need_partner:
        if not mint and assessment != "agree":
            return out("none", abstain=True, reason=f"counsel's memo did not clear the gate: {gwhy}", tokens=tokens, **common)
        route = "counsel"
        j, dossier = _package(state, res, memo, route, {**common, "tokens": tokens})
        return out(route, j=j, dossier=dossier, tokens=tokens, **common)

    # PARTNER — brief first, local gap research second, web tools only for what remains
    pj, pinfo = _call(_partner_prompt(question, state, cj), PARTNER_SCHEMA, PARTNER_SYSTEM, role="partner", cloud=cloud)
    pcalls = [pinfo]
    gaps = [g for g in (pj or {}).get("gaps") or [] if _s(g).strip()] if pj else []
    filled = 0
    if pj and gaps:
        filled = _fill_gaps(state, gaps, question, vertical, fetcher=fetcher, searcher=searcher)
        note = (f"\nTHE ASSOCIATE RESEARCHED YOUR GAPS AND ADDED {filled} NEW FINDINGS TO THE LEDGER BELOW." if filled
                else "\nTHE ASSOCIATE COULD NOT FIND YOUR GAPS IN OFFICIAL SOURCES. You have web tools for THESE GAPS ONLY: "
                     + "; ".join(_s(g)[:140] for g in gaps[:4]))
        pj2, pinfo2 = _call(_partner_prompt(question, state, cj, note), PARTNER_SCHEMA, PARTNER_SYSTEM, role="partner",
                            tools=(None if filled else __import__("frontier").WEB_TOOLS), cloud=cloud)
        pcalls.append(pinfo2)
        if pj2:
            pj = pj2
    tokens["partner"] = [{k: p.get(k) for k in ("tier", "model", "tokens_in", "tokens_out", "tokens_weighted")} for p in pcalls]
    if not pj:
        # Partner unavailable: counsel's work stands, flagged, rather than nothing going out.
        if mint:
            j, dossier = _package(state, res, memo, "counsel", {**common, "partner_pending": True, "tokens": tokens})
            return out("counsel", j=j, dossier=dossier, tokens=tokens, partner={"pending": True}, **common)
        return out("none", abstain=True, reason="partner unavailable and counsel's memo did not clear the gate",
                   tokens=tokens, **common)
    wmap = _adopt_web(state, pj.get("new_authorities"), fetcher=fetcher)
    remember(state, vertical, "partner", partner=pj)
    text = _s(pj.get("memo"))
    for w, fid in wmap.items():
        text = re.sub(rf"\b{w}\b", fid, text)
    text = re.sub(r"\[W\d+(?:,\s*W\d+)*\]", "", text)          # unverified web cites are dropped
    pj["memo"] = text
    pmemo, pstats, pconf, pparts, pmint, pwhy, _ = _finish(state, _chair_from(pj, memo), 100.0, "none", True)
    partner_meta = {"tier": pcalls[-1].get("tier"), "model": pcalls[-1].get("model"), "calls": len(pcalls),
                    "gaps": gaps[:6], "gaps_filled_locally": filled, "web_authorities_verified": len(wmap),
                    "rulings": [{"issue": _s(r.get("issue"))[:160], "ruling": _s(r.get("ruling"))[:300]} for r in pj.get("rulings") or []],
                    "gate": pwhy}
    if not pmint:
        if mint:
            j, dossier = _package(state, res, memo, "counsel", {**common, "partner_rejected": pwhy, "tokens": tokens})
            return out("counsel", j=j, dossier=dossier, tokens=tokens, partner=partner_meta, **common)
        return out("none", abstain=True, reason=f"partner memo did not clear the gate: {pwhy}", tokens=tokens,
                   partner=partner_meta, **common)
    j, dossier = _package(state, res, pmemo, "partner", {**common, "partner": partner_meta, "tokens": tokens})
    return out("partner", j=j, dossier=dossier, tokens=tokens, partner=partner_meta, **common)


def report(records=None):
    recs = records if records is not None else _records()
    from collections import Counter
    by = Counter(r.get("route") for r in recs)
    verts = sorted({r.get("vertical") for r in recs if r.get("vertical")})
    return {"matters": len(recs), "routes": dict(by), "trust": {v: trust(v, recs) for v in verts},
            "spot_checks": sum(1 for r in recs if r.get("spot_check") is True),
            "counsel_assessments": dict(Counter(r.get("counsel_assessment") for r in recs if r.get("counsel_assessment")))}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        print(json.dumps(report(), indent=1))
    else:
        import consilium_v2
        q = sys.argv[1] if len(sys.argv) > 1 else "Must a money services business register with FinCEN even if it holds state money transmitter licences?"
        v = sys.argv[2] if len(sys.argv) > 2 else "finserv"
        p = sys.argv[3] if len(sys.argv) > 3 else "medium"
        r = run(q, context=f"PRIORITY: {p}", vertical=v, priority=p, panel=consilium_v2._seat_pool(v, 3))
        print(json.dumps({k: r[k] for k in ("route", "abstain", "reason", "escalate_full")}, indent=1))
        print(json.dumps(r["meta"], indent=1, default=str)[:4000])
        if r.get("j"):
            print(json.dumps(r["j"]["memo"], indent=1)[:5000])

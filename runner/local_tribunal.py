#!/usr/bin/env python3
"""local_tribunal.py — the LOCAL tribunal, rebuilt around what a mid-size model is actually good at.

WHAT WENT WRONG WITH THE FIRST LOCAL TIER. It asked a small model to do a large model's job in one
breath per round: read a dossier, take a position, write a 900-word memo, then list citations from
memory of what it had just written. The independent commission rejected 51 of 52 of those cards —
median composite 0.29 against 0.70 for the frontier tier — while the cards themselves claimed a
median confidence of 0.95. The reviewers' notes name the failures precisely: the question was
reframed, authority was inferred from a heading, the governing rule was never opened, and the
confidence was invented.

A mid-size model is unreliable at open-ended legal synthesis and RELIABLE at narrow tasks: pick the
sentence in this passage that bears on this issue; does this quote support this claim, yes or no.
So the pipeline is built from narrow tasks, and everything that can be decided by bytes instead of
by a model is decided by bytes.

    PLAN       premise check, issues, candidate authorities, search queries. The playbook
               (playbooks.py — distilled once from frontier memos) says what to look for.
    RESEARCH   official search APIs + rule-resolved citations + playbook authorities + the
               authority cache + the firm's corpus. Pages are fetched by US. Passages are exact
               slices of the page, scored against each issue. One hop follows cross-references.
    EXTRACT    per issue, the model picks quotes from the passages and says what each establishes.
               Every quote is checked as a substring of its passage; a quote that is not there is
               repaired mechanically from the passage or dropped. Survivors are FINDINGS (F1, F2…).
    SEATS      three method-diverse experts answer using ONLY findings, claim by claim, each claim
               naming the findings it rests on.
    VERIFY     a different model where one fits, in a clean context, sees one claim and its
               quotes at a time: supported, overreach, or unsupported. Overreach is narrowed.
               Unsupported claims become assumptions. This is the round that removes the
               confident leap.
    CHALLENGE  each seat must state the strongest opposing claim and hold, concede or partly
               concede. Bouts are scored on grounding by arithmetic, not by a judge model.
    GAPS       what the seats said was missing drives one more research pass.
    CHAIR      writes from verified claims only, citing findings inline. Two drafts; the one that
               grounds more of what it says wins, by count.
    ADVERSARY  a different model attacks; one bounded revision.
    CONFIDENCE computed from claim coverage, issue coverage, source count, seat agreement and the
               adversary's severity. The model is never asked how sure it is.
    GATE       a memo is minted only when the evidence supports one. Otherwise the tribunal
               ABSTAINS, keeps the dossier and ledger for reuse, and says why.

ABSTENTION IS THE FEATURE. The old tier always produced a card. This one produces a card when it
can ground it, and a reusable, verified research file when it cannot — which a later run, a larger
model, or a frontier debate picks up without paying for research again.

MODEL SIZE. The pipeline runs on whatever local model is resident or fits. Below
ORCH_LOCAL_MIN_DEBATE_B (default 20B) it still does the narrow work — plan, extract, verify — and
abstains from writing the memo, because an 8-9B model's prose should not steer a build.

Everything is injectable (chat, fetcher, searcher) so the whole pipeline is tested without a model
or a network.
"""
from __future__ import annotations
import datetime
import json
import os
import re
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common_utils

_s = common_utils.safe_string_coerce

ENABLED = os.environ.get("ORCH_LOCAL_TRIBUNAL", "true").lower() not in ("0", "false", "no", "off")
MIN_DEBATE_B = float(os.environ.get("ORCH_LOCAL_MIN_DEBATE_B", "20"))
MAX_SOURCES = int(os.environ.get("ORCH_LOCAL_TRIBUNAL_MAX_SOURCES", "12"))
MAX_PASSAGES = int(os.environ.get("ORCH_LOCAL_TRIBUNAL_MAX_PASSAGES", "26"))
PASSAGE_CHARS = int(os.environ.get("ORCH_LOCAL_TRIBUNAL_PASSAGE_CHARS", "850"))
SEATS = int(os.environ.get("ORCH_LOCAL_TRIBUNAL_SEATS", "3"))
TIMEOUT = int(os.environ.get("ORCH_CONSILIUM_LOCAL_TIMEOUT_S", "900"))
GATE_MIN_SOURCES = int(os.environ.get("ORCH_LOCAL_GATE_MIN_SOURCES", "4"))
GATE_MIN_CLAIMS = int(os.environ.get("ORCH_LOCAL_GATE_MIN_CLAIMS", "5"))
GATE_MIN_COVERAGE = float(os.environ.get("ORCH_LOCAL_GATE_MIN_COVERAGE", "0.65"))
GATE_MIN_ISSUE_COVERAGE = float(os.environ.get("ORCH_LOCAL_GATE_MIN_ISSUE_COVERAGE", "0.6"))
USE_CORPUS = os.environ.get("ORCH_LOCAL_TRIBUNAL_CORPUS", "true").lower() not in ("0", "false", "no", "off")
CLOUD_FALLBACK = os.environ.get("ORCH_LOCAL_TRIBUNAL_CLOUD_FALLBACK", "true").lower() not in ("0", "false", "no", "off")
# A matter whose local model dies midway may finish its narrow steps in the cloud, up to this many.
CLOUD_STEP_CAP = int(os.environ.get("ORCH_LOCAL_TRIBUNAL_CLOUD_STEP_CAP", "30"))
HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
LEDGERS = os.path.join(HOME, "consilium", "ledgers")

BASE = """You are a careful regulatory analyst working inside a tribunal that checks everything you write.
Rules that are enforced by software after you answer:
 - You may rely ONLY on the material given to you in this message. Authority you remember but cannot
   see here is an assumption, and you must label it as one.
 - A quote must be copied character for character from the passage it comes from.
 - Do not infer what a rule says from its title or heading.
 - If the material does not answer the question, say so. "The record does not show" is a good answer.
Be specific and brief. Return ONLY the JSON object."""

PLAN_SCHEMA = {"type": "object", "properties": {
    "premise_ok": {"type": "boolean"}, "premise_problem": {"type": "string"},
    "restated_question": {"type": "string"},
    "jurisdictions": {"type": "array", "items": {"type": "string"}},
    "issues": {"type": "array", "items": {"type": "string"}},
    "authorities": {"type": "array", "items": {"type": "string"}},
    "searches": {"type": "array", "items": {"type": "object", "properties": {
        "backend": {"type": "string"}, "query": {"type": "string"}}, "required": ["backend", "query"]}}},
    "required": ["premise_ok", "premise_problem", "restated_question", "jurisdictions", "issues",
                 "authorities", "searches"]}

EXTRACT_SCHEMA = {"type": "object", "properties": {"findings": {"type": "array", "items": {
    "type": "object", "properties": {
        "passage": {"type": "string"}, "quote": {"type": "string"},
        "says": {"type": "string"}, "bears_on": {"type": "string"}},
    "required": ["passage", "quote", "says", "bears_on"]}}}, "required": ["findings"]}

SEAT_SCHEMA = {"type": "object", "properties": {
    "answer": {"type": "string"},
    "claims": {"type": "array", "items": {"type": "object", "properties": {
        "claim": {"type": "string"}, "findings": {"type": "array", "items": {"type": "string"}},
        "kind": {"type": "string"}}, "required": ["claim", "findings", "kind"]}},
    "probability": {"type": "number"},
    "missing": {"type": "array", "items": {"type": "string"}}},
    "required": ["answer", "claims", "probability", "missing"]}

VERIFY_SCHEMA = {"type": "object", "properties": {"checks": {"type": "array", "items": {
    "type": "object", "properties": {
        "n": {"type": "integer"}, "verdict": {"type": "string"}, "narrowed": {"type": "string"}},
    "required": ["n", "verdict", "narrowed"]}}}, "required": ["checks"]}

CHALLENGE_SCHEMA = {"type": "object", "properties": {
    "strongest_opposing_claim": {"type": "string"}, "from_seat": {"type": "string"},
    "moved": {"type": "boolean"}, "outcome": {"type": "string"},
    "final_answer": {"type": "string"}, "probability": {"type": "number"}},
    "required": ["strongest_opposing_claim", "from_seat", "moved", "outcome", "final_answer", "probability"]}

CHAIR_SCHEMA = {"type": "object", "properties": {
    "verdict": {"type": "string"}, "memo": {"type": "string"},
    "assumptions": {"type": "array", "items": {"type": "string"}},
    "dissent": {"type": "string"}, "flips_if": {"type": "string"}, "conditions": {"type": "string"},
    "unsettled": {"type": "boolean"},
    "options": {"type": "array", "items": {"type": "object", "properties": {
        "option": {"type": "string"}, "posture": {"type": "string"},
        "findings": {"type": "array", "items": {"type": "string"}}, "abandon_if": {"type": "string"}},
        "required": ["option", "posture", "findings", "abandon_if"]}}},
    "required": ["verdict", "memo", "assumptions", "dissent", "flips_if", "conditions", "unsettled", "options"]}

ATTACK_SCHEMA = {"type": "object", "properties": {
    "breaks": {"type": "boolean"}, "attack": {"type": "string"}, "missed_authority": {"type": "string"},
    "failing_fact_pattern": {"type": "string"}, "severity": {"type": "string"},
    "what_would_fix_it": {"type": "string"}},
    "required": ["breaks", "attack", "missed_authority", "failing_fact_pattern", "severity", "what_would_fix_it"]}


# ── small utilities ──────────────────────────────────────────────────────────────────────────────
def size_b(model):
    """Parameter count in billions parsed from a model name; 0 when unknown."""
    m = re.findall(r"(\d+(?:\.\d+)?)\s*b\b", str(model or "").lower().replace("-", " ").replace("_", " "))
    try:
        return max(float(x) for x in m) if m else 0.0
    except Exception:
        return 0.0


def _ws(t):
    return re.sub(r"\s+", " ", _s(t)).strip()


def _words(t):
    return re.findall(r"[a-z0-9]+", _s(t).lower())


def locate_quote(quote, passage, max_words=45):
    """-> a VERBATIM slice of `passage` for this quote, or ''. Exact match first; otherwise the
    sentence of the passage that shares the most words with the quote (a mechanical repair: the
    model pointed at the right place and mangled the characters)."""
    q, p = _ws(quote).strip('"“”\''), _ws(passage)
    if len(q) < 20 or not p:
        return ""
    if q in p:
        return " ".join(q.split()[:max_words]) if len(q.split()) > max_words else q
    qw = set(_words(q))
    if len(qw) < 4:
        return ""
    best, score = "", 0.0
    for sent in re.split(r"(?<=[.;:?!])\s+", p):
        sw = set(_words(sent))
        if len(sw) < 4:
            continue
        overlap = len(qw & sw) / len(qw)
        if overlap > score:
            best, score = sent, overlap
    if score < 0.7:
        return ""
    out = " ".join(best.split()[:max_words])
    return out if out in p and len(out) >= 20 else ""


def norm_severity(s):
    t = str(s or "").strip().lower()
    if "fatal" in t:
        return "fatal"
    if any(k in t for k in ("material", "high", "major", "severe", "serious", "significant", "medium", "moderate")):
        return "material"
    if any(k in t for k in ("marginal", "minor", "low")):
        return "marginal"
    return "none"


def strong_models():
    """Local rungs at or above the debate floor for the ASSOCIATE, smallest first. The associate makes
    ~25 narrow calls, so the fastest capable model does them; the largest rung that fits is kept for
    counsel (escalation.counsel_rung), mirroring associate and counsel in a firm. local_llm otherwise
    prefers whatever is resident — on a busy host, the 9B."""
    try:
        import local_llm
        return sorted([m for m in local_llm.MODELS if size_b(m) >= MIN_DEBATE_B], key=size_b)
    except Exception:
        return []


class Calls:
    def __init__(self, chat, prefer=None, cloud_fallback=False):
        self.chat, self.n, self.failed, self.models, self.by = chat, 0, 0, [], {}
        self.prefer = list(prefer or [])
        self.cloud_fallback, self.cloud_steps = cloud_fallback, 0

    def ask(self, prompt, schema, *, tag, max_tokens=1200, temperature=0.2, models=None, system=BASE):
        kw = {"system": system, "json_schema": schema, "max_tokens": max_tokens, "temperature": temperature,
              "timeout": TIMEOUT, "tag": tag}
        wanted = models or self.prefer
        if wanted:
            kw["models"] = wanted
        try:
            r = self.chat(prompt, **kw)
        except Exception as e:
            r = {"json": None, "error": f"{type(e).__name__}: {str(e)[:120]}"}
        if wanted and not models and (not isinstance(r, dict) or not isinstance(r.get("json"), dict) or r.get("error")):
            # no preferred rung could serve: fall to the whole ladder rather than fail the step
            kw.pop("models", None)
            try:
                r = self.chat(prompt, **kw)
            except Exception as e:
                r = {"json": None, "error": f"{type(e).__name__}: {str(e)[:120]}"}
        if (self.cloud_fallback and self.cloud_steps < CLOUD_STEP_CAP
                and (not isinstance(r, dict) or not isinstance(r.get("json"), dict) or r.get("error"))):
            # NEVER IDLE: no local model could take the step (the host had 0.6 GiB free on 2026-09-29).
            # The same narrow step runs on the cheapest cloud tier instead of stopping the tribunal.
            try:
                import frontier
                fr = frontier.complete(prompt, system=system, json_schema=schema, need=6, timeout=TIMEOUT,
                                       tag=tag + ".cloud", min_tier="codex")
                if isinstance(fr.get("json"), dict) and not fr.get("error"):
                    r = {"json": fr["json"], "text": fr.get("text"), "model": fr.get("model"), "error": "",
                         "tier": fr.get("tier")}
                    self.cloud_steps += 1
            except Exception:
                pass
        self.n += 1
        self.by[tag] = self.by.get(tag, 0) + 1
        j = r.get("json") if isinstance(r, dict) else None
        if not isinstance(j, dict) or r.get("error"):
            self.failed += 1
            return {}, r
        if r.get("model") and r["model"] not in self.models:
            self.models.append(r["model"])
        return j, r


# ── research ─────────────────────────────────────────────────────────────────────────────────────
def research(question, context, vertical, plan, *, fetcher, searcher, extra_queries=None, have=None):
    """-> dossier {sources, passages, _pages, leads, unresolved, queries}. Pages are fetched by us;
    passages are exact slices. `have` is a previous dossier to extend (gap research)."""
    import authority_search as asrch
    import local_research as lr
    import playbooks
    d = have or {"sources": [], "passages": [], "_pages": {}, "leads": [], "unresolved": [], "queries": [],
                 "issues": list(plan.get("issues") or [])}
    seen = {s["url"] for s in d["sources"]}
    qterms = asrch.terms(" ".join([question or "", plan.get("restated_question") or ""]), limit=30)
    issues = d["issues"] or [question]
    cands = []
    if not have:
        for a in plan.get("_holding_urls") or []:
            cands.append({"url": a["url"], "authority": a.get("authority") or "", "title": "", "jurisdiction": "",
                          "origin": "holding"})
        for a in playbooks.authorities(vertical, question):
            cands.append({"url": a["url"], "authority": a.get("cite") or "", "title": a.get("decides") or "",
                          "jurisdiction": "", "origin": "playbook"})
        try:
            import consilium_v2
            for h in consilium_v2._cache_hits(question, vertical, k=6):
                cands.append({"url": h.get("url"), "authority": h.get("authority") or h.get("title") or "",
                              "title": h.get("title") or "", "jurisdiction": h.get("jurisdiction") or "",
                              "origin": "authority_cache"})
        except Exception:
            pass
        named = " ; ".join([question or "", context or ""] + [_s(a) for a in plan.get("authorities") or []])
        for c in lr.resolve(named):
            cands.append({**c, "title": c.get("authority"), "origin": "resolved"})
    queries = list(extra_queries or []) if have else list(plan.get("searches") or [])
    if not have and not queries:
        queries = [{"backend": "ecfr", "query": " ".join(qterms[:8])}, {"backend": "fr", "query": " ".join(qterms[:8])}]
    if queries:
        try:
            hits, leads = searcher(queries)
        except Exception:
            hits, leads = [], []
        d["queries"] += [(q.get("query") if isinstance(q, dict) else str(q)) for q in queries][:8]
        for h in hits:
            cands.append({**h, "origin": "search:" + str(h.get("backend"))})
        for l in leads:
            if l.get("authority") and l["authority"] not in d["leads"]:
                d["leads"].append(l["authority"])
    if USE_CORPUS and not have:
        try:
            import local_llm
            free = local_llm.free_gb()
            if free is None or free >= 5:
                import corpus_retrieval
                for p in corpus_retrieval.top_passages(question, k=6) or []:
                    if p.get("source_url") and p.get("text"):
                        u = p["source_url"]
                        text = _ws(p["text"])
                        d["_pages"].setdefault(u, text)
                        cands.append({"url": u, "authority": (p.get("heading") or p.get("doc_title") or "")[:160],
                                      "title": (p.get("doc_title") or "")[:160], "jurisdiction": p.get("jurisdiction") or "",
                                      "origin": "corpus", "_held": text})
        except Exception:
            pass
    # fetch, score, keep the most relevant sources
    scored = []
    for c in cands:
        u = _s(c.get("url")).strip()
        if not u or u in seen:
            continue
        seen.add(u)
        page = c.get("_held") or ""
        if not page:
            try:
                page = fetcher(u) or ""
            except Exception:
                page = ""
        if len(page) < 200:
            d["unresolved"].append(f"{c.get('authority') or u} (could not open)")
            continue
        rel = asrch.relevance(page[:60000], qterms)
        bonus = 3.0 if c.get("origin") in ("playbook", "resolved", "holding") else 0.0
        scored.append((rel + bonus, c, page))
    scored.sort(key=lambda x: -x[0])
    room = max(0, MAX_SOURCES - len(d["sources"]))
    for rel, c, page in scored[:room]:
        if rel <= 0:
            continue
        sid = f"S{len(d['sources']) + 1}"
        d["_pages"][c["url"]] = page
        c["authority"] = asrch.label_for(c["url"], _s(c.get("authority")))
        d["sources"].append({"id": sid, "url": c["url"], "display_url": c.get("display_url") or c["url"],
                             "authority": _s(c.get("authority"))[:200], "title": _s(c.get("title"))[:200],
                             "jurisdiction": _s(c.get("jurisdiction")), "origin": c.get("origin"),
                             "kind": c.get("kind") or "", "quote": "", "verified": False, "proposition": ""})
        per_issue = {}
        for i, issue in enumerate(issues):
            want = asrch.terms(issue, limit=14) + qterms[:10]
            for p in asrch.passages(page, want, k=2, width=PASSAGE_CHARS):
                key = p["start"]
                if key not in per_issue or p["score"] > per_issue[key]["score"]:
                    per_issue[key] = {**p, "issue": i}
        for p in sorted(per_issue.values(), key=lambda x: -x["score"])[:3]:
            if len(d["passages"]) >= MAX_PASSAGES:
                break
            d["passages"].append({"id": f"P{len(d['passages']) + 1}", "source": sid, "url": c["url"],
                                  "authority": _s(c.get("authority"))[:160], "issue": p["issue"],
                                  "text": p["text"], "score": p["score"]})
    return d


def follow_references(d, *, fetcher):
    """One hop: citations that appear INSIDE the selected passages are opened too."""
    import authority_search as asrch
    import local_research as lr
    seen = {s["url"] for s in d["sources"]}
    added = 0
    text = " ; ".join(p["text"] for p in d["passages"])
    for c in lr.resolve(text):
        if added >= 3 or len(d["sources"]) >= MAX_SOURCES or c["url"] in seen:
            continue
        seen.add(c["url"])
        try:
            page = fetcher(c["url"]) or ""
        except Exception:
            page = ""
        if len(page) < 200:
            continue
        sid = f"S{len(d['sources']) + 1}"
        d["_pages"][c["url"]] = page
        d["sources"].append({"id": sid, "url": c["url"], "display_url": c["url"], "authority": c["authority"],
                             "title": c["authority"], "jurisdiction": c.get("jurisdiction") or "",
                             "origin": "cross_reference", "kind": "", "quote": "", "verified": False, "proposition": ""})
        want = []
        for issue in d.get("issues") or []:
            want += asrch.terms(issue, limit=10)
        for p in asrch.passages(page, want or asrch.terms(text, 20), k=2, width=PASSAGE_CHARS):
            if len(d["passages"]) < MAX_PASSAGES:
                d["passages"].append({"id": f"P{len(d['passages']) + 1}", "source": sid, "url": c["url"],
                                      "authority": c["authority"], "issue": 0, "text": p["text"], "score": p["score"]})
        added += 1
    return added


# ── extraction: passages -> verified findings ───────────────────────────────────────────────────
def extract(calls, question, d, findings, only_passages=None):
    issues = d.get("issues") or [question]
    todo = [p for p in d["passages"] if (only_passages is None or p["id"] in only_passages)]
    by_issue = {}
    for p in todo:
        by_issue.setdefault(p["issue"], []).append(p)
    for i, ps in sorted(by_issue.items()):
        issue = issues[i] if i < len(issues) else question
        for start in range(0, len(ps), 7):
            chunk = ps[start:start + 7]
            body = "\n\n".join(f"[{p['id']}] {p['authority']}\n{p['text']}" for p in chunk)
            j, _ = calls.ask(
                f"QUESTION: {question[:900]}\nISSUE: {issue[:400]}\n\nPASSAGES (each is an exact excerpt of an official source):\n{body}\n\n"
                "For each passage that actually bears on the issue, give: the passage id; a QUOTE copied character for "
                "character from that passage (at most 40 words, the operative words only); what the quote establishes in "
                "plain language (`says`); and how it bears on the issue (`bears_on`). Skip passages that do not bear on "
                "the issue. Do not add anything that is not in the passage.",
                EXTRACT_SCHEMA, tag="local.extract", max_tokens=1500, temperature=0.1)
            by_id = {p["id"]: p for p in chunk}
            for f in (j.get("findings") or [])[:10]:
                pid = _s(f.get("passage")).strip().strip("[]")
                p = by_id.get(pid)
                if not p:
                    continue
                quote = locate_quote(f.get("quote"), p["text"])
                if not quote or not _ws(f.get("says")) or asrch_is_chrome(quote):
                    continue
                if any(x["quote"] == quote and x["url"] == p["url"] for x in findings):
                    continue
                findings.append({"id": f"F{len(findings) + 1}", "passage": pid, "source": p["source"], "url": p["url"],
                                 "authority": p["authority"], "issue": i, "quote": quote,
                                 "says": _ws(f.get("says"))[:400], "bears_on": _ws(f.get("bears_on"))[:300]})
    return findings


def backfill(d, findings, question, per_issue=2):
    """A strong passage the model passed over still enters the ledger, as its own best sentence.
    The finding says exactly what the quote says and nothing more, so it cannot overstate."""
    import authority_search as asrch
    issues = d.get("issues") or [question]
    have = {f["passage"] for f in findings}
    added = 0
    for i, issue in enumerate(issues):
        if sum(1 for f in findings if f["issue"] == i) >= per_issue:
            continue
        want = asrch.terms(issue, limit=14) + asrch.terms(question, limit=10)
        room = per_issue - sum(1 for f in findings if f["issue"] == i)
        for p in sorted((p for p in d["passages"] if p["issue"] == i and p["id"] not in have),
                        key=lambda x: -x["score"])[:room]:
            best, score = "", 0.0
            for sent in re.split(r"(?<=[.;:?!])\s+", p["text"]):
                if len(sent.split()) < 8:
                    continue
                sc = asrch.relevance(sent, want)
                if sc > score:
                    best, score = sent, sc
            quote = " ".join(best.split()[:45])
            if score < 4 or len(quote) < 40 or quote not in p["text"] or asrch_is_chrome(quote):
                continue
            findings.append({"id": f"F{len(findings) + 1}", "passage": p["id"], "source": p["source"], "url": p["url"],
                             "authority": p["authority"], "issue": i, "quote": quote,
                             "says": quote[:400], "bears_on": f"selected mechanically for: {issue[:160]}",
                             "mechanical": True})
            have.add(p["id"])
            added += 1
    return added


def render_ledger(findings, max_chars=9000):
    lines = [f"[{f['id']}] {f['authority']}: \"{f['quote']}\" — establishes: {f['says']}" for f in findings]
    return "\n".join(lines)[:max_chars]


def _fids(raw, valid):
    out = []
    for x in raw or []:
        for m in re.findall(r"F\d+", _s(x).upper()):
            if m in valid and m not in out:
                out.append(m)
    return out


# ── seats, verification, challenge ───────────────────────────────────────────────────────────────
def seat_round(calls, question, plan, panel, findings, playbook, exemplar):
    valid = {f["id"] for f in findings}
    ledger = render_ledger(findings)
    seats = []
    for e in panel[:SEATS]:
        j, r = calls.ask(
            f"QUESTION: {question[:1200]}\n"
            + (f"NOTE ON THE QUESTION'S PREMISE: {plan.get('premise_problem')}\n" if not plan.get("premise_ok", True) else "")
            + f"ISSUES: {json.dumps(plan.get('issues') or [])[:900]}\n\n"
            f"YOU ARE: \"{e.get('public_label')}\" — method: {e.get('method')}; domain: {e.get('domain')}.\n"
            f"YOUR DOCTRINE: {_s(e.get('doctrine'))[:500]}\n\n"
            + (f"PLAYBOOK (how the senior tribunal approaches this area):\n{playbook}\n\n" if playbook else "")
            + f"EVIDENCE LEDGER (the ONLY support you may use):\n{ledger}\n\n"
            "Answer the question from your method. Build the answer from CLAIMS. Each claim is one sentence and names the "
            "finding ids it rests on. kind is `direct` when a finding says it, `inference` when you reason from findings, "
            "`assumption` when nothing in the ledger supports it (findings must then be empty). Give your probability "
            "(0-1) that a regulator or court lands on your answer, and list what is MISSING from the ledger that you "
            "would need in order to be sure — as specific things to look up.",
            SEAT_SCHEMA, tag="local.seat", max_tokens=1600, temperature=0.3)
        if not j:
            continue
        claims = []
        for c in (j.get("claims") or [])[:14]:
            text = _ws(c.get("claim"))
            if len(text) < 15:
                continue
            ids = _fids(c.get("findings"), valid)
            kind = _s(c.get("kind")).lower()
            kind = "assumption" if (not ids or "assum" in kind) else ("direct" if "direct" in kind else "inference")
            claims.append({"claim": text[:500], "findings": ids if kind != "assumption" else [], "kind": kind,
                           "status": "assumption" if kind == "assumption" else "unchecked"})
        try:
            prob = max(0.0, min(1.0, float(j.get("probability"))))
        except Exception:
            prob = 0.5
        seats.append({"seat": e.get("public_label"), "_expert": e, "answer": _ws(j.get("answer"))[:900],
                      "claims": claims, "probability": prob,
                      "missing": [_ws(m)[:200] for m in (j.get("missing") or [])[:5] if _ws(m)]})
    return seats


def verify_claims(calls, seats, findings, verifier_models=None):
    """Each claim against ITS OWN quotes, in a context that contains nothing else."""
    by_id = {f["id"]: f for f in findings}
    for s in seats:
        todo = [c for c in s["claims"] if c["status"] == "unchecked"]
        for start in range(0, len(todo), 8):
            chunk = todo[start:start + 8]
            body = "\n\n".join(
                f"{n}. CLAIM: {c['claim']}\n   QUOTES: " + " || ".join(
                    f"({by_id[i]['authority']}) \"{by_id[i]['quote']}\"" for i in c["findings"] if i in by_id)
                for n, c in enumerate(chunk, 1))
            prompt = ("For each numbered claim decide whether the QUOTES shown with it support it.\n"
                      " supported   the quotes say it, or it follows from them directly\n"
                      " overreach   the quotes support something narrower — write the narrower claim in `narrowed`\n"
                      " unsupported the quotes do not support it\n"
                      "Judge only from the quotes. Do not use outside knowledge. `narrowed` is \"\" unless overreach.\n\n" + body)
            j, _ = calls.ask(prompt, VERIFY_SCHEMA, tag="local.verify", max_tokens=900, temperature=0.0,
                             models=verifier_models)
            if not j and verifier_models:
                j, _ = calls.ask(prompt, VERIFY_SCHEMA, tag="local.verify", max_tokens=900, temperature=0.0)
            got = {}
            for k in j.get("checks") or []:
                try:
                    got[int(k.get("n"))] = k
                except Exception:
                    continue
            for n, c in enumerate(chunk, 1):
                k = got.get(n)
                if not k:
                    c["status"] = "unverified"
                    continue
                v = _s(k.get("verdict")).lower()
                if v.startswith("support"):
                    c["status"] = "supported"
                elif v.startswith("over") and len(_ws(k.get("narrowed"))) >= 15:
                    c["original"], c["claim"], c["status"] = c["claim"], _ws(k.get("narrowed"))[:500], "narrowed"
                else:
                    c["status"] = "unsupported"
    return seats


def grounded(seat):
    return [c for c in seat["claims"] if c["status"] in ("supported", "narrowed")]


def challenge_round(calls, question, seats):
    board = "\n".join(f"- {s['seat']} (p={s['probability']}): {s['answer'][:300]}\n    verified claims: "
                      + " | ".join(c["claim"][:160] for c in grounded(s)[:5]) for s in seats)
    for s in seats:
        others = [o for o in seats if o is not s]
        if not others:
            continue
        j, _ = calls.ask(
            f"QUESTION: {question[:900]}\n\nYOU ARE \"{s['seat']}\". YOUR ANSWER: {s['answer'][:500]}\n\nALL SEATS:\n{board}\n\n"
            "State the single strongest claim made AGAINST your answer by another seat, at its strongest, and name the "
            "seat. Then settle: outcome is `hold`, `concede` or `partial`. Conceding to better-grounded evidence is "
            "scored as a strength. Give your final answer in one or two sentences and your probability.",
            CHALLENGE_SCHEMA, tag="local.challenge", max_tokens=700, temperature=0.2)
        out = _s(j.get("outcome")).lower()
        s["steelman_of"] = _ws(j.get("from_seat"))[:120] or others[0]["seat"]
        s["steelman"] = _ws(j.get("strongest_opposing_claim"))[:600]
        s["moved"] = bool(j.get("moved"))
        s["outcome"] = "concede" if out.startswith("conc") else ("partial" if out.startswith("part") else "hold")
        s["final_answer"] = _ws(j.get("final_answer"))[:700] or s["answer"]
        try:
            s["final_probability"] = max(0.0, min(1.0, float(j.get("probability"))))
        except Exception:
            s["final_probability"] = s["probability"]
    return seats


def mechanical_bouts(seats):
    """Grounding decides the bout: more verified claims resting on more distinct findings wins."""
    def strength(s):
        g = grounded(s)
        total = max(1, len([c for c in s["claims"]]))
        return len(g) * (len(g) / total) + 0.25 * len({i for c in g for i in c["findings"]})
    bouts = []
    for i in range(len(seats)):
        for k in range(i + 1, len(seats)):
            a, b = seats[i], seats[k]
            sa, sb = strength(a), strength(b)
            if abs(sa - sb) < 0.25:
                w, margin = "tie", 0.1
            else:
                w, margin = ("A" if sa > sb else "B"), round(min(1.0, abs(sa - sb) / max(sa, sb, 1.0)), 2)
            bouts.append({"a": a["seat"], "b": b["seat"], "winner": w, "margin": margin,
                          "grounds": f"verified claims {len(grounded(a))} vs {len(grounded(b))}; scored on grounding by count"})
    return bouts[:4]


# ── chair, adversary, confidence ─────────────────────────────────────────────────────────────────
def _chair_prompt(question, plan, seats, findings, playbook, exemplar, attack=None, previous=None):
    verified = []
    for s in seats:
        for c in grounded(s):
            verified.append(f"- ({s['seat']}) {c['claim']} [{', '.join(c['findings'])}]")
    disagreements = "\n".join(f"- {s['seat']} [{s.get('outcome', 'hold')}] p={s.get('final_probability', s['probability'])}: "
                              f"{s.get('final_answer') or s['answer']}"[:420] for s in seats)
    assumptions = [c["claim"] for s in seats for c in s["claims"] if c["status"] in ("assumption", "unsupported", "unverified")]
    p = (f"QUESTION: {question[:1200]}\n"
         + (f"THE QUESTION'S PREMISE IS WRONG OR INCOMPLETE: {plan.get('premise_problem')}\n"
            f"ANSWER THIS INSTEAD, AND SAY SO IN THE FIRST LINE: {plan.get('restated_question')}\n"
            if not plan.get("premise_ok", True) else "")
         + f"ISSUES: {json.dumps(plan.get('issues') or [])[:900]}\nTODAY: {datetime.date.today().isoformat()}\n\n"
         f"VERIFIED CLAIMS (each was checked against its quotes; the ids in brackets are findings):\n"
         + "\n".join(verified)[:6500] + "\n\n"
         f"WHERE THE SEATS ENDED:\n{disagreements}\n\n"
         f"UNGROUNDED POINTS RAISED (assumptions, not authority):\n- " + "\n- ".join(a[:200] for a in assumptions[:10]) + "\n\n"
         f"EVIDENCE LEDGER:\n{render_ledger(findings, 7000)}\n\n"
         + (f"PLAYBOOK:\n{playbook[:2000]}\n\n" if playbook else "")
         + (f"STANDARD TO MEET (a senior memo on a related question — match its structure and candour; do NOT reuse "
            f"its conclusions or authorities unless they are in the ledger):\n{_s(exemplar.get('excerpt'))[:1500]}\n\n"
            if exemplar else ""))
    if attack and previous:
        p += (f"YOUR PREVIOUS MEMO:\n{_s(previous.get('memo'))[:5000]}\n\nAN INDEPENDENT ADVERSARY ATTACKED IT:\n"
              f"{json.dumps(attack)[:2500]}\n\nRevise the memo to absorb the attack, or answer it on the record. "
              "Narrow the verdict if the attack shows it was too broad.\n\n")
    p += ("Write the memo a General Counsel will act on this week, 450-900 words:\n"
          " 1. the answer in the first two sentences\n 2. the operative authority and what it says\n"
          " 3. the application to these facts\n 4. the limits of the answer and what the record does NOT show\n"
          " 5. what would flip it\n"
          "EVERY sentence that states what the law is or requires must end with the finding ids it rests on, in "
          "brackets, like [F3] or [F3, F7]. A legal statement with no finding id is not allowed in the memo — put it "
          "under `assumptions` instead. `dissent` is the strongest surviving objection from the seats, in their words. "
          "Refer to each authority by the label shown in the ledger; do not name any rule, part or section that "
          "is not in the ledger. `unsettled` is true when the ledger does not decide the question. `options` are 2-4 lawful ways the company "
          "could proceed, each with a posture (conservative | defensible | aggressive_arguable), the findings it rests "
          "on, and the event that means abandon it. An option is a change to the facts — product, partner, entity, "
          "licence, jurisdiction — never concealment or a misstatement to anyone.")
    return p


def grounding_stats(memo_text, valid_ids):
    """Sentences that assert law, and how many of them carry a valid finding id."""
    sents = [s.strip() for s in re.split(r"(?<=[.;?!])\s+(?=[A-Z(\[\"])", _ws(memo_text)) if len(s.strip()) > 25]
    legal = re.compile(r"(§|\bCFR\b|U\.S\.C|\bAct\b|\brule\b|\bregulat|\bstatut|\brequire|\bprohibit|\bmust\b|\bshall\b|"
                       r"\blicens|\bregister|\bexempt|\bunlawful|\bpermit|\bcourt\b|\bheld\b)", re.I)
    asserted = [s for s in sents if legal.search(s)]
    cited = [s for s in asserted if any(i in valid_ids for i in re.findall(r"F\d+", s))]
    used = []
    for i in re.findall(r"F\d+", memo_text or ""):
        if i in valid_ids and i not in used:
            used.append(i)
    return {"sentences": len(sents), "legal_sentences": len(asserted), "cited_sentences": len(cited),
            "ratio": round(len(cited) / len(asserted), 3) if asserted else 0.0, "findings_used": used,
            "uncited": [s[:240] for s in asserted if s not in cited][:6]}


GROUND_SCHEMA = {"type": "object", "properties": {"sentences": {"type": "array", "items": {
    "type": "object", "properties": {"n": {"type": "integer"}, "findings": {"type": "array", "items": {"type": "string"}}},
    "required": ["n", "findings"]}}}, "required": ["sentences"]}


def ground_pass(calls, chair, findings, verifier_models=None):
    """Every legal sentence the chair left uncited is either tied to findings — and that tie is
    CHECKED like any other claim — or struck from the memo and listed as an assumption."""
    by_id = {f["id"]: f for f in findings}
    text = _s(chair.get("memo"))
    stats = grounding_stats(text, set(by_id))
    full = [s.strip() for s in re.split(r"(?<=[.;?!])\s+(?=[A-Z(\[\"])", _ws(text)) if len(s.strip()) > 25]
    legal = re.compile(r"(§|\bCFR\b|U\.S\.C|\bAct\b|\brule\b|\bregulat|\bstatut|\brequire|\bprohibit|\bmust\b|\bshall\b|"
                       r"\blicens|\bregister|\bexempt|\bunlawful|\bpermit|\bcourt\b|\bheld\b)", re.I)
    uncited = [s for s in full if legal.search(s) and not any(i in by_id for i in re.findall(r"F\d+", s))][:12]
    if not uncited:
        return chair, {"uncited": 0, "grounded": 0, "struck": 0, "ratio_before": stats["ratio"]}
    j, _ = calls.ask(
        "Each numbered sentence below states something about the law but names no support. For each, list the "
        "finding ids from the ledger that support it, or an empty list if none does. Do not stretch.\n\n"
        + "\n".join(f"{n}. {s[:400]}" for n, s in enumerate(uncited, 1))
        + f"\n\nEVIDENCE LEDGER:\n{render_ledger(findings, 7000)}",
        GROUND_SCHEMA, tag="local.ground", max_tokens=700, temperature=0.0)
    proposed = {}
    for k in j.get("sentences") or []:
        try:
            proposed[int(k.get("n"))] = _fids(k.get("findings"), set(by_id))
        except Exception:
            continue
    seat = {"claims": [{"claim": s, "findings": proposed.get(n) or [], "kind": "inference",
                        "status": "unchecked" if proposed.get(n) else "unsupported"}
                       for n, s in enumerate(uncited, 1)]}
    verify_claims(calls, [seat], findings, verifier_models=verifier_models)
    grounded_n = struck = 0
    assumptions = list(chair.get("assumptions") or [])
    for s, c in zip(uncited, seat["claims"]):
        if c["status"] in ("supported", "narrowed"):
            new = (c["claim"] if c["status"] == "narrowed" else s).rstrip(". ") + f" [{', '.join(c['findings'])}]."
            text = text.replace(s, new, 1) if s in text else text
            grounded_n += 1
        else:
            if s in text:
                text = text.replace(s, "", 1)
                assumptions.append(s[:300])
                struck += 1
    chair = {**chair, "memo": re.sub(r"[ \t]{2,}", " ", text).strip(), "assumptions": assumptions}
    return chair, {"uncited": len(uncited), "grounded": grounded_n, "struck": struck, "ratio_before": stats["ratio"]}


def asrch_is_chrome(text):
    try:
        import authority_search
        return authority_search.is_chrome(text)
    except Exception:
        return False


def _cite_key(label):
    """'31 CFR 1022.380(a)(3)' -> ('cfr', '31', '1022.380'); used to compare named authorities."""
    t = _s(label)
    m = re.search(r"(\d+)\s*C\.?F\.?R\.?\s*(?:Part\s*|§\s*)?(\d+(?:\.\d+)?)", t, re.I)
    if m:
        return ("cfr", m.group(1), m.group(2))
    m = re.search(r"(\d+)\s*U\.?S\.?C\.?\s*§*\s*(\d+[a-z]?)", t, re.I)
    if m:
        return ("usc", m.group(1), m.group(2).lower())
    return None


def audit_citations(memo_text, findings):
    """Authorities the memo NAMES that are not in the evidence record. A CFR part matches any
    section inside it and a section matches its part, so '31 CFR 1022' and '31 CFR 1022.210' agree;
    '31 CFR 103' (recodified in 2011) matches nothing current and is reported."""
    held = set()
    for f in findings:
        k = _cite_key(f.get("authority"))
        if k:
            held.add(k)
            if k[0] == "cfr":
                held.add(("cfr", k[1], k[2].split(".")[0]))
    named, unknown = [], []
    for m in re.finditer(r"\d+\s*C\.?F\.?R\.?\s*(?:Part\s*|§\s*)?\d+(?:\.\d+)?|\d+\s*U\.?S\.?C\.?\s*§*\s*\d+[a-z]?",
                         _s(memo_text), re.I):
        k = _cite_key(m.group(0))
        if not k or k in named:
            continue
        named.append(k)
        ok = k in held or (k[0] == "cfr" and ("cfr", k[1], k[2].split(".")[0]) in held)
        if not ok:
            unknown.append(m.group(0).strip())
    return unknown


def finalize(chair, findings):
    """Citations are BUILT from the findings the memo used; the model never writes a citation."""
    by_id = {f["id"]: f for f in findings}
    stats = grounding_stats(_s(chair.get("memo")), set(by_id))
    order, cites = {}, []
    for fid in stats["findings_used"]:
        f = by_id[fid]
        order[fid] = len(cites) + 1
        cites.append({"source": f["authority"], "url": f["url"], "quote": f["quote"], "proposition": f["says"],
                      "verified": True, "confidence": 0.8, "finding": fid})
    memo = re.sub(r"F(\d+)", lambda m: str(order.get("F" + m.group(1), "?")) if ("F" + m.group(1)) in order else m.group(0),
                  _s(chair.get("memo")))
    options = []
    for o in (chair.get("options") or [])[:4]:
        ids = _fids(o.get("findings"), set(by_id))
        posture = _s(o.get("posture")).lower().replace("-", "_").replace(" ", "_")
        options.append({"option": _ws(o.get("option"))[:600],
                        "posture": posture if posture in ("conservative", "defensible", "aggressive_arguable") else "defensible",
                        "citations": [order[i] for i in ids if i in order], "grounded": bool(ids),
                        "abandon_if": _ws(o.get("abandon_if"))[:300]})
    assumptions = [_ws(a)[:300] for a in (chair.get("assumptions") or []) if _ws(a)][:12]
    assumptions += [f"Stated without a supporting finding: {u}" for u in stats["uncited"][:4]]
    unknown = audit_citations(_s(chair.get("memo")), findings)
    stats["unknown_authorities"] = unknown
    assumptions += [f"The memo names {u}, which is not in the evidence record — verify before relying on it "
                    f"(it may be superseded or renumbered)." for u in unknown[:6]]
    return {"verdict": _ws(chair.get("verdict"))[:1500], "memo": memo, "citations": cites, "assumptions": assumptions,
            "dissent": _ws(chair.get("dissent"))[:3000], "flips_if": _ws(chair.get("flips_if"))[:1500],
            "conditions": _ws(chair.get("conditions"))[:1500], "unsettled": bool(chair.get("unsettled")),
            "options": options}, stats


def confidence(seats, findings, stats, issues, severity, revised, model_b, unsettled):
    claims = [c for s in seats for c in s["claims"] if c["kind"] != "assumption"]
    ok = [c for c in claims if c["status"] in ("supported", "narrowed")]
    coverage = len(ok) / len(claims) if claims else 0.0
    covered = {f["issue"] for f in findings if any(f["id"] in c["findings"] for c in ok)}
    issue_cov = len(covered) / max(1, len(issues))
    sources = len({f["url"] for f in findings if any(f["id"] in c["findings"] for c in ok)})
    probs = [s.get("final_probability", s["probability"]) for s in seats]
    agree = 1.0 - min(1.0, (statistics.pstdev(probs) * 2.5 if len(probs) > 1 else 0.4))
    penalty = {"fatal": 0.25, "material": 0.10 if revised else 0.18, "marginal": 0.03}.get(severity, 0.0)
    c = 0.20 + 0.30 * coverage * min(1.0, issue_cov + 0.2) + 0.20 * stats.get("ratio", 0.0) \
        + 0.12 * min(1.0, sources / 8.0) + 0.10 * agree - penalty - 0.05 * min(3, len(stats.get("unknown_authorities") or []))
    cap = 0.85
    if unsettled:
        cap = min(cap, 0.75)
    if model_b and model_b < MIN_DEBATE_B:
        cap = min(cap, 0.60)
    return round(max(0.10, min(cap, c)), 2), {"claim_coverage": round(coverage, 3), "issue_coverage": round(issue_cov, 3),
                                              "grounded_sources": sources, "seat_agreement": round(agree, 3),
                                              "memo_grounding": stats.get("ratio", 0.0), "adversary_penalty": penalty}


def gate(seats, findings, stats, conf_parts, severity, revised, model_b, force=False):
    """(mint, reason). The tribunal writes a card only when the evidence supports one."""
    ok = [c for s in seats for c in s["claims"] if c["status"] in ("supported", "narrowed")]
    if model_b and model_b < MIN_DEBATE_B and not force:
        return False, f"resident model is {model_b:g}B (< {MIN_DEBATE_B:g}B): research and ledger kept, memo not minted"
    if conf_parts["grounded_sources"] < GATE_MIN_SOURCES:
        return False, f"only {conf_parts['grounded_sources']} sources support verified claims (< {GATE_MIN_SOURCES})"
    if len(ok) < GATE_MIN_CLAIMS:
        return False, f"only {len(ok)} claims survived verification (< {GATE_MIN_CLAIMS})"
    if conf_parts["claim_coverage"] < GATE_MIN_COVERAGE:
        return False, f"claim coverage {conf_parts['claim_coverage']} (< {GATE_MIN_COVERAGE})"
    if conf_parts["issue_coverage"] < GATE_MIN_ISSUE_COVERAGE:
        return False, f"issue coverage {conf_parts['issue_coverage']} (< {GATE_MIN_ISSUE_COVERAGE})"
    if stats.get("ratio", 0) < 0.6:
        return False, f"only {stats.get('ratio')} of the memo's legal statements carry a finding"
    if severity == "fatal" and not revised:
        return False, "the adversary's fatal attack was not answered"
    return True, "ok"


def save_ledger(question, docket_id, payload):
    try:
        os.makedirs(LEDGERS, exist_ok=True)
        import hashlib
        key = hashlib.sha1((str(docket_id or "") + "|" + _ws(question)[:400]).encode()).hexdigest()[:16]
        path = os.path.join(LEDGERS, key + ".json")
        with open(path, "w") as f:
            json.dump(payload, f, default=str)
        return path
    except Exception:
        return None


def _other_models(primary):
    try:
        import local_llm
        return [m for m in local_llm.MODELS if primary and primary not in m] or None
    except Exception:
        return None


# ── who holds the pen ────────────────────────────────────────────────────────────────────────────
# Research, extraction and verification are narrow tasks and stay local. WRITING the memo is the one
# open-ended step, and the operator's direction (2026-09-29) is to give it to whichever writer
# proves better: the strongest local model, or Sonnet working only from the verified ledger.
# local_benchmark.py measures both on the same evidence with the same commission and records the
# winner in pen_policy.json; `auto` follows that record, and with no record prefers a local model
# at or above the debate floor and falls back to the frontier writer when none fits.
PEN = os.environ.get("ORCH_LOCAL_PEN", "auto").strip().lower()          # auto | local | sonnet
PEN_POLICY = os.path.join(HOME, "consilium", "pen_policy.json")
PENS = ("local", "sonnet")


def pen_policy():
    try:
        with open(PEN_POLICY) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def choose_pen(model_b):
    if PEN in PENS:
        return PEN
    recorded = pen_policy().get("pen")
    if recorded == "sonnet":
        try:
            import frontier
            if frontier.can_think(min_tokens=20000, min_tier="codex"):
                return "sonnet"
        except Exception:
            pass
        return "local"
    if recorded == "local" and model_b >= MIN_DEBATE_B:
        return "local"
    if model_b >= MIN_DEBATE_B:
        return "local"
    try:
        import frontier
        if frontier.can_think(min_tokens=20000, min_tier="codex"):
            return "sonnet"
    except Exception:
        pass
    return "local"


def _pen_ask(state, pen, prompt, schema, *, tag, max_tokens, temperature):
    """One writing call. -> (json, model_name). A frontier pen that fails falls back to the local one."""
    if pen == "sonnet":
        try:
            import frontier
            r = frontier.complete(prompt, system=BASE, model=frontier.SONNET, json_schema=schema, timeout=900,
                                  tag="local.pen." + tag.split(".")[-1], min_tier="codex")
            j = r.get("json")
            if isinstance(j, dict) and not r.get("error"):
                state["pen_calls"] = state.get("pen_calls", 0) + 1
                state["pen_tokens"] = state.get("pen_tokens", 0) + int(r.get("tokens_weighted") or
                                                                       (r.get("tokens_in") or 0) + 5 * (r.get("tokens_out") or 0))
                return j, str(r.get("model") or "frontier")
        except Exception:
            pass
    j, r = state["calls"].ask(prompt, schema, tag=tag, max_tokens=max_tokens, temperature=temperature)
    return j, str((r or {}).get("model") or "local")


# ── prepare: everything up to the evidence and the settled seats ─────────────────────────────────
def prepare(question, context="", vertical=None, priority="medium", panel=None, docket_id=None, *,
            chat=None, fetcher=None, searcher=None):
    """-> state. state["abstain"] is set when the evidence cannot support a memo at all."""
    t0 = time.time()
    import authority_search
    import playbooks
    injected = chat is not None
    if chat is None:
        import local_llm
        chat = local_llm.chat
    if fetcher is None:
        import local_research
        fetcher = local_research.fetch
    searcher = searcher or authority_search.search
    panel = list(panel or [])
    calls = Calls(chat, prefer=None if injected else strong_models(),
                  cloud_fallback=(not injected) and CLOUD_FALLBACK)
    meta = {"engine": "local_tribunal", "version": 3, "phases": {}}
    state = {"question": question, "context": context, "vertical": vertical, "priority": priority,
             "docket_id": docket_id, "calls": calls, "meta": meta, "t0": t0, "abstain": None, "dossier": None}

    def stop(reason, dossier=None):
        state.update(abstain=reason, dossier=dossier)
        return state

    if not ENABLED:
        return stop("local tribunal disabled")
    if len(panel) < 2:
        return stop("fewer than two seats")
    playbook = playbooks.block(vertical, question)
    exemplar = playbooks.exemplar(vertical, question)
    meta["playbook"] = bool(playbook)
    meta["exemplar"] = (exemplar or {}).get("id")
    try:
        import escalation
        mem = escalation.memory(vertical, question)
    except Exception:
        mem = {"block": "", "urls": [], "holdings": []}
    if mem.get("block"):
        playbook = (playbook + "\n\n" + mem["block"]).strip()
    meta["firm_memory"] = {"holdings": len(mem.get("holdings") or []), "corrections": len(mem.get("corrections") or [])}

    plan, r = calls.ask(
        f"QUESTION: {question[:1500]}\nCONTEXT: {(context or '')[:800]}\nVERTICAL: {vertical}\n\n"
        + (f"PLAYBOOK (how the senior tribunal approaches this area):\n{playbook}\n\n" if playbook else "")
        + "Plan the research.\n"
        " premise_ok / premise_problem: does the question misstate the law, name the wrong regulator, or cite a "
        "provision for something it does not say? Questions often attach \"AI\" to rules that do not care how "
        "something was made. If so say what is wrong and restate the real question; otherwise restate it plainly.\n"
        " jurisdictions: the ones that actually govern.\n"
        " issues: 3 to 5 separate legal issues that must each be answered.\n"
        " authorities: precise citations you would open (e.g. \"31 CFR 1010.100\", \"15 U.S.C. 45\").\n"
        " searches: 3 to 6 searches. backend is `ecfr` (federal regulations), `fr` (Federal Register rules and "
        "notices) or `caselaw`. Queries are short noun phrases a statute would actually use.",
        PLAN_SCHEMA, tag="local.plan", max_tokens=1100, temperature=0.1)
    if not plan or not plan.get("issues"):
        return stop(f"planning failed: {(r or {}).get('error') or 'no issues returned'}"[:200])
    plan["issues"] = [_ws(i)[:300] for i in plan["issues"] if _ws(i)][:5]
    plan["_holding_urls"] = mem.get("urls") or []
    model_b = size_b(calls.models[0] if calls.models else "")
    meta["model_b"] = model_b
    meta["premise_ok"] = bool(plan.get("premise_ok", True))

    d = research(question, context, vertical, plan, fetcher=fetcher, searcher=searcher)
    hop = follow_references(d, fetcher=fetcher) if d["passages"] else 0
    meta["phases"]["research"] = {"sources": len(d["sources"]), "passages": len(d["passages"]), "hop_sources": hop,
                                  "queries": d["queries"][:8], "unresolved": len(d["unresolved"]), "leads": len(d["leads"])}
    if len(d["passages"]) < 3:
        return stop(f"research found {len(d['sources'])} sources and {len(d['passages'])} relevant passages", d)

    findings = extract(calls, question, d, [])
    by_model = len(findings)
    backfilled = backfill(d, findings, question)
    meta["phases"]["extract"] = {"findings": len(findings), "by_model": by_model, "backfilled": backfilled}
    state.update(plan=plan, d=d, findings=findings, playbook=playbook, exemplar=exemplar, model_b=model_b)
    if len(findings) < 3:
        save_ledger(question, docket_id, {"question": question, "plan": plan, "findings": findings,
                                          "sources": d["sources"], "meta": meta})
        return stop(f"only {len(findings)} verified findings could be extracted", d)

    seats = seat_round(calls, question, plan, panel, findings, playbook, exemplar)
    if len(seats) < 2:
        return stop("fewer than two seats produced an answer", d)
    verifier = _other_models(calls.models[0] if calls.models else None) if not injected else None
    verify_claims(calls, seats, findings, verifier_models=verifier)

    missing = []
    for s in seats:
        for m in s["missing"]:
            if m and m not in missing:
                missing.append(m)
    if missing:
        before = {p["id"] for p in d["passages"]}
        d = research(question, context, vertical, plan, fetcher=fetcher, searcher=searcher,
                     extra_queries=[{"backend": "", "query": m[:140]} for m in missing[:4]], have=d)
        new = {p["id"] for p in d["passages"]} - before
        n0 = len(findings)
        if new:
            extract(calls, question, d, findings, only_passages=new)
            if len(findings) > n0:
                fresh = seat_round(calls, question, plan, [s["_expert"] for s in seats], findings, playbook, exemplar)
                if len(fresh) >= 2:
                    verify_claims(calls, fresh, findings, verifier_models=verifier)
                    if sum(len(grounded(s)) for s in fresh) >= sum(len(grounded(s)) for s in seats):
                        seats = fresh
        meta["phases"]["gaps"] = {"asked": len(missing), "new_passages": len(new), "new_findings": len(findings) - n0}
    challenge_round(calls, question, seats)
    state.update(d=d, findings=findings, seats=seats, bouts=mechanical_bouts(seats), verifier=verifier)
    return state


# ── write: chair, adversary, revision, grounding, confidence, gate ───────────────────────────────
def write(state, pen=None, force=False):
    """-> the result dict. May be called more than once on one state, with different pens."""
    calls, meta = state["calls"], json.loads(json.dumps(state["meta"], default=str))
    question, plan, findings, seats = state["question"], state["plan"], state["findings"], state["seats"]
    playbook, exemplar, verifier = state["playbook"], state["exemplar"], state.get("verifier")
    d = {**state["d"], "sources": [dict(s) for s in state["d"]["sources"]]}
    pen = pen or choose_pen(state.get("model_b") or 0)
    pen_state = {"calls": calls}
    pen_models = []

    def done(abstain, reason, j=None, dossier=None, **extra):
        meta.update({"calls": calls.n, "calls_failed": calls.failed, "calls_by": dict(calls.by), "models": list(calls.models),
                     "cloud_steps": calls.cloud_steps,
                     "model": (pen_models[0] if pen_models else (calls.models[0] if calls.models else "local")),
                     "pen": pen, "pen_models": pen_models, "pen_calls": pen_state.get("pen_calls", 0),
                     "pen_tokens": pen_state.get("pen_tokens", 0),
                     "latency_s": round(time.time() - state["t0"], 1), "abstain": abstain, "reason": reason, **extra})
        return {"abstain": abstain, "reason": reason, "j": j, "dossier": dossier, "meta": meta}

    valid = {f["id"] for f in findings}
    drafts = []
    for temp in ((0.2,) if pen == "sonnet" else (0.2, 0.5)):
        cj, who = _pen_ask(pen_state, pen, _chair_prompt(question, plan, seats, findings, playbook, exemplar),
                           CHAIR_SCHEMA, tag="local.chair", max_tokens=3200, temperature=temp)
        if cj and len(_s(cj.get("memo"))) >= 300:
            if who not in pen_models:
                pen_models.append(who)
            st = grounding_stats(_s(cj.get("memo")), valid)
            drafts.append((st["ratio"] * 2 + min(1.0, len(st["findings_used"]) / 10.0), cj))
    if not drafts:
        save_ledger(question, state["docket_id"], {"question": question, "plan": plan, "findings": findings,
                                                   "sources": d["sources"], "meta": meta})
        return done(True, "the chair could not produce a memo", dossier=d)
    drafts.sort(key=lambda x: -x[0])
    chair = drafts[0][1]

    attack, ar = calls.ask(
        "You are opposing counsel, the examiner, and the enforcement division at once. Break the memo below using the "
        "evidence ledger and your judgement. Find the fact pattern where it fails, the authority it missed or read too "
        "generously, the step it assumed. severity is one of fatal | material | marginal | none. If it holds, say so.\n\n"
        f"QUESTION: {question[:900]}\nVERDICT: {_s(chair.get('verdict'))[:700]}\nMEMO: {_s(chair.get('memo'))[:5000]}\n\n"
        f"EVIDENCE LEDGER:\n{render_ledger(findings, 5000)}",
        ATTACK_SCHEMA, tag="local.adversary", max_tokens=1000, temperature=0.3, models=verifier)
    if not attack and verifier:
        attack, ar = calls.ask(
            f"Attack this memo. severity is fatal | material | marginal | none.\nQUESTION: {question[:900]}\n"
            f"VERDICT: {_s(chair.get('verdict'))[:700]}\nMEMO: {_s(chair.get('memo'))[:5000]}",
            ATTACK_SCHEMA, tag="local.adversary", max_tokens=1000, temperature=0.3)
    severity = norm_severity(attack.get("severity")) if attack else "none"
    revised = False
    if severity in ("fatal", "material"):
        rj, who = _pen_ask(pen_state, pen, _chair_prompt(question, plan, seats, findings, playbook, exemplar,
                                                         attack=attack, previous=chair),
                           CHAIR_SCHEMA, tag="local.revise", max_tokens=3200, temperature=0.2)
        if rj and len(_s(rj.get("memo"))) >= 300:
            chair, revised = rj, True

    chair, gp = ground_pass(calls, chair, findings, verifier_models=verifier)
    meta["phases"]["ground_pass"] = gp
    memo, stats = finalize(chair, findings)
    # the writer's size decides the memo's ceiling; a frontier pen is not capped by the local floor
    writer_b = 100.0 if (pen == "sonnet" and pen_state.get("pen_calls")) else (size_b(pen_models[0]) if pen_models else (state.get("model_b") or 0))
    conf, parts = confidence(seats, findings, stats, plan["issues"], severity, revised, writer_b, memo["unsettled"])
    memo["confidence"] = conf
    mint, why = gate(seats, findings, stats, parts, severity, revised, writer_b, force=force)

    used = {c["finding"] for c in memo["citations"]}
    for s in d["sources"]:
        fs = [f for f in findings if f["url"] == s["url"] and f["id"] in used]
        if fs:
            s.update(quote=fs[0]["quote"], proposition=fs[0]["says"], verified=True)
    j = {"seats": [{"seat": s["seat"], "r1_position": s["answer"], "r1_analysis": " | ".join(c["claim"] for c in grounded(s)[:4])[:900],
                    "r1_probability": s["probability"], "steelman_of": s.get("steelman_of", ""), "steelman": s.get("steelman", ""),
                    "moved": bool(s.get("moved")), "r3_outcome": s.get("outcome", "hold"),
                    "r3_position": s.get("final_answer") or s["answer"],
                    "r3_grounds": "; ".join(f"{c['claim'][:140]} [{','.join(c['findings'])}]" for c in grounded(s)[:3])[:900],
                    "r3_probability": s.get("final_probability", s["probability"]),
                    "conceded": s.get("steelman", "") if s.get("outcome") in ("concede", "partial") else "",
                    "claims_total": len(s["claims"]), "claims_verified": len(grounded(s))} for s in seats],
         "bouts": state["bouts"],
         "red_team": {"breaks": bool(attack.get("breaks")) if attack else False, "attack": _ws(attack.get("attack"))[:2000] if attack else "",
                      "failing_fact_pattern": _ws(attack.get("failing_fact_pattern"))[:800] if attack else "",
                      "missed_authority": _ws(attack.get("missed_authority"))[:800] if attack else "",
                      "severity": severity, "durable_because": ""},
         "memo": memo,
         "research": {"queries": d["queries"][:10], "sources_opened": [s["url"] for s in d["sources"]]},
         "adversary_done": {"ran": bool(attack), "model": (ar or {}).get("model"), "severity": severity,
                            "revised": revised, "local": True, "attack": _ws(attack.get("attack"))[:1500] if attack else ""}}
    dossier = {"issues": plan["issues"], "sources": d["sources"], "unresolved": d["unresolved"][:10],
               "queries": d["queries"][:10], "_pages": d["_pages"], "leads": d["leads"][:10]}
    path = save_ledger(question, state["docket_id"], {
        "question": question, "vertical": state["vertical"], "plan": plan, "findings": findings, "sources": d["sources"],
        "seats": [{k: v for k, v in s.items() if k != "_expert"} for s in seats], "memo": memo, "stats": stats,
        "confidence_parts": parts, "pen": pen, "gate": {"mint": mint, "reason": why}})
    return done(not mint, why, j=j, dossier=dossier, confidence=conf, confidence_parts=parts, grounding=stats,
                findings=len(findings), citations=len(memo["citations"]), options=len(memo["options"]),
                adversary_severity=severity, revised=revised, ledger=path, phases=meta["phases"])


def run(question, context="", vertical=None, priority="medium", panel=None, docket_id=None, *,
        chat=None, fetcher=None, searcher=None, force=False, pen=None):
    """-> {"abstain", "reason", "j", "dossier", "meta"}. j has the single-call tournament shape."""
    state = prepare(question, context, vertical, priority, panel, docket_id, chat=chat, fetcher=fetcher, searcher=searcher)
    if state.get("abstain"):
        calls, meta = state["calls"], state["meta"]
        meta.update({"calls": calls.n, "calls_failed": calls.failed, "calls_by": calls.by, "models": calls.models,
                     "model": (calls.models[0] if calls.models else "local"),
                     "latency_s": round(time.time() - state["t0"], 1), "abstain": True, "reason": state["abstain"]})
        return {"abstain": True, "reason": state["abstain"], "j": None, "dossier": state.get("dossier"), "meta": meta}
    if pen is None and chat is not None:
        pen = "local"                       # an injected model is the writer
    return write(state, pen=pen, force=force)


if __name__ == "__main__":
    import consilium_v2
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    q = args[0] if args else ("Is a dual-currency sweepstakes casino that redeems sweeps coins for cash prizes a money "
                              "transmitter requiring FinCEN MSB registration?")
    v = args[1] if len(args) > 1 else "finserv"
    pen = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--pen=")), None)
    out = run(q, context="PRIORITY: medium", vertical=v, panel=consilium_v2._seat_pool(v, SEATS),
              force="--force" in sys.argv, pen=pen)
    print(json.dumps(out["meta"], indent=1, default=str))
    if out.get("j"):
        print(json.dumps(out["j"]["memo"], indent=1)[:6000])

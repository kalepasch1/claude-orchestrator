#!/usr/bin/env python3
"""playbooks.py — what the frontier tier learned, written down once, used by the local tier forever.

THE IDEA. A 27B model does not lack the ability to follow a good analysis; it lacks the knowledge of
which analysis to run. Asked about token rewards it does not think to check 31 CFR 1010.100(ff)(5),
the agent-of-the-payee line, and the prepaid-access definition — a frontier model does. That
knowledge is already in this repo: every frontier tournament left a verified memo and a list of
authorities it opened. A playbook DISTILS those into, per vertical:

    topics              the recurring issue clusters
    always_check        the questions a careful lawyer asks every time that topic appears
    governing_authorities  the authorities that actually decide it, with the URLs that were opened
    false_premises      the mistakes questions in this area keep making
    decision_rules      how the tribunal decided when the text ran out

One frontier call per vertical, re-run when enough new frontier cards exist. After that the local
tier reads the playbook at zero cost on every question: in planning (what to look for), in research
(which authorities to open first), and at the chair (which decision rule applies).

EXEMPLARS are the second half: the nearest frontier memo to the question at hand, shown to the local
chair as the standard of structure and rigour to meet — not as a source. Conclusions are never
copied from an exemplar; only a finding in the evidence ledger can support a claim.
"""
from __future__ import annotations
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
DIR = os.path.join(HOME, "consilium", "playbooks")
MIN_CARDS = int(os.environ.get("ORCH_PLAYBOOK_MIN_CARDS", "3"))
REBUILD_AFTER_NEW_CARDS = int(os.environ.get("ORCH_PLAYBOOK_REBUILD_AFTER", "6"))

SCHEMA = {"type": "object", "properties": {
    "topics": {"type": "array", "items": {"type": "object", "properties": {
        "topic": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "always_check": {"type": "array", "items": {"type": "string"}},
        "governing_authorities": {"type": "array", "items": {"type": "object", "properties": {
            "cite": {"type": "string"}, "url": {"type": "string"}, "decides": {"type": "string"}},
            "required": ["cite", "url", "decides"]}},
        "false_premises": {"type": "array", "items": {"type": "string"}},
        "decision_rules": {"type": "array", "items": {"type": "string"}}},
        "required": ["topic", "keywords", "always_check", "governing_authorities", "false_premises",
                     "decision_rules"]}},
    "reasoning_moves": {"type": "array", "items": {"type": "string"}}},
    "required": ["topics", "reasoning_moves"]}

SYSTEM = """You are writing a PLAYBOOK for junior analysts from the finished work of a senior tribunal. Below are
memos the tribunal wrote in one practice area, each with the authorities it actually opened. Distil them
into reusable guidance. Do not restate the memos.

 topics                 6-12 recurring issue clusters in this practice area
 keywords               8-15 words or short phrases that signal the topic in a question
 always_check           the questions a careful lawyer asks EVERY time this topic appears, in order
 governing_authorities  the authorities that decide the topic. Use ONLY citations and URLs that appear in
                        the memos' authority lists below; copy each URL exactly. Say what it decides.
 false_premises         mistakes that questions in this area keep making (wrong regulator, a rule that
                        does not care about the technology used, a provision that does not say what is
                        claimed)
 decision_rules         how to decide when the text runs out, as the tribunal did
 reasoning_moves        8-15 general habits visible across the memos (separate each regime's trigger;
                        state what flips the answer; do not infer authority from a heading; ...)

Be specific and short. Return ONLY the JSON object."""


def _s(v):
    return v if isinstance(v, str) else ("" if v is None else json.dumps(v, ensure_ascii=False))


def _terms(text):
    import authority_search
    return authority_search.terms(text, limit=40)


def path(vertical):
    return os.path.join(DIR, re.sub(r"[^a-z0-9_]+", "_", (vertical or "general").lower()) + ".json")


def load(vertical):
    try:
        with open(path(vertical)) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _frontier_cards(vertical=None, limit=60):
    import db
    p = {"select": "id,vertical,question,verdict,position,citations,flips_if,process,publication_state,minted_at",
         "status": "eq.fresh", "publication_state": "in.(attorney_review,published)",
         "order": "minted_at.desc", "limit": str(limit)}
    if vertical:
        p["vertical"] = f"eq.{vertical}"
    out = []
    for c in db.select("verdict_cards", p) or []:
        try:
            proc = json.loads(c.get("process") or "{}")
        except Exception:
            proc = {}
        if str(proc.get("model") or "").startswith("claude"):
            out.append(c)
    return out


def _cites(card, verified_only=True):
    try:
        cs = json.loads(card.get("citations") or "[]")
    except Exception:
        cs = []
    return [{"cite": _s(c.get("source"))[:140], "url": _s(c.get("url"))} for c in cs
            if isinstance(c, dict) and c.get("url") and (c.get("verified") or not verified_only)]


def build(vertical, force=False):
    """One frontier call. Returns a summary dict; writes <HOME>/consilium/playbooks/<vertical>.json."""
    import frontier
    cards = _frontier_cards(vertical)
    have = load(vertical)
    if len(cards) < MIN_CARDS:
        return {"vertical": vertical, "built": False, "reason": f"only {len(cards)} frontier cards"}
    if have and not force and len(cards) - int(have.get("cards_used") or 0) < REBUILD_AFTER_NEW_CARDS:
        return {"vertical": vertical, "built": False, "reason": "current"}
    if not frontier.can_think(min_tokens=60000, min_tier="codex"):
        return {"vertical": vertical, "built": False, "reason": "frontier unavailable"}
    blocks, allowed = [], {}
    for c in cards[:14]:
        cs = _cites(c)[:14]
        for x in cs:
            allowed[x["url"]] = x["cite"]
        blocks.append(f"### QUESTION: {_s(c.get('question'))[:400]}\nVERDICT: {_s(c.get('verdict'))[:700]}\n"
                      f"REASONING: {_s(c.get('position'))[:2200]}\nFLIPS IF: {_s(c.get('flips_if'))[:400]}\n"
                      f"AUTHORITIES OPENED: {json.dumps(cs)[:2200]}")
    r = frontier.complete(f"PRACTICE AREA: {vertical}\nTODAY: {datetime.date.today().isoformat()}\n\n" + "\n\n".join(blocks),
                          system=SYSTEM, need=8, json_schema=SCHEMA, timeout=900, tag="playbook.build", min_tier="codex")
    j = r.get("json")
    if r.get("error") or not isinstance(j, dict) or not j.get("topics"):
        return {"vertical": vertical, "built": False, "reason": (r.get("error") or "malformed output")[:200]}
    dropped = 0
    for t in j["topics"]:
        kept = []
        for a in t.get("governing_authorities") or []:
            # Only authorities the tribunal actually opened may enter a playbook.
            if isinstance(a, dict) and a.get("url") in allowed:
                kept.append(a)
            else:
                dropped += 1
        t["governing_authorities"] = kept
    j.update({"vertical": vertical, "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "cards_used": len(cards), "model": r.get("model"),
              "exemplars": [{"id": c["id"], "question": _s(c.get("question"))[:600], "verdict": _s(c.get("verdict"))[:900],
                             "excerpt": _s(c.get("position"))[:2200]} for c in cards[:20]]})
    os.makedirs(DIR, exist_ok=True)
    tmp = path(vertical) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(j, f, indent=1)
    os.replace(tmp, path(vertical))
    return {"vertical": vertical, "built": True, "topics": len(j["topics"]), "authorities_dropped": dropped,
            "cards_used": len(cards), "tokens": [r.get("tokens_in"), r.get("tokens_out")]}


def relevant(vertical, question, k=3):
    """The k topics whose keywords overlap the question most."""
    pb = load(vertical)
    want = set(_terms(question))
    scored = []
    for t in pb.get("topics") or []:
        kws = " ".join(t.get("keywords") or []) + " " + _s(t.get("topic"))
        hit = len(want & set(_terms(kws)))
        if hit:
            scored.append((hit, t))
    scored.sort(key=lambda x: -x[0])
    return [t for _, t in scored[:k]], pb


def block(vertical, question, max_chars=3200):
    """Playbook text for a prompt. Empty string when no playbook exists."""
    topics, pb = relevant(vertical, question)
    if not pb:
        return ""
    lines = []
    for t in topics:
        lines.append(f"TOPIC: {t.get('topic')}")
        lines += [f"  always check: {x}" for x in (t.get("always_check") or [])[:6]]
        lines += [f"  authority: {a.get('cite')} — decides {a.get('decides')} <{a.get('url')}>"
                  for a in (t.get("governing_authorities") or [])[:6]]
        lines += [f"  common false premise: {x}" for x in (t.get("false_premises") or [])[:4]]
        lines += [f"  decision rule: {x}" for x in (t.get("decision_rules") or [])[:4]]
    moves = pb.get("reasoning_moves") or []
    if moves:
        lines.append("HABITS: " + " | ".join(moves[:10]))
    return "\n".join(lines)[:max_chars]


def authorities(vertical, question):
    """[{cite, url}] from the relevant topics — opened first by local research."""
    topics, _ = relevant(vertical, question)
    out, seen = [], set()
    for t in topics:
        for a in t.get("governing_authorities") or []:
            if a.get("url") and a["url"] not in seen:
                seen.add(a["url"])
                out.append({"cite": a.get("cite"), "url": a["url"], "decides": a.get("decides")})
    return out[:10]


def exemplar(vertical, question):
    """Nearest frontier memo by term overlap, or None. Shown as a standard of rigour, never as a source."""
    pb = load(vertical)
    want = set(_terms(question))
    best, score = None, 0
    for e in pb.get("exemplars") or []:
        s = len(want & set(_terms(e.get("question") or "")))
        if s > score:
            best, score = e, s
    return best if score >= 3 else None


def build_all(force=False):
    import db
    verts = sorted({c.get("vertical") for c in _frontier_cards(None, limit=200) if c.get("vertical")})
    return [build(v, force=force) for v in verts]


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        print(json.dumps(build_all(force="--force" in sys.argv), indent=1))
    elif len(sys.argv) > 2 and sys.argv[1] == "show":
        print(block(sys.argv[2], " ".join(sys.argv[3:]) or "money transmission tokens rewards"))
    else:
        print(json.dumps({os.path.basename(p): (load(os.path.basename(p)[:-5]).get("built_at"))
                          for p in (os.listdir(DIR) if os.path.isdir(DIR) else [])}, indent=1))

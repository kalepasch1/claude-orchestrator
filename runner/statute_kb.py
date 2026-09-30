#!/usr/bin/env python3
"""statute_kb.py — each jurisdiction's statutory definitions, verbatim, in one table (statute_definitions).

WHY (2026-09-29, operator-approved). Doctrine-selector questions are answered first by the jurisdiction's own
statute: its definition of gambling (and so its chance/skill standard), of a lottery, of a regulated game
promotion, of money transmission. The question-family pass kept re-finding those sections by case-law search
and web research and missed them where free sources had none. Held once, a cell becomes a lookup.

FILLED FOR FREE, NOTHING PARAPHRASED
    corpus        jurisdiction-scoped full-text search of the corpus, statutes and regulations only;
                  a passage is kept when it carries the topic's own vocabulary
    web_research  official statute pages the family pass already adopted through its capped,
                  fetch-verified web research (family_matrix.web_fill calls record())
Each row keeps the source's exact text, its URL and a hash of the text.

COVERAGE. `python3 statute_kb.py coverage` lists which jurisdictions have nothing per topic: the corpus
team's ingestion list.
"""
from __future__ import annotations
import datetime
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common_utils
import db

_s = common_utils.safe_string_coerce

TOPICS = {
    # topic: (search query, words a passage must carry -- stems, any one)
    "gambling": ("gambling chance consideration prize", ("gambl", "wager", "bet ")),
    "lottery": ("lottery chance consideration prize", ("lotter",)),
    "sweepstakes": ("game promotion sweepstakes registration bond", ("sweepstake", "game promotion", "promotional game")),
    "money_transmission": ("money transmission definition", ("money transmi", "transmission of money")),
    "skill_contest": ("contest skill prize entry fee", ("skill",)),
}
DOC_TYPES = ("statute", "regulation")
PER_RUN = int(os.environ.get("ORCH_STATUTE_KB_PER_RUN", "60"))        # jurisdiction-topic pairs per run
REFRESH_DAYS = int(os.environ.get("ORCH_STATUTE_KB_REFRESH_DAYS", "30"))


def jurisdictions():
    import authority_search as asrch
    return [f"US-{c}" for c, _n, _ids in asrch.STATES]


def _codes(jur):
    j = _s(jur).upper()
    return [j, j[3:]] if j.startswith("US-") else [j]


def sha(text):
    return hashlib.sha256(re.sub(r"\s+", " ", _s(text)).strip().encode()).hexdigest()[:32]


def record(jurisdiction, topic, citation, url, text, source="corpus", heading=None, doc_id=None, insert=None):
    """Upsert one verbatim statute passage. -> True when stored."""
    if topic not in TOPICS or not _s(url).startswith("http") or len(_s(text)) < 80:
        return False
    row = {"jurisdiction": _s(jurisdiction).upper(), "topic": topic, "citation": _s(citation)[:300] or _s(url)[:300],
           "heading": _s(heading)[:300] or None, "url": _s(url)[:1000], "text": _s(text)[:20000],
           "text_sha": sha(text), "source": source, "doc_id": _s(doc_id) or None,
           "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        (insert or db.insert)("statute_definitions", row, upsert=True)
        return True
    except Exception:
        return False


def lookup(jurisdiction, topic, limit=4, select=None):
    """Verbatim passages on file for a jurisdiction and topic, newest first."""
    rows = (select or db.select)("statute_definitions", {
        "select": "jurisdiction,topic,citation,heading,url,text,source,fetched_at",
        "jurisdiction": f"in.({','.join(_codes(jurisdiction))})", "topic": f"eq.{topic}",
        "order": "fetched_at.desc", "limit": str(limit)}) or []
    return rows


def _on_file(select=None):
    rows = (select or db.select)("statute_definitions", {"select": "jurisdiction,topic,fetched_at", "limit": "20000"}) or []
    seen = {}
    for r in rows:
        k = (r.get("jurisdiction"), r.get("topic"))
        seen[k] = max(seen.get(k, ""), _s(r.get("fetched_at")))
    return seen


def fill_from_corpus(limit=PER_RUN, search=None, insert=None, select=None):
    """Copy statute passages from the corpus for pairs with nothing recent on file. -> summary."""
    import corpus_db
    search = search or corpus_db.passages_scoped
    seen = _on_file(select)
    now = datetime.datetime.now(datetime.timezone.utc)
    todo = []
    for jur in jurisdictions():
        for topic in TOPICS:
            last = seen.get((jur, topic))
            if last:
                try:
                    if (now - datetime.datetime.fromisoformat(last.replace("Z", "+00:00"))).days < REFRESH_DAYS:
                        continue
                except Exception:
                    pass
            todo.append((jur, topic))
    out = {"pairs_due": len(todo), "searched": 0, "stored": 0, "outages": 0, "empty": 0}
    for jur, topic in todo[:limit]:
        query, words = TOPICS[topic]
        rows = search(query, _codes(jur), limit=6, doc_types=list(DOC_TYPES))
        out["searched"] += 1
        if rows is None:
            out["outages"] += 1
            continue
        kept = 0
        for r in rows:
            text = _s(r.get("text"))
            low = text.lower()
            if _s(r.get("doc_type")) not in DOC_TYPES or not any(w in low for w in words):
                continue
            if record(jur, topic, _s(r.get("title")) or _s(r.get("heading")), r.get("source_url"), text, "corpus",
                      heading=r.get("heading"), doc_id=r.get("doc_id"), insert=insert):
                kept += 1
        out["stored"] += kept
        out["empty"] += 0 if kept else 1
    print("statute_kb: " + json.dumps(out), flush=True)
    return out


def coverage(select=None):
    seen = _on_file(select)
    jurs = jurisdictions()
    out = {}
    for topic in TOPICS:
        have = [j for j in jurs if (j, topic) in seen]
        out[topic] = {"have": len(have), "of": len(jurs), "missing": [j for j in jurs if (j, topic) not in seen]}
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "coverage":
        print(json.dumps(coverage(), indent=1))
    else:
        import single_instance
        _owned, _deadline = single_instance.guard("statute_kb", interval_s=86400)
        if not _owned:
            print(json.dumps({"skipped": "statute_kb already running"}))
            raise SystemExit(0)
        try:
            fill_from_corpus()
        finally:
            if _deadline is not None:
                _deadline.cancel()

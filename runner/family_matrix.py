#!/usr/bin/env python3
"""family_matrix.py — answer a question FAMILY in one charting pass instead of one tournament per member.

WHY (2026-09-29). The law app asks some questions once per jurisdiction: "which formulation of the
chance/skill test does <state> apply" (47 states) and "how would <tribe> classify a game of this kind
under IGRA" (34 tribes). Those two families were 81 of 4,336 docketable gaps and 78% of their value;
each answer unblocks ~57 propositions. Run as separate matters they cost 81 tournaments, re-research the
same general law 81 times, and can come out mutually inconsistent. Charted together they share one
framework, and each cell costs a slice of one call.

THE PASS
    family       gap questions that differ only in the place or party they name (same template)
    framework    the general law common to every member, researched once per family and kept
    cells        per member, free research only: that jurisdiction's own courts (CourtListener,
                 court-filtered, opinion PDFs opened), tribal-state compacts (BIA), the corpus
                 filtered to the jurisdiction. Exact passages, no model.
    chart        one call per CHUNK members: a choice (from the question's own options when it lists
                 them), a short answer citing passage ids, a status, and verbatim quotes
    verify       every quote is re-found in its passage or dropped. A cell's answer must rest on at
                 least one verified quote from ITS OWN sources; framework passages alone cannot decide
                 a jurisdiction. Otherwise the cell is `open`.
    mint         each settled or contested cell becomes that member's verdict card (so the commission,
                 export and gap write-back handle it unchanged), carrying the family comparison.
                 Open cells go back to the individual route (the firm).

Cost: research is free; the chart is ~one mid-tier call per CHUNK members. The comparison across
jurisdictions — which ones use the most permissive test — comes out as a by-product.

State: <home>/consilium/families/<key>.json (framework, options, per-member status) and
docs/consilium/families/<date>-<slug>.md (the matrix).
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
import db  # noqa: F401  loads runner/.env first, so HOME below is the scheduler's

_s = common_utils.safe_string_coerce

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
STATE_DIR = os.path.join(HOME, "consilium", "families")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "consilium", "families")
ENABLED = os.environ.get("ORCH_FAMILY_MATRIX", "true").lower() not in ("0", "false", "no", "off")
MIN_FAMILY = int(os.environ.get("ORCH_FAMILY_MIN", "3"))
CELLS_PER_PASS = int(os.environ.get("ORCH_FAMILY_CELLS", "12"))
CHUNK = int(os.environ.get("ORCH_FAMILY_CHUNK", "4"))
NEED = int(os.environ.get("ORCH_FAMILY_NEED", "7"))
RETRY_DAYS = int(os.environ.get("ORCH_FAMILY_RETRY_DAYS", "14"))
NO_SOURCE_RETRY_DAYS = int(os.environ.get("ORCH_FAMILY_NO_SOURCE_RETRY_DAYS", "3"))
TRANSIENT_LIMIT = int(os.environ.get("ORCH_FAMILY_TRANSIENT_LIMIT", "3"))
# Web research for members free research could not reach (operator: up to 6 calls a day, 2026-09-29).
WEB_CALLS_PER_DAY = int(os.environ.get("ORCH_FAMILY_WEB_CALLS_PER_DAY", "6"))
WEB_CHUNK = int(os.environ.get("ORCH_FAMILY_WEB_CHUNK", "4"))
PASSAGES_PER_CELL = int(os.environ.get("ORCH_FAMILY_PASSAGES", "4"))
FRAMEWORK_PASSAGES = 6
PASSAGE_CHARS = 850
STATUSES = ("settled", "contested", "open")
# What a cell's answer rests on. Only a direct statement of the test settles a jurisdiction (2026-09-29: the
# commission sent back Florida, settled on an amusement-machine exemption definition, and New York, settled
# on advocacy quoted in a decision later reversed).
BASES = ("statute", "court_holding", "attorney_general", "regulator", "compact", "dicta", "advocacy_or_record",
         "reversed_or_superseded", "narrower_provision", "other_jurisdiction", "none")
DIRECT = {"statute", "court_holding", "attorney_general", "regulator", "compact"}
MAX_REVISIONS = int(os.environ.get("ORCH_FAMILY_MAX_REVISIONS", "2"))

_SKIP = {"What", "Which", "Does", "Do", "Is", "Are", "Can", "May", "Must", "How", "Under", "When", "Where", "Who",
         "Whether", "If", "The", "A", "An", "In", "For", "Has", "Have", "Would", "Should", "Context"}
# A parenthesised word stays inside a name ('Muscogee (Creek) Nation'), or that member drops out of its family.
_RUN = re.compile(r"\b[A-Z][A-Za-z.'-]+(?:\s+(?:of\s+(?:the\s+)?)?\(?[A-Z][A-Za-z.'-]+\)?)*")
_GENERIC = {"tribe", "tribes", "indian", "indians", "nation", "band", "bands", "community", "the", "of", "and",
            "tribal", "reservation", "rancheria", "pueblo", "confederated", "people", "group"}


# ── families ─────────────────────────────────────────────────────────────────────────────────────
def _core(q):
    q = re.split(r"\(Context:", q or "", maxsplit=1)[0]
    q = re.sub(r"^\s*\[[^\]]*\]\s*", "", q)
    return re.sub(r"\s+", " ", q).strip()


def _runs(q):
    """Proper-name runs in the question core, leading question words stripped."""
    out = []
    for m in _RUN.finditer(_core(q)):
        words = m.group(0).split()
        while words and words[0] in _SKIP:
            words = words[1:]
        if words:
            out.append(" ".join(words))
    return out


def template(q):
    core = _core(q)

    def rep(m):
        words = m.group(0).split()
        lead = []
        while words and words[0] in _SKIP:
            lead.append(words.pop(0))
        return m.group(0) if not words else " ".join(lead + ["{X}"])
    t = _RUN.sub(rep, core)
    return re.sub(r"(\{X\}[\s,]*)+", "{X} ", t).strip().lower()


def family_key(tmpl, vertical):
    return hashlib.sha1(f"{vertical}|{tmpl}".encode()).hexdigest()[:12]


def families(rows):
    """Gap docket rows -> [{key, template, vertical, members: [row + _member]}] with >= MIN_FAMILY members,
    highest total value first."""
    groups = {}
    for r in rows:
        t = template(r.get("question"))
        if "{x}" not in t:
            continue
        groups.setdefault((t, r.get("vertical")), []).append(r)
    out = []
    for (t, vert), rs in groups.items():
        if len(rs) < MIN_FAMILY:
            continue
        common = set(_runs(rs[0].get("question")))
        for r in rs[1:]:
            common &= set(_runs(r.get("question")))
        for r in rs:
            own = [x for x in _runs(r.get("question")) if x not in common]
            r["_member"] = own[0] if own else (_s(r.get("_jurisdiction")) or "?")
        out.append({"key": family_key(t, vert), "template": t, "vertical": vert, "members": rs,
                    "question": _core(rs[0].get("question")).replace(rs[0]["_member"], "{X}", 1),
                    "value": round(sum(float(r.get("_value") or 0) for r in rs), 1)})
    out.sort(key=lambda f: -f["value"])
    return out


def items(question):
    """Numbered sub-items the question asks about: '(1) Pick-em against the house: Player selects ... (2) ...'
    -> [{n, name, desc}]. 2026-09-29: the tribal membership question lists every catalogued game type."""
    core = _core(question)
    out = []
    for m in re.finditer(r"\((\d{1,2})\)\s*([^:()]{2,80}):\s*(.+?)(?=\s*\(\d{1,2}\)\s|$)", core):
        out.append({"n": int(m.group(1)), "name": m.group(2).strip(), "desc": m.group(3).strip()[:300]})
    return out if len(out) >= 2 else []


def options(question):
    """'... apply -- predominant purpose (dominant factor), material element, any chance, or X?' -> list."""
    m = re.search(r"(?:--|—|:)\s*([^?]+)\?", _core(question))
    if not m:
        return []
    tail = re.split(r"\s+(?:--|—)\s+and\s+|\s+and does\b", m.group(1))[0]
    parts = [p.strip(" ,.;") for p in re.split(r",\s*(?:or\s+)?|\s+or\s+", tail) if p.strip(" ,.;")]
    parts = [re.sub(r"^(?:the|a|an)\s+", "", p, flags=re.I) for p in parts]
    return parts if 2 <= len(parts) <= 8 and all(len(p) <= 80 for p in parts) else []


# ── family state ─────────────────────────────────────────────────────────────────────────────────
def _state_path(key):
    return os.path.join(STATE_DIR, f"{key}.json")


def load_state(key):
    try:
        with open(_state_path(key)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(key, st):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = _state_path(key) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, default=str)
    os.replace(tmp, _state_path(key))


def _recent(iso, days):
    try:
        t = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return (datetime.datetime.now(datetime.timezone.utc) - t).days < days
    except Exception:
        return False


def todo(fam):
    """Members the pass has not charted recently."""
    st = load_state(fam["key"])
    cells = st.get("cells") or {}
    def due(rec):
        if rec.get("needs_rechart"):
            return True
        days = NO_SOURCE_RETRY_DAYS if rec.get("no_sources") else RETRY_DAYS
        return not _recent(rec.get("at"), days)
    return [r for r in fam["members"] if due(cells.get(str(r["id"])) or {})]


def _review_for(card_id):
    import db
    rows = db.select("publication_reviews", {"select": "id,decision,detail,created_at", "artifact_id": f"eq.{card_id}",
                                             "artifact_type": "eq.verdict_card", "order": "created_at.desc",
                                             "limit": "1"}) or []
    return rows[0] if rows else None


def revisit_all():
    """The commission's verdict comes back to the chart. A family card sent back ('revise'/'reject') gets its
    critique recorded on the cell, its docket row returned to 'stale', and a re-chart on the next pass --
    at most MAX_REVISIONS times per member. -> number of cells reopened."""
    import db
    reopened = 0
    try:
        names = [n for n in os.listdir(STATE_DIR) if n.endswith(".json") and n != "web_calls.json"]
    except OSError:
        return 0
    for name in names:
        key = name[:-5]
        st = load_state(key)
        changed = False
        for did, rec in (st.get("cells") or {}).items():
            if not rec.get("minted") or rec.get("needs_rechart") or int(rec.get("revisions") or 0) >= MAX_REVISIONS:
                continue
            cards = db.select("verdict_cards", {"select": "id", "docket_id": f"eq.{did}", "limit": "1"}) or []
            if not cards:
                continue
            rv = _review_for(cards[0]["id"])
            if not rv or rv.get("decision") not in ("revise", "reject") or rv.get("id") == rec.get("reviewed_by"):
                continue
            d = rv.get("detail") if isinstance(rv.get("detail"), dict) else {}
            rat = d.get("rationales") if isinstance(d.get("rationales"), dict) else {}
            rec.update(critique="; ".join(f"{k}: {v}" for k, v in rat.items() if v)[:1500] or rv.get("decision"),
                       needs_rechart=True, card_id=cards[0]["id"], reviewed_by=rv.get("id"))
            try:
                db.update("legal_docket", {"id": did}, {"status": "stale"})
            except Exception:
                pass
            changed = True
            reopened += 1
        if changed:
            save_state(key, st)
    return reopened


def _flag_rereview(card_id, reason):
    import db
    rv = _review_for(card_id)
    if not rv:
        return
    d = rv.get("detail") if isinstance(rv.get("detail"), dict) else {}
    d = {**d, "requires_rereview": True, "rereview_reason": reason}
    db.update("publication_reviews", {"id": rv["id"]}, {"detail": d})


def next_family(gap_rows):
    for fam in families(gap_rows):
        if todo(fam):
            return fam
    return None


def held_for_family(gap_rows):
    """Ids of gap rows waiting for a family pass (so the individual route does not take them first)."""
    held = set()
    for fam in families(gap_rows):
        held |= {r["id"] for r in todo(fam)}
    return held


# ── research (free) ──────────────────────────────────────────────────────────────────────────────
FRAMEWORK_SEEDS = [
    (re.compile(r"\bigra\b|class i\b|class ii|class iii|tribal|compact", re.I), [
        ("25 U.S.C. § 2703 (IGRA definitions)", "https://www.law.cornell.edu/uscode/text/25/2703"),
        ("25 U.S.C. § 2710 (tribal gaming ordinances; Class III compacts)", "https://www.law.cornell.edu/uscode/text/25/2710"),
        ("25 CFR 502.3 (Class II gaming)", "https://www.law.cornell.edu/cfr/text/25/502.3"),
        ("25 CFR 502.4 (Class III gaming)", "https://www.law.cornell.edu/cfr/text/25/502.4"),
        ("25 CFR 502.8 (electronic or electromechanical facsimile)", "https://www.law.cornell.edu/cfr/text/25/502.8")]),
]


_WEAK = {"formulation", "apply", "applies", "determining", "determine", "whether", "test", "tests", "which", "does",
         "constitutes", "constitute", "kind", "classify", "would", "under", "address", "jurisdiction", "factor",
         "factors", "purpose", "element", "instinct", "predominant", "material", "dominant", "any", "game", "games",
         "play", "delivered", "ordinance", "question", "promotion"}


def anchors(question, k=3):
    """The question's distinctive subject words: every source a cell uses must contain them. Call with the
    family's generic question — a member's name is not a subject word."""
    import authority_search as asrch
    q = question.replace("{X}", " ")
    return [t.lower() for t in asrch.terms(q, limit=30) if t.lower() not in _WEAK and len(t) >= 4][:k]


def case_query(question, opts):
    """Boolean CourtListener query: the subject anchors AND any of the option names as phrases.
    2026-09-29: a bag of words ('formulation chance skill test apply') returned Daubert and custody opinions."""
    a = anchors(question)
    q = " AND ".join(a)
    phrases = []
    for o in opts:
        for part in re.split(r"\s*\(|\)\s*", o):
            part = re.sub(r"\s+test$", "", part.strip(), flags=re.I)
            if len(part.split()) >= 2 and part.lower() not in (p.lower() for p in phrases):
                phrases.append(part)
    if phrases:
        q += " AND (" + " OR ".join(f'"{p}"' for p in phrases[:6]) + ")"
    return q


def _relevant(page, question):
    a = [t.lower().rstrip("s") for t in anchors(question)]
    low = page[:200000].lower()
    return sum(1 for t in a if t[:6] in low) >= max(1, len(a) - 1)


DERIVED_LABELS = {"test-any-chance": "any chance", "test-material-element": "material element",
                  "test-predominant-purpose": "predominant purpose (dominant factor)",
                  "test-gambling-instinct": "gambling instinct test"}


def derived_prior(codes, select=None):
    """Smarter's statute-derived chance/skill memberships for a jurisdiction (cade_derive_family_members):
    [(label, citation)]. A lead and a hint, never evidence -- a state often carries two tests for different
    activities (2026-09-29: Florida, Kansas, Kentucky, Massachusetts)."""
    try:
        if select is None:
            import corpus_db
            select = corpus_db.select
        rows = select("intel_jurisdiction_family_members", {
            "select": "family_id,basis_citation", "jurisdiction_id": f"in.({','.join(codes)})",
            "established_by": "neq.unestablished", "family_id": "like.test-*", "limit": "40"}) or []
    except Exception:
        return []
    out = []
    for r in rows:
        lab, cit = DERIVED_LABELS.get(r.get("family_id")), _s(r.get("basis_citation")).strip()
        if lab and (lab, cit) not in out:
            out.append((lab, cit))
    return out


def section_tokens(citation):
    """'Fla. Stat. § 849.25(1)(a)' -> ['849.25']; 'K.S.A. 21-6403(e)' -> ['21-6403']; full-text search matches these."""
    return list(dict.fromkeys(re.findall(r"\b\d{1,4}[A-Z]?[.\-]\d{1,5}(?:\.\d+)?\b", _s(citation))))[:2]


def kb_topics(fam):
    """statute_definitions topics that answer this family's question."""
    t = fam.get("template") or ""
    out = []
    if re.search(r"chance|skill|gambl", t):
        out += ["gambling", "lottery"]
    if re.search(r"sweepstake|promotion|amoe|free.?entry", t):
        out.append("sweepstakes")
    if re.search(r"money transmi|transmitter|msb", t):
        out.append("money_transmission")
    return out


def _want(question, opts):
    import authority_search as asrch
    extra = []
    for o in opts:
        extra += asrch.terms(o, limit=4)
    return asrch.terms(question, limit=18) + extra


def _phrases(opts):
    out = []
    for o in opts:
        for part in re.split(r"\s*\(|\)\s*", o):
            part = re.sub(r"\s+test$", "", part.strip(), flags=re.I).lower()
            if len(part.split()) >= 2 and part not in out:
                out.append(part)
    return out


def focus(question, opts):
    """What a passage must be about: option phrases (x3), the sub-question's terms (x2), the anchors (x1)."""
    import authority_search as asrch
    sub = re.split(r"\band does\b|\band is\b|\band are\b", _core(question), maxsplit=1)
    extras = [t.lower() for t in asrch.terms(sub[1], limit=6) if t.lower() not in _WEAK] if len(sub) > 1 else []
    return {"phrases": _phrases(opts), "extras": extras, "anchors": [a.lower() for a in anchors(question)]}


def _anchor_hits(low, f):
    return sum(1 for a in f["anchors"] if re.search(r"\b" + re.escape(a) + r"\b", low))


def _score(text, f):
    low = text.lower()
    return (3 * sum(1 for p in f["phrases"] if p in low) + 2 * sum(1 for e in f["extras"] if e in low)
            + _anchor_hits(low, f))


def _slices(page, want, source, k, f=None):
    """Exact windows of the page centred on the family's doctrinal phrases (2026-09-29: generic ranking
    chose passages about Daubert 'factors'; stemmed search matched 'any chance of finding employment').
    A window must carry at least two of the question's subject words as whole words."""
    import authority_search as asrch
    if not f:
        return [{"text": p["text"], "score": p["score"], "authority": source["authority"], "url": source["url"],
                 "origin": source.get("origin")} for p in asrch.passages(page, want, k=k, width=PASSAGE_CHARS)]
    low = page.lower()
    starts = sorted({m.start() for kw in f["phrases"] + f["extras"] for m in re.finditer(re.escape(kw), low)})
    if not starts and f["anchors"]:
        starts = [m.start() for m in re.finditer(r"\b" + re.escape(f["anchors"][0]) + r"\b", low)]
    wins = []
    half = PASSAGE_CHARS // 2
    for i in starts[:500]:
        s, e = max(0, i - half), min(len(page), i + half)
        dot = page.rfind(". ", max(0, s - 160), i)
        s = dot + 2 if dot != -1 else s
        end = page.find(". ", max(i, e - 80), min(len(page), e + 160))
        e = end + 1 if end != -1 else e
        text = page[s:e].strip()
        if len(text) < 80 or asrch.is_chrome(text[:240]):
            continue
        if _anchor_hits(text.lower(), f) < min(2, len(f["anchors"])):
            continue
        wins.append((_score(text, f), s, e, text))
    wins.sort(key=lambda w: (-w[0], w[1]))
    out = []
    for sc, s, e, text in wins:
        # A doctrinal phrase (score >= 4), or every subject word of the question as a whole word: a passage
        # can decide the test without naming it ("whether chance or skill predominates in gambling").
        on_topic = sc >= 4 or (len(f["anchors"]) >= 3 and _anchor_hits(text.lower(), f) == len(f["anchors"]))
        if not on_topic or any(not (e <= ps or s >= pe) for _, ps, pe in [(0, o["_s"], o["_e"]) for o in out]):
            continue
        out.append({"text": text, "score": sc, "authority": source["authority"], "url": source["url"],
                    "origin": source.get("origin"), "_s": s, "_e": e})
        if len(out) >= k:
            break
    for o in out:
        o.pop("_s", None)
        o.pop("_e", None)
    return out


def framework_research(fam, opts, *, fetcher, searcher):
    """General-law passages for the whole family (ids G1..)."""
    import local_research as lr
    import authority_search as asrch
    generic = fam["question"].replace("{X}", "a jurisdiction")
    want = _want(generic, opts)
    f = focus(generic, opts)
    cands = []
    for rx, seeds in FRAMEWORK_SEEDS:
        if rx.search(generic):
            cands += [{"authority": a, "url": u, "origin": "framework_seed"} for a, u in seeds]
    cands += [{"authority": c["authority"], "url": c["url"], "origin": "resolved"} for c in lr.resolve(generic)]
    if opts:
        # Opinions that set out the competing tests side by side, from any court. (Playbook authorities
        # are jurisdiction-specific statutes, not the framework, and are left to the individual route.)
        for c in searcher(case_query(generic, opts), "", 4) or []:
            if c.get("url"):
                cands.append({"authority": c["authority"], "url": c["url"], "origin": "caselaw"})
            elif c.get("page_url") and len(_s(c.get("snippet"))) >= 120:
                cands.append({"authority": c["authority"] + " [search excerpt]", "url": c["page_url"],
                              "origin": "caselaw_excerpt", "_held": _s(c["snippet"])})
    passages, seen = [], set()
    for c in cands:
        if not c.get("url") or c["url"] in seen:
            continue
        seen.add(c["url"])
        page = c.pop("_held", "") or fetcher(c["url"]) or ""
        if len(page) >= 100 and (c["origin"] == "framework_seed" or _relevant(page, generic)):
            if c["origin"] != "caselaw_excerpt":
                c["authority"] = asrch.label_for(c["url"], c["authority"])
            passages += _slices(page, want, c, 2, f)
    passages.sort(key=lambda p: -p["score"])
    out = passages[:FRAMEWORK_PASSAGES]
    for i, p in enumerate(out, 1):
        p["id"] = f"G{i}"
    return out


_COMPACTS = os.path.join(HOME, "consilium", "bia_compacts.json")
BIA = "https://www.bia.gov/as-ia/oig/gaming-compacts"


def compact_index(max_pages=60, ttl_days=7):
    """[{title, url}] for every document in the BIA gaming-compacts listing, cached weekly."""
    try:
        if time.time() - os.path.getmtime(_COMPACTS) < ttl_days * 86400:
            with open(_COMPACTS) as f:
                return json.load(f)
    except (OSError, ValueError):
        pass
    import urllib.parse
    import urllib.request
    import local_research as lr
    docs, seen = [], set()
    for page in range(max_pages):
        try:
            req = urllib.request.Request(f"{BIA}?page={page}", headers={"User-Agent": lr.UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                html_text = r.read().decode("utf-8", "replace")
        except Exception:
            break
        found = 0
        for href, text in re.findall(r'href="([^"]+\.pdf)"[^>]*>([^<]{3,200})<', html_text, re.I):
            url = urllib.parse.urljoin("https://www.bia.gov", href)
            if url in seen:
                continue
            seen.add(url)
            found += 1
            docs.append({"title": re.sub(r"\s+", " ", text).strip(), "url": url})
        if not found:
            break
    if docs:
        os.makedirs(os.path.dirname(_COMPACTS), exist_ok=True)
        with open(_COMPACTS, "w") as f:
            json.dump(docs, f)
    return docs


def _toks(t):
    return {w for w in re.findall(r"[a-z]{3,}", _s(t).lower().replace("_", " ")) if w not in _GENERIC}


def names_entity(page, member):
    """The page is about THIS entity: its full name appears, or all of its words (generic ones included)
    appear within 80 characters. 2026-09-29: 'Oneida Indian Nation' (New York) matched the Oneida Nation
    of Wisconsin's compact on the single distinctive word."""
    low = re.sub(r"\s+", " ", page.lower())
    name = re.sub(r"\s+", " ", member.lower()).strip()
    if name in low:
        return True
    words = [w for w in re.findall(r"[a-z]{3,}", name) if w not in ("the", "tribe", "tribes")]
    if not words:
        return False
    # Only filler words may split a name ('Sault Ste. Marie Tribe of Chippewa', 'Pueblo of Laguna').
    # 2026-09-29: 'the Oneida Nation, a sovereign Indian nation' satisfied a looser any-three-words rule.
    gap = r"\W+(?:(?:of|the|tribe|tribes|band|bands|indians|community|and)\W+){0,3}"
    orders = [words] + ([words[::-1]] if len(words) == 2 else [])
    return any(re.search(r"\b" + gap.join(re.escape(w) for w in ws) + r"\b", low) for ws in orders)


def compacts_for(member, index=None, k=2):
    """The member's most recent compact documents, matched on the distinctive words of its name."""
    want = _toks(member)
    if not want:
        return []
    hits = []
    for d in index if index is not None else compact_index():
        have = _toks(d["title"] + " " + urllib_unquote(d["url"].rsplit("/", 1)[-1]))
        if want <= have:
            m = re.search(r"(19|20)\d{2}[._ ](\d{2})[._ ](\d{2})", urllib_unquote(d["title"] + " " + d["url"]))
            is_compact = bool(re.search(r"compact|amendment", urllib_unquote(d["title"] + d["url"]), re.I))
            hits.append((is_compact, m.group(0).replace("_", ".").replace(" ", ".") if m else "0000", d))
    hits.sort(key=lambda x: (x[0], x[1]), reverse=True)        # compacts and amendments first, newest first
    return [{"authority": f"{member} tribal-state gaming compact ({date if date != '0000' else 'undated'})",
             "url": d["url"], "origin": "bia_compact"} for _c, date, d in hits[:k]]


def urllib_unquote(s):
    import urllib.parse
    return urllib.parse.unquote(s)


def cell_research(row, fam, opts, *, fetcher, searcher, compacts=None):
    """-> (passages, transient). The member's own passages (ids assigned by the caller); `transient` is
    True when a search failed or no candidate page could be opened, so an empty result is an outage,
    not evidence that no authority exists."""
    import authority_search as asrch
    member = row["_member"]
    q = _core(row.get("question"))
    want = _want(q, opts) + asrch.terms(member, limit=4)
    f = focus(fam["question"], opts)
    cands, transient = [], False
    st = asrch.state(row.get("_jurisdiction")) or asrch.state(member)
    if st:
        code, name, courts = st
        found = searcher(case_query(fam["question"], opts), courts, 5)
        transient = found is None
        if found is not None and len([c for c in found if c.get("url")]) < 2:
            # Few fetchable opinions under the phrase query: widen to the subject words alone; the
            # passage scorer still demands the doctrine's own vocabulary.
            wider = searcher(" AND ".join(anchors(fam["question"])), courts, 5)
            found = found + [c for c in (wider or []) if c.get("url") not in {x.get("url") for x in found}]
        for c in found or []:
            if c.get("url"):
                cands.append({"authority": c["authority"], "url": c["url"], "origin": "caselaw"})
            elif c.get("page_url") and len(_s(c.get("snippet"))) >= 120:
                # No fetchable copy of the opinion: the search index's own excerpt of it, cited to the
                # opinion's page. Exact text, but only the excerpt.
                cands.append({"authority": c["authority"] + " [search excerpt]", "url": c["page_url"],
                              "origin": "caselaw_excerpt", "_held": _s(c["snippet"])})
    if re.search(r"tribe|tribal|igra|compact", fam["template"]):
        cands += compacts_for(member, index=compacts)
    # Statutes another pipeline derived this jurisdiction's test from: open them as leads (and keep them).
    prior = []
    if st and re.search(r"chance|skill", fam.get("template") or ""):
        codes2 = [f"US-{st[0]}", st[0]]
        prior = derived_prior(codes2)
        try:
            import corpus_db
            import statute_kb
            seen_tok = set()
            for _lab, cit in prior:
                for tok in section_tokens(cit):
                    if tok in seen_tok:
                        continue
                    seen_tok.add(tok)
                    for p in corpus_db.passages_scoped(tok, codes2, limit=2, doc_types=["statute", "regulation"]) or []:
                        if p.get("source_url") and len(_s(p.get("text"))) >= 100:
                            cands.append({"authority": f"{cit} ({_s(p.get('title') or p.get('heading'))[:80]})",
                                          "url": p["source_url"], "origin": "corpus", "_held": _s(p["text"])})
                            statute_kb.record(f"US-{st[0]}", "gambling", cit, p["source_url"], p["text"], "corpus",
                                              heading=p.get("heading"), doc_id=p.get("doc_id"))
        except Exception:
            pass
    row["_prior"] = prior
    # The jurisdiction's own statutes on file (statute_definitions), verbatim: a lookup, not a search.
    kb_jur = f"US-{st[0]}" if st else _s(row.get("_jurisdiction"))
    if kb_jur:
        try:
            import statute_kb
            for topic in kb_topics(fam):
                for r in statute_kb.lookup(kb_jur, topic, limit=3):
                    cands.append({"authority": (_s(r.get("citation")) or _s(r.get("heading")))[:160] + " (statute)",
                                  "url": r["url"], "origin": "corpus", "_held": _s(r.get("text"))})
        except Exception:
            pass
    # The corpus by full-text search, scoped to the jurisdiction (2026-09-29: the embedding route below is
    # skipped whenever the host cannot run a local embedding model, which is most of the day; this one
    # needs none, and found the Ohio Supreme Court's skill-game decision CourtListener had no PDF for).
    codes = []
    if st:
        codes = [f"US-{st[0]}", st[0]]
    elif _s(row.get("_jurisdiction")):
        codes = [_s(row.get("_jurisdiction"))]
    if codes:
        try:
            import corpus_db
            hits = corpus_db.passages_scoped(" ".join(anchors(fam["question"])), codes, limit=6)
            for p in hits or []:
                if p.get("source_url") and len(_s(p.get("text"))) >= 100:
                    cands.append({"authority": (_s(p.get("title")) or _s(p.get("heading")))[:160] + (
                                      f" ({p.get('doc_type')})" if p.get("doc_type") else ""),
                                  "url": p["source_url"], "origin": "corpus", "_held": _s(p["text"])})
        except Exception:
            pass
    try:
        if os.environ.get("ORCH_CONSILIUM_LOCAL_DISABLED", "").lower() in ("1", "true", "yes", "on"):
            raise RuntimeError("local inference off for this launch")   # embeddings are local inference
        import local_llm
        free = local_llm.free_gb()
        if free is None or free >= 5:
            import corpus_retrieval
            jur = st[0] if st else None
            for p in corpus_retrieval.top_passages(q, k=4, jurisdiction=jur) or []:
                if p.get("source_url") and p.get("text"):
                    cands.append({"authority": (p.get("heading") or p.get("doc_title") or "")[:160],
                                  "url": p["source_url"], "origin": "corpus", "_held": _s(p["text"])})
    except Exception:
        pass
    passages, seen, opened = [], set(), 0
    for c in cands:
        if c["url"] in seen:
            continue
        seen.add(c["url"])
        page = c.pop("_held", "") or fetcher(c["url"]) or ""
        opened += 1 if page else 0
        if c["origin"] == "bia_compact" and not names_entity(page, member):
            continue
        if len(page) >= 100 and (c["origin"] in ("bia_compact", "corpus") or _relevant(page, fam["question"])):
            if c["origin"] != "caselaw_excerpt":
                c["authority"] = asrch.label_for(c["url"], c["authority"])
            passages += _slices(page, want, c, 2, f)
    passages.sort(key=lambda p: -p["score"])
    if cands and not opened:
        transient = True
    return passages[:PASSAGES_PER_CELL], transient


# ── the chart ────────────────────────────────────────────────────────────────────────────────────
CHART_SCHEMA = {"type": "object", "required": ["framework", "cells"], "properties": {
    "framework": {"type": "string"},
    "framework_quotes": {"type": "array", "items": {"type": "object", "required": ["passage", "quote"], "properties": {
        "passage": {"type": "string"}, "quote": {"type": "string"}}}},
    "cells": {"type": "array", "items": {"type": "object",
                                         "required": ["cell", "entity_ok", "choice", "answer", "status", "quotes",
                                                      "flips_if"],
                                         "properties": {
        "cell": {"type": "integer"}, "entity_ok": {"type": "boolean"},
        "basis": {"type": "string", "enum": list(BASES)},
        "choice": {"type": "string"}, "answer": {"type": "string"},
        "status": {"type": "string", "enum": list(STATUSES)},
        "items": {"type": "array", "items": {"type": "object", "required": ["item", "choice", "passages"], "properties": {
            "item": {"type": "integer"}, "choice": {"type": "string"},
            "passages": {"type": "array", "items": {"type": "string"}}}}},
        "quotes": {"type": "array", "items": {"type": "object", "required": ["passage", "quote"], "properties": {
            "passage": {"type": "string"}, "quote": {"type": "string"}}}},
        "flips_if": {"type": "string"}}}}}}

CHART_SYSTEM = """You chart ONE legal question across several jurisdictions at once, for a regulatory
research desk whose output is checked by software:
 - Use ONLY the passages given. Each is an exact excerpt of a source our system opened.
 - A quote must be copied character for character from the passage you name.
 - Framework passages (G..) state general law. A jurisdiction's own passages carry its id (M3.. for
   cell 3). A jurisdiction's choice must rest on at least one of ITS OWN passages; if its passages do
   not decide the question, its status is "open" and its choice "undetermined". Do not fill a cell from
   what you remember about that jurisdiction.
 - "settled": its own passages decide it. "contested": its passages conflict, show a split, or apply
   different tests to different games. "open": they do not decide it.
 - A passage that concerns a different entity than the cell's jurisdiction (another tribe of a similar
   name, another state) must not be used for that cell. Set entity_ok to false when the cell's own
   passages concern a different entity; that cell is then open.
 - If the question depends on facts it does not give (e.g. "a game of this kind" with no game described),
   answer what the jurisdiction's own sources establish (which classes or activities are authorized, which
   devices or channels are covered) and say that the result for a specific game turns on its mechanics.
 - "settled" needs a DIRECT statement of the jurisdiction's test: its statute, a holding of its court, its
   attorney general, its regulator, or (for a tribe) its compact. Set `basis` to what the answer rests on.
   Party argument, legislative record, dicta, a decision later reversed or superseded, a provision narrower
   than the question (one exemption, one device), or another jurisdiction's law is at most "contested".
   Where a passage shows subsequent history (reversed, overruled, amended), say so.
 - In each answer, put the supporting passage ids in brackets after the sentence they support, e.g. [M3.1][G2].
Return ONLY the JSON object."""


def chart_prompt(fam, opts, framework, framework_text, cells, its=None):
    lines = [f"QUESTION (asked once per jurisdiction): {fam['question'].replace('{X}', '<jurisdiction>')}"]
    lines.append("OPTIONS: " + ("; ".join(opts) + " — choose one per jurisdiction, or 'other: <name>' if its own "
                                "passages apply a different test" if opts else "free answer (one short phrase as the choice)"))
    if framework_text:
        lines.append("\nFRAMEWORK ALREADY SETTLED FOR THIS FAMILY (keep consistent with it):\n" + framework_text[:1500])
    lines.append("\nFRAMEWORK PASSAGES (general law):")
    lines += [f"[{p['id']}] {p['authority']}\n{p['text']}" for p in framework]
    for c in cells:
        lines.append(f"\n== CELL {c['n']}: {c['row']['_member']} ==")
        if c["row"].get("_prior"):
            lines.append("DERIVED ELSEWHERE FROM STATUTES (a hint, NOT evidence; different statutes can apply different "
                         "tests to different activities, which makes a cell contested): "
                         + "; ".join(f"{lab} ({cit})" for lab, cit in c["row"]["_prior"][:6]))
        if c.get("critique"):
            lines.append("PRIOR REVIEW OF THIS CELL (the commission sent it back; fix these points or mark it "
                         "contested/open): " + c["critique"][:900])
        if not c["passages"]:
            lines.append("(no passages were found for this jurisdiction)")
        lines += [f"[{p['id']}] {p['authority']}\n{p['text']}" for p in c["passages"]]
    lines.append("\nFor the framework: up to 6 sentences on the general law, citing [G..] ids"
                 + (" (keep it consistent with the settled framework above)" if framework_text else "")
                 + ", and its quotes. For EVERY cell above: choice, a 2-5 sentence answer citing passage ids, status, "
                   "the verbatim quotes you relied on (passage id + quote of at most 40 words), and what would flip it.")
    if its:
        lines.append(f"\nThe question lists {len(its)} numbered game types. For EVERY cell also give `items`: one entry per "
                     "numbered game type with its choice from the options (or 'undetermined') and the ids of that cell's OWN "
                     "passages that support it. A game type its own passages do not reach is 'undetermined' -- do not "
                     "classify a game from general law alone. The cell's `choice` summarises what its sources authorize.")
    return "\n".join(lines)


def _match_choice(choice, opts):
    """Model choice -> the option it names. Exact first, then whole-phrase matches, longest first.
    2026-09-29: a prefix test mapped 'Class III' to 'Class II' on every tribal cell."""
    c = _s(choice).strip()
    if not opts or not c:
        return c[:80] or "undetermined"
    low = re.sub(r"\s+", " ", c.lower())
    for o in opts:
        if low == o.lower():
            return o
    best = None
    for o in opts:
        for form in {o.lower(), o.split("(")[0].strip().lower(), *re.findall(r"\(([^)]+)\)", o.lower()),
                     re.sub(r"^igra\s+", "", o.lower())}:
            form = form.strip()
            if form and re.search(r"(?<![\w])" + re.escape(form) + r"(?![\w])", low):
                if best is None or len(form) > best[0]:
                    best = (len(form), o)
    return best[1] if best else c[:80]


def verify_cell(cell_json, cell, framework, its=None, opts=None):
    """-> {choice, answer, status, quotes (verified), own, flips_if, why, items}"""
    import local_tribunal as lt
    texts = {p["id"]: p for p in framework + cell["passages"]}
    quotes = []
    for q in cell_json.get("quotes") or []:
        pid = _s(q.get("passage")).strip().strip("[]")
        p = texts.get(pid)
        if not p:
            continue
        exact = lt.locate_quote(q.get("quote"), p["text"])
        if exact and not any(x["id"] == pid and x["quote"] == exact for x in quotes):
            quotes.append({"id": pid, "quote": exact, "authority": p["authority"], "url": p["url"]})
    own = [q for q in quotes if q["id"].startswith(f"M{cell['n']}.")]
    status = _s(cell_json.get("status")).lower()
    status = status if status in STATUSES else "open"
    why = ""
    basis = _s(cell_json.get("basis")).lower()
    if cell_json.get("entity_ok") is False:
        status, why = "open", "its sources concern a different entity"
    elif status != "open" and not own:
        status, why = "open", "no verified quote from the jurisdiction's own sources"
    elif status == "settled" and basis not in DIRECT:
        status, why = "contested", f"basis '{basis or 'unstated'}' is not a direct statement of the test"
    own_ids = {q["id"] for q in own}
    got = {}
    for it in cell_json.get("items") or []:
        try:
            got[int(it.get("item"))] = it
        except Exception:
            continue
    checked = []
    for i in its or []:
        it = got.get(i["n"]) or {}
        ids = {_s(p).strip().strip("[]") for p in it.get("passages") or []}
        choice = _match_choice(it.get("choice"), opts or []) if (ids & own_ids and status != "open") else "undetermined"
        if _s(choice).lower().startswith("undetermined"):
            choice = "undetermined"
        checked.append({"n": i["n"], "name": i["name"], "choice": choice})
    return {"basis": basis, "choice": _s(cell_json.get("choice")), "answer": _s(cell_json.get("answer")).strip(), "status": status,
            "quotes": quotes, "own": len(own), "flips_if": _s(cell_json.get("flips_if")).strip()[:600], "why": why,
            "items": checked}


def _numbered(text, quotes):
    """Replace [G1]/[M3.2] with [n] over the verified quotes; drop ids that did not verify."""
    order = {}
    for i, q in enumerate(quotes, 1):
        order.setdefault(q["id"], i)

    def sub(m):
        ids = re.findall(r"[GM]\d+(?:\.\d+)?", m.group(0))
        nums = sorted({order[i] for i in ids if i in order})
        return "".join(f"[{n}]" for n in nums)
    return re.sub(r"(?:\[\s*[GM]\d+(?:\.\d+)?\s*\])+", sub, text)


def confidence_for(v):
    if v["status"] == "settled":
        return 0.72 if v["own"] >= 2 else 0.62
    return 0.55 if v["status"] == "contested" else 0.0


def card_agg(fam, row, v, framework_text, framework_quotes, board, meta):
    quotes = v["quotes"] + [q for q in framework_quotes if all(q["id"] != x["id"] for x in v["quotes"])]
    answer = _numbered(v["answer"], quotes)
    fw = _numbered(framework_text, quotes)
    member = row["_member"]
    others = [f"- {m}: {c} ({s})" for m, c, s in board if m != member][:60]
    choice = _match_choice(v["choice"], meta.get("options") or [])
    by_game = []
    if v.get("items"):
        k = sum(1 for i in v["items"] if i["choice"] != "undetermined")
        by_game = [f"BY GAME TYPE ({k} of {len(v['items'])} classified from this jurisdiction's own sources):"] + \
                  [f"- ({i['n']}) {i['name']}: {i['choice']}" for i in v["items"]] + [""]
    opinion = "\n".join([
        f"{member} — {_core(row.get('question'))}", "",
        f"ANSWER ({v['status']}): {answer}", "",
        *by_game,
        f"GENERAL FRAMEWORK: {fw}" if fw else "", "",
        f"ACROSS THE FAMILY ({len(board)} jurisdictions charted together; open cells are still being researched):",
        *others, "",
        "METHOD: charted in one pass with its sibling jurisdictions from exact passages of sources our system "
        "opened (this jurisdiction's own courts, compacts and regulations); every quote was re-found on its page. "
        "Authorities that were not opened are not reflected."])
    cites = []
    for q in quotes:
        prop = next((s for s in re.split(r"(?<=[.;])\s+", v["answer"] + " " + framework_text) if q["id"] in s), "")
        cites.append({"source": q["authority"], "url": q["url"], "quote": q["quote"], "verified": True,
                      "finding": q["id"], "proposition": re.sub(r"\[[^\]]*\]", "", prop).strip()[:300]
                      or ("general framework" if q["id"].startswith("G") else f"{member}: {choice}")})
    conf = confidence_for(v)
    return {"question": row.get("question"),
            "verdict": f"{member}: {choice}" + (" (contested)" if v["status"] == "contested" else "")
                       + (f"; {sum(1 for i in v['items'] if i['choice'] != 'undetermined')} of {len(v['items'])} game types classified"
                          if v.get("items") else ""),
            "opinion": opinion, "citations": cites,
            "assumptions": ["Charted from the passages opened; later or unopened authority may change the answer."],
            "conviction": round(conf * 10, 1), "dissent": "none", "flips_if": v["flips_if"],
            "conditions": "", "unsettled": v["status"] == "contested",
            "process": {"engine": "consilium_v2", "mode": "family_matrix", "route": "family_matrix",
                        "tier": meta.get("tier"), "model": meta.get("model"), "family": fam["key"],
                        "template": fam["template"][:300], "members": len(fam["members"]), "cell_status": v["status"],
                        "own_quotes": v["own"], "citation_count": len(cites), "verified_citations": len(cites),
                        "items": v.get("items") or None,
                        "red_team_severity": "none", "priority": row.get("priority")}}


WEB_SCHEMA = {"type": "object", "required": ["jurisdictions"], "properties": {"jurisdictions": {"type": "array", "items": {
    "type": "object", "required": ["cell", "sources"], "properties": {
        "cell": {"type": "integer"},
        "sources": {"type": "array", "items": {"type": "object", "required": ["url", "quote", "says"], "properties": {
            "url": {"type": "string"}, "quote": {"type": "string"}, "says": {"type": "string"}}}}}}}}}

WEB_SYSTEM = """You find primary sources for a regulatory research desk. Your output is checked by software:
every quote is fetched from its URL and searched for verbatim, and anything not found is discarded.
 - Prefer the jurisdiction's own statute or regulation, a court of that jurisdiction, its attorney general
   or gaming regulator; for a tribe, its tribal-state compact or NIGC/BIA documents naming that tribe.
 - Each quote: at most 40 words, copied character for character from the page at that URL.
 - A source about a different jurisdiction or a similarly named entity does not count.
 - If you cannot find an official source for a jurisdiction, return an empty list for it.
Return ONLY the JSON object."""


def _web_calls_today(key=None, add=0):
    path = os.path.join(STATE_DIR, "web_calls.json")
    today = datetime.date.today().isoformat()
    try:
        with open(path) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    n = int(d.get(today) or 0) + add
    if add:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(path, "w") as f:
            json.dump({today: n}, f)
    return n


def _default_web(prompt):
    import frontier
    r = frontier.complete(prompt, system=WEB_SYSTEM, need=8, tools=frontier.WEB_TOOLS, max_turns=14,
                          json_schema=WEB_SCHEMA, tag="family.web", timeout=1500, min_tier="frontier")
    j = r.get("json") if not r.get("error") else None
    if j is None and r.get("text") and not r.get("error"):
        j = frontier.extract_json(r["text"])
    return j, r


def web_fill(fam, cells, *, fetcher, web=None, limit_calls=None):
    """Members with no passages after free research get one web-research call per WEB_CHUNK members.
    A source is adopted only when our own fetch finds its quote on the page; the passage is then an
    exact slice of that page around the quote, like every other passage. -> number of calls made."""
    import local_tribunal as lt
    empty = [c for c in cells if not c["passages"]]
    if not empty:
        return 0
    budget = WEB_CALLS_PER_DAY - _web_calls_today() if limit_calls is None else limit_calls
    if budget <= 0:
        return 0
    if web is None:
        try:
            import frontier
            if not frontier.can_think(min_tokens=60000, min_tier="frontier"):
                return 0
        except Exception:
            return 0
    web = web or _default_web
    calls = 0
    q = fam["question"].replace("{X}", "<jurisdiction>")
    for start in range(0, len(empty), WEB_CHUNK):
        if calls >= budget:
            break
        chunk = empty[start:start + WEB_CHUNK]
        listing = "\n".join(f"CELL {c['n']}: {c['row']['_member']}" for c in chunk)
        j, _r = web(f"QUESTION (asked once per jurisdiction): {q}\n\nJURISDICTIONS:\n{listing}\n\n"
                    "For each cell, find up to 3 official sources that answer the question for that jurisdiction.")
        calls += 1
        if limit_calls is None:
            _web_calls_today(add=1)
        by_n = {}
        for it in ((j or {}).get("jurisdictions") or []):
            try:
                by_n[int(it.get("cell"))] = it.get("sources") or []
            except Exception:
                continue
        for c in chunk:
            for src in by_n.get(c["n"], [])[:3]:
                url = _s(src.get("url")).strip()
                if not url.startswith("http"):
                    continue
                page = fetcher(url) or ""
                exact = lt.locate_quote(src.get("quote"), page) if page else ""
                if not exact or exact not in page:
                    continue
                i = page.find(exact)
                half = PASSAGE_CHARS // 2
                s0, e0 = max(0, i - half), min(len(page), i + len(exact) + half)
                if not names_entity(page, c["row"]["_member"]) and c["row"]["_member"].lower() not in page.lower():
                    continue                     # a page that never names the jurisdiction is not its source
                import authority_search as asrch
                label = asrch.label_for(url, "") or url[:120]
                c["passages"].append({"text": page[s0:e0], "score": 5, "authority": label, "url": url, "origin": "web",
                                      "id": f"M{c['n']}.{len(c['passages']) + 1}"})
                # An official page found once is kept for every later family and matter (statute_definitions).
                try:
                    import statute_kb
                    import authority_search as asrch2
                    st2 = asrch2.state(c["row"].get("_jurisdiction")) or asrch2.state(c["row"]["_member"])
                    jur = f"US-{st2[0]}" if st2 else _s(c["row"].get("_jurisdiction"))
                    for topic in kb_topics(fam)[:1]:
                        if jur:
                            statute_kb.record(jur, topic, label, url, page[s0:e0], "web_research")
                except Exception:
                    pass
    return calls


def _default_searcher(query, courts, n):
    import authority_search as asrch
    return asrch.caselaw_opinions(query, courts, n)


def _chart_call(prompt):
    import frontier
    r = frontier.complete(prompt, system=CHART_SYSTEM, need=NEED, max_turns=1, json_schema=CHART_SCHEMA,
                          tag="family.chart", timeout=1500)
    j = r.get("json") if not r.get("error") else None
    if j is None and r.get("text") and not r.get("error"):
        j = frontier.extract_json(r["text"])
    return j, r


def run(fam, *, mint=None, fetcher=None, searcher=None, chart=None, compacts=None, max_cells=CELLS_PER_PASS,
        write_doc=True, web=None, web_calls=None):
    """Chart up to `max_cells` uncharted members of `fam`. -> summary dict."""
    import local_research as lr
    fetcher = fetcher or lr.fetch
    searcher = searcher or _default_searcher
    chart = chart or _chart_call
    t0 = time.time()
    st = load_state(fam["key"]) or {"key": fam["key"], "template": fam["template"], "vertical": fam["vertical"],
                                     "question": fam["question"], "cells": {}}
    opts = st.get("options") or options(fam["members"][0].get("question"))
    st["options"] = opts
    its = items(fam["members"][0].get("question"))
    if not st.get("framework_passages"):
        st["framework_passages"] = framework_research(fam, opts, fetcher=fetcher, searcher=searcher)
    framework = st["framework_passages"]
    rows = todo(fam)[:max_cells]
    out = {"family": fam["key"], "template": fam["template"][:120], "members": len(fam["members"]), "cells": 0,
           "settled": 0, "contested": 0, "open": 0, "minted": 0, "chart_calls": 0, "tokens_in": 0, "tokens_out": 0,
           "tiers": {}}
    cells, out["transient"] = [], 0
    for n, row in enumerate(rows, 1):
        ps, transient = cell_research(row, fam, opts, fetcher=fetcher, searcher=searcher, compacts=compacts)
        if not ps and transient:
            out["transient"] += 1            # an outage: retried on the next pass...
            tries = st.setdefault("transient", {})
            tries[str(row["id"])] = tries.get(str(row["id"]), 0) + 1
            if tries[str(row["id"])] >= TRANSIENT_LIMIT:
                # ...but a search that keeps failing (a bad court id, a dead host) must not keep the
                # family first in line forever and starve the one-at-a-time route.
                st["cells"][str(row["id"])] = {"member": row["_member"], "status": "open", "no_sources": True,
                                               "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                               "why": f"search failed {tries[str(row['id'])]} times"}
                tries.pop(str(row["id"]))
            continue
        for k, p in enumerate(ps, 1):
            p["id"] = f"M{n}.{k}"
        prev = (st.get("cells") or {}).get(str(row["id"])) or {}
        cells.append({"n": n, "row": row, "passages": ps, "critique": prev.get("critique") if prev.get("needs_rechart") else None,
                      "card_id": prev.get("card_id") if prev.get("needs_rechart") else None,
                      "revisions": int(prev.get("revisions") or 0)})
    try:
        out["web_calls"] = web_fill(fam, cells, fetcher=fetcher, web=web, limit_calls=web_calls)
    except Exception as e:
        out["web_error"] = f"{type(e).__name__}: {str(e)[:100]}"
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for start in range(0, len(cells), CHUNK):
        chunk = cells[start:start + CHUNK]
        researched = [c for c in chunk if c["passages"]]
        for c in chunk:
            if not c["passages"]:
                st["cells"][str(c["row"]["id"])] = {"member": c["row"]["_member"], "status": "open", "at": now,
                                                    "why": "no sources found for this jurisdiction",
                                                    "no_sources": True}
                out["cells"] += 1
                out["open"] += 1
        if not researched:
            continue
        j, r = chart(chart_prompt(fam, opts, framework, st.get("framework_text") or "", researched, its))
        out["chart_calls"] += 1
        out["tokens_in"] += int((r or {}).get("tokens_in") or 0)
        out["tokens_out"] += int((r or {}).get("tokens_out") or 0)
        tier = (r or {}).get("tier") or "frontier"
        out["tiers"][tier] = out["tiers"].get(tier, 0) + 1
        if not isinstance(j, dict):
            continue                          # nothing recorded: these members are retried next pass
        if not st.get("framework_text") and _s(j.get("framework")).strip():
            fq = []
            for q in j.get("framework_quotes") or []:
                p = next((x for x in framework if x["id"] == _s(q.get("passage")).strip("[] ")), None)
                if p:
                    import local_tribunal as lt
                    exact = lt.locate_quote(q.get("quote"), p["text"])
                    if exact:
                        fq.append({"id": p["id"], "quote": exact, "authority": p["authority"], "url": p["url"]})
            if fq:
                st["framework_text"], st["framework_quotes"] = _s(j["framework"]).strip()[:2000], fq
        by_n = {int(c.get("cell") or 0): c for c in j.get("cells") or [] if isinstance(c, dict)}
        for c in researched:
            v = verify_cell(by_n.get(c["n"]) or {}, c, framework, its, opts)
            if c["n"] not in by_n:
                v["why"] = "the chart did not answer this cell"
            rec = {"member": c["row"]["_member"], "status": v["status"],
                   "choice": _match_choice(v["choice"], opts) if v["status"] != "open" else "undetermined",
                   "own": v["own"], "at": now, "why": v["why"], "tier": tier, "model": (r or {}).get("model"),
                   "docket_id": c["row"]["id"], "items": {str(i["n"]): i["choice"] for i in v.get("items") or []},
                   "basis": v.get("basis"), "revisions": c.get("revisions", 0) + (1 if c.get("card_id") else 0),
                   "reviewed_by": ((st.get("cells") or {}).get(str(c["row"]["id"])) or {}).get("reviewed_by")}
            c["v"], c["rec"], c["tier"], c["model"] = v, rec, tier, (r or {}).get("model")
            st["cells"][str(c["row"]["id"])] = rec
            out["cells"] += 1
            out[v["status"]] += 1
    board = [(x["member"], x.get("choice") or "undetermined", x["status"]) for x in st["cells"].values()]
    for c in cells:
        v = c.get("v")
        if not v or v["status"] == "open":
            continue
        agg = card_agg(fam, c["row"], v, st.get("framework_text") or "", st.get("framework_quotes") or [], board,
                       {"options": opts, "tier": c["tier"], "model": c["model"]})
        if c.get("card_id"):
            agg["_existing_card_id"] = c["card_id"]
            agg["process"]["revision_of_review"] = c["rec"].get("reviewed_by")
        if mint is not None:
            try:
                ok = mint(c["row"], agg)
            except Exception as e:
                ok = False
                c["rec"]["mint_error"] = f"{type(e).__name__}: {str(e)[:120]}"
            c["rec"]["minted"] = bool(ok)
            out["minted"] += 1 if ok else 0
            if ok and c.get("card_id"):
                try:
                    _flag_rereview(c["card_id"], "family re-chart after the commission's critique")
                except Exception:
                    pass
        remember(fam, c["row"], v, agg)
    save_state(fam["key"], st)
    if write_doc:
        try:
            out["doc"] = write_matrix(fam, st)
        except Exception as e:
            out["doc_error"] = f"{type(e).__name__}: {str(e)[:100]}"
    out["latency_s"] = round(time.time() - t0, 1)
    print("family_matrix: " + json.dumps(out), flush=True)
    return out


def remember(fam, row, v, agg):
    """A charted cell becomes a firm-memory holding, so an individual matter on the same jurisdiction
    starts from it."""
    try:
        import escalation as es
        auth = [{"authority": c["source"], "url": c["url"], "quote": c["quote"]} for c in agg["citations"]
                if c.get("finding", "").startswith("M")][:4]
        if not auth:
            return
        rec = {"kind": "holding", "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "vertical": fam["vertical"], "tier": "family", "route": "family_matrix",
               "question": _s(row.get("question"))[:400], "issue": _core(row.get("question"))[:300],
               "ruling": agg["verdict"][:600], "authorities": auth}
        os.makedirs(os.path.dirname(es.MEMORY), exist_ok=True)
        with open(es.MEMORY, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def write_matrix(fam, st):
    os.makedirs(OUT_DIR, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", fam["template"].replace("{x}", ""))[:60].strip("-")
    path = os.path.join(OUT_DIR, f"{datetime.date.today().isoformat()}-{slug}.md")
    rows = sorted(st["cells"].values(), key=lambda c: (STATUSES.index(c["status"]) if c["status"] in STATUSES else 3,
                                                     c.get("choice") or "", c["member"]))
    counts = {}
    for c in rows:
        if c["status"] != "open":
            counts[c.get("choice")] = counts.get(c.get("choice"), 0) + 1
    lines = [f"# {fam['question'].replace('{X}', '<jurisdiction>')}", "",
             f"_Question family charted by `runner/family_matrix.py`, {len(rows)} of {len(fam['members'])} members so far._",
             "", "Internal research. Each cell was answered only from its own jurisdiction's sources, with quotes checked "
             "against the page. Nothing here has had attorney review.", ""]
    if st.get("framework_text"):
        lines += ["## Framework", "", st["framework_text"], ""]
    if counts:
        lines += ["## Distribution", ""] + [f"- **{k}**: {n}" for k, n in sorted(counts.items(), key=lambda x: -x[1])] + [""]
    lines += ["## Matrix", "", "| Jurisdiction | Answer | Status | Note |", "|---|---|---|---|"]
    for c in rows:
        note = c.get("why") or (f"{c.get('own')} own source quote(s)" if c.get("own") else "")
        lines.append(f"| {c['member']} | {c.get('choice') or 'undetermined'} | {c['status']} | {note} |")
    its = items(fam["members"][0].get("question")) if fam.get("members") else []
    if its and any(c.get("items") for c in rows):
        def short(ch):
            if not ch or ch == "undetermined":
                return "·"
            last = ch.split()[-1]
            return last if re.fullmatch(r"[IVX]+", last) else ch.split()[0][:5]
        lines += ["", "## By game type", "", "| Jurisdiction | " + " | ".join(str(i["n"]) for i in its) + " |",
                  "|---|" + "---|" * len(its)]
        for c in rows:
            if c.get("items"):
                lines.append(f"| {c['member']} | " + " | ".join(short(c["items"].get(str(i["n"]))) for i in its) + " |")
        lines += [""] + [f"{i['n']}. {i['name']}" for i in its]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return os.path.relpath(path, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


if __name__ == "__main__":
    import gap_intake
    fams = families(gap_intake.pending_gap_rows())
    for f in fams:
        print(json.dumps({"key": f["key"], "members": len(f["members"]), "todo": len(todo(f)), "value": f["value"],
                          "question": f["question"][:140], "options": options(f["members"][0].get("question"))}))
    if "--run" in sys.argv[1:] and fams:
        import legal_docket
        fam = next((f for f in fams if todo(f)), None)
        if fam:
            run(fam, mint=legal_docket.mint_card if "--mint" in sys.argv[1:] else None)

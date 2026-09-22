#!/usr/bin/env python3
"""local_research.py — the AUTHORITY DOSSIER without a subscription call.

The frontier research clerk cost 60-130K weighted tokens per question and "verified" meant the model
said it opened the page. This builder spends nothing and verifies mechanically:

  1. SPOT   the authorities in play: citations written in the question, in the firm's corpus
            passages and authority-cache hits for it, plus (optionally) a short local-model call
            that names the operative statutes and rules by citation.
  2. RESOLVE each citation to its official or canonical URL by rule — LII for the CFR, the U.S. Code
            and NYCRR, nysenate.gov for New York statutes, the Federal Register API for FR documents.
            No search engine, no guessing.
  3. FETCH  the page ourselves (urllib, on-disk cache), strip it to text.
  4. QUOTE  the sentence(s) that bear on the question, chosen by term overlap, <= 40 words, copied
            from the page. verified=True means the quote IS a substring of the text we fetched —
            a property of the bytes, not a claim by a model.

Output is the same DOSSIER shape consilium_v2 debates on. What cannot be resolved by rule (case law,
agency letters without a stable URL) is listed under `unresolved` so the tribunal treats it as an
assumption and an escalation can target exactly that gap. Everything is fail-soft.
"""
from __future__ import annotations
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import db as _db  # noqa: F401
except Exception:
    pass

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
PAGES = os.path.join(HOME, "consilium", "pages")
PAGE_TTL_S = int(os.environ.get("ORCH_LOCAL_RESEARCH_PAGE_TTL_S", str(7 * 86400)))
MAX_SOURCES = int(os.environ.get("ORCH_LOCAL_RESEARCH_MAX_SOURCES", "14"))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
SPOT_WITH_MODEL = os.environ.get("ORCH_LOCAL_RESEARCH_SPOT", "true").lower() not in ("0", "false", "no", "off")

_CFR = re.compile(r"\b(\d{1,2})\s*C\.?\s*F\.?\s*R\.?\s*(?:§+\s*|part\s+|pt\.?\s*|section\s+|sec\.?\s*)?(\d{2,5})(?:\.(\d{1,5}[a-z]?))?", re.I)
_USC = re.compile(r"\b(\d{1,2})\s*U\.?\s*S\.?\s*C\.?\s*(?:§+\s*|section\s+|sec\.?\s*)?(\d{1,6}[a-z]?)", re.I)
_NYCRR = re.compile(r"\b(\d{1,2})\s*NYCRR\s*(?:part\s+|§+\s*)?(\d{1,4})(?:\.(\d{1,4}))?", re.I)
_FRDOC = re.compile(r"\b(20\d{2}-\d{4,6})\b")
_NY_LAW = re.compile(r"\b(?:N\.?Y\.?\s+)?(Banking|Penal|General Business|Racing, Pari-Mutuel Wagering and Breeding|Insurance|"
                     r"Financial Services|Executive|Tax)\s+Law\s*(?:§+\s*|section\s+|sec\.?\s*)?(\d{1,4}(?:-[a-z])?(?:\.\d+)?)", re.I)
_NY_CODES = {"banking": "BNK", "penal": "PEN", "general business": "GBS", "insurance": "ISC", "financial services": "FIS",
             "racing, pari-mutuel wagering and breeding": "PML", "executive": "EXC", "tax": "TAX"}
_STOP = set("the a an and or of to in for on by with from as at is are be was were that this these those its it their "
            "they which who what when where how does do did can could would should must may shall any all our your we you "
            "under over into about between than then there such other same also not per via use used using company "
            "business whether question section part title subsection paragraph".split())


def resolve(text):
    """Citations in `text` -> [{authority, url, jurisdiction}] by rule. Order of appearance, de-duplicated."""
    out, seen = [], set()

    def add(auth, url, juris):
        if url not in seen:
            seen.add(url)
            out.append({"authority": auth, "url": url, "jurisdiction": juris})
    t = text or ""
    for m in _CFR.finditer(t):
        title, part, sec = m.group(1), m.group(2), m.group(3)
        if sec:
            add(f"{int(title)} CFR {part}.{sec}", f"https://www.law.cornell.edu/cfr/text/{int(title)}/{part}.{sec}", "US_FEDERAL")
        else:
            add(f"{int(title)} CFR Part {part}", f"https://www.law.cornell.edu/cfr/text/{int(title)}/part-{part}", "US_FEDERAL")
    for m in _USC.finditer(t):
        add(f"{int(m.group(1))} U.S.C. § {m.group(2)}", f"https://www.law.cornell.edu/uscode/text/{int(m.group(1))}/{m.group(2).lower()}", "US_FEDERAL")
    for m in _NYCRR.finditer(t):
        title, part, sec = m.group(1), m.group(2), m.group(3)
        if sec:
            add(f"{int(title)} NYCRR {part}.{sec}", f"https://www.law.cornell.edu/regulations/new-york/{int(title)}-NYCRR-{part}.{sec}", "NY")
    for m in _NY_LAW.finditer(t):
        code = _NY_CODES.get(m.group(1).lower())
        if code:
            add(f"NY {m.group(1)} Law § {m.group(2)}", f"https://www.nysenate.gov/legislation/laws/{code}/{m.group(2).upper()}", "NY")
    for d in _FRDOC.findall(t):
        add(f"Federal Register doc. {d}", f"https://www.federalregister.gov/api/v1/documents/{d}.json", "US_FEDERAL")
    return out


# ── fetch ────────────────────────────────────────────────────────────────────────────────────────
def to_text(raw, url=""):
    if url.endswith(".json") or raw.lstrip().startswith("{"):
        try:
            d = json.loads(raw)
            return " ".join(str(d.get(k) or "") for k in ("title", "abstract", "action", "dates", "citation", "html_url"))
        except Exception:
            pass
    raw = re.sub(r"(?is)<(script|style|nav|header|footer|noscript|svg|form)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|section|blockquote)>", "\n", raw)
    txt = html.unescape(re.sub(r"(?s)<[^>]+>", " ", raw))
    # ONE canonical form: every run of whitespace is a single space. Quotes are cut from, and verified
    # against, this exact string — so a line break inside a sentence can never split a quote.
    return re.sub(r"\s+", " ", txt).strip()


def fetch(url, timeout=25):
    """-> page text ('' on failure). Cached on disk for PAGE_TTL_S."""
    key = hashlib.sha1(url.encode()).hexdigest()
    path = os.path.join(PAGES, key + ".txt")
    try:
        if time.time() - os.path.getmtime(path) < PAGE_TTL_S:
            with open(path) as f:
                return f.read()
    except OSError:
        pass
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json;q=0.9,*/*;q=0.5"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if "pdf" in (r.headers.get("Content-Type") or "").lower():
                return ""
            raw = r.read(3_000_000).decode("utf-8", "replace")
    except Exception:
        return ""
    txt = to_text(raw, url)
    if len(txt) < 200:
        return ""
    try:
        os.makedirs(PAGES, exist_ok=True)
        with open(path, "w") as f:
            f.write(txt)
    except OSError:
        pass
    return txt


# ── quote selection (mechanical) ─────────────────────────────────────────────────────────────────
def keywords(text):
    return {w for w in re.findall(r"[a-z][a-z\-]{3,}", (text or "").lower()) if w not in _STOP}


def _sentences(text):
    parts = re.split(r"(?<=[.;])\s+(?=[A-Z(\"“])", text or "")
    return [p.strip() for p in parts if 40 <= len(p.strip()) <= 1200]


def excerpt_around(page_text, quote, radius=700):
    """Up to ~2*radius characters of the page around the quote, for the tribunal to READ. Citations
    may quote any span of it; verification is always against the full page text."""
    i = page_text.find(quote) if quote else -1
    if i < 0:
        return page_text[:2 * radius]
    return page_text[max(0, i - radius): i + len(quote) + radius]


def best_quote(page_text, question, max_words=40, skip_chars=0):
    """The passage of the page with the highest term overlap with the question, cut to <= max_words
    WITHOUT altering a character, so it remains a substring of the page. '' when nothing overlaps."""
    qk = keywords(question)
    best, best_score = "", 0.0
    for sent in _sentences(page_text[skip_chars:]):
        sk = keywords(sent)
        if not sk:
            continue
        score = len(qk & sk) + 0.15 * sum(1 for w in ("shall", "must", "means", "unlawful", "no person", "required", "except") if w in sent.lower())
        if score > best_score:
            best, best_score = sent, score
    if not best or best_score < 1:
        return ""
    words = best.split(" ")
    if len(words) > max_words:
        best = " ".join(words[:max_words])
    return best if best in page_text else ""


def verified(quote, page_text):
    return bool(quote) and len(quote) >= 20 and quote in page_text


def corpus_authority(citation):
    """The firm's own authority table (human-reviewed standing, operative text held) for a citation
    whose public host refuses automated fetches. -> {url, text, standing} or None."""
    try:
        import corpus_db
        key = re.sub(r"[^A-Za-z0-9.§ ]", " ", citation or "").strip()
        m = re.search(r"(\d[\d.\-a-z]*)\s*$", key)
        if not m:
            return None
        rows = corpus_db.select("corpus_authority_standing", {
            "select": "citation,url,standing,operative_text,jurisdiction_id",
            "citation": f"ilike.*{m.group(1)}*", "operative_text": "not.is.null", "limit": "8"})
        want = keywords(citation)
        best = max(rows, key=lambda r: len(want & keywords(r.get("citation"))), default=None)
        if best and len(want & keywords(best.get("citation"))) >= 1 and len(best.get("operative_text") or "") >= 200:
            return {"url": best.get("url") or "", "text": re.sub(r"\s+", " ", best["operative_text"]).strip(),
                    "standing": best.get("standing"), "citation": best.get("citation")}
    except Exception:
        pass
    return None


# ── spotting ─────────────────────────────────────────────────────────────────────────────────────
SPOT_SCHEMA = {"type": "object", "properties": {
    "issues": {"type": "array", "items": {"type": "string"}},
    "authorities": {"type": "array", "items": {"type": "string"}}},
    "required": ["issues", "authorities"]}

SPOT_SYSTEM = ("You are a regulatory research clerk. Name the OPERATIVE primary authorities for the question as precise "
               "citations a machine can resolve: '31 CFR 1022.380', '31 U.S.C. § 5330', '23 NYCRR 200.3', 'NY Banking Law § 641', "
               "'18 U.S.C. § 1960'. Statutes and regulations only, section-level, at most 12, the controlling ones first, "
               "including the strongest authority AGAINST the obvious answer. Also list at most 6 contested issues. "
               "If you are not sure a section exists, leave it out.")


def spot(question, context="", chat=None):
    if not SPOT_WITH_MODEL:
        return [], []
    try:
        if chat is None:
            import local_llm
            chat = local_llm.chat
        r = chat(f"QUESTION: {question}\nCONTEXT: {(context or '')[:1200]}", system=SPOT_SYSTEM, json_schema=SPOT_SCHEMA,
                 max_tokens=700, temperature=0.1, timeout=600, tag="consilium.local.spot")
        j = r.get("json") if isinstance(r.get("json"), dict) else {}
        return [str(i)[:200] for i in (j.get("issues") or [])][:6], [str(a)[:120] for a in (j.get("authorities") or [])][:12]
    except Exception:
        return [], []


# ── the dossier ──────────────────────────────────────────────────────────────────────────────────
def build(question, context="", vertical=None, corpus_passages=None, cache_hits=None, chat=None, fetcher=None,
          authority_lookup=corpus_authority):
    """-> (dossier, info). dossier is None only when not one verified source could be produced.
    dossier["_pages"] maps url -> the full text held, so citations can be verified against the page."""
    t0 = time.time()
    fetcher = fetcher or fetch
    sources, seen, pages = [], set(), {}

    def push(src):
        u = (src.get("url") or "").strip()
        if u and u not in seen and len(sources) < MAX_SOURCES:
            seen.add(u)
            sources.append(src)

    # corpus passages are text the firm already holds: opened by definition, quote cut from them.
    for p in (corpus_passages or [])[:6]:
        text = p.get("text") or ""
        q = best_quote(text, question)
        if q and p.get("source_url"):
            text = re.sub(r"\s+", " ", text).strip()
            q = best_quote(text, question)
            if not q:
                continue
            pages[p["source_url"]] = text
            push({"url": p["source_url"], "title": (p.get("doc_title") or "")[:160], "authority": (p.get("heading") or p.get("doc_title") or "")[:160],
                  "jurisdiction": p.get("jurisdiction") or "", "quote": q, "excerpt": text[:1400], "proposition": "",
                  "verified": True, "origin": "corpus"})
    for h in (cache_hits or [])[:6]:
        if h.get("url") and h.get("quote"):
            push({"url": h["url"], "title": h.get("title") or "", "authority": h.get("authority") or "", "jurisdiction": h.get("jurisdiction") or "",
                  "quote": h["quote"], "proposition": h.get("proposition") or "", "verified": True, "origin": "authority_cache"})
    issues, named = spot(question, context, chat=chat)
    cited = resolve(" ; ".join([question or "", context or ""] + named))
    unresolved, fetched, failed = [], 0, 0
    for c in cited:
        if len(sources) >= MAX_SOURCES:
            break
        page, origin = fetcher(c["url"]), "fetched"
        if not page:
            held = authority_lookup(c["authority"]) if authority_lookup else None
            if held:
                page, origin = held["text"], f"corpus_authority:{held.get('standing')}"
                c = {**c, "url": held.get("url") or c["url"]}
        if not page:
            failed += 1
            unresolved.append(f"{c['authority']} (could not open {c['url']})")
            continue
        fetched += 1
        q = best_quote(page, question)
        pages[c["url"]] = page
        push({"url": c["url"], "title": c["authority"], "authority": c["authority"], "jurisdiction": c["jurisdiction"],
              "quote": q, "excerpt": excerpt_around(page, q), "proposition": "", "verified": verified(q, page), "origin": origin})
    resolvable = {c["authority"].lower() for c in cited}
    for a in named:
        if not resolve(a):
            unresolved.append(f"{a} (no rule-based URL; treat as an assumption or escalate)")
    info = {"engine": "local_research", "latency_s": round(time.time() - t0, 1), "named": len(named), "resolved": len(cited),
            "fetched": fetched, "fetch_failed": failed, "sources": len(sources),
            "verified_sources": sum(1 for s in sources if s.get("verified")), "tokens_in": 0, "tokens_out": 0,
            "cost_weighted": 0, "cached": False, "model": "local", "error": ""}
    if not any(s.get("verified") for s in sources):
        info["error"] = "no verified source could be produced locally"
        return None, info
    return {"issues": issues, "sources": sources, "unresolved": unresolved[:10], "queries": [], "_pages": pages}, info


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else ("Must an esports wagering company that uses an LLM for KYC obtain a BitLicense under 23 NYCRR 200.3 "
                                               "or register as an MSB under 31 CFR 1022.380 to comply with NY Banking Law § 641?")
    d, info = build(q)
    print(json.dumps(info, indent=1))
    for s in (d or {}).get("sources", []):
        print(("✓" if s["verified"] else "✗"), s["authority"], "|", s["url"], "\n    ", s["quote"][:200])
    print("unresolved:", (d or {}).get("unresolved"))

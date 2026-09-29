#!/usr/bin/env python3
"""authority_search.py — DISCOVERY for the local tier: official search APIs, no keys, no cost.

WHY. The local tier could only open an authority it could already NAME: local_research resolves
citations by rule ("31 CFR 1022.380" -> a URL). When the question misnamed the rule — and 27 of 30
sampled docket questions did — the dossier was built from the wrong pages, and the memo reasoned
confidently from them. A frontier model fixes this by searching. The local tier can search too:

  eCFR            full-text search over the current Code of Federal Regulations
  Federal Register rules, proposed rules and notices, with full text
  CourtListener   case-law search (metadata and the opening of the opinion; LEADS only — the
                  opinion text needs a token, so a case is never cited from here)

Every result is a CANDIDATE. Nothing is citable until the page has been fetched and a verbatim
passage selected from it (passages()), so a wrong search hit costs a fetch, never a false citation.

passages() is mechanical: it scores sentence windows of the fetched page against the terms of the
issue and returns exact slices of the page text. The model later chooses quotes from those slices
and the quote is re-checked as a substring, so the chain from page to citation never passes
through a model's memory.
"""
from __future__ import annotations
import json
import os
import re
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
      "Version/17.0 Safari/605.1.15")
TIMEOUT = int(os.environ.get("ORCH_AUTHORITY_SEARCH_TIMEOUT_S", "25"))
ENABLED = os.environ.get("ORCH_AUTHORITY_SEARCH", "true").lower() not in ("0", "false", "no", "off")

_STOP = set("""a an and are as at be been being but by can could did do does for from had has have how if in into is it its
may might more most must no nor not of on or our shall should so such than that the their them then there these they this
those to under upon was were what when where whether which while who whom why will with within without would you your
company companies platform operator business use uses using used any all each other also only same new via per
""".split())


def terms(text, limit=24):
    """Content words, lower-cased, in order of first appearance."""
    out, seen = [], set()
    for w in re.findall(r"[a-z][a-z0-9\-]{2,}", (text or "").lower()):
        if w in _STOP or w in seen:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= limit:
            break
    return out


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read(2_000_000).decode("utf-8", "replace"))


def _strip(html_text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(html_text or ""))).strip()


def ecfr(query, n=5):
    """Current CFR sections matching the query. URL is the Cornell LII page for the section, which
    any reader (and the publication commission) can open."""
    out = []
    try:
        d = _get_json("https://www.ecfr.gov/api/search/v1/results?per_page=%d&query=%s"
                      % (max(n * 3, 10), urllib.parse.quote(query[:200])))
    except Exception:
        return out
    seen = set()
    for r in d.get("results") or []:
        h = r.get("hierarchy") or {}
        if r.get("removed") or r.get("reserved") or r.get("ends_on") or r.get("type") != "Section":
            continue
        title, sec = h.get("title"), h.get("section")
        if not title or not sec or (title, sec) in seen:
            continue
        seen.add((title, sec))
        heads = r.get("headings") or r.get("hierarchy_headings") or {}
        out.append({"backend": "ecfr", "kind": "regulation", "jurisdiction": "US_FEDERAL",
                    "authority": f"{title} CFR {sec}", "title": _strip(heads.get("section"))[:200],
                    "url": f"https://www.law.cornell.edu/cfr/text/{title}/{sec}",
                    "excerpt": _strip(r.get("full_text_excerpt"))[:400], "citable": True})
        if len(out) >= n:
            break
    return out


def federal_register(query, n=4):
    """Rules, proposed rules and notices. URL is the full-text endpoint, which is fetchable."""
    out = []
    fields = "".join("&fields[]=" + f for f in ("title", "document_number", "html_url", "raw_text_url",
                                                 "publication_date", "type", "abstract", "citation", "agency_names"))
    try:
        d = _get_json("https://www.federalregister.gov/api/v1/documents.json?per_page=%d&order=relevance%s"
                      "&conditions[term]=%s" % (n, fields, urllib.parse.quote(query[:200])))
    except Exception:
        return out
    for r in d.get("results") or []:
        if not r.get("raw_text_url"):
            continue
        cite = r.get("citation") or f"FR Doc. {r.get('document_number')}"
        out.append({"backend": "fr", "kind": str(r.get("type") or "notice").lower().replace(" ", "_"),
                    "jurisdiction": "US_FEDERAL",
                    "authority": f"{cite} ({r.get('publication_date')}), {', '.join(r.get('agency_names') or [])[:80]}",
                    "title": _strip(r.get("title"))[:200], "url": r["raw_text_url"],
                    "display_url": r.get("html_url"), "excerpt": _strip(r.get("abstract"))[:400],
                    "published": r.get("publication_date"), "citable": True})
    return out


def caselaw(query, n=4):
    """LEADS: case name, court, date. Never citable from here (the opinion text is not held)."""
    out = []
    try:
        d = _get_json("https://www.courtlistener.com/api/rest/v4/search/?type=o&order_by=score%%20desc"
                      "&page_size=%d&q=%s" % (n, urllib.parse.quote(query[:200])))
    except Exception:
        return out
    for r in (d.get("results") or [])[:n]:
        cites = ", ".join(r.get("citation") or [])[:80]
        out.append({"backend": "caselaw", "kind": "court_opinion", "jurisdiction": r.get("court_id") or "",
                    "authority": f"{_strip(r.get('caseName'))[:120]}{(' , ' + cites) if cites else ''} "
                                 f"({r.get('court_id')}, {str(r.get('dateFiled') or '')[:10]})",
                    "title": _strip(r.get("caseName"))[:200],
                    "url": "https://www.courtlistener.com" + str(r.get("absolute_url") or ""),
                    "excerpt": "", "citable": False})
    return out


BACKENDS = {"ecfr": ecfr, "fr": federal_register, "caselaw": caselaw}


def search(queries, per_query=4, backends=("ecfr", "fr", "caselaw")):
    """queries: list of strings or {backend, query}. -> (candidates, leads), de-duplicated by URL."""
    if not ENABLED:
        return [], []
    cands, leads, seen = [], [], set()
    for q in queries[:8]:
        if isinstance(q, dict):
            text, only = str(q.get("query") or ""), str(q.get("backend") or "").lower()
        else:
            text, only = str(q), ""
        text = text.strip()
        if len(text) < 4:
            continue
        for name in backends:
            if only and only in BACKENDS and name != only:
                continue
            for hit in BACKENDS[name](text, per_query):
                if hit["url"] in seen:
                    continue
                seen.add(hit["url"])
                hit["query"] = text[:120]
                (cands if hit.get("citable") else leads).append(hit)
    return cands, leads


# ── passages: exact slices of the page, scored against the issue ────────────────────────────────
def _sentences(text):
    """[(start, end)] spans. The page text is whitespace-normalised, so spans are stable slices."""
    spans, start = [], 0
    for m in re.finditer(r"(?<=[.;:?!])\s+(?=[A-Z(\"'\[§0-9])", text):
        if m.start() - start >= 40:
            spans.append((start, m.start()))
            start = m.end()
    if len(text) - start >= 20:
        spans.append((start, len(text)))
    return spans


def relevance(text, want):
    """Distinct wanted terms present, weighted a little by frequency. 0 when nothing matches."""
    low = (text or "").lower()
    score = 0.0
    for t in want:
        c = low.count(t)
        if c:
            score += 2.0 + min(c, 4) * 0.25
    return score


_CHROME = re.compile(r"(\s>\s.*\s>\s)|(^|\s)(Subtitle|CHAPTER|PART|SUBCHAPTER)\s+[A-Z0-9]+\s*[—-]|skip to|breadcrumb|"
                     r"print this page|table of contents|site map|\bmenu\b", re.I)


def is_chrome(text):
    """Breadcrumbs, heading chains and page furniture: never evidence."""
    t = text or ""
    if _CHROME.search(t):
        return True
    words = t.split()
    return bool(words) and sum(1 for w in words if w.isupper() and len(w) > 2) / len(words) > 0.4


def label_for(url, fallback=""):
    """A precise authority label derived from the URL, so the writer sees "31 CFR 1022.210", not
    "Treasury/FinCEN regulation" (2026-09-29: a generic label let a 9B model call the AML-program
    rule by its pre-2011 name, 31 CFR 103, while citing the current section)."""
    u = url or ""
    m = re.search(r"law\.cornell\.edu/cfr/text/(\d+)/(part-)?([\w.\-]+)", u)
    if m:
        return f"{m.group(1)} CFR {'Part ' if m.group(2) else ''}{m.group(3)}"
    m = re.search(r"law\.cornell\.edu/uscode/text/(\d+)/([\w\-]+)", u)
    if m:
        return f"{m.group(1)} U.S.C. § {m.group(2)}"
    m = re.search(r"ecfr\.gov/current/title-(\d+)/.*section-([\w.\-]+)", u)
    if m:
        return f"{m.group(1)} CFR {m.group(2)}"
    m = re.search(r"regulations/new-york/(\d+)-NYCRR-([\w.\-]+)", u)
    if m:
        return f"{m.group(1)} NYCRR {m.group(2)}"
    m = re.search(r"federalregister\.gov/.*?/(\d{4}-\d{4,6})", u)
    if m and not fallback:
        return f"FR Doc. {m.group(1)}"
    return fallback or u


def passages(page_text, want, k=3, width=900):
    """Top-k non-overlapping windows of consecutive sentences, each an EXACT slice of page_text."""
    if not page_text or not want:
        return []
    spans = _sentences(page_text)
    if not spans:
        return []
    windows = []
    for i in range(len(spans)):
        s, e = spans[i][0], spans[i][1]
        j = i
        while j + 1 < len(spans) and spans[j + 1][1] - s <= width:
            j += 1
            e = spans[j][1]
        chunk = page_text[s:min(e, s + width)]
        if is_chrome(chunk[:240]):
            continue
        sc = relevance(chunk, want)
        if sc > 0:
            windows.append((sc, s, s + len(chunk)))
    windows.sort(key=lambda w: (-w[0], w[1]))
    picked = []
    for sc, s, e in windows:
        if any(not (e <= ps or s >= pe) for _, ps, pe in picked):
            continue
        picked.append((sc, s, e))
        if len(picked) >= k:
            break
    picked.sort(key=lambda w: w[1])
    return [{"text": page_text[s:e], "score": round(sc, 2), "start": s} for sc, s, e in picked]


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "money transmitter registration prepaid access rewards tokens"
    c, l = search([q])
    for h in c:
        print("CITABLE", h["backend"], "|", h["authority"], "|", h["url"])
    for h in l:
        print("LEAD   ", h["backend"], "|", h["authority"])

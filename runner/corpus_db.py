#!/usr/bin/env python3
"""corpus_db.py — read-only client for the SHARED legal corpus (the smarter/apparently.cc project).

The orchestrator's own control plane (db.py) is one Supabase project; the regulatory corpus the
experts should be grounded in — corpus_documents (1,200+ primary sources: agency rules, court
opinions, guidance, statutes, AG opinions, no-action letters), corpus_clauses (15,000+ paragraph
units with text), corpus_authority_standing (783 authorities with human-review standing),
enforcement_actions, regulatory_feed_entries (Federal Register / eCFR change feed) — lives in a
DIFFERENT project. apparently-law already carries credentials for it (CORPUS_SUPABASE_URL /
CORPUS_SUPABASE_SERVICE_KEY); this module reads them from the environment first and from that
app's .env as a fallback, and exposes the same tiny select() shape db.py does.

READ-ONLY BY DESIGN. Nothing here writes. The corpus has its own review workflow (human review
raises standing and gates nothing — see apparently-law/docs/corpus-migrations/README.md); the
experts consume it and propose, they never mutate it. Legacy callers remain fail-soft;
strict callers distinguish an unavailable corpus from a successful empty read.
"""
from __future__ import annotations
import json
import re
import os
import math
import urllib.error
import urllib.parse
import urllib.request

APPARENTLY_LAW_DIR = os.environ.get("APPARENTLY_LAW_DIR", os.path.expanduser("~/Documents/apparently-law"))
_CREDS = None
MAX_READ_BYTES = 4 * 1024 * 1024


class CorpusReadError(RuntimeError):
    """Sanitized operational reason: never includes source text, URLs or credentials."""
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _creds():
    global _CREDS
    if _CREDS is not None:
        return _CREDS
    url = os.environ.get("CORPUS_SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("CORPUS_SUPABASE_SERVICE_KEY", "").strip()
    if not (url and key):
        try:
            with open(os.path.join(APPARENTLY_LAW_DIR, ".env")) as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    v = v.strip().strip('"').strip("'")
                    if k.strip() == "CORPUS_SUPABASE_URL" and not url:
                        url = v.rstrip("/")
                    elif k.strip() == "CORPUS_SUPABASE_SERVICE_KEY" and not key:
                        key = v
        except OSError:
            pass
    _CREDS = (url, key) if (url and key) else ("", "")
    return _CREDS


def available():
    url, key = _creds()
    return bool(url and key)


def select(table, params=None, timeout=40, *, strict=False):
    """Bounded GET. strict=True raises CorpusReadError rather than returning false emptiness."""
    url, key = _creds()
    if not (url and key):
        if strict:
            raise CorpusReadError("corpus_unconfigured")
        return []
    qs = urllib.parse.urlencode(params or {}, safe=".,()*:")
    req = urllib.request.Request(f"{url}/rest/v1/{table}" + (f"?{qs}" if qs else ""),
                                 headers={"apikey": key, "Authorization": f"Bearer {key}",
                                          "Accept": "application/json"})
    try:
        timeout = float(timeout)
        timeout = min(40, max(1, timeout)) if math.isfinite(timeout) else 40
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(MAX_READ_BYTES + 1)
        if len(raw) > MAX_READ_BYTES:
            raise CorpusReadError("corpus_response_budget")
        rows = json.loads(raw.decode("utf-8"))
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise CorpusReadError("corpus_response_invalid")
        return rows
    except urllib.error.HTTPError as error:
        reason = ("corpus_auth_error" if error.code in (401, 403) else
                  "corpus_query_error" if 400 <= error.code < 500 and error.code != 429 else
                  "corpus_unavailable")
        error.close()
    except CorpusReadError as error:
        reason = error.reason
    except (ValueError, UnicodeError, TypeError):
        reason = "corpus_response_invalid"
    except Exception:
        reason = "corpus_unavailable"
    if strict:
        raise CorpusReadError(reason) from None
    return []


def rpc(fn, args, timeout=40):
    """POST a read-only corpus function (e.g. search_corpus_passages_scoped). None on failure, so a
    caller can tell an outage from an empty answer."""
    url, key = _creds()
    if not (url and key):
        return None
    req = urllib.request.Request(f"{url}/rest/v1/rpc/{fn}", data=json.dumps(args).encode(),
                                 headers={"apikey": key, "Authorization": f"Bearer {key}",
                                          "Accept": "application/json", "Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=min(40, max(1, float(timeout)))) as r:
            raw = r.read(MAX_READ_BYTES + 1)
        if len(raw) > MAX_READ_BYTES:
            return None
        rows = json.loads(raw.decode("utf-8"))
        return rows if isinstance(rows, list) else None
    except Exception:
        return None


def passages_scoped(query, jurisdictions, limit=6):
    """Jurisdiction-scoped full-text passages (no embeddings, so it works when the host cannot run a
    local embedding model). Each row carries the clause's full text when it can be read. None on outage."""
    rows = rpc("search_corpus_passages_scoped", {"query_text": query, "p_jurisdictions": list(jurisdictions),
                                                 "p_include_federal": False, "p_limit": int(limit)})
    if rows is None:
        return None
    ids = [r.get("clause_id") for r in rows if r.get("clause_id")]
    full = {}
    if ids:
        for c in select("corpus_clauses", {"select": "clause_id,text",
                                           "clause_id": "in.(" + ",".join('"%s"' % i.replace('"', '') for i in ids) + ")"}):
            full[c.get("clause_id")] = c.get("text") or ""
    for r in rows:
        r["text"] = full.get(r.get("clause_id")) or r.get("snippet") or ""
    return rows


def document_text(doc_id, max_chars=60000, *, strict=False):
    """Ordered clause source text, then the original document text if no usable clauses.

    A failed clause query NEVER permits fallback: it is not evidence of missing
    clauses. Only source text is read; summaries and generated material are excluded.
    """
    try:
        max_chars = min(60000, max(0, int(max_chars)))
        rows = select("corpus_clauses", {"select": "clause_id,heading,text", "doc_id": f"eq.{doc_id}",
                                         "order": "clause_id.asc", "limit": "400"}, strict=True)
        parts, n = [], 0
        for row in rows:
            value = row.get("text")
            if value is not None and not isinstance(value, str):
                raise CorpusReadError("corpus_response_invalid")
            text = (value or "").strip()
            if not text:
                continue
            parts.append(text)
            n += len(text) + 2
            if n >= max_chars:
                break
        if parts:
            return "\n\n".join(parts)[:max_chars]
        rows = select("corpus_documents", {"select": "text", "doc_id": f"eq.{doc_id}", "limit": "1"}, strict=True)
        value = rows[0].get("text") if rows else None
        if value is not None and not isinstance(value, str):
            raise CorpusReadError("corpus_response_invalid")
        return (value or "").strip()[:max_chars]
    except CorpusReadError:
        if strict:
            raise
        return ""


# ── boilerplate removal ─────────────────────────────────────────────────────────────────────────
# Scraped pages carry the site's navigation into the document body. On WAC 260-12-010 the
# ambiguity scanner's fifteen top-weighted "undefined terms" were all menu entries ("District
# Finder", "Page Program", "House/Senate Class Photos"). Ingest should strip these; until it does,
# readers that ANALYSE the text call clean_text(). It only ever removes whole segments, so every
# sentence that survives is still a verbatim substring of the source.
_NAV_WORDS = re.compile(
    r"\b(skip to (main )?content|site ?map|contact us|privacy (policy|notice)|terms of use|accessibility|"
    r"log ?in|sign in|sign up|subscribe|rss|follow us|breadcrumb|toggle navigation|main menu|search (this )?site|"
    r"website search|print (this )?page|share this|back to top|district finder|find your (legislator|district)|"
    r"class photos|page program|internship program|bill information|cookie(s)? (policy|settings)|all rights reserved)\b",
    re.I)
_LEGAL_SIGNAL = re.compile(
    r"(\bshall\b|\bmust\b|\bmay not\b|\bmeans\b|\bincludes?\b|\bprohibit|\brequire|\bunlawful\b|\blicens|"
    r"\bpursuant\b|\bsubsection\b|\bsection\b|\bperson\b|§|\(\w{1,4}\)|\d)", re.I)


def _is_boilerplate(segment):
    t = segment.strip()
    if not t:
        return True
    words = t.split()
    if _NAV_WORDS.search(t) and len(words) < 40 and not re.search(r"\bshall\b|\bmeans\b|§", t, re.I):
        return True
    if len(words) <= 8 and not _LEGAL_SIGNAL.search(t) and not re.search(r"[.;:]$", t):
        return True
    # a run of Title Case labels with no verbs or punctuation is a menu, not a rule
    caps = sum(1 for w in words if w[:1].isupper())
    if len(words) >= 6 and caps / len(words) > 0.75 and not re.search(r"[.;:,]", t) and not _LEGAL_SIGNAL.search(t):
        return True
    return False


def clean_text(text):
    """Drop navigation and page chrome. Segments are removed whole; nothing is rewritten."""
    if not isinstance(text, str) or not text.strip():
        return text or ""
    out = []
    for block in re.split(r"\n\s*\n", text):
        lines = [ln for ln in block.split("\n") if not _is_boilerplate(ln)]
        kept = "\n".join(lines).strip()
        if kept and not _is_boilerplate(kept):
            out.append(kept)
    cleaned = "\n\n".join(out)
    # Page chrome is a minority of a real document. If "cleaning" would remove most of the text,
    # the heuristics have misread the document and the original is returned untouched.
    if len(cleaned) < 0.5 * len(text.strip()):
        return text
    return cleaned


def recent_feed(days=45, limit=40):
    import datetime
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    return select("regulatory_feed_entries", {
        "select": "title,summary,source_url,jurisdiction,urgency,gaming_verticals,entry_type,published_date,feed_source,status",
        "published_date": f"gte.{since}", "order": "published_date.desc", "limit": str(limit)})


if __name__ == "__main__":
    print(json.dumps({"available": available(),
                      "documents": len(select("corpus_documents", {"select": "doc_id", "limit": "5"})),
                      "feed_sample": recent_feed(limit=3)}, indent=2, default=str)[:1500])

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

#!/usr/bin/env python3
"""
moat_activate.py - activate engagement moat from seed data or live OPEN endpoints.

Seeds bootstrap the moat cycle from golden engagement JSON. The --live flag
hits real Federal Register / EDGAR endpoints (no API key needed).

Env vars:
    ORCH_MOAT_LIVE           "true" to hit real endpoints (default "false")
    ORCH_MOAT_SEED_PATH      override default seed path
    ORCH_MOAT_FR_LIMIT       max Federal Register results (default 5)
    ORCH_MOAT_EDGAR_LIMIT    max EDGAR results (default 5)
"""
import os, sys, json, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

try:
    import urllib.request
    import urllib.parse
except ImportError:
    urllib = None

LIVE = os.environ.get("ORCH_MOAT_LIVE", "false").lower() in ("1", "true", "yes")
FR_LIMIT = int(os.environ.get("ORCH_MOAT_FR_LIMIT", "5"))
EDGAR_LIMIT = int(os.environ.get("ORCH_MOAT_EDGAR_LIMIT", "5"))

DEFAULT_SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "seeds", "golden_engagements_seed.json")

_stats_lock = threading.Lock()
_stats = {"activations": 0, "seed_records": 0, "live_fr": 0,
          "live_edgar": 0, "errors": 0}


def _inc(key, n=1):
    with _stats_lock:
        _stats[key] = _stats.get(key, 0) + n


def _load_seed(seed_path=None):
    """Load golden engagements from seed JSON file."""
    path = seed_path or os.environ.get("ORCH_MOAT_SEED_PATH") or DEFAULT_SEED
    try:
        with open(path) as f:
            records = json.load(f)
        _inc("seed_records", len(records))
        return records
    except Exception:
        _inc("errors")
        return []


def _fetch_federal_register(limit=None):
    """Fetch recent documents from Federal Register API (no key needed)."""
    limit = limit or FR_LIMIT
    url = (f"https://www.federalregister.gov/api/v1/documents.json"
           f"?per_page={limit}&order=newest")
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": "beethoven-moat/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        results = data.get("results", [])
        records = []
        for doc in results[:limit]:
            records.append({
                "id": f"fr-{doc.get('document_number', '')}",
                "source": "federal_register",
                "title": doc.get("title", ""),
                "url": doc.get("html_url", ""),
                "full_text_url": doc.get("raw_text_url") or doc.get("html_url", ""),
                "published": doc.get("publication_date", ""),
                "stage": doc.get("type", "unknown"),
                "agency": (doc.get("agencies", [{}])[0].get("name", "")
                           if doc.get("agencies") else ""),
            })
        _inc("live_fr", len(records))
        return records
    except Exception:
        _inc("errors")
        return []


def _fetch_edgar(limit=None):
    """Fetch recent EDGAR full-text search results (no key needed)."""
    limit = limit or EDGAR_LIMIT
    url = (f"https://efts.sec.gov/LATEST/search-index"
           f"?q=%22annual+report%22&dateRange=custom"
           f"&startdt=2024-01-01&enddt=2025-01-01&forms=10-K")
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": "beethoven-moat/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        hits = data.get("hits", {}).get("hits", [])
        records = []
        for hit in hits[:limit]:
            src = hit.get("_source", {})
            records.append({
                "id": f"edgar-{src.get('file_num', hit.get('_id', ''))}",
                "source": "edgar",
                "title": src.get("display_names", [src.get("entity_name", "")])[0]
                         if src.get("display_names") else src.get("entity_name", ""),
                "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&filenum={src.get('file_num', '')}",
                "full_text_url": src.get("file_url", ""),
                "published": src.get("file_date", ""),
                "stage": "annual_filing",
            })
        _inc("live_edgar", len(records))
        return records
    except Exception:
        _inc("errors")
        return []


def trigger_once(seed_path=None, live=None):
    """Activate moat from seed data, optionally hitting live OPEN endpoints.

    Args:
        seed_path: path to seed JSON (default: runner/seeds/golden_engagements_seed.json)
        live: if True, also fetch from Federal Register + EDGAR
    Returns:
        list of engagement records
    """
    use_live = live if live is not None else LIVE
    records = _load_seed(seed_path or DEFAULT_SEED)
    if use_live:
        records.extend(_fetch_federal_register())
        records.extend(_fetch_edgar())
    _inc("activations")
    return records


def stats():
    with _stats_lock:
        return dict(_stats)


def reset_stats():
    with _stats_lock:
        for k in _stats:
            _stats[k] = 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Activate moat from seed data")
    parser.add_argument("--live", action="store_true", help="Hit real OPEN endpoints")
    parser.add_argument("--seed", default=None, help="Path to seed JSON")
    args = parser.parse_args()
    results = trigger_once(seed_path=args.seed, live=args.live)
    print(json.dumps({"activated": len(results), "records": results[:3]}, indent=2))

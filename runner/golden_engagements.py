#!/usr/bin/env python3
"""
golden_engagements.py — schema for real regulatory matters as ordered stage sequences.

Each golden engagement captures a CONFIRMED real-world regulatory proceeding with:
  {stage_input, real_next_document, real_outcome}

Ingester adapters (network INJECTED/mocked in tests; urllib only, no requests):
  - Federal Register API (open)
  - SEC EDGAR (open)
  - regulations.gov (REGULATIONS_GOV_API_KEY)
  - CourtListener/RECAP (COURTLISTENER_API_TOKEN)

CONFIRMED seed: CFTC "Prediction Markets; Public Interest Determinations"
  FR doc 2026-11854 (91 FR 35806, NPRM 2026-06-12), ANPRM 91 FR 12516
"""
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

@dataclass
class StageDocument:
    """A document produced or consumed at a stage."""
    doc_id: str               # e.g. "2026-11854" (FR doc number)
    title: str
    source: str               # e.g. "federal_register", "sec_edgar"
    url: str
    published_date: str       # ISO date
    doc_type: str             # e.g. "NPRM", "ANPRM", "final_rule", "comment"


@dataclass
class Stage:
    """One stage in a regulatory engagement."""
    order: int
    name: str                 # e.g. "ANPRM", "Comment Period", "NPRM"
    stage_input: str          # what triggered this stage
    real_next_document: Optional[StageDocument] = None
    real_outcome: str = ""    # what actually happened
    started: str = ""         # ISO date
    ended: str = ""           # ISO date


@dataclass
class GoldenEngagement:
    """A confirmed real regulatory matter as an ordered stage sequence."""
    matter_id: str
    title: str
    agency: str
    docket_id: str
    status: str               # "active", "closed", "pending"
    stages: List[Stage] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


# ---------------------------------------------------------------------------
# Ingester adapters — network function is INJECTED for testability
# ---------------------------------------------------------------------------

def _default_fetch(url: str, headers: dict = None) -> dict:
    """Default network fetcher using urllib (no requests dependency)."""
    req = Request(url, headers=headers or {})
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except (URLError, json.JSONDecodeError) as e:
        return {"error": str(e)}


class FederalRegisterIngester:
    """Fetch documents from the Federal Register API (open, no key needed)."""
    BASE = "https://www.federalregister.gov/api/v1"

    def __init__(self, fetch: Callable = None):
        self.fetch = fetch or _default_fetch

    def get_document(self, doc_number: str) -> Optional[StageDocument]:
        data = self.fetch(f"{self.BASE}/documents/{doc_number}.json")
        if "error" in data or "title" not in data:
            return None
        return StageDocument(
            doc_id=doc_number, title=data.get("title", ""),
            source="federal_register",
            url=data.get("html_url", f"https://www.federalregister.gov/d/{doc_number}"),
            published_date=data.get("publication_date", ""),
            doc_type=data.get("type", "unknown"),
        )


class SECEdgarIngester:
    """Fetch filings from SEC EDGAR (open, no key needed)."""
    BASE = "https://efts.sec.gov/LATEST/search-index"

    def __init__(self, fetch: Callable = None):
        self.fetch = fetch or _default_fetch

    def search_filings(self, query: str, limit: int = 5) -> List[StageDocument]:
        data = self.fetch(
            f"https://efts.sec.gov/LATEST/search-index?q={query}&dateRange=custom&startdt=2025-01-01&forms=&hits.hits.total=true",
            headers={"User-Agent": "golden-engagements/1.0"}
        )
        if "error" in data:
            return []
        hits = data.get("hits", {}).get("hits", [])[:limit]
        return [
            StageDocument(
                doc_id=h.get("_id", ""), title=h.get("_source", {}).get("file_description", ""),
                source="sec_edgar", url=f"https://www.sec.gov/Archives/edgar/data/{h.get('_id', '')}",
                published_date=h.get("_source", {}).get("file_date", ""), doc_type="filing",
            ) for h in hits
        ]


class RegulationsGovIngester:
    """Fetch docket/comment data from regulations.gov (requires API key)."""
    BASE = "https://api.regulations.gov/v4"

    def __init__(self, fetch: Callable = None, api_key: str = None):
        self.fetch = fetch or _default_fetch
        self.api_key = api_key or os.environ.get("REGULATIONS_GOV_API_KEY", "")

    def get_docket(self, docket_id: str) -> Optional[dict]:
        if not self.api_key:
            return None
        data = self.fetch(
            f"{self.BASE}/dockets/{docket_id}",
            headers={"X-Api-Key": self.api_key}
        )
        return data if "error" not in data else None


class CourtListenerIngester:
    """Fetch opinions/dockets from CourtListener/RECAP (requires API token)."""
    BASE = "https://www.courtlistener.com/api/rest/v3"

    def __init__(self, fetch: Callable = None, api_token: str = None):
        self.fetch = fetch or _default_fetch
        self.api_token = api_token or os.environ.get("COURTLISTENER_API_TOKEN", "")

    def search_opinions(self, query: str, limit: int = 5) -> List[StageDocument]:
        if not self.api_token:
            return []
        data = self.fetch(
            f"{self.BASE}/search/?q={query}&type=o&page_size={limit}",
            headers={"Authorization": f"Token {self.api_token}"}
        )
        if "error" in data or "results" not in data:
            return []
        return [
            StageDocument(
                doc_id=str(r.get("id", "")),
                title=r.get("caseName", r.get("case_name", "")),
                source="courtlistener",
                url=f"https://www.courtlistener.com{r.get('absolute_url', '')}",
                published_date=r.get("dateFiled", r.get("date_filed", "")),
                doc_type="opinion",
            ) for r in data["results"][:limit]
        ]


# ---------------------------------------------------------------------------
# CONFIRMED seed: CFTC Prediction Markets
# ---------------------------------------------------------------------------

CFTC_PREDICTION_MARKETS = GoldenEngagement(
    matter_id="cftc-prediction-markets-2026",
    title='CFTC "Prediction Markets; Public Interest Determinations"',
    agency="CFTC",
    docket_id="CFTC-2026-0005",
    status="active",
    stages=[
        Stage(
            order=1, name="ANPRM",
            stage_input="CFTC seeks public input on prediction markets regulation",
            real_next_document=StageDocument(
                doc_id="2026-03140", title="Event Contracts; Advance Notice of Proposed Rulemaking",
                source="federal_register",
                url="https://www.federalregister.gov/d/2026-03140",
                published_date="2026-02-18", doc_type="ANPRM",
            ),
            real_outcome="91 FR 12516 — ANPRM published, 60-day comment period",
            started="2026-02-18", ended="2026-04-21",
        ),
        Stage(
            order=2, name="NPRM",
            stage_input="CFTC proposes specific rules based on ANPRM comments",
            real_next_document=StageDocument(
                doc_id="2026-11854",
                title="Prediction Markets; Public Interest Determinations",
                source="federal_register",
                url="https://www.federalregister.gov/d/2026-11854",
                published_date="2026-06-12", doc_type="NPRM",
            ),
            real_outcome="91 FR 35806 — NPRM published, comment period open",
            started="2026-06-12", ended="",
        ),
    ],
    metadata={
        "fr_citation_anprm": "91 FR 12516",
        "fr_citation_nprm": "91 FR 35806",
        "related_exchanges": ["Kalshi", "Polymarket", "CME"],
    },
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_GOLDEN_ENGAGEMENTS: Dict[str, GoldenEngagement] = {
    CFTC_PREDICTION_MARKETS.matter_id: CFTC_PREDICTION_MARKETS,
}


def get_engagement(matter_id: str) -> Optional[GoldenEngagement]:
    return _GOLDEN_ENGAGEMENTS.get(matter_id)


def list_engagements() -> List[GoldenEngagement]:
    return list(_GOLDEN_ENGAGEMENTS.values())


if __name__ == "__main__":
    for eng in list_engagements():
        print(json.dumps(eng.to_dict(), indent=2, default=str))

"""
golden_engagements.py - Schema and ingester adapters for real regulatory matters.

Defines an ordered stage sequence for a real matter:
  {stage_input, real_next_document, real_outcome}

Ingester adapters for:
  - Federal Register API (open)
  - SEC EDGAR (open)
  - regulations.gov (requires REGULATIONS_GOV_API_KEY)
  - CourtListener/RECAP (requires COURTLISTENER_API_TOKEN)

All adapters use urllib only (no requests library). Network is injected
so tests run offline with bundled fixtures.
"""
from __future__ import annotations
import json
import urllib.request
import urllib.error
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional


@dataclass
class Stage:
    """A single stage in a regulatory engagement."""
    name: str
    stage_input: str
    real_next_document: Optional[str] = None
    real_outcome: Optional[str] = None


@dataclass
class GoldenEngagement:
    """A real matter represented as an ordered sequence of stages."""
    matter_id: str
    title: str
    agency: str
    stages: list[Stage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GoldenEngagement":
        stages = [Stage(**s) for s in data.get("stages", [])]
        return cls(
            matter_id=data["matter_id"],
            title=data["title"],
            agency=data["agency"],
            stages=stages,
            metadata=data.get("metadata", {}),
        )


# ── Ingester adapters ───────────────────────────────────────────
# Each adapter takes a fetcher callable (url -> bytes) so tests can
# inject fixtures without network access.

Fetcher = Callable[[str, Optional[dict[str, str]]], bytes]


def _default_fetcher(url: str, headers: Optional[dict[str, str]] = None) -> bytes:
    """Default fetcher using urllib (no requests dependency)."""
    req = urllib.request.Request(url)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def ingest_federal_register(
    doc_number: str, fetcher: Fetcher = _default_fetcher
) -> dict[str, Any]:
    """Fetch a Federal Register document by doc number."""
    url = f"https://www.federalregister.gov/api/v1/documents/{doc_number}.json"
    raw = fetcher(url, None)
    return json.loads(raw)


def ingest_edgar(
    accession: str, fetcher: Fetcher = _default_fetcher
) -> dict[str, Any]:
    """Fetch an SEC EDGAR filing by accession number."""
    clean = accession.replace("-", "")
    url = f"https://efts.sec.gov/LATEST/search-index?q=%22{clean}%22&dateRange=custom&startdt=2020-01-01"
    raw = fetcher(url, {"User-Agent": "cade-orchestrator/1.0"})
    return json.loads(raw)


def ingest_regulations_gov(
    docket_id: str, api_key: str, fetcher: Fetcher = _default_fetcher
) -> dict[str, Any]:
    """Fetch a regulations.gov docket by ID."""
    url = f"https://api.regulations.gov/v4/dockets/{docket_id}"
    raw = fetcher(url, {"X-Api-Key": api_key, "Content-Type": "application/json"})
    return json.loads(raw)


def ingest_courtlistener(
    case_id: str, api_token: str, fetcher: Fetcher = _default_fetcher
) -> dict[str, Any]:
    """Fetch a CourtListener/RECAP case by ID."""
    url = f"https://www.courtlistener.com/api/rest/v4/dockets/{case_id}/"
    raw = fetcher(url, {"Authorization": f"Token {api_token}"})
    return json.loads(raw)


def build_golden_seed() -> GoldenEngagement:
    """Build the confirmed golden seed: CFTC Prediction Markets NPRM."""
    return GoldenEngagement(
        matter_id="cftc-prediction-markets-2026",
        title="Prediction Markets; Public Interest Determinations",
        agency="CFTC",
        stages=[
            Stage(
                name="anprm",
                stage_input="CFTC issues ANPRM on event contracts",
                real_next_document="91 FR 12516",
                real_outcome="Public comment period opened",
            ),
            Stage(
                name="nprm",
                stage_input="CFTC publishes NPRM based on ANPRM comments",
                real_next_document="FR doc 2026-11854 (91 FR 35806)",
                real_outcome="Proposed rule for public interest determinations",
            ),
            Stage(
                name="related_nprm",
                stage_input="Related NPRM on event contract amendments",
                real_next_document="FR doc 2026-13239",
                real_outcome="Additional proposed amendments",
            ),
            Stage(
                name="comment_period",
                stage_input="Public comment period on NPRM",
                real_next_document=None,
                real_outcome="Awaiting comments and final rule",
            ),
        ],
        metadata={
            "fr_doc_number": "2026-11854",
            "fr_citation": "91 FR 35806",
            "publication_date": "2026-06-12",
            "anprm_citation": "91 FR 12516",
            "related_nprm_doc": "2026-13239",
        },
    )

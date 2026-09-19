#!/usr/bin/env python3
"""benchmark_ingest.py — source the benchmark targets so benchmark_redlines.py can run (§7.4).

benchmark_redlines refuses to redline a filing we do not hold (integrity rule 1): a target stays
`pending_source` until the public filing's text is ingested through benchmark_redlines.ingest_source,
which records a SHA-256 digest of exactly what we held. The five seeded targets carried only hints
("Supreme Court docket 16-476", "courtlistener.com"). This job turns a hint into a held filing:
one research call on the mid tier locates the PRIMARY public filing on an official or canonical
source (supremecourt.gov, the court's site, CourtListener/RECAP, justice.gov, a state AG site),
opens it, and returns a verbatim excerpt of the argument sections plus the URL. Budget-gated; one
target per run by default; never overwrites a held source unless BENCH_INGEST_FORCE=true.

    python3 benchmark_ingest.py              # ingest the next pending target(s)
    python3 benchmark_ingest.py --dry-run    # show which target would run and the prompt
    python3 benchmark_ingest.py --status     # counts by status
"""
from __future__ import annotations
import datetime
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import frontier

BATCH = int(os.environ.get("BENCH_INGEST_BATCH", "1"))
MIN_TOKENS = int(os.environ.get("ORCH_BENCH_INGEST_MIN_TOKENS", "80000"))
FORCE = os.environ.get("BENCH_INGEST_FORCE", "false").lower() in ("1", "true", "yes", "on")
NEED = int(os.environ.get("ORCH_BENCH_INGEST_NEED", "7"))
MAX_TURNS = int(os.environ.get("ORCH_BENCH_INGEST_TURNS", "16"))
MIN_EXCERPT = 3000
MIN_CONFIDENCE = 0.6

SCHEMA = {"type": "object", "properties": {
    "filing_url": {"type": "string"}, "filing_title": {"type": "string"}, "filing_party": {"type": "string"},
    "court": {"type": "string"}, "docket_no": {"type": "string"}, "filed_date": {"type": "string"},
    "source_excerpt": {"type": "string"},
    "table_of_contents": {"type": "array", "items": {"type": "string"}},
    "sources_opened": {"type": "array", "items": {"type": "string"}},
    "confidence": {"type": "number"}, "unavailable_reason": {"type": "string"}},
    "required": ["filing_url", "filing_title", "filing_party", "court", "docket_no", "filed_date",
                 "source_excerpt", "table_of_contents", "sources_opened", "confidence", "unavailable_reason"]}

SYSTEM = """You are a court-records clerk sourcing a PUBLIC filing for a benchmark redline. Locate the PRIMARY
filing for the matter described — the merits brief, the principal appellate brief or opinion, or
the lead consent decree/complaint — on an official or canonical public source: supremecourt.gov,
the court's own site, CourtListener/RECAP, justice.gov, a state attorney general's site, or the
agency docket. Open it with WebFetch. Then return JSON:
 * filing_url: the URL you actually opened (a PDF or HTML of the filing itself, not a blog summary);
 * source_excerpt: VERBATIM text of the filing's argument sections, in order, up to ~24,000
   characters — no paraphrase, no summary, no added headings. If the document is a PDF you could not
   read, say so in unavailable_reason and set confidence below 0.5;
 * table_of_contents: the filing's argument headings; filing_party/court/docket_no/filed_date as filed;
 * confidence: that filing_url is the canonical primary filing and source_excerpt is verbatim.
For a LINE of matters (several cases), pick the single most canonical filing and name it in
filing_title. TOOL BUDGET: at most {tool_budget} tool calls; stop and write the JSON when spent.
Return ONLY the JSON object."""

USER = """TARGET: {case_name}
COURT: {court}   DOCKET: {docket_no}   TYPE: {filing_type}   VERTICAL: {vertical}
WHERE THE PUBLIC FILINGS LIVE (hint): {filing_url}
WHY IT MATTERS: {stakes}
TODAY: {today}

Find and open the primary filing, then return the JSON object."""


def _targets(limit):
    try:
        return db.select("benchmark_targets", {
            "select": "id,case_name,court,docket_no,vertical,filing_type,filing_url,stakes,source_text,status,priority",
            "status": "eq.pending_source", "order": "priority.asc,created_at.asc", "limit": str(limit)}) or []
    except Exception:
        return []


def prompt_for(t):
    return USER.format(case_name=t.get("case_name") or "", court=t.get("court") or "", docket_no=t.get("docket_no") or "n/a",
                       filing_type=t.get("filing_type") or "", vertical=t.get("vertical") or "",
                       filing_url=t.get("filing_url") or "", stakes=(t.get("stakes") or "")[:600],
                       today=datetime.date.today().isoformat())


def decide(j):
    """-> (status, reason) from the research JSON."""
    ex = str((j or {}).get("source_excerpt") or "")
    conf = float((j or {}).get("confidence") or 0)
    url = str((j or {}).get("filing_url") or "").strip()
    if len(ex) >= MIN_EXCERPT and conf >= MIN_CONFIDENCE and url.startswith("http"):
        return "ready", ""
    why = str((j or {}).get("unavailable_reason") or "")
    return "source_unavailable", (why or f"excerpt {len(ex)} chars, confidence {conf:.2f}, url={'ok' if url else 'missing'}")[:300]


def ingest_one(t, research=None):
    research = research or frontier.complete
    r = research(prompt_for(t), system=SYSTEM.format(tool_budget=max(4, MAX_TURNS - 4)), need=NEED,
                 tools=frontier.WEB_TOOLS, max_turns=MAX_TURNS, json_schema=SCHEMA, timeout=900, tag="benchmark.ingest")
    j = r.get("json") if isinstance(r.get("json"), dict) else None
    meta = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "model": r.get("model"),
            "tokens_in": r.get("tokens_in"), "tokens_out": r.get("tokens_out"), "error": r.get("error") or "",
            "sources_opened": ((j or {}).get("sources_opened") or [])[:12], "confidence": (j or {}).get("confidence"),
            "filing_title": (j or {}).get("filing_title"), "salvaged": bool(r.get("salvaged"))}
    if r.get("error") or not j:
        return {"id": t.get("id"), "status": "pending_source", "reason": r.get("error") or "no JSON", "ingest": meta}
    status, reason = decide(j)
    patch = {"filing_party": (j.get("filing_party") or None), "docket_no": (j.get("docket_no") or t.get("docket_no") or None),
             "process": {**_proc(t), "ingest": meta, "toc": (j.get("table_of_contents") or [])[:40]},
             "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if status == "ready":
        import benchmark_redlines
        res = benchmark_redlines.ingest_source(t["id"], j["source_excerpt"], filing_url=j["filing_url"])
        if res.get("error"):
            status, reason = "pending_source", res["error"]
        else:
            patch["process"]["ingest"]["digest"] = res.get("digest")
    else:
        patch["status"] = "source_unavailable"
        patch["process"]["ingest"]["reason"] = reason
        if j.get("filing_url", "").startswith("http"):
            patch["filing_url"] = j["filing_url"]
    try:
        db.update("benchmark_targets", {"id": t["id"]}, patch)
    except Exception as e:
        reason = f"{reason} | update failed: {e}"
    return {"id": t.get("id"), "case": (t.get("case_name") or "")[:60], "status": status, "reason": reason,
            "excerpt_chars": len(str(j.get("source_excerpt") or "")), "filing_url": j.get("filing_url"), "ingest": meta}


def _proc(t):
    p = t.get("process")
    if isinstance(p, str):
        try:
            p = json.loads(p)
        except Exception:
            p = {}
    return p if isinstance(p, dict) else {}


def run(limit=BATCH, dry_run=False):
    out = {"considered": 0, "ingested": 0, "unavailable": 0, "skipped_budget": 0, "results": []}
    for t in _targets(limit * 2):
        if out["considered"] >= limit:
            break
        if (t.get("source_text") or "") and not FORCE:
            continue
        if dry_run:
            out["considered"] += 1
            out["results"].append({"id": t.get("id"), "case": t.get("case_name"), "prompt": prompt_for(t)})
            continue
        if not frontier.available(min_tokens=MIN_TOKENS):
            out["skipped_budget"] += 1
            break
        out["considered"] += 1
        res = ingest_one(t)
        out["results"].append(res)
        out["ingested" if res["status"] == "ready" else "unavailable" if res["status"] == "source_unavailable" else "skipped_budget"] += 1
    return out


def status():
    try:
        rows = db.select("benchmark_targets", {"select": "status", "limit": "200"}) or []
    except Exception:
        rows = []
    counts = {}
    for r in rows:
        counts[r.get("status")] = counts.get(r.get("status"), 0) + 1
    return counts


if __name__ == "__main__":
    if "--status" in sys.argv:
        print(json.dumps(status(), indent=2))
    else:
        print(json.dumps(run(dry_run="--dry-run" in sys.argv), indent=2, default=str)[:6000])

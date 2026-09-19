import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import benchmark_ingest as bi  # noqa: E402


def test_schema_is_strictable_and_decision_rules():
    import frontier
    s = frontier.strict_schema(bi.SCHEMA)
    assert s["additionalProperties"] is False and set(s["required"]) == set(bi.SCHEMA["properties"])
    assert bi.decide({"source_excerpt": "x" * 3000, "confidence": 0.8, "filing_url": "https://a"}) == ("ready", "")
    st, why = bi.decide({"source_excerpt": "x" * 500, "confidence": 0.9, "filing_url": "https://a", "unavailable_reason": "PDF unreadable"})
    assert st == "source_unavailable" and why == "PDF unreadable"
    st, why = bi.decide({"source_excerpt": "x" * 5000, "confidence": 0.3, "filing_url": "https://a"})
    assert st == "source_unavailable" and "confidence 0.30" in why


def test_ingest_goes_through_benchmark_redlines_door(monkeypatch):
    writes = []   # bi.db and benchmark_redlines.db are the same module; tell the writes apart by content
    monkeypatch.setattr(bi.db, "update", lambda t, m, p: writes.append(("br" if "source_digest" in p else "bi", t, m, p)))
    t = {"id": "t1", "case_name": "Murphy v. NCAA", "court": "SCOTUS", "docket_no": None, "filing_type": "brief",
         "vertical": "gaming", "filing_url": "docket 16-476", "stakes": "s", "process": {}}
    excerpt = "ARGUMENT " * 600
    research = lambda prompt, **kw: {"error": "", "model": "claude-opus-5", "tokens_in": 10, "tokens_out": 5, "json": {
        "filing_url": "https://www.supremecourt.gov/x.pdf", "filing_title": "Brief for Petitioners", "filing_party": "NJ",
        "court": "SCOTUS", "docket_no": "16-476", "filed_date": "2017-08-29", "source_excerpt": excerpt,
        "table_of_contents": ["I", "II"], "sources_opened": ["https://www.supremecourt.gov/x.pdf"], "confidence": 0.9,
        "unavailable_reason": ""}}
    assert "Murphy v. NCAA" in bi.prompt_for(t) and "docket 16-476" in bi.prompt_for(t)
    res = bi.ingest_one(t, research=research)
    assert res["status"] == "ready" and res["excerpt_chars"] == len(excerpt)
    door = [w for w in writes if w[0] == "br"][0]
    assert door[3]["status"] == "ready" and door[3]["filing_url"] == "https://www.supremecourt.gov/x.pdf"
    import hashlib
    assert door[3]["source_digest"] == hashlib.sha256(excerpt.encode()).hexdigest()
    mine = [w for w in writes if w[0] == "bi"][0]
    assert mine[3]["docket_no"] == "16-476" and mine[3]["process"]["ingest"]["digest"] == door[3]["source_digest"]
    assert "status" not in mine[3]          # status is set only through the redlines door


def test_unavailable_and_failed_research(monkeypatch):
    writes = []
    monkeypatch.setattr(bi.db, "update", lambda t, m, p: writes.append((t, m, p)))
    t = {"id": "t2", "case_name": "Kalshi line", "process": '{"k": 1}'}
    res = bi.ingest_one(t, research=lambda prompt, **kw: {"error": "", "model": "m", "json": {
        "filing_url": "https://x", "filing_title": "", "filing_party": "", "court": "", "docket_no": "", "filed_date": "",
        "source_excerpt": "short", "table_of_contents": [], "sources_opened": [], "confidence": 0.9, "unavailable_reason": "PDF unreadable"}})
    assert res["status"] == "source_unavailable" and writes[0][2]["status"] == "source_unavailable"
    assert writes[0][2]["process"]["k"] == 1 and writes[0][2]["process"]["ingest"]["reason"] == "PDF unreadable"
    res = bi.ingest_one(t, research=lambda prompt, **kw: {"error": "API Error", "model": "m", "json": None})
    assert res["status"] == "pending_source" and len(writes) == 1     # nothing written on a failed call


def test_run_respects_budget_and_held_sources(monkeypatch):
    monkeypatch.setattr(bi, "_targets", lambda n: [{"id": "held", "source_text": "x" * 5000}, {"id": "p", "case_name": "c"}])
    monkeypatch.setattr(bi.frontier, "available", lambda min_tokens=0: False)
    out = bi.run(limit=2)
    assert out["skipped_budget"] == 1 and out["considered"] == 0
    out = bi.run(limit=2, dry_run=True)
    assert out["considered"] == 1 and out["results"][0]["id"] == "p" and "prompt" in out["results"][0]

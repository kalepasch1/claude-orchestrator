"""Consilium engineering tribunal (run_code) and its hooks — no model calls."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

DIFF = """diff --git a/runner/x.py b/runner/x.py
--- a/runner/x.py
+++ b/runner/x.py
@@ -1,4 +1,5 @@
-    card["citations"] = json.dumps(citations)[:8000]
+    card["citations"] = _json_capped(citations, 60000)
+    db.update("legal_docket", {"id": row["id"]}, {"status": "answered"})
"""


def _tribunal(verdict="revise", risk=0.4, findings=None, seats=None):
    return {"seats": seats or [
        {"seat": "Correctness & Regression", "r1_position": "revise", "r1_analysis": "a", "steelman": "s", "moved": True,
         "r3_outcome": "hold", "r3_position": "revise: cap", "r3_probability": 0.7},
        {"seat": "Security & Abuse", "r1_position": "approve", "r1_analysis": "a", "steelman": "s", "moved": False,
         "r3_outcome": "hold", "r3_position": "approve", "r3_probability": 0.9}],
        "findings": findings if findings is not None else [
            {"severity": "major", "file": "runner/x.py", "where": "mint_card", "seat": "Correctness & Regression",
             "claim": "docket marked answered before the card insert is confirmed",
             "evidence": 'db.update("legal_docket", {"id": row["id"]}, {"status": "answered"})', "fix": "move after insert"},
            {"severity": "blocker", "file": "runner/y.py", "where": "nowhere", "seat": "Security & Abuse",
             "claim": "invented", "evidence": "os.system(user_input)", "fix": "n/a"}],
        "red_team": {"attack": "a", "severity": "medium", "failing_scenario": "f"},
        "memo": {"verdict": verdict, "summary": "sum", "risk": risk, "conditions": "c", "dissent": "d", "rollout": "canary"}}


def test_has_diff_and_verbatim_finding_verification():
    import consilium_v2 as c
    assert c.has_diff(DIFF) and not c.has_diff("please add a button") and not c.has_diff("")
    out = c.verify_findings(_tribunal()["findings"], DIFF)
    assert out[0]["verified"] is True and out[0]["severity"] == "major"
    assert out[1]["verified"] is False and out[1]["severity"] == "unverified" and out[1]["severity_claimed"] == "blocker"
    assert c.verify_findings([{"severity": "nit", "evidence": "short"}], DIFF)[0]["verified"] is False  # too short to be evidence


def test_run_code_returns_committee_shape_and_demotes_unverified_blockers(monkeypatch, tmp_path):
    import consilium_v2 as c
    import frontier
    calls = []
    monkeypatch.setattr(c, "ENABLED", True)
    monkeypatch.setattr(c, "_append_transcript", lambda rec: None)
    monkeypatch.setattr(frontier, "available", lambda min_tokens=4000: True)

    def complete(prompt, **kw):
        calls.append(kw)
        assert kw["tools"] is None and kw["max_turns"] == 1 and "ENGINEERING TRIBUNAL" in kw["system"]
        assert "DIFF (the record" in prompt and 'Correctness & Regression' in prompt
        return {"error": "", "model": "claude-opus-5", "json": _tribunal(), "tokens_in": 9000, "tokens_out": 3000}
    monkeypatch.setattr(frontier, "complete", complete)
    agg = c.run_code("Fix citations cap", "context", DIFF, project="claude-orchestrator", blast_radius=0.5)
    assert calls[0]["need"] == 8
    assert agg["recommendation"] == "REVISE" and agg["verdict"] == "revise" and agg["risk"] == 0.4
    assert agg["aggregate"] == 8.0                      # mean r3 probability × 10
    assert agg["critical"] is False                      # the only "blocker" was unverified
    assert agg["process"]["verified_findings"] == 1 and agg["process"]["blockers"] == 0
    assert [p["verdict"] for p in agg["panel"]] == ["needs-info", "support"]
    assert agg["auto_ok"] is False and agg["escalate"] is False
    # high blast radius -> Fable; an approve with a verified blocker is downgraded to revise
    monkeypatch.setattr(frontier, "complete", lambda prompt, **kw: calls.append(kw) or {
        "error": "", "model": frontier.FABLE, "tokens_in": 1, "tokens_out": 1,
        "json": _tribunal("approve", 0.1, findings=[{"severity": "blocker", "file": "runner/x.py", "where": "w", "seat": "s",
                                                     "claim": "c", "evidence": 'card["citations"] = _json_capped(citations, 60000)', "fix": "f"}])})
    agg = c.run_code("t", "", DIFF, blast_radius=0.9)
    assert calls[-1]["need"] == 9 and agg["verdict"] == "revise" and agg["critical"] is True
    # no diff / no budget -> None
    assert c.run_code("t", "prose only", "") is None
    monkeypatch.setattr(frontier, "available", lambda min_tokens=4000: False)
    assert c.run_code("t", "", DIFF) is None


def test_committees_routes_material_diffs_to_the_tribunal(monkeypatch):
    import committees as cm
    import consilium_v2 as c
    seen = []
    monkeypatch.setattr(cm, "CONSILIUM_CODE", True)
    monkeypatch.setattr(c, "run_code", lambda title, body, **kw: seen.append(kw) or {"aggregate": 8.0, "recommendation": "GO", "verdict": "approve"})
    monkeypatch.setattr(cm, "_triage_panels", lambda *a, **k: (_ for _ in ()).throw(AssertionError("legacy panels must not run")))
    body = "production migration touching billing for all users\n" + DIFF
    out = cm.review("task", "id1", "Migrate billing table", body, app="tomorrow")
    assert out["recommendation"] == "GO" and out["materiality"] >= 0.5 and seen[0]["project"] == "tomorrow"
    # low-materiality prose without a diff falls through to the legacy path
    monkeypatch.setattr(cm, "_triage_panels", lambda *a, **k: [])
    out = cm.review("task", "id2", "Rename a variable", "tidy naming", app="tomorrow")
    assert out["recommendation"] == "HOLD" and out["panel"] == []
    # a tribunal failure is fail-soft
    monkeypatch.setattr(c, "run_code", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cm.review("task", "id3", "Migrate billing table", body, app="tomorrow")["panel"] == []


def test_premerge_cothink_takes_the_stricter_verdict(monkeypatch):
    import illuminati_cothink as ic
    import consilium_v2 as c
    monkeypatch.setattr(ic, "ENABLED", True)
    monkeypatch.setattr(ic, "CONSILIUM_PREMERGE", True)
    monkeypatch.setattr(ic, "_post", lambda path, body: {"verdict": "proceed", "rationale": "fine", "dimensions": [{"d": 1}]})
    monkeypatch.setattr(c, "run_code", lambda title, body, diff, **kw: {
        "verdict": "block", "risk": 0.8, "recommendation": "HOLD", "summary": "unsafe",
        "findings": [{"severity": "blocker", "claim": "c", "file": "f", "evidence": "e", "verified": True}], "process": {"engine": "consilium_v2.code"}})
    v = ic.review("premerge", {"title": "t", "diff": DIFF, "project": "p"})
    assert v["verdict"] == "escalate" and v["rationale"].startswith("Consilium engineering tribunal: unsafe")
    assert len(v["dimensions"]) == 2 and v["dimensions"][1]["dimension"] == "code:blocker" and v["consilium"]["verdict"] == "block"
    # remote stricter than tribunal -> remote verdict kept, tribunal still attached
    monkeypatch.setattr(ic, "_post", lambda path, body: {"verdict": "escalate", "rationale": "legal", "dimensions": []})
    monkeypatch.setattr(c, "run_code", lambda *a, **k: {"verdict": "approve", "risk": 0.1, "recommendation": "GO", "summary": "ok", "findings": [], "process": {}})
    v = ic.review("premerge", {"title": "t", "diff": DIFF})
    assert v["verdict"] == "escalate" and v["rationale"] == "legal" and v["consilium"]["verdict"] == "approve"
    # remote unreachable -> degraded proceed is replaced by the tribunal's verdict
    import urllib.error
    monkeypatch.setattr(ic, "_post", lambda path, body: (_ for _ in ()).throw(urllib.error.URLError("down")))
    monkeypatch.setattr(c, "run_code", lambda *a, **k: {"verdict": "revise", "risk": 0.4, "recommendation": "REVISE", "summary": "r", "findings": [], "process": {}})
    v = ic.review("premerge", {"title": "t", "diff": DIFF})
    assert v["verdict"] == "review" and v["degraded"] is False
    # no diff in the subject -> untouched degraded verdict; non-premerge phases never call the tribunal
    v = ic.review("premerge", {"title": "t", "body": "prose"})
    assert v["verdict"] == "proceed" and v["degraded"] is True
    monkeypatch.setattr(c, "run_code", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    monkeypatch.setattr(ic, "_post", lambda path, body: {"verdict": "proceed", "rationale": "", "dimensions": []})
    assert ic.review("build", {"diff": DIFF})["verdict"] == "proceed"

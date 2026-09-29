"""The fallback chain: Claude -> GPT-5.5 -> local, and what each lower tier may decide."""
import json
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def _setup(monkeypatch, tmp_path, *, claude=True, codex=True, local=True, strong_resident=False):
    import frontier
    monkeypatch.setattr(frontier, "NEVER_IDLE", True)
    monkeypatch.setattr(frontier, "STATE", str(tmp_path / "b.json"))
    monkeypatch.setattr(frontier, "HOME", str(tmp_path))
    monkeypatch.setattr(frontier, "tier_available", lambda t, m=4000: {"frontier": claude, "codex": codex, "local": local}[t])
    monkeypatch.setattr(frontier, "codex_available", lambda *a, **k: codex)
    monkeypatch.setattr(frontier, "_strong_local_resident", lambda: "exo:mlx-community/Qwen3.5-35B-A3B-4bit" if strong_resident else None)
    monkeypatch.setattr(frontier, "research_context", lambda prompt, **k: "\n\nRESEARCH: fetched passages")
    log = []
    monkeypatch.setattr(frontier, "_complete_claude", lambda prompt, **k: (log.append("claude") or
                        {"text": "{}", "json": {"by": "claude"}, "error": "", "model": "claude-fable-5-1"}))
    monkeypatch.setattr(frontier, "codex_complete", lambda prompt, **k: (log.append(("codex", "RESEARCH" in prompt)) or
                        {"text": "{}", "json": {"by": "codex"}, "error": "", "model": "gpt-5.5"}))
    fake_local = types.SimpleNamespace(chat=lambda user, **k: (log.append(("local", "RESEARCH" in user)) or
                                       {"text": "{}", "json": {"by": "local"}, "error": "", "model": "qwen-27b", "provider": "exo"}),
                                       available=lambda: local)
    monkeypatch.setitem(sys.modules, "local_llm", fake_local)
    return frontier, log


def test_claude_serves_when_up(monkeypatch, tmp_path):
    f, log = _setup(monkeypatch, tmp_path)
    r = f.complete("q", need=9, json_schema={"type": "object"})
    assert r["json"] == {"by": "claude"} and r["tier"] == "frontier" and log == ["claude"]


def test_claude_down_falls_to_codex_with_research_for_tool_calls(monkeypatch, tmp_path):
    f, log = _setup(monkeypatch, tmp_path, claude=False)
    r = f.complete("q", need=9, tools=f.WEB_TOOLS, json_schema={"type": "object"})
    assert r["json"] == {"by": "codex"} and r["tier"] == "codex" and log == [("codex", True)]


def test_both_clouds_down_falls_to_local(monkeypatch, tmp_path):
    f, log = _setup(monkeypatch, tmp_path, claude=False, codex=False)
    r = f.complete("q", need=9, tools=f.WEB_TOOLS, json_schema={"type": "object"})
    assert r["json"] == {"by": "local"} and r["tier"] == "local" and r["fallback"]["to"] == "local"
    assert log == [("local", True)]


def test_min_tier_codex_never_accepts_local(monkeypatch, tmp_path):
    f, log = _setup(monkeypatch, tmp_path, claude=False, codex=False)
    r = f.complete("q", need=8, json_schema={"type": "object"}, min_tier="codex")
    assert r["error"] and r["tier"] is None and log == []
    assert f.can_think(min_tier="codex") is False and f.can_think() is True


def test_claude_error_climbs_down(monkeypatch, tmp_path):
    f, log = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(f, "_complete_claude", lambda prompt, **k: (log.append("claude") or {"error": "529 Overloaded", "json": None}))
    r = f.complete("q", need=9, json_schema={"type": "object"})
    assert r["tier"] == "codex" and log == ["claude", ("codex", False)]


def test_routine_work_goes_local_first_when_a_strong_model_is_resident(monkeypatch, tmp_path):
    f, log = _setup(monkeypatch, tmp_path, strong_resident=True)
    r = f.complete("q", need=6, json_schema={"type": "object"})
    assert r["tier"] == "local" and log == [("local", False)]
    log.clear()
    r = f.complete("q", need=9, json_schema={"type": "object"})         # hard work still goes to the frontier
    assert r["tier"] == "frontier" and log == ["claude"]


def test_nothing_available_is_reported_not_raised(monkeypatch, tmp_path):
    f, log = _setup(monkeypatch, tmp_path, claude=False, codex=False, local=False)
    r = f.complete("q", need=9)
    assert r["error"].startswith("no tier could answer") and f.can_think() is False


def test_local_tier_triage_may_not_retire_or_rewrite(tmp_path, monkeypatch):
    import docket_triage as t
    monkeypatch.setattr(t, "LEDGER", str(tmp_path / "l.jsonl"))
    batch = [{"id": "1", "vertical": "gaming", "question": "q1"}, {"id": "2", "vertical": "gaming", "question": "q2"}]
    dec = [{"n": 1, "decision": "retire", "priority": "low", "lens": "answer", "decision_value": 0, "premise_ok": False,
            "premise_error": "x", "rewritten_question": "", "duplicate_of": 0},
           {"n": 2, "decision": "rewrite", "priority": "high", "lens": "pathway", "decision_value": 0.9, "premise_ok": False,
            "premise_error": "y", "rewritten_question": "A much better question about the actual governing rule here?", "duplicate_of": 0}]
    out = t.apply(batch, dec, dry_run=True, tier="local")
    assert out["retire"] == 0 and out["rewrite"] == 0 and out["keep"] == 2
    rows = [json.loads(x) for x in open(t.LEDGER)]
    assert all(r["tier"] == "local" and "question" not in r["patch"] and r["patch"].get("status") != "retired" for r in rows)
    assert t._triaged_ids() == set()                    # a cloud clerk will still see them


def test_commission_local_reviewer_is_provisional(monkeypatch):
    import publication_commission as pc
    scores = {"evidence": 0.9, "rigor": 0.9, "novelty": 0.8, "utility": 0.9, "risk": 0.9}

    def fake(key, prompt, art):
        return {"score": scores[key], "rationale": "r", "tier": "local" if key == "novelty" else "frontier"}
    monkeypatch.setattr(pc, "_score_one", fake)
    rec = pc.review_artifact({"id": "a", "type": "verdict_card"})
    assert rec["provisional"] is True and rec["decision"] == "steer_only"      # would have been publish
    monkeypatch.setattr(pc, "_score_one", lambda k, p, a: {**fake(k, p, a), "tier": "frontier"})
    assert pc.review_artifact({"id": "a", "type": "verdict_card"})["decision"] == "publish"


def test_local_models_yield_to_the_machine_heavy_lock(tmp_path, monkeypatch):
    import importlib, os as _os
    monkeypatch.delitem(sys.modules, "local_llm", raising=False)
    import local_llm
    importlib.reload(local_llm)
    lock = tmp_path / "heavy.lock"
    monkeypatch.setattr(local_llm, "HEAVY_LOCK", str(lock))
    monkeypatch.setattr(local_llm, "resident", lambda p, m: m == "gemma3:12b")
    monkeypatch.setattr(local_llm, "free_gb", lambda: 40.0)
    assert local_llm.heavy_lock_active() is None
    assert local_llm.fits("ollama", "qwen3.5:27b-mlx")[0] is True
    lock.mkdir()
    (lock / "owner").write_text(f"bench-local-llm {_os.getpid()} 2026-09-29T15:09:32Z strong\nbenchmark\n")
    assert local_llm.heavy_lock_active() == "bench-local-llm"
    assert local_llm.fits("ollama", "qwen3.5:27b-mlx")[0] is False       # never load a new model
    assert local_llm.fits("ollama", "gemma3:12b")[0] is True              # resident models still serve
    assert local_llm.exo_ensure("mlx-community/Qwen3.5-9B-4bit") is False
    (lock / "owner").write_text("consilium 1 2026-09-29T15:09:32Z strong\nours\n")
    assert local_llm.heavy_lock_active() is None                          # our own lane does not block us
    waiters = tmp_path / "heavy.lock.waiters"
    waiters.mkdir()
    (waiters / "bench-local-llm").write_text("x 2026-09-29T15:25:00Z\n")
    assert local_llm.heavy_lock_active() == "bench-local-llm"              # a queued lane counts too

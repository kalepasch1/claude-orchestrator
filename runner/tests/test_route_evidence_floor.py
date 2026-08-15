"""Route selection needs evidence.

Route learning had no minimum sample size: 118 of 152 live routes were won on n<=2
observations, and `verify_diff` -- the op that decides whether a diff is correct -- ran on
llama3.2:3b at avg quality 4.7 from a SINGLE sample. Cost-optimizing the verifier is a
plausible direct cause of the phantom-merge reclassification.

Two rules are pinned here:
  1. a sample floor, so live routes do not flap on sparse telemetry;
  2. verification-critical ops get NO below-bar fallback route at all.
"""
import app_triage_review as atr


def _ops(rows):
    """Shape rows the way _aggregate_and_route reads them from app_operations."""
    out = []
    for app, op, prov, model, cost, q, n in rows:
        out.extend([{"app": app, "operation": op, "provider": prov, "model": model,
                     "cost_usd": cost, "quality_score": q} for _ in range(n)])
    return out


def _run(monkeypatch, rows, **env):
    written = []
    monkeypatch.setattr(atr.db, "select", lambda *a, **k: _ops(rows))
    monkeypatch.setattr(atr.db, "insert",
                        lambda table, row, **k: written.append(row))
    monkeypatch.setattr(atr, "ROUTE_MIN_SAMPLES", env.get("min_samples", 20))
    monkeypatch.setattr(atr, "CRITICAL_OPS", env.get("critical", {"verify_diff"}))
    monkeypatch.setattr(atr, "QUALITY_BAR", env.get("bar", 7.0))
    atr._aggregate_and_route()
    return written


def test_single_sample_candidate_cannot_beat_a_proven_incumbent(monkeypatch):
    """n=1 at zero cost must not unseat n=50, however cheap it looks."""
    written = _run(monkeypatch, [
        ("app", "plan", "local", "tiny", 0.0, 9.9, 1),
        ("app", "plan", "openai", "gpt", 0.02, 8.0, 50),
    ])
    assert len(written) == 1
    assert written[0]["provider"] == "openai"


def test_cheap_model_wins_once_it_has_enough_samples(monkeypatch):
    """The optimizer still works -- it just has to earn it."""
    written = _run(monkeypatch, [
        ("app", "plan", "local", "tiny", 0.0, 8.5, 25),
        ("app", "plan", "openai", "gpt", 0.02, 8.0, 50),
    ])
    assert len(written) == 1
    assert written[0]["provider"] == "local"
    assert "n=25" in written[0]["reason"]


def test_nothing_meets_the_floor_writes_no_route(monkeypatch):
    written = _run(monkeypatch, [
        ("app", "plan", "local", "tiny", 0.0, 9.0, 2),
        ("app", "plan", "openai", "gpt", 0.02, 8.0, 3),
    ])
    assert written == []


def test_critical_op_below_the_bar_writes_no_route(monkeypatch):
    """verify_diff at q=4.7 must not be routed even with n=100 -- this is the phantom-merge path."""
    written = _run(monkeypatch, [
        ("app", "verify_diff", "local", "llama3.2:3b", 0.0, 4.7, 100),
    ])
    assert written == []


def test_critical_op_routes_normally_when_a_candidate_clears_the_bar(monkeypatch):
    written = _run(monkeypatch, [
        ("app", "verify_diff", "local", "llama3.2:3b", 0.0, 4.7, 100),
        ("app", "verify_diff", "claude", "sonnet", 0.05, 8.6, 40),
    ])
    assert len(written) == 1
    assert written[0]["provider"] == "claude"


def test_non_critical_op_may_still_use_a_below_bar_fallback(monkeypatch):
    """The critical rule is scoped -- ordinary ops keep their best-effort fallback."""
    written = _run(monkeypatch, [
        ("app", "summarize", "local", "tiny", 0.0, 5.5, 40),
    ])
    assert len(written) == 1
    assert written[0]["provider"] == "local"
    assert "fallback" in written[0]["reason"]

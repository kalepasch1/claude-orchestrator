"""Wave C Part 4 (compounding half) must be WIRED, not merely shipped.

golden_path.py landed complete and tested in slice 4 and was then imported by nothing
outside its own test file, so per-vertical golden paths and strategy-aware generation
never reached a single shard. These tests pin the wiring itself: if planner stops calling
golden_path, they fail — which is the only failure mode slice 4 did not already cover.
"""
import os
import sys

import pytest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

import planner            # noqa: E402
import golden_path        # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("ORCH_APPROVED_STRUCTURE", "ORCH_STRUCTURE_APPROVED_BY",
                "ORCH_STRUCTURE_JURISDICTIONS"):
        monkeypatch.delenv(key, raising=False)


def _tasks():
    return [{"slug": "contracts", "prompt": "define the interfaces", "deps": []},
            {"slug": "entry-flow", "prompt": "build the entry flow", "deps": ["contracts"]}]


# ── the wiring itself ───────────────────────────────────────────────────────────────────

def test_planner_actually_imports_golden_path():
    """The regression that caused this task: a complete module nobody called."""
    src = open(os.path.join(RUNNER, "planner.py")).read()
    assert "import golden_path" in src
    assert "_apply_golden_path" in src


def test_plan_calls_apply_golden_path(monkeypatch):
    seen = {}

    def _spy(tasks, project=None, repo=None):
        seen["called"] = True
        seen["project"] = project
        return tasks

    monkeypatch.setattr(planner, "_apply_golden_path", _spy)
    monkeypatch.setattr(planner, "_shard_by_sections", lambda m: [])
    monkeypatch.setattr(planner.claude_cli, "run",
                        lambda *a, **k: {"text": '[{"slug":"t","prompt":"p","deps":[]}]'})
    planner.plan("do a thing", project="sweeps")
    assert seen.get("called") is True
    assert seen.get("project") == "sweeps"


# ── strategy-aware generation ───────────────────────────────────────────────────────────

def test_approved_structure_is_injected_into_every_shard(monkeypatch):
    monkeypatch.setenv("ORCH_APPROVED_STRUCTURE", "sweepstakes")
    monkeypatch.setenv("ORCH_STRUCTURE_APPROVED_BY", "tribunal")
    monkeypatch.setattr(planner, "_merged_shards", lambda *a, **k: [])

    out = planner._apply_golden_path(_tasks(), project="sweeps")
    for task in out:
        assert "APPROVED STRUCTURE: sweepstakes" in task["prompt"]
        assert "alternate method of entry" in task["prompt"]
        assert task["structure"] == "sweepstakes"


def test_unapproved_structure_is_refused_not_injected(monkeypatch, capsys):
    """Proposed but not approved: refuse loudly rather than build the wrong thing well."""
    monkeypatch.setenv("ORCH_APPROVED_STRUCTURE", "sweepstakes")   # no APPROVED_BY
    monkeypatch.setattr(planner, "_merged_shards", lambda *a, **k: [])

    out = planner._apply_golden_path(_tasks(), project="sweeps")
    assert all("APPROVED STRUCTURE" not in t["prompt"] for t in out)
    assert "GOLDEN PATH REFUSED" in capsys.readouterr().err


def test_no_strategy_leaves_prompts_untouched(monkeypatch):
    monkeypatch.setattr(planner, "_merged_shards", lambda *a, **k: [])
    before = _tasks()
    out = planner._apply_golden_path([dict(t) for t in before], project="sweeps")
    assert [t["prompt"] for t in out] == [t["prompt"] for t in before]


# ── golden paths (outcome-ranked, not similarity-ranked) ────────────────────────────────

def _shards():
    """Ten merged shards; `first-pass` is the only clean one, so it must be the template."""
    pool = [{"slug": f"slow-{i}", "vertical": "sweeps", "merged": True,
             "attempts": 4, "review_cycles": 3, "days_to_merge": 9.0} for i in range(9)]
    pool.append({"slug": "first-pass", "vertical": "sweeps", "merged": True,
                 "attempts": 1, "review_cycles": 0, "days_to_merge": 1.0})
    return pool


def test_template_is_the_best_outcome_not_the_nearest(monkeypatch):
    monkeypatch.setattr(planner, "_merged_shards", lambda *a, **k: _shards())
    out = planner._apply_golden_path(_tasks(), project="sweeps")
    for task in out:
        assert "GOLDEN PATH: start from first-pass" in task["prompt"]
        assert task["golden_template"] == "first-pass"


def test_golden_template_accompanies_an_approved_structure(monkeypatch):
    monkeypatch.setenv("ORCH_APPROVED_STRUCTURE", "sweepstakes")
    monkeypatch.setenv("ORCH_STRUCTURE_APPROVED_BY", "tribunal")
    monkeypatch.setattr(planner, "_merged_shards", lambda *a, **k: _shards())
    out = planner._apply_golden_path(_tasks(), project="sweeps")
    assert "APPROVED STRUCTURE: sweepstakes" in out[0]["prompt"]
    assert "first-pass" in out[0]["prompt"]


# ── invariants ──────────────────────────────────────────────────────────────────────────

def test_injection_is_idempotent_across_replans(monkeypatch):
    monkeypatch.setenv("ORCH_APPROVED_STRUCTURE", "sweepstakes")
    monkeypatch.setenv("ORCH_STRUCTURE_APPROVED_BY", "tribunal")
    monkeypatch.setattr(planner, "_merged_shards", lambda *a, **k: [])

    once = planner._apply_golden_path(_tasks(), project="sweeps")
    twice = planner._apply_golden_path([dict(t) for t in once], project="sweeps")
    for task in twice:
        assert task["prompt"].count(planner.GOLDEN_PATH_MARKER) == 1


def test_never_drops_or_reorders_tasks(monkeypatch):
    monkeypatch.setenv("ORCH_APPROVED_STRUCTURE", "sweepstakes")
    monkeypatch.setenv("ORCH_STRUCTURE_APPROVED_BY", "tribunal")
    monkeypatch.setattr(planner, "_merged_shards", lambda *a, **k: _shards())
    out = planner._apply_golden_path(_tasks(), project="sweeps")
    assert [t["slug"] for t in out] == ["contracts", "entry-flow"]


def test_fail_soft_when_golden_path_raises(monkeypatch):
    monkeypatch.setattr(golden_path, "strategy_context",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(planner, "_merged_shards", lambda *a, **k: [])
    before = _tasks()
    out = planner._apply_golden_path([dict(t) for t in before], project="sweeps")
    assert [t["prompt"] for t in out] == [t["prompt"] for t in before]


def test_fail_soft_when_db_is_unreachable(monkeypatch):
    """No SUPABASE env is the normal state on a dev box; planning must still work."""
    assert planner._merged_shards("sweeps") == [] or isinstance(
        planner._merged_shards("sweeps"), list)


# ── strategy resolution ─────────────────────────────────────────────────────────────────

def test_strategy_json_is_read_from_the_repo(tmp_path, monkeypatch):
    cfg = tmp_path / ".orchestrator"
    cfg.mkdir()
    (cfg / "strategy.json").write_text(
        '{"structure": "lending", "approved": true, "jurisdictions": ["CA", "NY"]}')
    monkeypatch.setattr(planner, "_merged_shards", lambda *a, **k: [])

    out = planner._apply_golden_path(_tasks(), project="loans", repo=str(tmp_path))
    assert "APPROVED STRUCTURE: lending" in out[0]["prompt"]
    assert "JURISDICTIONS: CA, NY" in out[0]["prompt"]
    assert "APR disclosure" in out[0]["prompt"]


def test_env_override_beats_strategy_json(tmp_path, monkeypatch):
    cfg = tmp_path / ".orchestrator"
    cfg.mkdir()
    (cfg / "strategy.json").write_text('{"structure": "lending", "approved": true}')
    monkeypatch.setenv("ORCH_APPROVED_STRUCTURE", "contest")
    monkeypatch.setenv("ORCH_STRUCTURE_APPROVED_BY", "tribunal")
    assert planner._approved_strategy("p", str(tmp_path))["structure"] == "contest"


def test_malformed_strategy_json_is_not_fatal(tmp_path):
    cfg = tmp_path / ".orchestrator"
    cfg.mkdir()
    (cfg / "strategy.json").write_text("{not json")
    assert planner._approved_strategy("p", str(tmp_path)) == {}


def test_days_between_handles_garbage():
    assert planner._days_between(None, None) == 0.0
    assert planner._days_between("nope", "2026-01-01T00:00:00Z") == 0.0
    assert planner._days_between(
        "2026-01-01T00:00:00Z", "2026-01-03T00:00:00Z") == pytest.approx(2.0)

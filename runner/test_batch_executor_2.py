#!/usr/bin/env python3
"""
test_batch_executor_2.py — Tests for all 5 batch-executor-2 modules.

Covers:
  - experiment_analyzer: analyze_experiment, recommend_next_experiments
  - config_optimizer: suggest_config_changes, analyze_config_history
  - branch_integration_predictor: score_integration_priority, rank_for_integration
  - branch_preflight: preflight_check
  - test_framework: TestResult, discover_tests, run_command_test
"""
import os, sys, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ── experiment_analyzer tests ──

def test_experiment_analyzer_no_db():
    """analyze_experiment returns safe default when db is unavailable."""
    import experiment_analyzer as ea
    old_db = ea.db
    ea.db = None
    try:
        result = ea.analyze_experiment("fake-id")
        assert result["status"] == "insufficient_data"
        assert result["recommendation"] == "no_data"
    finally:
        ea.db = old_db


def test_experiment_analyzer_mean_stddev():
    """_mean and _stddev compute correctly."""
    from experiment_analyzer import _mean, _stddev
    assert _mean([]) == 0.0
    assert _mean([2, 4, 6]) == 4.0
    assert _stddev([]) == 0.0
    assert _stddev([1]) == 0.0
    assert abs(_stddev([2, 4, 6]) - 1.6329931618) < 0.001


def test_experiment_analyzer_recommendations_no_db():
    """recommend_next_experiments returns empty when db is unavailable."""
    import experiment_analyzer as ea
    old_db = ea.db
    ea.db = None
    try:
        assert ea.recommend_next_experiments() == []
    finally:
        ea.db = old_db


# ── config_optimizer tests ──

def test_config_optimizer_no_db():
    """suggest_config_changes returns empty when db is unavailable."""
    import config_optimizer as co
    old_db = co.db
    co.db = None
    try:
        assert co.suggest_config_changes() == []
        assert co.analyze_config_history() == []
    finally:
        co.db = old_db


def test_config_optimizer_stats():
    """stats returns expected keys."""
    import config_optimizer as co
    s = co.stats()
    assert "lookback_hours" in s
    assert "min_throughput_gain" in s


# ── branch_integration_predictor tests ──

def test_predictor_score_safe_kinds():
    """Safe kinds (docs, chore) get a higher base score."""
    from branch_integration_predictor import score_integration_priority
    safe_task = {"kind": "docs", "slug": "update-readme"}
    risky_task = {"kind": "build", "slug": "new-feature"}
    safe_score = score_integration_priority(safe_task)
    risky_score = score_integration_priority(risky_task)
    assert safe_score > risky_score, f"safe={safe_score} should be > risky={risky_score}"


def test_predictor_score_with_history():
    """History penalties reduce score."""
    from branch_integration_predictor import score_integration_priority
    history = {"build": {"conflict_rate": 0.5, "testfail_rate": 0.3, "count": 10}}
    task = {"kind": "build", "slug": "feat-x"}
    score_no_hist = score_integration_priority(task, history=None)
    score_with_hist = score_integration_priority(task, history=history)
    assert score_with_hist < score_no_hist


def test_predictor_rank_ordering():
    """rank_for_integration sorts highest score first."""
    from branch_integration_predictor import rank_for_integration
    tasks = [
        {"kind": "build", "slug": "a"},
        {"kind": "docs", "slug": "b"},
        {"kind": "chore", "slug": "c"},
    ]
    ranked = rank_for_integration(tasks)
    # docs and chore should come before build
    slugs = [t.get("slug") for _, t in ranked]
    build_idx = slugs.index("a")
    assert build_idx > 0, "build task should not be first"


def test_predictor_age_bonus():
    """Older tasks get a slight priority bonus."""
    from branch_integration_predictor import score_integration_priority
    old_time = (datetime.datetime.now(datetime.timezone.utc)
                - datetime.timedelta(hours=48)).isoformat()
    new_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
    old_task = {"kind": "build", "slug": "old", "created_at": old_time}
    new_task = {"kind": "build", "slug": "new", "created_at": new_time}
    assert score_integration_priority(old_task) > score_integration_priority(new_task)


# ── branch_preflight tests ──

def test_preflight_no_repo():
    """preflight_check handles missing repo gracefully."""
    from branch_preflight import preflight_check
    tasks = [{"slug": "task-1"}, {"slug": "task-2"}]
    result = preflight_check("proj-1", "/nonexistent/repo", tasks)
    # All should be unresolvable since repo doesn't exist
    assert result["total_checked"] == 2
    assert len(result["unresolvable"]) == 2
    assert len(result["ready"]) == 0
    assert len(result["missing"]) == 0


def test_preflight_run_no_db():
    """run_preflight returns error when db is unavailable."""
    import branch_preflight as bp
    old_db = bp.db
    bp.db = None
    try:
        result = bp.run_preflight("fake-project-id")
        assert "error" in result
    finally:
        bp.db = old_db


# ── test_framework tests ──

def test_framework_test_result():
    """TestResult serializes correctly."""
    from test_framework import TestResult
    r = TestResult("my_test", "unit", True, 1.5, None, "ok")
    d = r.to_dict()
    assert d["name"] == "my_test"
    assert d["category"] == "unit"
    assert d["passed"] is True
    assert d["duration_s"] == 1.5


def test_framework_run_command_test():
    """run_command_test works with simple shell commands."""
    from test_framework import run_command_test
    r = run_command_test("echo_test", "echo hello", category="unit")
    assert r.passed is True
    assert "hello" in r.output


def test_framework_run_command_test_fail():
    """run_command_test detects failures."""
    from test_framework import run_command_test
    r = run_command_test("fail_test", "exit 1", category="unit")
    assert r.passed is False
    assert r.error is not None


def test_framework_discover_tests():
    """discover_tests finds test files in the runner directory."""
    from test_framework import discover_tests
    runner_dir = os.path.dirname(os.path.abspath(__file__))
    tests = discover_tests(runner_dir)
    assert "unit" in tests
    # This test file should be discovered
    names = [t["name"] for t in tests["unit"]]
    assert "test_batch_executor_2" in names


def test_framework_output_truncation():
    """TestResult truncates output to 2000 chars."""
    from test_framework import TestResult
    long_output = "x" * 5000
    r = TestResult("t", "unit", True, 0, None, long_output)
    assert len(r.output) == 2000


# ── Run all tests ──

if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{passed}/{passed+failed} passed")
    sys.exit(0 if failed == 0 else 1)

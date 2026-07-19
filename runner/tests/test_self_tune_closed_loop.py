"""Tests for self_tune.py closed-loop tuning improvements."""
import os, sys, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_time_weight_decay():
    """Time weight decays exponentially with half-life."""
    from self_tune import _time_weight
    assert _time_weight(0) == 1.0
    # At half-life, weight should be ~0.5
    from self_tune import DECAY_HALFLIFE_DAYS
    w = _time_weight(DECAY_HALFLIFE_DAYS)
    assert 0.49 < w < 0.51, f"Expected ~0.5 at half-life, got {w}"
    # Double the half-life -> ~0.25
    w2 = _time_weight(DECAY_HALFLIFE_DAYS * 2)
    assert 0.24 < w2 < 0.26, f"Expected ~0.25 at 2x half-life, got {w2}"
    # Negative age -> 1.0 (defensive)
    assert _time_weight(-5) == 1.0


def test_time_weight_positive_and_bounded():
    """Weight is always positive and <= 1."""
    from self_tune import _time_weight
    for days in [0, 1, 7, 30, 365, 1000]:
        w = _time_weight(days)
        assert 0 < w <= 1.0, f"Weight {w} out of bounds for {days} days"


def test_plan_model_preferences_empty(monkeypatch):
    """No crash on empty project list."""
    import self_tune
    monkeypatch.setattr("self_tune.db", type("MockDB", (), {
        "select": staticmethod(lambda *a, **kw: []),
        "update": staticmethod(lambda *a, **kw: None),
    })())
    assert self_tune.plan_model_preferences() == []


def test_plan_changes_insufficient_signal(monkeypatch):
    """plan_changes returns empty when n_eff < MIN_EFFECTIVE_SAMPLES."""
    import self_tune
    # Return a project but outcomes with very high decay (old data)
    calls = []
    def mock_select(table, params=None):
        if table == "projects":
            return [{"id": "p1", "name": "testproj", "confidence_threshold": 0.55, "auto_merge": True}]
        if table == "outcomes":
            # Return 5 rows - below MIN_EFFECTIVE_SAMPLES even with weight=1
            return [{"tests_passed": True, "integrated": True, "created_at": "2020-01-01T00:00:00Z"}] * 5
        return []
    monkeypatch.setattr("self_tune.db", type("MockDB", (), {
        "select": staticmethod(mock_select),
        "update": staticmethod(lambda *a, **kw: None),
    })())
    changes = self_tune.plan_changes()
    assert changes == [], f"Expected no changes with insufficient data, got {changes}"

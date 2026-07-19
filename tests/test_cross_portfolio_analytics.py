"""Tests for cross_portfolio_analytics — verify aggregation logic."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'runner'))
from cross_portfolio_analytics import aggregate_cross_portfolio, _lift, _p_value_approx


def test_lift_calculation():
    assert _lift(0.5, 0.6) == 20.0
    assert _lift(0.0, 0.5) == 0.0
    assert _lift(0.8, 0.8) == 0.0


def test_p_value_basic():
    # Large sample, big difference => small p
    p = _p_value_approx(1000, 0.5, 1000, 0.7)
    assert p < 0.01
    # Same rates => high p
    p2 = _p_value_approx(100, 0.5, 100, 0.5)
    assert p2 > 0.9


def test_aggregate_mock():
    mock = [
        {"app": "app1", "tactic": "routing", "control_n": 100,
         "control_rate": 0.60, "variant_n": 100, "variant_rate": 0.72},
        {"app": "app2", "tactic": "routing", "control_n": 100,
         "control_rate": 0.55, "variant_n": 100, "variant_rate": 0.65},
        {"app": "app3", "tactic": "routing", "control_n": 100,
         "control_rate": 0.70, "variant_n": 100, "variant_rate": 0.77},
    ]
    result = aggregate_cross_portfolio(mock)
    assert result["total_experiments"] == 3
    routing = result["tactics"]["routing"]
    assert routing["apps_tested"] == 3
    assert routing["portfolio_avg_lift_pct"] > 0
    # Each app should have a positive lift
    for app_data in routing["per_app"]:
        assert app_data["lift_pct"] > 0


if __name__ == "__main__":
    test_lift_calculation()
    test_p_value_basic()
    test_aggregate_mock()
    print("All tests passed.")

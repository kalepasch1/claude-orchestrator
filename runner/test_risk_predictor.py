#!/usr/bin/env python3
"""test_risk_predictor.py — tests for risk_predictor module."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from risk_predictor import RiskPredictor, predict_risk


def test_normal_small_change():
    p = RiskPredictor()
    score = p.predict_risk(lines_changed=10, files_changed=1, has_tests=True,
                           author_pass_rate=0.95, test_coverage_pct=90)
    assert 0.0 <= score <= 1.0, f"score out of range: {score}"
    assert score < 0.5, f"small safe change should be low risk: {score}"


def test_normal_large_risky_change():
    p = RiskPredictor()
    score = p.predict_risk(lines_changed=2000, files_changed=50, has_tests=False,
                           author_pass_rate=0.3, test_coverage_pct=5)
    assert score > 0.5, f"large risky change should be high risk: {score}"


def test_no_tests_increases_risk():
    p = RiskPredictor()
    with_tests = p.predict_risk(lines_changed=100, files_changed=5, has_tests=True,
                                author_pass_rate=0.8, test_coverage_pct=60)
    without_tests = p.predict_risk(lines_changed=100, files_changed=5, has_tests=False,
                                   author_pass_rate=0.8, test_coverage_pct=60)
    assert without_tests > with_tests, "no tests should increase risk"


def test_edge_new_author_zero_history():
    p = RiskPredictor()
    score = p.predict_risk(lines_changed=50, files_changed=3, has_tests=True,
                           author_pass_rate=0.0, test_coverage_pct=70)
    assert 0.0 <= score <= 1.0


def test_edge_huge_change():
    p = RiskPredictor()
    score = p.predict_risk(lines_changed=50000, files_changed=500, has_tests=True,
                           author_pass_rate=0.9, test_coverage_pct=80)
    assert score > 0.5, f"huge change should be risky: {score}"


def test_edge_zero_everything():
    p = RiskPredictor()
    score = p.predict_risk(lines_changed=0, files_changed=0, has_tests=True,
                           author_pass_rate=1.0, test_coverage_pct=100)
    assert score < 0.3, f"zero change should be low risk: {score}"


def test_edge_none_inputs():
    """None inputs should not raise — fail-soft returns 0.5 or a valid score."""
    p = RiskPredictor()
    score = p.predict_risk(lines_changed=None, files_changed=None, has_tests=True,
                           author_pass_rate=None, test_coverage_pct=None)
    assert 0.0 <= score <= 1.0


def test_module_level_singleton():
    score = predict_risk(lines_changed=20, files_changed=2, has_tests=True,
                         author_pass_rate=0.9, test_coverage_pct=85)
    assert 0.0 <= score <= 1.0


def test_train_improves_predictions():
    """Training on historical data should move predictions in the right direction."""
    p = RiskPredictor(weights=[0.0, 0.0, 0.0, 0.0, 0.0], bias=0.0)
    examples = [
        ({"lines_changed": 10, "files_changed": 1, "has_tests": True,
          "author_pass_rate": 0.9, "test_coverage_pct": 90}, True),
        ({"lines_changed": 5000, "files_changed": 80, "has_tests": False,
          "author_pass_rate": 0.2, "test_coverage_pct": 5}, False),
    ]
    p.train(examples, lr=0.05, epochs=200)
    safe = p.predict_risk(lines_changed=10, files_changed=1, has_tests=True,
                          author_pass_rate=0.9, test_coverage_pct=90)
    risky = p.predict_risk(lines_changed=5000, files_changed=80, has_tests=False,
                           author_pass_rate=0.2, test_coverage_pct=5)
    assert risky > safe, f"after training risky ({risky}) should exceed safe ({safe})"


def test_sigmoid_clamp():
    p = RiskPredictor()
    assert p._sigmoid(1000) == 1.0
    assert p._sigmoid(-1000) < 1e-10


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS: {name}")
    print("test_risk_predictor: all tests passed")

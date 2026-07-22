"""Shadow test: ab_edge constants and module structure."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ab_edge


def test_canary_pct_exists():
    assert hasattr(ab_edge, 'CANARY_PCT')

def test_canary_pct_is_numeric():
    assert isinstance(ab_edge.CANARY_PCT, (int, float))

def test_canary_pct_in_range():
    assert 0 <= ab_edge.CANARY_PCT <= 100

def test_run_function_exists():
    assert callable(getattr(ab_edge, 'run', None))

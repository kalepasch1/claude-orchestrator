"""Shadow test: adaptive_pipeline.should_use_pipeline routing logic."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from adaptive_pipeline import should_use_pipeline


def test_should_use_pipeline_returns_bool():
    result = should_use_pipeline({"kind": "build", "slug": "test"}, "beethoven")
    assert isinstance(result, bool)

def test_should_use_pipeline_with_empty_task():
    result = should_use_pipeline({}, "beethoven")
    assert isinstance(result, bool)

def test_should_use_pipeline_with_canary():
    result = should_use_pipeline({"kind": "canary", "slug": "c1"}, "beethoven")
    assert isinstance(result, bool)

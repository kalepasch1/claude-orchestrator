"""merge_train refuses to boot if a CRITICAL module has an undefined name.

An undefined `release_manifest` in release_train._integrate_regate_and_push
tripped static_sanity.assert_critical at merge_train startup, and the job
crash-looped 127 times without merging anything. The name was also inside a
bare `except Exception: pass`, so had the gate not caught it the
post-integration manifest gate would simply never have been recorded.

This pins the gate rather than the single name: any future undefined name in
a CRITICAL module fails here instead of in a silent crash loop.
"""
import os
import sys

import pytest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

import static_sanity

pyflakes = pytest.importorskip("pyflakes", reason="static_sanity is a no-op without pyflakes")


def _undefined_names(path):
    from pyflakes.api import check
    from pyflakes.reporter import Reporter
    import io
    out, err = io.StringIO(), io.StringIO()
    with open(path, encoding="utf-8", errors="replace") as f:
        check(f.read(), path, Reporter(out, err))
    return [ln for ln in out.getvalue().splitlines() if "undefined name" in ln]


def test_release_train_has_no_undefined_names():
    found = _undefined_names(os.path.join(RUNNER, "release_train.py"))
    assert found == [], "release_train.py has undefined names:\n" + "\n".join(found)


def test_release_manifest_is_resolvable_where_the_gate_is_recorded():
    """The specific regression: the post-integration record_gate call site."""
    src = open(os.path.join(RUNNER, "release_train.py"), encoding="utf-8").read()
    marker = 'release_manifest.record_gate(\n                        manifest["id"], "post-integration"'
    assert marker in src, "post-integration record_gate call site moved; update this test"
    before = src.split(marker)[0]
    assert "import release_manifest" in before, (
        "release_manifest is used at the post-integration gate with no import in scope")


@pytest.mark.parametrize("module", static_sanity.CRITICAL_MODULES)
def test_every_critical_module_is_free_of_undefined_names(module):
    path = os.path.join(RUNNER, module)
    if not os.path.exists(path):
        pytest.skip(f"{module} not present")
    found = _undefined_names(path)
    assert found == [], f"{module} has undefined names:\n" + "\n".join(found)


def test_assert_critical_passes():
    """The actual startup gate merge_train calls. Must not raise."""
    assert static_sanity.assert_critical("test") is True

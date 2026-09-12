"""Guard: a JOBS entry without a handler must fail loudly, by name.

Regression for the decisionbriefs crashloop: a missing `run_*` function made the JOBS
dict literal raise a bare `NameError` at module scope, so every caller saw an opaque
import crash instead of the name that was actually missing.
"""
import os
import sys
import textwrap

import pytest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import periodic  # noqa: E402


def test_declared_names_include_known_jobs():
    names = periodic._declared_job_handler_names()
    assert "run_editorial" in names
    assert "run_decisionbriefs" in names
    # every declared name resolves in the real module — the live table is consistent
    assert periodic._require_job_handlers(names) == []


def test_missing_handler_raises_named_error():
    ns = {"run_present": lambda: None}
    with pytest.raises(RuntimeError) as exc:
        periodic._require_job_handlers(["run_present", "run_editorial", "run_gone"], ns)
    msg = str(exc.value)
    assert "run_gone" in msg and "run_editorial" in msg
    assert "run_present" not in msg
    assert "NameError" not in msg


def test_non_callable_counts_as_missing():
    with pytest.raises(RuntimeError) as exc:
        periodic._require_job_handlers(["run_x"], {"run_x": None})
    assert "run_x" in str(exc.value)


def test_declared_names_parse_from_arbitrary_source(tmp_path):
    src = tmp_path / "fake_periodic.py"
    src.write_text(textwrap.dedent(
        """
        def run_a(): pass
        JOBS = {"a": run_a, "b": run_missing}
        """
    ))
    assert periodic._declared_job_handler_names(str(src)) == ["run_a", "run_missing"]


def test_declared_names_fail_soft_on_bad_source(tmp_path):
    bad = tmp_path / "broken.py"
    bad.write_text("JOBS = {  # unterminated\n")
    assert periodic._declared_job_handler_names(str(bad)) == []
    assert periodic._declared_job_handler_names(str(tmp_path / "nope.py")) == []

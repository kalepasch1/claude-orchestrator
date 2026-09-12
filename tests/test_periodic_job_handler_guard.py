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


# --- the guard must be CALLED, not merely defined --------------------------
#
# Everything above tests the helpers in isolation, and all of it passed while
# nothing in periodic.py invoked them. Both helpers sat BELOW the JOBS literal
# with no caller, so the NameError they exist to explain still fired first and
# the guard never spoke — a control that reads as enforced and is not.
#
# These pin the wiring itself, by reading the source rather than the behaviour,
# because the behaviour under test is "this line exists before that line".

import ast  # noqa: E402

PERIODIC_PATH = os.path.join(RUNNER, "periodic.py")


def _periodic_ast():
    with open(PERIODIC_PATH, encoding="utf-8", errors="replace") as fh:
        return ast.parse(fh.read())


def _jobs_assign_lineno(tree):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "JOBS" for t in node.targets
        ):
            return node.lineno
    pytest.fail("no module-level JOBS assignment found in periodic.py")


def _guard_call_linenos(tree):
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_require_job_handlers"
    ]


def test_guard_is_actually_called():
    calls = _guard_call_linenos(_periodic_ast())
    assert calls, (
        "_require_job_handlers is never called in periodic.py — the JOBS dispatch "
        "table is unguarded and the helper is decoration"
    )


def test_guard_runs_before_the_jobs_literal():
    """Evaluating the dict is what raises, so the check has to precede it."""
    tree = _periodic_ast()
    jobs_line = _jobs_assign_lineno(tree)
    calls = _guard_call_linenos(tree)
    assert any(line < jobs_line for line in calls), (
        f"_require_job_handlers is only called at line(s) {calls}, none before the "
        f"JOBS literal on line {jobs_line}; the NameError fires first"
    )


def test_import_leaves_every_job_callable():
    """The end state the guard exists to protect."""
    assert periodic.JOBS
    assert sorted(k for k, v in periodic.JOBS.items() if not callable(v)) == []

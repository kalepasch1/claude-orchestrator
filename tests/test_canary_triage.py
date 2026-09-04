"""canary_triage: the narrowest check that each failure class routes to the right fix.

`canary_triage` decides, unattended, which remediation task a failed self-deploy canary
files. A misclassification does not fail loudly — it files confident, plausible, wrong
work. It had no test at all. Pure and injectable, so this needs no DB, no network and no
other task.
"""
import os
import sys

import pytest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import canary_triage as ct  # noqa: E402


# --- classify -------------------------------------------------------------------------

def test_labelled_conflict_marker():
    assert ct.classify("<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> br\n") == "conflict-marker"


def test_unlabelled_conflict_marker():
    """git writes a bare `<<<<<<<` when there is no label; the old check needed a space."""
    log = "  File \"hisanta/__init__.py\", line 23\n    <<<<<<<\nSyntaxError: invalid syntax\n"
    assert ct.classify(log) == "conflict-marker"


def test_sentinel_phrase_is_enough_without_a_marker():
    assert ct.classify("leftover conflict marker in tracked code") == "conflict-marker"


def test_missing_module():
    assert ct.classify("ModuleNotFoundError: No module named 'nope'") == "missing-module"


def test_import_error_that_is_not_a_missing_module():
    assert ct.classify("ImportError: cannot import name 'x' from 'y'") == "import-error"


def test_missing_module_wins_over_generic_import_error():
    log = "ImportError while loading conftest\nModuleNotFoundError: No module named 'z'"
    assert ct.classify(log) == "missing-module"


def test_shape_comparison_is_a_stale_test():
    for log in ("AssertionError: assert {'a': 1} == {'a': 2}",
                "AssertionError\nLeft contains 2 more items",
                "AssertionError\nRight contains one more item",
                "AssertionError: omitting 3 identical items"):
        assert ct.classify(log) == "stale-test", log


def test_behavioural_failure_is_a_real_regression():
    assert ct.classify("AssertionError: assert 3 == 4") == "real-regression"


def test_collection_interrupt():
    assert ct.classify("!!! Interrupted: 3 errors during collection !!!") == "collection-error"


def test_syntax_error_without_markers_is_a_collection_error():
    assert ct.classify("SyntaxError: invalid syntax") == "collection-error"


def test_unrecognised_log_is_unknown_not_guessed():
    assert ct.classify("everything is fine") == "unknown"


def test_empty_and_none_are_unknown():
    assert ct.classify("") == "unknown"
    assert ct.classify(None) == "unknown"


def test_classification_is_case_insensitive():
    assert ct.classify("modulenotfounderror: no module named 'q'") == "missing-module"


# --- triage ---------------------------------------------------------------------------

def test_unknown_is_escalated_never_filed():
    filed = []
    out = ct.triage("nothing matches", enqueue_fn=filed.append, project_id="p")
    assert out == {"class": "unknown", "filed": False}
    assert filed == [], "a guessed remediation is worse than no remediation"


def test_no_enqueue_fn_classifies_without_filing():
    assert ct.triage("ModuleNotFoundError: x")["filed"] is False


def test_files_a_routed_remediation_task():
    filed = []
    out = ct.triage("ModuleNotFoundError: No module named 'x'",
                    enqueue_fn=filed.append, project_id="p1", head="abcdef1234567890")
    assert out == {"class": "missing-module", "filed": True}
    rec = filed[0]
    assert rec["project_id"] == "p1"
    assert rec["kind"] == "remediation"
    assert rec["slug"] == "remediation-canary-missing-module-abcdef12"
    assert "does not exist" in rec["prompt"]
    assert "abcdef123456" in rec["prompt"]


def test_slug_is_stable_without_a_head():
    filed = []
    ct.triage("ImportError: boom", enqueue_fn=filed.append, project_id="p")
    assert filed[0]["slug"] == "remediation-canary-import-error"


def test_every_routable_class_has_guidance():
    """A class with no route entry would raise KeyError inside the unattended triage."""
    logs = {
        "conflict-marker": "<<<<<<< HEAD",
        "missing-module": "ModuleNotFoundError: x",
        "import-error": "ImportError: x",
        "collection-error": "Interrupted: errors during collection",
        "stale-test": "AssertionError: assert {'a': 1} == {'a': 2}",
        "real-regression": "AssertionError: assert 1 == 2",
    }
    for expected, log in logs.items():
        filed = []
        out = ct.triage(log, enqueue_fn=filed.append, project_id="p")
        assert out["class"] == expected, log
        assert out["filed"] is True
        assert filed[0]["prompt"].strip()


def test_a_failing_enqueue_is_reported_not_raised():
    def boom(_rec):
        raise RuntimeError("queue down")
    out = ct.triage("ModuleNotFoundError: x", enqueue_fn=boom, project_id="p")
    assert out == {"class": "missing-module", "filed": False}

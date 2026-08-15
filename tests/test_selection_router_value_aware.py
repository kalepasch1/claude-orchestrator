"""An early exit from testing has to be earned by the diff, not by the label.

Two defects in test_selection_router.select_test_strategy:

  1. The "skip" entries in FILE_PATTERN_OVERRIDES were unreachable — the
     override loop only acted when scope == "full".
  2. A task whose *kind* skips (docs/chore/format) skipped tests no matter
     what it actually changed, so a task tagged "docs" that edited
     runner/db.py ran nothing at all.

These pin the corrected precedence: escalation > corroborated skip > kind.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import test_selection_router as router


# ── the regression that mattered ─────────────────────────────────────────────

def test_docs_kind_touching_code_does_not_skip():
    s = router.select_test_strategy("docs", ["runner/db.py"])
    assert s["scope"] == "full"
    assert router.should_skip_tests("docs", ["runner/db.py"]) is False


@pytest.mark.parametrize("kind", ["docs", "chore", "format"])
def test_every_skipping_kind_is_corroborated_by_the_diff(kind):
    assert router.select_test_strategy(kind, ["src/app.ts"])["scope"] == "full"
    assert router.select_test_strategy(kind, ["README.md"])["scope"] == "skip"


def test_partially_inert_diff_does_not_skip():
    """One non-inert file is enough to deny the early exit."""
    s = router.select_test_strategy("docs", ["README.md", "runner/db.py"])
    assert s["scope"] == "full"


def test_fully_inert_diff_skips():
    s = router.select_test_strategy("docs", ["README.md", "NOTES.txt"])
    assert s["scope"] == "skip"
    assert s["cmd"] == "true"


# ── skip patterns are now reachable at all ───────────────────────────────────

def test_inert_diff_earns_early_exit_even_for_a_full_kind():
    s = router.select_test_strategy("build", ["docs/guide.md"])
    assert s["scope"] == "skip"
    assert router.get_test_command("build", ["docs/guide.md"]) == "true"


# ── escalation still outranks everything ─────────────────────────────────────

@pytest.mark.parametrize("path,reason", [
    ("tests/test_thing.py", "test file changed"),
    ("package.json", "dependency change"),
    (".env.production", "env config change"),
])
def test_escalating_patterns_force_a_full_run(path, reason):
    s = router.select_test_strategy("docs", [path])
    assert s["scope"] == "full"
    assert reason in s["reason"]


def test_escalation_beats_an_otherwise_inert_diff():
    s = router.select_test_strategy("docs", ["README.md", "package.json"])
    assert s["scope"] == "full"


# ── unchanged behaviour ──────────────────────────────────────────────────────

def test_kind_strategy_applies_when_no_files_are_known():
    assert router.select_test_strategy("docs")["scope"] == "skip"
    assert router.select_test_strategy("bugfix")["scope"] == "full"
    assert router.select_test_strategy("canary")["scope"] == "targeted"


def test_unknown_kind_defaults_to_full():
    s = router.select_test_strategy("wat")
    assert s["scope"] == "full" and "unknown kind" in s["reason"]


def test_disabled_router_always_runs_full(monkeypatch):
    monkeypatch.setattr(router, "ENABLED", False)
    assert router.select_test_strategy("docs", ["README.md"])["scope"] == "full"


def test_project_test_cmd_overrides_only_on_full():
    assert router.get_test_command("bugfix", None, "pytest -q") == "pytest -q"
    assert router.get_test_command("docs", ["README.md"], "pytest -q") == "true"


def test_returned_strategy_is_a_copy():
    """Callers must not be able to mutate the shared TEST_STRATEGIES table."""
    s = router.select_test_strategy("build")
    s["scope"] = "mutated"
    assert router.TEST_STRATEGIES["build"]["scope"] == "full"


def test_route_summary_counts_by_scope():
    counts = router.route_summary([{"kind": "docs"}, {"kind": "build"}, {"kind": "canary"}])
    assert counts["skip"] == 1 and counts["full"] == 1 and counts["targeted"] == 1

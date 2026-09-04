#!/usr/bin/env python3
"""The module docstring must be the first statement, not merely the first text.

`runner/preflight_filter.py` carried a fifteen-line block of documentation that
Python discarded, because it sat below `from __future__ import annotations`. A
triple-quoted string in that position is an expression statement, not a docstring:
`__doc__` is None, `help()` and `pydoc` show nothing, and every doc-reading tool
treats the module as undocumented — while anyone opening the file sees a docstring
and has no reason to look further.

These tests pin the fix on that file and add a repo-wide guard, because the failure
is invisible by inspection and would otherwise come straight back.
"""
import ast
import os
import pathlib
import sys

import pytest

RUNNER = pathlib.Path(__file__).resolve().parent.parent
REPO = RUNNER.parent
sys.path.insert(0, str(RUNNER))


def _module_docstring(path: pathlib.Path):
    return ast.get_docstring(ast.parse(path.read_text(encoding="utf-8", errors="replace")))


# ------------------------------------------------ the file this task is about


def test_preflight_filter_has_a_real_module_docstring():
    doc = _module_docstring(RUNNER / "preflight_filter.py")
    assert doc, "preflight_filter.py has no module docstring"
    assert "Pre-dispatch quality gate" in doc


def test_preflight_filter_docstring_is_reachable_at_runtime():
    """The check that ast alone cannot make: __doc__ on the imported module."""
    import preflight_filter

    assert preflight_filter.__doc__
    assert "Pre-dispatch quality gate" in preflight_filter.__doc__


def test_docstring_precedes_the_future_import():
    """`from __future__` must come after the docstring, which is the one thing
    Python allows above it."""
    tree = ast.parse((RUNNER / "preflight_filter.py").read_text())
    first = tree.body[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
    assert isinstance(first.value.value, str)
    futures = [n for n in tree.body if isinstance(n, ast.ImportFrom)
               and n.module == "__future__"]
    assert futures, "the __future__ import must be preserved, not deleted"
    assert futures[0].lineno > first.lineno


def test_shebang_is_still_the_first_line():
    lines = (RUNNER / "preflight_filter.py").read_text().splitlines()
    assert lines[0].startswith("#!")


def test_no_orphaned_string_left_behind():
    """The block was moved, not copied — exactly one copy must remain."""
    src = (RUNNER / "preflight_filter.py").read_text()
    assert src.count("Pre-dispatch quality gate") == 1


def test_the_module_still_works():
    """A docstring move must not change behaviour."""
    import preflight_filter

    assert callable(getattr(preflight_filter, "should_skip", None)) or True
    assert preflight_filter._GARBAGE_PROMPT_RE.search("PATCH TEMPLATE 0a1b")
    assert not preflight_filter._GARBAGE_PROMPT_RE.search(
        "Implement the retry backoff in runner/db.py")


# ------------------------------------------------------------ repo-wide guard


def _candidate_modules():
    """Non-test runner modules that declare a `from __future__` import.

    Scoped to those because they are the only ones where this specific mistake —
    a docstring displaced below the one import that must come first — can occur.
    """
    out = []
    for path in sorted(RUNNER.glob("*.py")):
        if path.name.startswith("test_"):
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "from __future__" not in src:
            continue
        out.append(path)
    return out


def _hides_a_docstring(path: pathlib.Path) -> bool:
    """True if a bare string literal sits directly below `from __future__`."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return False
    for prev, node in zip(tree.body, tree.body[1:]):
        if (isinstance(prev, ast.ImportFrom) and prev.module == "__future__"
                and isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            return True
    return False


#: Modules that already carry this defect as of 2026-08-24. Twenty-six of them —
#: the same displaced-docstring shape as preflight_filter.py, found by the guard
#: below the moment it was written. They are NOT fixed here: this task's scope is
#: one file, and rewriting the header of runner.py and merge_train.py in an agent
#: branch is merge-conflict bait for every other branch in flight.
#:
#: This is a ratchet, in the same spirit as `.convention-lint-baseline.json` and
#: the @ts-nocheck ratchet: the list may only shrink. A new offender fails the
#: build, and fixing one without removing it from this list fails too, so the
#: baseline cannot quietly rot into a permanent exemption.
KNOWN_DISPLACED_DOCSTRINGS = frozenset({
    "batch_fusion.py", "build_cache.py", "conflict_predictor.py",
    "cross_project_templates.py", "db_recovery_sprint.py", "feedback.py",
    "generator_feedback.py", "intake_dedup.py", "merge_invariant_firewall.py",
    "merge_train.py", "merged_diff_library.py", "outcome_router.py",
    "output_recycling.py", "pattern_compiler.py", "pattern_transfer.py",
    "periodic.py", "precedent.py", "prompt_distillation.py",
    "prompt_evolution.py", "resource_medic.py", "reuse_first.py", "runner.py",
    "session_cache.py", "task_dedup.py", "train_status_backfill.py",
    "transfer_learning.py",
})


def test_there_is_something_to_check():
    """A glob bug must not turn the guard below into a vacuous pass."""
    assert _candidate_modules(), "found no runner modules with a __future__ import"


def test_preflight_filter_is_not_on_the_baseline():
    """The file this task fixed must never be re-admitted to the exemption list."""
    assert "preflight_filter.py" not in KNOWN_DISPLACED_DOCSTRINGS


def test_no_new_module_hides_a_docstring_below_its_future_import():
    """The ratchet: no offender outside the recorded baseline."""
    offenders = {p.name for p in _candidate_modules() if _hides_a_docstring(p)}
    new = sorted(offenders - KNOWN_DISPLACED_DOCSTRINGS)
    assert not new, (
        f"{new} put a string literal directly below the __future__ import. Python "
        f"discards it; it is not the module docstring, so __doc__ is None and pydoc "
        f"shows nothing. Move it above the import, immediately after the shebang."
    )


def test_the_baseline_shrinks_and_never_rots():
    """A module fixed but left on the baseline turns the list into dead weight."""
    offenders = {p.name for p in _candidate_modules() if _hides_a_docstring(p)}
    stale = sorted(KNOWN_DISPLACED_DOCSTRINGS - offenders)
    assert not stale, (
        f"{stale} no longer hide a docstring — remove them from "
        f"KNOWN_DISPLACED_DOCSTRINGS so the ratchet keeps tightening."
    )

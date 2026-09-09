"""Every test root is either collected by default, or excluded on purpose.

This repo has three directories holding `test_*.py`: `runner`, `tests`, and
`tools/tests`. Until today `testpaths` named only the first, so:

  * `tools/tests` — 400 tests — was collected by NOTHING. Not testpaths, not any
    workflow under .github/workflows, not the merge gate. Four hundred assertions
    that could not fail, and no signal that they weren't running.
  * `tests` — 2,289 tests — could not be collected standalone at all:
    `tests/test_test_provenance.py` imported `tools/test_provenance.py`, a module
    that is not in this repository, and pytest treats a collection error as
    fatal. One absent module aborted a 146-file root before a single test ran.

Both were invisible for the same reason: nothing asserted that a directory full
of tests is actually reached. A test that never runs is worse than no test,
because it reads as coverage.

So this file asserts the invariant directly. A new test root is either added to
`testpaths` or written down here with the reason it is not — and either way it is
a decision on the record rather than a directory nobody noticed.
"""
import configparser
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PYTEST_INI = os.path.join(ROOT, "pytest.ini")

# Directories that hold tests but are deliberately outside the default run.
# Each entry must carry a reason; an empty reason fails the test below, so this
# cannot become a silent allowlist.
_SUBPACKAGE_REASON = (
    "In-repo Python package (it has its own __init__.py) whose tests nothing "
    "collects. Found by this guard on 2026-09-09; not added to testpaths in the "
    "same change because none of these roots has been run to green and a bare "
    "`pytest` must not go red for unrelated reasons. Each needs its own pass: "
    "run it, fix or delete what fails, then move it into testpaths and drop this "
    "entry.")

KNOWN_UNCOLLECTED = {
    "tests": ("2,289 tests that have never been run to green in one piece. The "
              "merge gate runs them explicitly (`pytest runner/tests tests`); "
              "adding them to testpaths would make a bare `pytest` red for "
              "reasons unrelated to whoever typed it. Remove this entry once the "
              "root is green."),
    # The inventory below is the point of this file: twelve directories of tests
    # that no gate, no workflow and no default invocation reaches. They are named
    # here so the number is on the record and cannot quietly grow.
    "beethoven": _SUBPACKAGE_REASON,
    "hisanta": _SUBPACKAGE_REASON,
    "ops": _SUBPACKAGE_REASON,
    "pareto": _SUBPACKAGE_REASON,
    "src": _SUBPACKAGE_REASON,
    "triage": _SUBPACKAGE_REASON,
}

# Directories that are not test roots even though a matching file may appear
# under them.
IGNORED_PREFIXES = (
    ".git", "node_modules", "__pycache__", "_to_delete", "intake",
    "claude-orchestrator-wt", "patches",
)


def _testpaths():
    cfg = configparser.ConfigParser()
    cfg.read(PYTEST_INI)
    raw = cfg.get("pytest", "testpaths", fallback="")
    return [p.strip() for p in raw.split() if p.strip()]


def _test_root_dirs():
    """Directories directly containing at least one `test_*.py`."""
    roots = set()
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel = os.path.relpath(dirpath, ROOT)
        if rel == ".":
            rel = ""
        parts = rel.split(os.sep) if rel else []
        if any(p.startswith(".") or p in IGNORED_PREFIXES for p in parts):
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in IGNORED_PREFIXES]
        if any(re.match(r"test_.*\.py$", f) for f in filenames):
            roots.add(rel or ".")
    return roots


def _covered(rel, testpaths):
    return any(rel == tp or rel.startswith(tp.rstrip("/") + os.sep)
               for tp in testpaths)


# ── the invariant ───────────────────────────────────────────────────────────

def test_testpaths_is_declared_at_all():
    # Without it, which tests run depends on the path someone happens to type.
    assert _testpaths(), "pytest.ini declares no testpaths"


def test_tools_tests_is_collected_by_default():
    """The regression this file exists for: 400 tests run by nothing."""
    assert _covered("tools/tests", _testpaths()), (
        "tools/tests is not in testpaths — its tests cannot fail")


def test_runner_is_still_collected():
    assert _covered("runner/tests", _testpaths())


def test_every_test_root_is_collected_or_explicitly_excused():
    testpaths = _testpaths()
    unexplained = []
    for rel in sorted(_test_root_dirs()):
        if _covered(rel, testpaths):
            continue
        top = rel.split(os.sep)[0]
        if top in KNOWN_UNCOLLECTED or rel in KNOWN_UNCOLLECTED:
            continue
        unexplained.append(rel)
    assert not unexplained, (
        "these directories hold tests that nothing collects, and are not listed "
        "in KNOWN_UNCOLLECTED with a reason: %s" % unexplained)


def test_every_excuse_carries_a_reason():
    # An allowlist without reasons is just a way to hide the problem.
    for name, reason in KNOWN_UNCOLLECTED.items():
        assert reason and len(reason) > 40, (
            "KNOWN_UNCOLLECTED[%r] needs a real reason" % name)


def test_an_excused_root_that_became_collected_is_flagged():
    """Stale excuses are their own failure mode.

    If `tests` is later added to testpaths, this entry must be deleted — leaving
    it behind would keep suppressing a check that no longer needs suppressing,
    and the next genuinely-uncollected root under it would slip past.
    """
    testpaths = _testpaths()
    stale = [n for n in KNOWN_UNCOLLECTED if _covered(n, testpaths)]
    assert not stale, (
        "these are in testpaths now and their KNOWN_UNCOLLECTED entry should be "
        "removed: %s" % stale)


def test_an_excused_root_still_exists():
    # A reason for a directory that is gone is noise that outlives its subject.
    missing = [n for n in KNOWN_UNCOLLECTED
               if not os.path.isdir(os.path.join(ROOT, n))]
    assert not missing, "KNOWN_UNCOLLECTED names directories that no longer exist: %s" % missing


# ── the collection blocker that hid the second root ─────────────────────────

def test_the_tests_root_can_at_least_be_collected():
    """`tests/` must not abort on import, whether or not it is in testpaths.

    pytest treats a collection error as fatal for the whole run, so a single
    module importing something absent takes down every sibling. That is how
    2,289 tests went from 'excluded' to 'impossible to include'.
    """
    import subprocess
    import sys
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q",
         "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert "error during collection" not in (proc.stdout + proc.stderr), (
        proc.stdout[-2000:] + proc.stderr[-2000:])


def test_a_test_whose_subject_is_missing_skips_rather_than_erroring():
    """Pinned on the specific file that caused it.

    tests/test_test_provenance.py is the executable specification of a linter
    (tools/test_provenance.py) that was never committed. Preserving it as a
    module-scope skip keeps the spec and names why it is dormant; a bare import
    made it a landmine for every other test in the directory.
    """
    path = os.path.join(ROOT, "tests", "test_test_provenance.py")
    if not os.path.exists(path):
        pytest.skip("tests/test_test_provenance.py has been removed")
    src = open(path).read()
    assert "importorskip" in src, (
        "this module imports a subject that may be absent; it must skip rather "
        "than raise at collection")

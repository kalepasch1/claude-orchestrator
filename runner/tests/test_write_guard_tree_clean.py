#!/usr/bin/env python3
"""write_guard has a unit test. Nothing checked the tree it guards.

`runner/write_guard.py` was written because a model emitted
`test_template_95fc17a.py` at the repo root whose entire body was its own
filename, breaking `pytest --collect-only` for the whole repo with
`NameError: name 'test_template_95fc17a' is not defined`. The guard refuses that
write — and `runner/tests/test_write_guard.py` proves the predicate is correct on
synthetic inputs.

But the guard only runs on WRITES. It cannot see what is already committed, and
the original offending file was still sitting in the repo root months later: it
predates the guard, so the guard never had a chance to refuse it. A predicate
nothing applies to the real tree is a rule with no enforcement.

This is the enforcement — the same `write_guard.check()`, run over every tracked
test file. Deliberately narrow: it asserts nothing new, it just makes the rule
already stated in write_guard.py true of the repository.

Run: python3 -m unittest runner.tests.test_write_guard_tree_clean -v
"""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import write_guard

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: Vendored/generated trees the guard has no authority over.
_SKIP_PREFIXES = (".git/", "node_modules/", ".venv/", "venv/", "__pycache__/",
                  ".pytest_cache/", ".aider.tags.cache.v4/", ".runtime/")

#: RATCHET. Test files that pre-date the guard and sit outside its allowed test
#: dirs. They are deliberately co-located with the code they cover (subproject
#: fixtures, tooling), and relocating them is a separate change with its own
#: import fallout — so they are named here rather than silently tolerated.
#:
#: The list may SHRINK, never grow. A new entry means an agent wrote a test
#: somewhere the guard would have refused, which is the thing this file exists to
#: catch. Nothing may be added to it without moving the file instead.
_LOCATION_RATCHET = frozenset({
    "pareto/2080/contracts/test_contracts_smoke.py",
    "pareto/2080/household_legal/test_household_legal.py",
    "test_missing_branch_scenario.py",
    "tools/test_merged_diff_memory.py",
    "tools/test_merged_diff_memory_comprehensive.py",
})


def _tracked_test_files():
    """Every git-tracked `test_*.py` / `*_test.py`. Empty list outside a checkout."""
    try:
        out = subprocess.check_output(
            ["git", "ls-files", "*test_*.py", "*_test.py"],
            cwd=REPO, text=True, timeout=60)
    except Exception:  # fail-soft: no git, no shallow checkout, no problem
        return []
    files = []
    for line in out.splitlines():
        rel = line.strip()
        if not rel or any(rel.startswith(p) or f"/{p}" in rel for p in _SKIP_PREFIXES):
            continue
        base = os.path.basename(rel)
        if base.startswith("test_") or base.endswith("_test.py"):
            files.append(rel)
    return files


def _read(rel):
    try:
        with open(os.path.join(REPO, rel), errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


class TreeIsCleanTest(unittest.TestCase):
    """Every committed test file would survive its own write guard."""

    @classmethod
    def setUpClass(cls):
        cls.files = _tracked_test_files()

    def test_the_scan_found_something(self):
        # A silently-empty scan would make every assertion below vacuous.
        if not self.files:
            self.skipTest("not a git checkout; nothing to scan")
        self.assertGreater(len(self.files), 50)

    def test_no_tracked_test_file_is_refused_by_the_guard(self):
        if not self.files:
            self.skipTest("not a git checkout; nothing to scan")
        offenders = []
        for rel in self.files:
            if rel in _LOCATION_RATCHET:
                continue
            reason = write_guard.check(rel, _read(rel))
            if reason:
                offenders.append(f"{rel}: {reason}")
        self.assertEqual(offenders, [],
                         "committed test files the write guard would refuse:\n  "
                         + "\n  ".join(offenders))

    def test_the_location_ratchet_only_shrinks(self):
        if not self.files:
            self.skipTest("not a git checkout; nothing to scan")
        tracked = set(self.files)
        stale = sorted(_LOCATION_RATCHET - tracked)
        self.assertEqual(stale, [],
                         "these were moved or deleted — remove them from _LOCATION_RATCHET "
                         f"so it cannot be used to re-admit them: {stale}")

    def test_ratcheted_files_are_only_location_violations(self):
        # The ratchet forgives WHERE a file lives. It must never forgive garbled
        # content — that is the failure the guard was written for.
        if not self.files:
            self.skipTest("not a git checkout; nothing to scan")
        for rel in sorted(_LOCATION_RATCHET & set(self.files)):
            body = _read(rel)
            self.assertNotEqual(body.strip(), os.path.basename(rel), rel)
            self.assertGreater(len(body.strip()), len(rel) * 2, rel)

    def test_no_test_file_body_is_just_its_own_name(self):
        # The original failure, asserted directly rather than via the guard, so a
        # future refactor of check() cannot quietly stop covering it.
        if not self.files:
            self.skipTest("not a git checkout; nothing to scan")
        offenders = [rel for rel in self.files
                     if _read(rel).strip() == os.path.basename(rel)]
        self.assertEqual(offenders, [], f"truncated model output committed as tests: {offenders}")

    def test_no_test_file_sits_at_the_repo_root(self):
        if not self.files:
            self.skipTest("not a git checkout; nothing to scan")
        root_level = [rel for rel in self.files
                      if "/" not in rel and rel not in _LOCATION_RATCHET]
        self.assertEqual(root_level, [],
                         f"tests belong in {write_guard.test_dirs()}, not the repo root: {root_level}")


class GuardStillWorksTest(unittest.TestCase):
    """Pin the two predicates this scan depends on, so a regression is attributable."""

    def test_root_level_test_file_is_refused(self):
        self.assertIsNotNone(write_guard.check("test_example.py"))

    def test_self_naming_body_is_refused(self):
        self.assertIsNotNone(
            write_guard.check("runner/tests/test_x.py", "test_x.py\n"))

    def test_a_normal_test_file_is_allowed(self):
        self.assertIsNone(
            write_guard.check("runner/tests/test_x.py", "import unittest\n"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""Tests for runner/tools/adjudicate_conflicted_refs.py.

Each case builds a throwaway git repo, so the assertions are about the
adjudicator's logic rather than about whatever the fleet repo looks like today.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
)

import adjudicate_conflicted_refs as acr  # noqa: E402


def _run(repo, *args):
    subprocess.run(
        ["git", "-C", repo] + list(args),
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _commit(repo, message):
    _run(repo, "add", "-A")
    _run(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.com",
        "commit",
        "-q",
        "-m",
        message,
    )
    return subprocess.run(
        ["git", "-C", repo, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout.strip()


def _write(repo, path, text):
    full = os.path.join(repo, path)
    os.makedirs(os.path.dirname(full) or repo, exist_ok=True)
    with open(full, "w", encoding="utf-8") as handle:
        handle.write(text)


class TestPathShape(unittest.TestCase):
    """is_malformed is the guard against creating files named after diff noise."""

    def test_assertion_line_is_malformed(self):
        self.assertTrue(acr.is_malformed("unittest.main()"))

    def test_embedded_source_blob_is_malformed(self):
        self.assertTrue(
            acr.is_malformed('"runner/utils/x.py\\nimport os\\nENABLED = True"')
        )

    def test_ordinary_path_is_not_malformed(self):
        self.assertFalse(acr.is_malformed("runner/tools/lint_conventions.py"))
        self.assertFalse(acr.is_malformed(".githooks/pre-commit"))

    def test_empty_and_none_are_malformed(self):
        self.assertTrue(acr.is_malformed(""))
        self.assertTrue(acr.is_malformed(None))

    def test_absolute_and_flaglike_paths_are_malformed(self):
        self.assertTrue(acr.is_malformed("/etc/passwd"))
        self.assertTrue(acr.is_malformed("--force"))

    def test_noise_paths_are_detected(self):
        self.assertTrue(acr.is_noise(".preopt_cache/x.json"))
        self.assertTrue(acr.is_noise("web/.claude/settings.local.json"))
        self.assertFalse(acr.is_noise("runner/runner.py"))

    def test_subsystem_of(self):
        self.assertEqual(acr.subsystem_of("runner/tools/x.py"), "runner")
        self.assertEqual(acr.subsystem_of("Makefile"), acr.ROOT_SUBSYSTEM)


class TestClassifyFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = self._tmp.name
        _run(self.repo, "init", "-q", "-b", "main")
        _write(self.repo, "keep.py", "x = 1\n")
        self.base = _commit(self.repo, "base")

    def tearDown(self):
        self._tmp.cleanup()

    def test_deleted_in_sweep_is_absent_in_sweep(self):
        """The killer case: a ledger's file list is a diff, not a manifest."""
        os.remove(os.path.join(self.repo, "keep.py"))
        _write(self.repo, "other.py", "y = 1\n")
        sweep = _commit(self.repo, "sweep with keep.py deleted")
        entry = acr.classify_file(self.repo, self.base, sweep, "keep.py")
        self.assertEqual(entry["verdict"], acr.ABSENT_IN_SWEEP)

    def test_identical_blob(self):
        _write(self.repo, "other.py", "y = 1\n")
        sweep = _commit(self.repo, "sweep")
        entry = acr.classify_file(self.repo, self.base, sweep, "keep.py")
        self.assertEqual(entry["verdict"], acr.IDENTICAL)

    def test_absent_on_base_is_recoverable(self):
        _write(self.repo, "brand_new.py", "z = 1\n")
        sweep = _commit(self.repo, "sweep")
        entry = acr.classify_file(self.repo, self.base, sweep, "brand_new.py")
        self.assertEqual(entry["verdict"], acr.ABSENT_ON_BASE)

    def test_diverged_when_both_sides_changed(self):
        # The sweep must live OFF the base's history, which is what a real
        # refs/orch-rescue ref is. If it were an ancestor the swept blob would
        # legitimately be HISTORICAL, and the test would be asserting on the
        # shape of its own fixture rather than on the classifier.
        _run(self.repo, "checkout", "-q", "-b", "sweepside")
        _write(self.repo, "keep.py", "x = 2  # sweep side\n")
        sweep = _commit(self.repo, "sweep")
        _run(self.repo, "checkout", "-q", "main")
        _write(self.repo, "keep.py", "x = 3  # base side\n")
        base2 = _commit(self.repo, "base moves on")
        entry = acr.classify_file(self.repo, base2, sweep, "keep.py")
        self.assertEqual(entry["verdict"], acr.DIVERGED)

    def test_historical_when_base_moved_past_the_swept_blob(self):
        sweep = self.base  # the swept blob is exactly the base's earlier state
        _write(self.repo, "keep.py", "x = 1\nx2 = 2\n")
        base2 = _commit(self.repo, "base moves on")
        entry = acr.classify_file(self.repo, base2, sweep, "keep.py")
        self.assertEqual(entry["verdict"], acr.HISTORICAL)

    def test_malformed_path_never_touches_git(self):
        entry = acr.classify_file(self.repo, self.base, self.base, "unittest.main()")
        self.assertEqual(entry["verdict"], acr.MALFORMED)

    def test_bad_ref_fails_soft(self):
        entry = acr.classify_file(self.repo, self.base, "deadbeef" * 5, "keep.py")
        self.assertEqual(entry["verdict"], acr.ABSENT_IN_SWEEP)


class TestLedgerAndRollup(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = self._tmp.name
        _run(self.repo, "init", "-q", "-b", "main")
        _write(self.repo, "keep.py", "x = 1\n")
        self.base = _commit(self.repo, "base")
        _write(self.repo, "brand_new.py", "z = 1\n")
        self.sweep = _commit(self.repo, "sweep")

    def tearDown(self):
        self._tmp.cleanup()

    def _ledger(self, files):
        path = os.path.join(self.repo, "ledger.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "items": [
                        {
                            "classification": acr.CONFLICTED,
                            "sha": self.sweep,
                            "ref": "refs/orch-rescue/test",
                            "created_at": 1,
                            "files": files,
                        },
                        {"classification": "ALREADY_PRESENT", "files": ["ignored.py"]},
                    ]
                },
                handle,
            )
        return path

    def test_load_conflicted_selects_only_conflicts(self):
        items = acr.load_conflicted(self._ledger(["keep.py"]))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["classification"], acr.CONFLICTED)

    def test_missing_ledger_returns_empty_not_raises(self):
        self.assertEqual(acr.load_conflicted("/nonexistent/ledger.json"), [])

    def test_unreadable_ledger_returns_empty_not_raises(self):
        bad = os.path.join(self.repo, "bad.json")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertEqual(acr.load_conflicted(bad), [])

    def test_recoverable_lists_only_absent_on_base(self):
        items = acr.load_conflicted(self._ledger(["keep.py", "brand_new.py"]))
        report = acr.adjudicate(self.repo, self.base, items)
        self.assertEqual([m["path"] for m in report["recoverable"]], ["brand_new.py"])

    def test_noise_is_never_recoverable(self):
        _write(self.repo, ".preopt_cache/x.json", "{}\n")
        sweep2 = _commit(self.repo, "sweep with cache")
        items = [
            {
                "classification": acr.CONFLICTED,
                "sha": sweep2,
                "ref": "r",
                "created_at": 1,
                "files": [".preopt_cache/x.json"],
            }
        ]
        report = acr.adjudicate(self.repo, self.base, items)
        self.assertEqual(report["recoverable"], [])

    def test_recover_absent_writes_the_file(self):
        items = acr.load_conflicted(self._ledger(["brand_new.py"]))
        report = acr.adjudicate(self.repo, self.base, items)
        os.remove(os.path.join(self.repo, "brand_new.py"))
        written = acr.recover_absent(self.repo, report)
        self.assertEqual(written, ["brand_new.py"])
        with open(os.path.join(self.repo, "brand_new.py"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "z = 1\n")

    def test_recover_absent_is_idempotent_and_never_clobbers(self):
        items = acr.load_conflicted(self._ledger(["brand_new.py"]))
        report = acr.adjudicate(self.repo, self.base, items)
        with open(os.path.join(self.repo, "brand_new.py"), "w", encoding="utf-8") as h:
            h.write("OPERATOR EDIT\n")
        self.assertEqual(acr.recover_absent(self.repo, report), [])
        with open(os.path.join(self.repo, "brand_new.py"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "OPERATOR EDIT\n")

    def test_needs_human_review_lists_only_diverged(self):
        # A DIVERGED verdict needs a swept blob that NEVER existed on the base,
        # so the sweep has to sit off the base's history with its own content.
        # A sweep that is an ancestor is legitimately HISTORICAL instead.
        _run(self.repo, "checkout", "-q", "-b", "sweepside", self.base)
        _write(self.repo, "keep.py", "x = 2  # sweep side\n")
        _write(self.repo, "brand_new.py", "z = 1\n")
        self.sweep = _commit(self.repo, "sweep off to the side")
        _run(self.repo, "checkout", "-q", "main")
        _write(self.repo, "keep.py", "x = 99  # base side\n")
        base2 = _commit(self.repo, "base diverges")
        items = acr.load_conflicted(self._ledger(["keep.py", "brand_new.py"]))
        report = acr.adjudicate(self.repo, base2, items)
        self.assertEqual([m["path"] for m in report["needs_human_review"]], ["keep.py"])

    def test_report_is_json_serialisable(self):
        items = acr.load_conflicted(self._ledger(["keep.py"]))
        report = acr.adjudicate(self.repo, self.base, items)
        self.assertIn("counts", json.loads(json.dumps(report)))


if __name__ == "__main__":
    unittest.main()

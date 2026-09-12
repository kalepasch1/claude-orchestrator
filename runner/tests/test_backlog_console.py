#!/usr/bin/env python3
"""`beethoven consolidate` / `beethoven backlog status`.

The acceptance criterion is that `backlog status` returns JSON where
`collapsed_tasks` is a subset of the tasks that went in, and any remainder is tagged
`manual_review`. That was unevaluable because no `beethoven` executable existed and
`backlog_status` printed a human table rather than JSON. Both gaps are closed here
WITHOUT rebuilding consolidation: backlog_compactor still does the collapsing.

Proof: python3 -m pytest runner/tests/test_backlog_console.py -q
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backlog_console as bc  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _Store:
    """A DB seam with no database: queued slugs in, updates recorded."""

    def __init__(self, queued=(), decomposed=(), manual=(), fail=False):
        self.queued = list(queued)
        self.decomposed = list(decomposed)
        self.manual = list(manual)
        self.updates = []
        self.fail = fail

    def select(self, table, params=None):
        if self.fail:
            raise RuntimeError("control plane down")
        state = (params or {}).get("state", "")
        note = (params or {}).get("note", "")
        if state == "eq.QUEUED":
            return [{"slug": s} for s in self.queued]
        if state == "eq.DECOMPOSED":
            return [{"slug": s} for s in self.decomposed]
        if note.startswith("like.manual_review"):
            return [{"slug": s} for s in self.manual]
        return []

    def count(self, table, params=None):
        if self.fail:
            raise RuntimeError("control plane down")
        return len(self.queued) if (params or {}).get("state") == "eq.QUEUED" else 0

    def update(self, table, match, patch):
        self.updates.append((match, patch))
        return [match]


class TestConsolidate(unittest.TestCase):
    def setUp(self):
        self.log = os.path.join(tempfile.mkdtemp(), "consolidation.log")

    def test_collapsed_tasks_is_a_subset_of_what_went_in(self):
        """The headline acceptance criterion, now actually assertable."""
        before = ["a", "b", "c", "d", "e", "f"]
        store = _Store(queued=list(before))

        def _compact():
            store.queued = ["e", "f"]      # a-d were collapsed
            return {"created": 1, "parked": 4}

        result = bc.consolidate(compactor=_compact, store=store, log_path=self.log)
        self.assertTrue(set(result["collapsed_tasks"]).issubset(set(before)))
        self.assertEqual(result["collapsed_tasks"], ["a", "b", "c", "d"])

    def test_survivors_are_tagged_manual_review_with_a_reason(self):
        store = _Store(queued=["a", "b"])

        def _compact():
            store.queued = ["b"]
            return {}

        result = bc.consolidate(compactor=_compact, store=store, log_path=self.log)
        self.assertEqual([e["slug"] for e in result["manual_review"]], ["b"])
        self.assertTrue(result["manual_review"][0]["reason"])

    def test_manual_review_is_written_back_to_the_task(self):
        store = _Store(queued=["a"])
        bc.consolidate(compactor=lambda: {}, store=store, log_path=self.log)
        self.assertEqual(store.updates[0][0], {"slug": "a"})
        self.assertTrue(store.updates[0][1]["note"].startswith("manual_review:"))

    def test_collapsed_and_manual_review_partition_the_input(self):
        before = ["a", "b", "c"]
        store = _Store(queued=list(before))

        def _compact():
            store.queued = ["c"]
            return {}

        result = bc.consolidate(compactor=_compact, store=store, log_path=self.log)
        covered = set(result["collapsed_tasks"]) | {e["slug"] for e in result["manual_review"]}
        self.assertEqual(covered, set(before))

    def test_the_compactor_summary_is_passed_through(self):
        store = _Store(queued=[])
        result = bc.consolidate(compactor=lambda: {"created": 2, "parked": 9},
                                store=store, log_path=self.log)
        self.assertEqual(result["summary"]["parked"], 9)

    def test_a_raising_compactor_is_reported_not_propagated(self):
        store = _Store(queued=["a"])

        def _boom():
            raise RuntimeError("compactor exploded")

        result = bc.consolidate(compactor=_boom, store=store, log_path=self.log)
        self.assertFalse(result["ok"])
        self.assertIn("compactor exploded", result["error"])

    def test_an_unavailable_store_does_not_raise(self):
        result = bc.consolidate(compactor=lambda: {}, store=None, log_path=self.log)
        self.assertTrue(result["ok"])
        self.assertEqual(result["collapsed_tasks"], [])

    def test_a_failing_store_read_does_not_raise(self):
        result = bc.consolidate(compactor=lambda: {}, store=_Store(fail=True),
                                log_path=self.log)
        self.assertTrue(result["ok"])

    def test_the_result_is_json_serializable(self):
        store = _Store(queued=["a"])
        payload = bc.consolidate(compactor=lambda: {}, store=store, log_path=self.log)
        self.assertIn("collapsed_tasks", json.loads(json.dumps(payload, default=str)))

    def test_limit_is_forwarded_when_given(self):
        seen = {}

        def _compact(limit=None):
            seen["limit"] = limit
            return {}

        bc.consolidate(compactor=_compact, store=_Store(), limit=25, log_path=self.log)
        self.assertEqual(seen["limit"], 25)


class TestConsolidationLog(unittest.TestCase):
    def setUp(self):
        self.log = os.path.join(tempfile.mkdtemp(), "consolidation.log")

    def test_every_run_is_logged(self):
        bc.consolidate(compactor=lambda: {}, store=_Store(), log_path=self.log)
        with open(self.log) as fh:
            self.assertIn("consolidate", fh.read())

    def test_each_manual_review_reason_is_logged(self):
        bc.consolidate(compactor=lambda: {}, store=_Store(queued=["a"]), log_path=self.log)
        with open(self.log) as fh:
            body = fh.read()
        self.assertIn("manual_review a:", body)

    def test_the_log_is_append_only(self):
        for _ in range(3):
            bc.consolidate(compactor=lambda: {}, store=_Store(), log_path=self.log)
        with open(self.log) as fh:
            self.assertEqual(len(fh.read().strip().splitlines()), 3)

    def test_an_unwritable_log_never_fails_the_run(self):
        self.assertFalse(bc.log_line("x", "/proc/definitely/not/writable/x.log"))
        result = bc.consolidate(compactor=lambda: {}, store=_Store(),
                                log_path="/proc/definitely/not/writable/x.log")
        self.assertTrue(result["ok"])


class TestStatus(unittest.TestCase):
    def test_status_returns_json_not_a_table(self):
        payload = bc.status(store=_Store(queued=["a", "b"], decomposed=["x"], manual=["y"]))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["collapsed_tasks"], ["x"])
        self.assertEqual(payload["manual_review"], ["y"])

    def test_status_counts_the_backlog(self):
        payload = bc.status(store=_Store(queued=["a", "b", "c"]))
        self.assertEqual(payload["states"]["QUEUED"], 3)
        self.assertEqual(payload["backlog_total"], 3)

    def test_merged_is_not_counted_as_backlog(self):
        self.assertNotIn("MERGED", bc.BACKLOG_STATES)
        self.assertNotIn("QUARANTINED", bc.BACKLOG_STATES)

    def test_status_degrades_rather_than_raising(self):
        payload = bc.status(store=_Store(fail=True))
        self.assertFalse(payload["ok"])
        self.assertIn("errors", payload)

    def test_status_without_a_control_plane_is_reported(self):
        payload = bc.status(store=None)
        self.assertFalse(payload["ok"])


class TestCli(unittest.TestCase):
    def test_help_exits_zero(self):
        self.assertEqual(bc.main(["--help"]), 0)

    def test_no_arguments_is_a_usage_error(self):
        self.assertEqual(bc.main([]), 2)

    def test_unknown_command_is_a_usage_error(self):
        self.assertEqual(bc.main(["frobnicate"]), 2)

    def test_the_entrypoint_exists_and_is_executable(self):
        path = os.path.join(REPO, "bin", "beethoven")
        self.assertTrue(os.path.isfile(path), f"{path} missing")
        self.assertTrue(os.access(path, os.X_OK), f"{path} not executable")

    def test_the_entrypoint_runs_and_prints_usage(self):
        out = subprocess.run([sys.executable, os.path.join(REPO, "bin", "beethoven"), "--help"],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("beethoven consolidate", out.stdout)

    def test_the_entrypoint_rejects_an_unknown_command_with_json(self):
        out = subprocess.run([sys.executable, os.path.join(REPO, "bin", "beethoven"), "nope"],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 2)
        self.assertFalse(json.loads(out.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()

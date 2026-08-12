#!/usr/bin/env python3
"""Unit tests for zombie_reaper.terminate_expired.

Uses an in-memory task store (no DB, no network) and a captured log, so the tests
assert both the state transition and the operator-facing warning.

Named test_zombie_reaper_terminate.py rather than test_zombie_reaper.py because
that name is already taken by the tests for the detection half in runner.py.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("ORCH_DB_ENABLED", "false")

import zombie_reaper  # noqa: E402


class InMemoryStore:
    """Minimal stand-in for runner/db.py: select + update over a dict of rows."""

    def __init__(self, rows=None, fail_on_select=(), fail_on_update=()):
        self.rows = {r["id"]: dict(r) for r in (rows or [])}
        self.fail_on_select = set(fail_on_select)
        self.fail_on_update = set(fail_on_update)
        self.updates = []

    @staticmethod
    def _eq(params, key):
        raw = str((params or {}).get(key) or "")
        return raw[3:] if raw.startswith("eq.") else raw

    def select(self, table, params=None):
        assert table == "tasks"
        task_id = self._eq(params, "id")
        if task_id in self.fail_on_select:
            raise RuntimeError("simulated read failure")
        row = self.rows.get(task_id)
        return [dict(row)] if row else []

    def update(self, table, match, patch):
        assert table == "tasks"
        task_id = match["id"]
        if task_id in self.fail_on_update:
            raise RuntimeError("simulated write failure")
        self.updates.append((task_id, dict(patch)))
        self.rows[task_id].update(patch)
        return [dict(self.rows[task_id])]


class CapturingLog:
    def __init__(self):
        self.warnings = []
        self.errors = []

    def warning(self, msg, *args):
        self.warnings.append(msg % args if args else msg)

    warn = warning

    def error(self, msg, *args):
        self.errors.append(msg % args if args else msg)

    def info(self, *a, **k):
        pass

    debug = info


class ReaperTestCase(unittest.TestCase):
    def setUp(self):
        self._real_log = zombie_reaper._log
        self.log = CapturingLog()
        zombie_reaper._log = self.log
        os.environ["ORCH_ZOMBIE_TERMINATE_ENABLED"] = "true"

    def tearDown(self):
        zombie_reaper._log = self._real_log
        os.environ.pop("ORCH_ZOMBIE_TERMINATE_ENABLED", None)

    @staticmethod
    def task(task_id, state="RUNNING", note=""):
        return {"id": task_id, "slug": f"slug-{task_id}", "state": state,
                "note": note, "account": "runner-1"}


class HappyPathTests(ReaperTestCase):
    def test_expired_task_moves_to_failed(self):
        store = InMemoryStore([self.task("t1")])
        r = zombie_reaper.terminate_expired(["t1"], store=store)
        self.assertEqual(r["terminated"], ["t1"])
        self.assertEqual(store.rows["t1"]["state"], "FAILED")

    def test_note_carries_the_reason(self):
        store = InMemoryStore([self.task("t1")])
        zombie_reaper.terminate_expired(["t1"], store=store)
        self.assertIn("zombie-reaper: expired heartbeat", store.rows["t1"]["note"])

    def test_existing_note_is_preserved(self):
        store = InMemoryStore([self.task("t1", note="attempt 3 of 5")])
        zombie_reaper.terminate_expired(["t1"], store=store)
        note = store.rows["t1"]["note"]
        self.assertIn("attempt 3 of 5", note)
        self.assertIn("expired heartbeat", note)

    def test_warning_names_the_task_id(self):
        store = InMemoryStore([self.task("t-abc")])
        zombie_reaper.terminate_expired(["t-abc"], store=store)
        self.assertTrue(any("t-abc" in w for w in self.log.warnings))

    def test_custom_reason_is_used(self):
        store = InMemoryStore([self.task("t1")])
        zombie_reaper.terminate_expired(["t1"], reason="repair budget exhausted",
                                        store=store)
        self.assertIn("repair budget exhausted", store.rows["t1"]["note"])

    def test_batch_terminates_every_expired_id(self):
        store = InMemoryStore([self.task(f"t{i}") for i in range(5)])
        r = zombie_reaper.terminate_expired([f"t{i}" for i in range(5)], store=store)
        self.assertEqual(len(r["terminated"]), 5)
        self.assertTrue(all(row["state"] == "FAILED" for row in store.rows.values()))

    def test_update_sets_updated_at(self):
        store = InMemoryStore([self.task("t1")])
        zombie_reaper.terminate_expired(["t1"], store=store)
        self.assertEqual(store.updates[0][1]["updated_at"], "now()")


class ConcurrencyAndEdgeCaseTests(ReaperTestCase):
    def test_missing_task_is_skipped_not_raised(self):
        store = InMemoryStore([])
        r = zombie_reaper.terminate_expired(["ghost"], store=store)
        self.assertEqual(r["missing"], ["ghost"])
        self.assertEqual(store.updates, [])

    def test_task_finished_concurrently_is_not_terminated(self):
        store = InMemoryStore([self.task("t1", state="DONE")])
        r = zombie_reaper.terminate_expired(["t1"], store=store)
        self.assertEqual(r["skipped"], ["t1"])
        self.assertEqual(store.rows["t1"]["state"], "DONE")
        self.assertEqual(store.updates, [])

    def test_task_requeued_concurrently_is_not_terminated(self):
        store = InMemoryStore([self.task("t1", state="QUEUED")])
        r = zombie_reaper.terminate_expired(["t1"], store=store)
        self.assertEqual(r["skipped"], ["t1"])
        self.assertEqual(store.rows["t1"]["state"], "QUEUED")

    def test_one_bad_id_does_not_abandon_the_batch(self):
        store = InMemoryStore(
            [self.task("good1"), self.task("bad"), self.task("good2")],
            fail_on_update={"bad"})
        r = zombie_reaper.terminate_expired(["good1", "bad", "good2"], store=store)
        self.assertEqual(r["terminated"], ["good1", "good2"])
        self.assertEqual(r["errored"], ["bad"])

    def test_read_failure_is_reported_not_raised(self):
        store = InMemoryStore([self.task("t1")], fail_on_select={"t1"})
        r = zombie_reaper.terminate_expired(["t1"], store=store)
        self.assertEqual(r["errored"], ["t1"])

    def test_empty_input_is_a_no_op(self):
        store = InMemoryStore([self.task("t1")])
        r = zombie_reaper.terminate_expired([], store=store)
        self.assertEqual(r, {"terminated": [], "skipped": [], "missing": [],
                             "errored": []})
        self.assertEqual(store.updates, [])

    def test_none_input_is_a_no_op(self):
        store = InMemoryStore([self.task("t1")])
        self.assertEqual(zombie_reaper.terminate_expired(None, store=store)["terminated"], [])

    def test_single_string_id_is_accepted(self):
        store = InMemoryStore([self.task("t1")])
        r = zombie_reaper.terminate_expired("t1", store=store)
        self.assertEqual(r["terminated"], ["t1"])

    def test_duplicate_ids_are_terminated_once(self):
        store = InMemoryStore([self.task("t1")])
        r = zombie_reaper.terminate_expired(["t1", "t1", "t1"], store=store)
        self.assertEqual(r["terminated"], ["t1"])
        self.assertEqual(len(store.updates), 1)

    def test_blank_and_none_ids_are_dropped(self):
        store = InMemoryStore([self.task("t1")])
        r = zombie_reaper.terminate_expired(["", None, "  ", "t1"], store=store)
        self.assertEqual(r["terminated"], ["t1"])
        self.assertEqual(r["missing"], [])

    def test_non_iterable_input_is_a_no_op(self):
        store = InMemoryStore([self.task("t1")])
        self.assertEqual(zombie_reaper.terminate_expired(12345, store=store)["terminated"],
                         [])

    def test_unresolvable_store_marks_everything_errored(self):
        class Broken:
            def select(self, *a, **k):
                raise RuntimeError("down")

            def update(self, *a, **k):
                raise RuntimeError("down")

        r = zombie_reaper.terminate_expired(["t1", "t2"], store=Broken())
        self.assertEqual(r["errored"], ["t1", "t2"])


class DryRunTests(ReaperTestCase):
    def test_disabled_via_env_does_not_write(self):
        os.environ["ORCH_ZOMBIE_TERMINATE_ENABLED"] = "false"
        store = InMemoryStore([self.task("t1")])
        r = zombie_reaper.terminate_expired(["t1"], store=store)
        self.assertEqual(r["terminated"], ["t1"])
        self.assertEqual(store.updates, [])
        self.assertEqual(store.rows["t1"]["state"], "RUNNING")

    def test_explicit_dry_run_overrides_env(self):
        store = InMemoryStore([self.task("t1")])
        zombie_reaper.terminate_expired(["t1"], store=store, dry_run=True)
        self.assertEqual(store.updates, [])

    def test_dry_run_still_respects_state_guard(self):
        store = InMemoryStore([self.task("t1", state="DONE")])
        r = zombie_reaper.terminate_expired(["t1"], store=store, dry_run=True)
        self.assertEqual(r["skipped"], ["t1"])
        self.assertEqual(r["terminated"], [])


class ClassApiTests(ReaperTestCase):
    def test_instance_can_target_a_different_state_pair(self):
        reaper = zombie_reaper.ZombieReaper(expected_state="RETRY",
                                            failed_state="BLOCKED")
        store = InMemoryStore([self.task("t1", state="RETRY")])
        r = reaper.terminate_expired(["t1"], store=store)
        self.assertEqual(r["terminated"], ["t1"])
        self.assertEqual(store.rows["t1"]["state"], "BLOCKED")

    def test_store_bound_at_construction_is_used(self):
        store = InMemoryStore([self.task("t1")])
        reaper = zombie_reaper.ZombieReaper(store=store)
        self.assertEqual(reaper.terminate_expired(["t1"])["terminated"], ["t1"])

    def test_module_function_delegates_to_singleton(self):
        self.assertIsInstance(zombie_reaper._reaper, zombie_reaper.ZombieReaper)


if __name__ == "__main__":
    unittest.main()

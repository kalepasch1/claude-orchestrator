"""Regressions in the canonical enqueue path, measured 2026-08-12.

1. db.test_trigger PATCHed state to the hardcoded literal "TESTING", which is
   not a member of the task_state enum on this database. Every PATCH was
   rejected and swallowed by a bare `except: return None`, so the QUEUED->trigger
   transition had never fired anywhere and nothing said so.
2. enqueue_task._find_open_by_intent read the newest 1000 open rows and scanned
   them in Python. An open task older than that page was invisible to dedup, so
   an equivalent open intent could be inserted a second time.
"""

import os
import sys
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import db  # noqa: E402
import enqueue_task  # noqa: E402

REAL_STATES = ("QUEUED", "WAITING", "RUNNING", "RETRY", "DONE", "BLOCKED", "CONFLICT",
               "TESTFAIL", "MERGED", "SHELVED", "MERGING", "DECOMPOSED", "QUARANTINED",
               "SUPERSEDED", "CLOSED", "DEPLOYED_AND_VERIFIED", "PHANTOM_UNVERIFIED")


class TriggerStateTests(unittest.TestCase):
    def setUp(self):
        self._req = db._req
        self._cache = getattr(db.task_state_values, "_cache", None)
        self._trigger = db.TRIGGER_STATE
        db.task_state_values._cache = REAL_STATES
        self.calls = []

    def tearDown(self):
        db._req = self._req
        db.task_state_values._cache = self._cache
        db.TRIGGER_STATE = self._trigger

    def _patch_req(self, rows=None, boom=None):
        def fake(method, path, **kw):
            self.calls.append((method, path, kw))
            if boom:
                raise boom
            return rows or []
        db._req = fake

    def test_illegal_trigger_state_is_explained_not_swallowed(self):
        """The regression: TESTING is not in the enum, so the PATCH is rejected.

        The old code swallowed this into a bare `return None`, so an enqueue that
        never triggered looked exactly like one that did.
        """
        db.TRIGGER_STATE = "TESTING"
        self._patch_req(boom=RuntimeError(
            'invalid input value for enum task_state: "TESTING"'))
        self.assertIsNone(db.test_trigger("task-1"))
        self.assertIn("not a member of task_state", db.test_trigger.last_error)
        self.assertIn("QUEUED and claimable", db.test_trigger.last_error)
        self.assertIn("TESTING", db.test_trigger.last_error)

    def test_a_legal_state_is_never_pre_refused_from_a_sampled_list(self):
        """A sample is a lower bound on the enum, never proof of illegality."""
        db.task_state_values._cache = ("QUEUED", "RUNNING")
        db.TRIGGER_STATE = "SHELVED"          # legal, but absent from the sample
        self._patch_req(rows=[{"id": "task-1", "state": "SHELVED"}])
        self.assertIsNotNone(db.test_trigger("task-1"))
        self.assertTrue(self.calls, "the write must be attempted")

    def test_bad_enum_detector(self):
        self.assertTrue(db._looks_like_bad_enum(
            RuntimeError('invalid input value for enum task_state: "TESTING"')))
        self.assertTrue(db._looks_like_bad_enum(RuntimeError("ERROR: 22P02 ... enum")))
        self.assertFalse(db._looks_like_bad_enum(RuntimeError("connection reset")))

    def test_legal_trigger_state_is_written_atomically(self):
        db.TRIGGER_STATE = "SHELVED"
        self._patch_req(rows=[{"id": "task-1", "state": "SHELVED"}])
        row = db.test_trigger("task-1")
        self.assertEqual(row["state"], "SHELVED")
        method, path, kw = self.calls[0]
        self.assertEqual((method, path), ("PATCH", "/rest/v1/tasks"))
        # Atomicity: the guard on the old state is what makes it a safe trigger.
        self.assertEqual(kw["params"]["state"], "eq.QUEUED")
        self.assertEqual(kw["params"]["id"], "eq.task-1")
        self.assertEqual(kw["body"]["state"], "SHELVED")

    def test_already_claimed_task_reports_why(self):
        db.TRIGGER_STATE = "SHELVED"
        self._patch_req(rows=[])
        self.assertIsNone(db.test_trigger("task-1"))
        self.assertIn("not QUEUED at trigger time", db.test_trigger.last_error)

    def test_db_error_is_fail_soft_and_recorded(self):
        db.TRIGGER_STATE = "SHELVED"
        self._patch_req(boom=RuntimeError("postgrest exploded"))
        self.assertIsNone(db.test_trigger("task-1"))
        self.assertIn("postgrest exploded", db.test_trigger.last_error)

    def test_missing_task_id_is_fail_soft(self):
        self.assertIsNone(db.test_trigger(""))
        self.assertIsNone(db.test_trigger(None))

    def test_unknown_state_sample_does_not_block_the_write(self):
        """() means 'could not determine' — never treat that as 'illegal'."""
        db.task_state_values._cache = ()
        db.TRIGGER_STATE = "TESTING"
        self._patch_req(rows=[{"id": "task-1"}])
        self.assertIsNotNone(db.test_trigger("task-1"))


class IntentScanTests(unittest.TestCase):
    """_find_open_by_intent must not miss an open task past the first page."""

    def setUp(self):
        self._select = enqueue_task.db.select

    def tearDown(self):
        enqueue_task.db.select = self._select

    def _rows(self, n, start=0):
        return [{"id": f"id-{i}", "slug": f"slug-{i}", "state": "QUEUED",
                 "attempt": 0, "note": ""} for i in range(start, start + n)]

    def test_marker_match_is_filtered_server_side(self):
        seen = {}

        def fake_select(table, params):
            seen.update(params)
            key = params.get("note", "")
            if key.startswith("like."):
                return [{"id": "hit", "slug": "s", "state": "QUEUED", "attempt": 0,
                         "note": "[enqueue-intent:p::wanted::]"}]
            return []

        enqueue_task.db.select = fake_select
        row = enqueue_task._find_open_by_intent("p", "p::wanted::")
        self.assertEqual(row["id"], "hit")
        self.assertTrue(seen["note"].startswith("like.*[enqueue-intent:"))

    def test_legacy_match_beyond_the_first_page_is_found(self):
        """The regression: this row sat past row 1000 and was invisible."""
        target = {"id": "old", "slug": "wanted", "state": "QUEUED", "attempt": 0,
                  "note": ""}
        pages = [self._rows(enqueue_task._INTENT_SCAN_PAGE),
                 self._rows(5) + [target]]

        def fake_select(table, params):
            if str(params.get("note", "")).startswith("like."):
                return []
            index = int(params.get("offset", 0)) // enqueue_task._INTENT_SCAN_PAGE
            return pages[index] if index < len(pages) else []

        enqueue_task.db.select = fake_select
        key = enqueue_task.intent_key("p", "wanted")
        self.assertEqual(enqueue_task._find_open_by_intent("p", key)["id"], "old")

    def test_scan_terminates_on_a_short_page(self):
        calls = []

        def fake_select(table, params):
            calls.append(params.get("offset", "0"))
            if str(params.get("note", "")).startswith("like."):
                return []
            return self._rows(3)

        enqueue_task.db.select = fake_select
        self.assertIsNone(enqueue_task._find_open_by_intent("p", "p::nope::"))
        self.assertLessEqual(len(calls), 2, "a short page must end the scan")

    def test_scan_is_bounded(self):
        def fake_select(table, params):
            if str(params.get("note", "")).startswith("like."):
                return []
            return self._rows(enqueue_task._INTENT_SCAN_PAGE)

        enqueue_task.db.select = fake_select
        self.assertIsNone(enqueue_task._find_open_by_intent("p", "p::nope::"))

    def test_key_with_filter_metacharacters_skips_the_like_pass(self):
        seen = []

        def fake_select(table, params):
            seen.append(params)
            return []

        enqueue_task.db.select = fake_select
        enqueue_task._find_open_by_intent("p", "p::a,b(c)::")
        self.assertFalse(any("note" in p for p in seen))


class ScanKnobTests(unittest.TestCase):
    def test_bad_values_fall_back_to_the_default(self):
        for bad in ("", "abc", "0", "-1"):
            os.environ["ORCH_INTENT_SCAN_PAGE"] = bad
            self.assertEqual(enqueue_task._int_env("ORCH_INTENT_SCAN_PAGE", 1000), 1000, bad)
        os.environ.pop("ORCH_INTENT_SCAN_PAGE", None)

    def test_override_applies(self):
        os.environ["ORCH_INTENT_SCAN_PAGE"] = "250"
        try:
            self.assertEqual(enqueue_task._int_env("ORCH_INTENT_SCAN_PAGE", 1000), 250)
        finally:
            os.environ.pop("ORCH_INTENT_SCAN_PAGE", None)


if __name__ == "__main__":
    unittest.main()

"""A project the cache has not seen is invisible to claim_task, not merely stale.

claim_task caches the projects list at module scope for five minutes, then
derives HOST AFFINITY from it: `local_repo_pids` is built from the cached rows,
and every task whose project_id is absent from that set is filtered out of the
claim. So during the TTL a project that was just added — or whose repo_path was
just corrected, or whose repo was just cloned onto this machine — does not get
lower priority. It gets no lane at all, and the runner prints "no
locally-runnable tasks" while its queue is full.

This surfaced as a test-isolation failure first: two tests in
test_pinned_express_lane.py declared their own projects, inherited the previous
test's cached list instead, had all their tasks filtered out, and so passed
alone but failed in suite order. Same mechanism, smaller blast radius.
"""
import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db


PROJECT_FIELDS = "id,name,priority,concurrency_weight,repo_path"


def _project(pid, name, repo_path=None):
    return {"id": pid, "name": name, "priority": 5,
            "concurrency_weight": 1, "repo_path": repo_path}


class TestProjectsCacheInvalidation(unittest.TestCase):

    def setUp(self):
        # Save and restore rather than leaving the clock at zero: an invalidated
        # cache makes the next file's first refresh issue a projects query its
        # mock did not expect.
        self._saved_projects = list(db._cached_projects_list)
        self._saved_at = db._PROJECT_CACHE_TIME["at"]
        db.invalidate_projects_cache()

    def tearDown(self):
        db._cached_projects_list = self._saved_projects
        db._PROJECT_CACHE_TIME["at"] = self._saved_at

    def test_the_cache_starts_empty_after_invalidation(self):
        self.assertEqual(db._cached_projects_list, [])

    def test_a_warm_cache_is_not_re_read(self):
        """The TTL is the point of the cache — it must still hold."""
        calls = []

        def counting(table, params=None):
            calls.append(table)
            return [_project("p1", "one")]

        with patch.object(db, "select", side_effect=counting):
            db._refresh_projects_cache()
            db._refresh_projects_cache()
            db._refresh_projects_cache()

        self.assertEqual(len(calls), 1)

    def test_invalidating_forces_the_next_refresh_to_re_read(self):
        first = [_project("p1", "one")]
        second = [_project("p1", "one"), _project("p2", "two")]
        responses = [first, second]

        def popping(table, params=None):
            return responses.pop(0)

        with patch.object(db, "select", side_effect=popping):
            db._refresh_projects_cache()
            self.assertEqual(len(db._cached_projects_list), 1)

            db.invalidate_projects_cache()
            db._refresh_projects_cache()

        self.assertEqual([p["id"] for p in db._cached_projects_list], ["p1", "p2"])

    def test_a_newly_added_project_is_invisible_until_invalidation(self):
        """The production symptom: not lower priority — no lane at all."""
        old = [_project("p-old", "old")]
        new = [_project("p-old", "old"), _project("p-new", "new")]
        responses = [old, new, new]

        def popping(table, params=None):
            return responses.pop(0) if responses else new

        with patch.object(db, "select", side_effect=popping):
            db._refresh_projects_cache()
            visible = {p["id"] for p in db._cached_projects_list}
            self.assertNotIn("p-new", visible, "precondition: cache predates the project")

            db._refresh_projects_cache()          # still inside the TTL
            self.assertNotIn("p-new", {p["id"] for p in db._cached_projects_list})

            db.invalidate_projects_cache()
            db._refresh_projects_cache()
            self.assertIn("p-new", {p["id"] for p in db._cached_projects_list})

    def test_a_refresh_failure_keeps_the_previous_list(self):
        """Fail-soft: a DB blip must not empty the cache and idle every lane."""
        with patch.object(db, "select", return_value=[_project("p1", "one")]):
            db._refresh_projects_cache()

        db._PROJECT_CACHE_TIME["at"] = 0.0        # force a refresh attempt
        with patch.object(db, "select", side_effect=RuntimeError("postgrest is down")):
            db._refresh_projects_cache()

        self.assertEqual([p["id"] for p in db._cached_projects_list], ["p1"])

    def test_invalidate_is_safe_to_call_when_already_empty(self):
        db.invalidate_projects_cache()
        db.invalidate_projects_cache()
        self.assertEqual(db._cached_projects_list, [])

    def test_invalidate_resets_the_ttl_clock(self):
        db._PROJECT_CACHE_TIME["at"] = time.time()
        db.invalidate_projects_cache()
        self.assertEqual(db._PROJECT_CACHE_TIME["at"], 0.0)


if __name__ == "__main__":
    unittest.main()

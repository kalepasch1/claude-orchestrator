"""Standalone verification for the vendor-diversification and host-resume-watch fixes.
Not committed as a repo test file (run ad hoc) -- exercises the new code paths against
mock pools/db so it proves behavior without touching the live database.
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agentic_coders
import agentic_repair
import host_resume_watch
import account_pool
import router_stats
import provider_rate_tracker
import model_slashing


FAKE_POOL = [
    {"name": "claude", "cost": 5.0, "cap": 10},
    {"name": "codex", "cost": 1.0, "cap": 8},
    {"name": "gemini", "cost": 0.5, "cap": 7},
]


class TestPickAvoid(unittest.TestCase):
    def setUp(self):
        self._pool_patch = patch.object(agentic_coders, "_pool", return_value=FAKE_POOL)
        self._pool_patch.start()
        self._within = patch.object(agentic_coders, "_within_cap", return_value=True)
        self._within.start()
        self._terms = patch.object(agentic_coders, "_allowed_by_terms", return_value=True)
        self._terms.start()
        self._ollama = patch.object(agentic_coders, "_heavy_ollama_saturated", return_value=False)
        self._ollama.start()
        self._diff = patch.object(agentic_coders, "_task_difficulty", return_value="easy")
        self._diff.start()
        self._sens = patch.object(agentic_coders, "_task_sensitivity", return_value="standard")
        self._sens.start()
        # These do real I/O (Supabase queries, rate-limit state) in production; every one
        # is reachable from pick() once the task isn't resolved by an early forced-coder
        # return, so they must be stubbed out for a fast, network-free unit test.
        self._exhausted = patch.object(account_pool, "claude_exhausted", return_value=False)
        self._exhausted.start()
        self._router = patch.object(router_stats, "best_coder", return_value=None)
        self._router.start()
        self._throttle = patch.object(provider_rate_tracker, "is_throttled", return_value=False)
        self._throttle.start()
        self._slash = patch.object(model_slashing, "penalty_for", return_value=0.0)
        self._slash.start()
        # _capacity_utilization() does a real DB round-trip (capacity_pacer -> db.select),
        # which hangs with no network access in this sandbox -- stub it to a mid value.
        self._util = patch.object(agentic_coders, "_capacity_utilization", return_value=0.3)
        self._util.start()
        # _explicit_full_offload_requested() and _paid_credits_enabled() may also read
        # live config/DB state depending on environment; pin them to deterministic values.
        self._offload = patch.object(agentic_coders, "_explicit_full_offload_requested", return_value=False)
        self._offload.start()

    def tearDown(self):
        patch.stopall()

    def test_forced_coder_honored_when_not_avoided(self):
        task = {"force_coder": "codex", "slug": "t1"}
        self.assertEqual(agentic_coders.pick(task), "codex")

    def test_forced_coder_skipped_when_avoided(self):
        task = {"force_coder": "codex", "slug": "t1", "_avoid_coders": ["codex"]}
        result = agentic_coders.pick(task)
        self.assertNotEqual(result, "codex", "avoided forced coder must not be reselected")

    def test_no_avoid_list_is_pure_passthrough(self):
        task = {"force_coder": "codex", "slug": "t1"}
        # identical result whether _avoid_coders key is absent or empty
        self.assertEqual(agentic_coders.pick(dict(task)), agentic_coders.pick({**task, "_avoid_coders": []}))

    def test_avoiding_claude_still_returns_someone(self):
        task = {"force_coder": "claude", "slug": "t1", "_avoid_coders": ["claude"]}
        result = agentic_coders.pick(task)
        self.assertIsNotNone(result)
        self.assertNotEqual(result, "claude")


class TestChooseCoderAvoid(unittest.TestCase):
    def test_choose_coder_without_avoid_reuses_model(self):
        task = {"model": "codex", "remediation_count": 1}
        self.assertEqual(agentic_repair.choose_coder(task), "codex")

    def test_choose_coder_with_avoid_does_not_reuse_model(self):
        task = {"model": "codex", "remediation_count": 1}
        with patch.object(agentic_repair, "agentic_coders", create=True):
            import agentic_coders as ac
            with patch.object(ac, "pick", return_value="gemini") as mock_pick:
                result = agentic_repair.choose_coder(task, avoid={"codex"})
                self.assertEqual(result, "gemini")
                mock_pick.assert_called_once()

    def test_repair_patch_prefer_non_claude_diversifies(self):
        task = {"id": "abc", "slug": "orphan-1", "model": "codex", "remediation_count": 1,
                "attempt": 1, "note": "ran for 25 minutes then vanished with a real traceback here"}
        with patch("agentic_coders.pick", return_value="gemini") as mock_pick:
            patch_out = agentic_repair.repair_patch(task, "orphaned, no output", category="orphaned-running",
                                                      prefer_non_claude=True)
        self.assertEqual(patch_out["force_coder"], "gemini")
        self.assertEqual(patch_out["model"], "gemini")
        # the avoid-set actually reached agentic_coders.pick()
        called_task = mock_pick.call_args[0][0]
        self.assertIn("codex", called_task.get("_avoid_coders", []))

    def test_repair_patch_without_prefer_non_claude_keeps_old_behavior(self):
        task = {"id": "abc", "slug": "orphan-1", "model": "codex", "remediation_count": 1,
                "attempt": 1, "note": "ran for 25 minutes then vanished with a real traceback here"}
        patch_out = agentic_repair.repair_patch(task, "orphaned, no output", category="orphaned-running")
        self.assertEqual(patch_out["force_coder"], "codex")  # unchanged default behavior


class TestHostResumeWatch(unittest.TestCase):
    def _rows(self, controls_rows, heartbeat_rows_by_host):
        def fake_select(table, params=None):
            if table == "controls":
                return controls_rows
            if table == "runner_heartbeats":
                host = params["hostname"].split("eq.")[1]
                return heartbeat_rows_by_host.get(host, [])
            return []
        return fake_select

    def test_no_paused_hosts_resumes_nothing(self):
        with patch.object(host_resume_watch.db, "select", side_effect=self._rows([], {})):
            resumed, checked = host_resume_watch.check_and_resume(master_sha="deadbeef")
        self.assertEqual((resumed, checked), (0, 0))

    def test_stale_code_sha_is_not_resumed(self):
        controls = [{"id": "c1", "scope": "host", "project": "ghost-host", "paused": True,
                     "updated_by": "orch-operator-bootstrap", "reason": "dead"}]
        hb = {"ghost-host": [
            {"hostname": "ghost-host", "code_sha": "OLDSHA", "last_seen": "2026-08-08T16:10:00+00:00"},
            {"hostname": "ghost-host", "code_sha": "OLDSHA", "last_seen": "2026-08-08T16:06:00+00:00"},
        ]}
        with patch.object(host_resume_watch.db, "select", side_effect=self._rows(controls, hb)), \
             patch.object(host_resume_watch.time, "time", return_value=1754669400.0):  # ~2026-08-08T16:10
            with patch.object(host_resume_watch.db, "update") as mock_update:
                resumed, checked = host_resume_watch.check_and_resume(master_sha="CURRENTSHA")
        self.assertEqual(resumed, 0)
        mock_update.assert_not_called()

    def test_single_heartbeat_is_not_enough(self):
        controls = [{"id": "c1", "scope": "host", "project": "ghost-host", "paused": True,
                     "updated_by": "orch-operator-bootstrap", "reason": "dead"}]
        hb = {"ghost-host": [{"hostname": "ghost-host", "code_sha": "CURRENTSHA", "last_seen": "2026-08-08T16:10:00+00:00"}]}
        with patch.object(host_resume_watch.db, "select", side_effect=self._rows(controls, hb)):
            with patch.object(host_resume_watch.db, "update") as mock_update:
                resumed, checked = host_resume_watch.check_and_resume(master_sha="CURRENTSHA")
        self.assertEqual(resumed, 0)
        mock_update.assert_not_called()

    def test_manually_paused_host_is_never_touched(self):
        controls = [{"id": "c1", "scope": "host", "project": "some-host", "paused": True,
                     "updated_by": "kalepasch", "reason": "manual: investigating disk issue"}]
        hb = {"some-host": [
            {"hostname": "some-host", "code_sha": "CURRENTSHA", "last_seen": "2026-08-08T16:10:00+00:00"},
            {"hostname": "some-host", "code_sha": "CURRENTSHA", "last_seen": "2026-08-08T16:05:00+00:00"},
        ]}
        with patch.object(host_resume_watch.db, "select", side_effect=self._rows(controls, hb)):
            with patch.object(host_resume_watch.db, "update") as mock_update:
                resumed, checked = host_resume_watch.check_and_resume(master_sha="CURRENTSHA")
        self.assertEqual(checked, 0, "a human-set pause must not even be considered a candidate")
        mock_update.assert_not_called()

    def test_verified_fresh_and_matching_sha_resumes(self):
        controls = [{"id": "c1", "scope": "host", "project": "ghost-host", "paused": True,
                     "updated_by": "orch-operator-bootstrap", "reason": "dead 32 days"}]
        hb = {"ghost-host": [
            {"hostname": "ghost-host", "code_sha": "CURRENTSHA", "last_seen": "2026-08-08T16:10:00+00:00"},
            {"hostname": "ghost-host", "code_sha": "CURRENTSHA", "last_seen": "2026-08-08T16:05:00+00:00"},
        ]}
        import datetime
        fresh_epoch = datetime.datetime.fromisoformat("2026-08-08T16:10:00+00:00").timestamp()
        with patch.object(host_resume_watch.db, "select", side_effect=self._rows(controls, hb)), \
             patch.object(host_resume_watch.time, "time", return_value=fresh_epoch + 30):
            with patch.object(host_resume_watch.db, "update") as mock_update, \
                 patch.object(host_resume_watch.db, "insert") as mock_insert:
                resumed, checked = host_resume_watch.check_and_resume(master_sha="CURRENTSHA")
        self.assertEqual(resumed, 1)
        args, kwargs = mock_update.call_args
        self.assertEqual(args[0], "controls")
        self.assertEqual(args[1], {"id": "c1"})
        self.assertFalse(args[2]["paused"])
        mock_insert.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)

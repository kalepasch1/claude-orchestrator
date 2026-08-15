#!/usr/bin/env python3
"""Tests for runner/pipeline_selftest.py — §2 machine + pipeline heartbeat alerts."""
import datetime
import os
import sys
import tempfile
import time
import unittest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

import fleet_immune_contracts as fic  # noqa: E402
import pipeline_selftest as ps  # noqa: E402


def _iso(seconds_ago=0):
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=seconds_ago)).isoformat()


class MachineHeartbeatTests(unittest.TestCase):
    def test_silent_machine_raises_an_operator_alert(self):
        """Mac 2 was down half a day with nothing saying so."""
        verdicts = ps.check_machine_heartbeats(rows=[
            {"hostname": "mac1", "last_seen": _iso(30)},
            {"hostname": "Mandys-MacBook-Pro.local", "last_seen": _iso(6 * 3600)},
        ], control_rows=[])
        subjects = {v.subject: v for v in verdicts}
        self.assertIn("host:Mandys-MacBook-Pro.local", subjects)
        self.assertEqual(subjects["host:Mandys-MacBook-Pro.local"].action, "alert")
        self.assertNotIn("host:mac1", subjects)

    def test_thirty_minute_silence_is_the_alert_boundary(self):
        quiet = ps.check_machine_heartbeats(rows=[{"hostname": "mac2", "last_seen": _iso(1900)}],
                                            control_rows=[])
        self.assertTrue(any(v.state == fic.DOWN for v in quiet))
        fresh = ps.check_machine_heartbeats(rows=[{"hostname": "mac2", "last_seen": _iso(60)}],
                                            control_rows=[])
        self.assertEqual(fresh, [])

    def test_alert_includes_last_fleet_control_ack_age(self):
        verdicts = ps.check_machine_heartbeats(
            rows=[{"hostname": "mac2", "last_seen": _iso(4000)}],
            control_rows=[{"handled_by": "mac2", "handled_at": _iso(7200)}])
        self.assertGreater(verdicts[0].detail.get("last_control_ack_age_s", 0), 7000)

    def test_no_heartbeats_at_all_is_itself_an_alert(self):
        verdicts = ps.check_machine_heartbeats(rows=[], control_rows=[])
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0].state, fic.DOWN)
        self.assertIn("publisher", verdicts[0].reason)

    def test_most_recent_heartbeat_per_host_wins(self):
        verdicts = ps.check_machine_heartbeats(rows=[
            {"hostname": "mac2", "last_seen": _iso(9999)},
            {"hostname": "mac2", "last_seen": _iso(10)},
        ], control_rows=[])
        self.assertEqual(verdicts, [])

    def test_garbage_rows_are_skipped_not_fatal(self):
        verdicts = ps.check_machine_heartbeats(rows=[None, "junk",
                                                     {"hostname": "mac2", "last_seen": _iso(9999)}],
                                               control_rows=[])
        self.assertEqual(len(verdicts), 1)


class PressureConsistencyTests(unittest.TestCase):
    def test_fresh_db_with_stale_file_is_named_as_a_consumer_bug(self):
        """The exact false train-stale shape: don't fire the train, fix the reader."""
        v = ps.check_pressure_consistency(file_age_s=99999, db_age_s=30)
        self.assertEqual(v.action, "fix_consumer")
        self.assertIn("false train-stale", v.reason)

    def test_missing_file_with_fresh_db_is_also_a_consumer_bug(self):
        v = ps.check_pressure_consistency(file_age_s=None, db_age_s=30)
        self.assertEqual(v.action, "fix_consumer")

    def test_both_stale_means_the_train_really_is_stuck(self):
        v = ps.check_pressure_consistency(file_age_s=99999, db_age_s=99999)
        self.assertEqual(v.state, fic.STUCK)
        self.assertEqual(v.action, "fire_train")

    def test_both_fresh_is_healthy(self):
        self.assertFalse(ps.check_pressure_consistency(file_age_s=10, db_age_s=10).actionable)

    def test_fresh_file_with_stale_db_flags_the_writer(self):
        v = ps.check_pressure_consistency(file_age_s=10, db_age_s=99999)
        self.assertEqual(v.action, "investigate")

    def test_report_names_the_authoritative_source(self):
        v = ps.check_pressure_consistency(file_age_s=10, db_age_s=10)
        self.assertEqual(v.detail["authoritative"], fic.SOURCE_DB)


class BootCommitTests(unittest.TestCase):
    def test_missing_marker_is_reported(self):
        v = ps.check_boot_commit(paths=["/nonexistent/.runner_boot_commit"])
        self.assertEqual(v.action, "write_boot_commit")
        self.assertIn("does nothing, forever", v.reason)

    def test_empty_marker_counts_as_missing(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".runner_boot_commit")
            open(path, "w").close()
            self.assertEqual(ps.check_boot_commit(paths=[path]).action, "write_boot_commit")

    def test_present_marker_is_healthy(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".runner_boot_commit")
            self.assertTrue(ps.write_boot_commit("abc1234", path=path))
            self.assertFalse(ps.check_boot_commit(paths=[path]).actionable)

    def test_write_boot_commit_rejects_empty_sha(self):
        self.assertFalse(ps.write_boot_commit(""))
        self.assertFalse(ps.write_boot_commit(None))


class RecoveryModeTests(unittest.TestCase):
    def test_recovery_mode_past_72h_warns(self):
        v = ps.check_release_recovery_mode(min_batch=1, since_ts=_iso(96 * 3600))
        self.assertEqual(v.action, "review_release_mode")

    def test_recent_recovery_mode_does_not_warn(self):
        self.assertFalse(
            ps.check_release_recovery_mode(min_batch=1, since_ts=_iso(3600)).actionable)

    def test_normal_batching_is_never_flagged(self):
        self.assertFalse(ps.check_release_recovery_mode(min_batch=10, since_ts=_iso(999999)).actionable)


class AutoRevertTests(unittest.TestCase):
    def test_a_single_low_reading_does_not_revert(self):
        should, state, reason = ps.evaluate_auto_revert(10, state={}, now_t=1000, min_batch=1)
        self.assertFalse(should)
        self.assertIn("below_floor_since", state)
        self.assertIn("starting sustain window", reason)

    def test_sustained_low_queue_reverts_after_24h(self):
        _, state, _ = ps.evaluate_auto_revert(10, state={}, now_t=0, min_batch=1)
        should, state, reason = ps.evaluate_auto_revert(
            10, state=state, now_t=25 * 3600, min_batch=1)
        self.assertTrue(should)
        self.assertIn("restoring default release batching", reason)
        self.assertNotIn("below_floor_since", state)

    def test_a_queue_spike_resets_the_sustain_window(self):
        _, state, _ = ps.evaluate_auto_revert(10, state={}, now_t=0, min_batch=1)
        _, state, _ = ps.evaluate_auto_revert(800, state=state, now_t=3600, min_batch=1)
        self.assertNotIn("below_floor_since", state)
        should, _, _ = ps.evaluate_auto_revert(10, state=state, now_t=25 * 3600, min_batch=1)
        self.assertFalse(should, "the window must restart after a spike, not resume")

    def test_partial_window_reports_progress_without_reverting(self):
        _, state, _ = ps.evaluate_auto_revert(10, state={}, now_t=0, min_batch=1)
        should, _, reason = ps.evaluate_auto_revert(10, state=state, now_t=6 * 3600, min_batch=1)
        self.assertFalse(should)
        self.assertIn("6h of 24h", reason)

    def test_no_revert_when_not_in_recovery_mode(self):
        should, _, reason = ps.evaluate_auto_revert(0, state={}, now_t=0, min_batch=10)
        self.assertFalse(should)
        self.assertEqual(reason, "not in recovery mode")

    def test_evaluation_is_fail_soft_on_junk(self):
        should, _, _ = ps.evaluate_auto_revert("not-a-number", state={}, min_batch=1)
        self.assertFalse(should)


class EnvOverrideTests(unittest.TestCase):
    def _env(self, body):
        fd, path = tempfile.mkstemp(suffix=".env")
        with os.fdopen(fd, "w") as f:
            f.write(body)
        self.addCleanup(os.unlink, path)
        return path

    def test_override_is_commented_not_deleted(self):
        path = self._env("FOO=1\nRELEASE_MIN_BATCH=1\nBAR=2\n")
        self.assertTrue(ps.remove_env_override(env_path=path))
        text = open(path).read()
        self.assertIn("# auto-reverted", text)
        self.assertIn("RELEASE_MIN_BATCH=1", text, "the incident record must stay readable")
        self.assertNotIn("\nRELEASE_MIN_BATCH=1\n", text, "the live setting must be inert")
        self.assertIn("FOO=1", text)
        self.assertIn("BAR=2", text)

    def test_already_commented_override_is_a_no_op(self):
        path = self._env("# RELEASE_MIN_BATCH=1\n")
        self.assertFalse(ps.remove_env_override(env_path=path))

    def test_absent_file_is_fail_soft(self):
        self.assertFalse(ps.remove_env_override(env_path="/nonexistent/.env"))


class StateTests(unittest.TestCase):
    def test_state_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state.json")
            self.assertTrue(ps.save_state({"below_floor_since": 123.0}, path=path))
            self.assertEqual(ps.load_state(path=path)["below_floor_since"], 123.0)

    def test_corrupt_state_loads_as_empty(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state.json")
            with open(path, "w") as f:
                f.write("{not json")
            self.assertEqual(ps.load_state(path=path), {})

    def test_render_is_fail_soft(self):
        self.assertIsInstance(ps.render(None), str)
        self.assertIn("all checks clear", ps.render({"verdicts": []}))


if __name__ == "__main__":
    unittest.main()

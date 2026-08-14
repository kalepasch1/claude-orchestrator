"""A pause must stop every fleet actor, not just task claims.

trg_stale_host_claim_guard fires on `tasks.account` changing — a task CLAIM.
Release-train and merge-train work is not a task claim, so a paused host went on
running QA gates, build gates and release attempts against its own stale checkout.

Evidence, 2026-08-06 21:10. A beethoven release failed with an npm log path of
`/Users/mandypa...` — Mandys-MacBook-Pro, PAUSED since 19:02, 40+ commits stale,
0 of 46 tasks completed in 48h. Its failed rows flip the project RED, which trips
ORCH_RELEASE_BACKPRESSURE and rejects new work FLEET-WIDE.

The rule that makes the fix safe, inherited from the claim guard: block STARTING,
never block FINISHING. Stranding in-flight work is worse than the failure being fixed.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paused_host_guard


class PausedHostTestCase(unittest.TestCase):

    def _paused(self, yes, reason="stale code, 40+ commits behind"):
        """Patch the pause lookup rather than the controls table."""
        return patch.object(paused_host_guard, "host_is_paused",
                            return_value=(yes, reason if yes else ""))

    def setUp(self):
        self.alerts = []
        self._rec = patch.object(
            paused_host_guard, "record_rejection",
            side_effect=lambda actor, detail, project=None:
                self.alerts.append({"actor": actor, "detail": detail, "project": project}))
        self._rec.start()
        self.addCleanup(self._rec.stop)


class TestMayStart(PausedHostTestCase):

    def test_an_active_host_may_start(self):
        with self._paused(False):
            ok, why = paused_host_guard.may_start("release_train")
        self.assertTrue(ok)
        self.assertEqual(why, "")

    def test_a_paused_host_may_not_start(self):
        with self._paused(True):
            ok, why = paused_host_guard.may_start("release_train")
        self.assertFalse(ok)
        self.assertIn("release_train", why)
        self.assertIn("paused", why)

    def test_the_reason_is_carried_into_the_refusal(self):
        with self._paused(True, "toolchain broken"):
            _, why = paused_host_guard.may_start("merge_train")
        self.assertIn("toolchain broken", why)

    def test_a_failed_pause_lookup_fails_open(self):
        """A guard that halts every train when controls blips is a worse outage.

        The DB trigger is the backstop for a client that gets this wrong, which is
        what makes failing open here safe rather than negligent.
        """
        import kill_switch

        with patch.object(kill_switch, "is_paused",
                          side_effect=RuntimeError("controls unreachable")):
            paused, reason = paused_host_guard.host_is_paused()
            ok, _ = paused_host_guard.may_start("release_train")

        self.assertFalse(paused)
        self.assertEqual(reason, "")
        self.assertTrue(ok, "a controls outage must not halt every train in the fleet")

    def test_refuse_records_the_rejection(self):
        with self._paused(True):
            ok, _ = paused_host_guard.refuse("release_train", project="beethoven")
        self.assertFalse(ok)
        self.assertEqual(len(self.alerts), 1, "silence is how this went unseen")
        self.assertEqual(self.alerts[0]["project"], "beethoven")

    def test_refuse_records_nothing_when_the_host_is_active(self):
        with self._paused(False):
            ok, _ = paused_host_guard.refuse("release_train", project="beethoven")
        self.assertTrue(ok)
        self.assertEqual(self.alerts, [])


class TestReleaseTrainIsGated(PausedHostTestCase):
    """1. Paused host: release_train exits before running gates, writes no release row."""

    def test_run_exits_before_electing_an_integration_owner(self):
        import release_train

        with self._paused(True), \
             patch.object(release_train.db, "select") as sel:
            result = release_train.run()

        self.assertIn("skipped", result)
        self.assertIn("paused", result["skipped"])
        sel.assert_not_called()

    def test_run_for_exits_before_touching_the_repo(self):
        import release_train

        with self._paused(True), \
             patch.object(release_train.db, "select") as sel:
            result = release_train.run_for("beethoven")

        self.assertIn("skipped", result)
        sel.assert_not_called()

    def test_an_active_host_is_not_blocked(self):
        import release_train

        with self._paused(False), \
             patch.object(release_train.db, "select", return_value=[{}]):
            result = release_train.run_for("beethoven")

        self.assertNotIn("skipped", result)

    def test_a_paused_host_writes_no_failed_release_row(self):
        """This is the row that flips a project RED and trips fleet-wide back-pressure."""
        import release_train

        with self._paused(True), \
             patch.object(release_train, "_recent_failed_gate", return_value=False), \
             patch.object(release_train.db, "insert") as ins:
            row = release_train._insert_failed_release(
                "beethoven", "build", 3, "aaa", "bbb", "staging BUILD red")

        self.assertIsNone(row)
        ins.assert_not_called()
        self.assertEqual(len(self.alerts), 1)
        self.assertIn("build", self.alerts[0]["actor"])

    def test_an_active_host_still_writes_the_failed_release_row(self):
        import release_train

        with self._paused(False), \
             patch.object(release_train, "_recent_failed_gate", return_value=False), \
             patch.object(release_train.db, "insert", return_value=[{"id": "r1"}]) as ins:
            release_train._insert_failed_release(
                "beethoven", "build", 3, "aaa", "bbb", "staging BUILD red")

        ins.assert_called_once()


class TestMergeTrainIsGated(PausedHostTestCase):
    """2. Paused host: merge_train does not start a new pass."""

    def test_train_run_exits_before_taking_the_lease(self):
        import merge_train

        with self._paused(True), \
             patch.object(merge_train.integration_runtime, "global_lease") as lease:
            result = merge_train.train_run()

        self.assertIn("skipped", result)
        self.assertIn("paused", result["skipped"])
        lease.assert_not_called()


class TestInFlightWorkIsNeverStranded(PausedHostTestCase):
    """3. A paused host CAN complete and record a pass already in flight.

    The claim guard's contract, kept: `may_start` is consulted at the top of a pass and
    nowhere else, so no code path can use it to interrupt work already under way.
    """

    def test_the_guard_exposes_no_way_to_stop_work_in_progress(self):
        public = {name for name in dir(paused_host_guard) if not name.startswith("_")}
        for forbidden in ("may_continue", "abort", "stop", "interrupt", "may_finish"):
            self.assertNotIn(forbidden, public)

    def test_recording_an_outcome_is_not_a_start(self):
        """A releases UPDATE (building -> success) must not consult the guard at all."""
        import release_train

        with self._paused(True), \
             patch.object(release_train.db, "update", return_value=[{"id": "r1"}]) as upd:
            release_train.db.update("releases", {"id": "r1"}, {"deploy_status": "success"})

        upd.assert_called_once()
        self.assertEqual(self.alerts, [], "completing in-flight work raises no refusal")


class TestHostStamp(PausedHostTestCase):
    """The row that flips a project RED must say who wrote it."""

    def test_release_rows_are_stamped_with_the_host(self):
        import release_train

        with patch.object(release_train.db, "insert", return_value=[{"id": "r1"}]) as ins:
            release_train._insert_release({"project": "beethoven", "deploy_status": "failed"})

        self.assertEqual(ins.call_args.args[1]["host"], paused_host_guard.HOST)

    def test_a_db_without_the_host_column_still_records_the_release(self):
        """Code and migrations deploy independently; a lagging DB must not stop releases."""
        import release_train

        calls = []

        def picky(table, row):
            calls.append(row)
            if "host" in row:
                raise RuntimeError('column "host" of relation "releases" does not exist')
            return [{"id": "r1"}]

        with patch.object(release_train.db, "insert", side_effect=picky):
            out = release_train._insert_release({"project": "beethoven"})

        self.assertEqual(out, [{"id": "r1"}])
        self.assertEqual(len(calls), 2)
        self.assertNotIn("host", calls[1])


class TestMigrationShape(unittest.TestCase):
    """4/5/6 are enforced in SQL; assert the guard's shape rather than a live DB."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "supabase", "migrations", "20260806220000_paused_host_release_guard.sql")
        with open(path) as fh:
            cls.sql = fh.read()

    def test_the_guard_is_insert_only_so_completion_is_never_blocked(self):
        self.assertIn("before insert on public.releases", self.sql)
        self.assertNotIn("before insert or update", self.sql.lower())

    def test_it_reuses_the_claim_guards_pause_lookup(self):
        """Two guards that decide 'is this host paused' differently is a bug waiting."""
        self.assertIn("stale_host_is_paused", self.sql)

    def test_rejections_are_recorded_not_swallowed(self):
        self.assertIn("release_from_paused_host", self.sql)
        self.assertIn("insert into public.runner_alerts", self.sql)

    def test_the_alert_kind_matches_the_runner_side_constant(self):
        self.assertIn(f"'{paused_host_guard.ALERT_KIND}'", self.sql)

    def test_the_host_column_is_added_idempotently(self):
        self.assertIn("add column if not exists host", self.sql)

    def test_an_unattributable_row_is_not_refused(self):
        self.assertIn("if NEW.host is null", self.sql)


if __name__ == "__main__":
    unittest.main()

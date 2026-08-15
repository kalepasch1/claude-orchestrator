#!/usr/bin/env python3
"""Tests for runner/stash_census.py — audit addendum §C (stash count discrepancy).

The behaviour under test is the operator's actual requirement: bulk stash triage must NOT
begin while any machine's pile is invisible or internally inconsistent (592-vs-315).
"""
import datetime
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))

import stash_census  # noqa: E402


def _ts(seconds_ago=0):
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=seconds_ago)).isoformat()


def _census(host, count, reflog=None, age=0):
    return {"host": host, "repo": "/tmp/r", "count": count,
            "reflog_count": count if reflog is None else reflog,
            "oldest": "stash@{0}: WIP", "ts": _ts(age)}


class FakeDao:
    """Minimal in-memory stand-in for fleet_config_dao."""

    def __init__(self, value=None):
        self.rows = {}
        if value is not None:
            self.rows[stash_census.CENSUS_KEY] = {"key": stash_census.CENSUS_KEY, "value": value}
        self.writes = []

    def get(self, key):
        return self.rows.get(key)

    def set_value(self, key, value, note=None, updated_by=None):
        self.rows[key] = {"key": key, "value": value, "note": note, "updated_by": updated_by}
        self.writes.append((key, value))
        return None, self.rows[key]


class ExplodingDao(FakeDao):
    def get(self, key):
        raise RuntimeError("db down")

    def set_value(self, *a, **k):
        raise RuntimeError("db down")


class LocalCensusTests(unittest.TestCase):
    def test_parses_counts_and_oldest(self):
        def runner(repo, *args):
            if args[:2] == ("stash", "list"):
                return "stash@{0}: WIP on master\nstash@{1}: sentinel-drift\n\n"
            if args[:2] == ("reflog", "stash"):
                return "aaa refs/stash@{0}: WIP\nbbb refs/stash@{1}: x\n"
            return ""

        c = stash_census.local_census(repo="/tmp/r", host="mac1", runner=runner)
        self.assertEqual(c["count"], 2)
        self.assertEqual(c["reflog_count"], 2)
        self.assertEqual(c["host"], "mac1")
        self.assertIn("sentinel-drift", c["oldest"])

    def test_empty_repo_is_zero_not_error(self):
        c = stash_census.local_census(repo="/tmp/r", host="mac1", runner=lambda *a, **k: "")
        self.assertEqual(c["count"], 0)
        self.assertEqual(c["reflog_count"], 0)

    def test_git_failure_is_fail_soft(self):
        def boom(*a, **k):
            raise OSError("no git")

        c = stash_census.local_census(repo="/tmp/r", host="mac1", runner=boom)
        self.assertEqual(c["count"], 0)
        self.assertEqual(c["host"], "mac1")


class ReconcileTests(unittest.TestCase):
    def test_single_host_when_second_is_expected_blocks_triage(self):
        """The 592-vs-315 case: Mac 2 never reported, so its pile is invisible."""
        report = stash_census.reconcile(
            {"mac1": _census("mac1", 315)},
            expected_hosts=("mac1", "Mandys-MacBook-Pro.local"),
        )
        self.assertTrue(report["triage_blocked"])
        self.assertIn("Mandys-MacBook-Pro.local", report["missing_hosts"])
        self.assertTrue(any("invisible" in r for r in report["reasons"]))

    def test_both_hosts_fresh_and_consistent_unblocks_and_sums(self):
        report = stash_census.reconcile(
            {"mac1": _census("mac1", 315),
             "Mandys-MacBook-Pro.local": _census("Mandys-MacBook-Pro.local", 277)},
            expected_hosts=("mac1", "Mandys-MacBook-Pro.local"),
        )
        self.assertFalse(report["triage_blocked"], report["reasons"])
        self.assertEqual(report["total"], 592)
        self.assertEqual(report["per_host"]["Mandys-MacBook-Pro.local"], 277)

    def test_reflog_mismatch_flags_drop_suspect_and_blocks(self):
        report = stash_census.reconcile(
            {"mac1": _census("mac1", 315, reflog=592)},
            expected_hosts=("mac1",),
        )
        self.assertIn("mac1", report["drop_suspects"])
        self.assertTrue(report["triage_blocked"])

    def test_stale_host_is_unknown_not_zero(self):
        report = stash_census.reconcile(
            {"mac1": _census("mac1", 315),
             "mac2": _census("mac2", 277, age=999999)},
            expected_hosts=("mac1", "mac2"),
            stale_s=3600,
        )
        self.assertIn("mac2", report["stale_hosts"])
        self.assertNotIn("mac2", report["per_host"])
        self.assertEqual(report["total"], 315)
        self.assertTrue(report["triage_blocked"])

    def test_no_reports_at_all_blocks(self):
        report = stash_census.reconcile({})
        self.assertTrue(report["triage_blocked"])
        self.assertEqual(report["total"], 0)

    def test_garbage_entries_are_ignored_not_fatal(self):
        report = stash_census.reconcile({"mac1": "not-a-dict", "mac2": _census("mac2", 4)})
        self.assertEqual(report["total"], 4)

    def test_none_input_is_fail_soft(self):
        report = stash_census.reconcile(None)
        self.assertTrue(report["triage_blocked"])

    def test_no_expected_hosts_still_requires_a_report(self):
        self.assertTrue(stash_census.reconcile({}, expected_hosts=())["triage_blocked"])
        self.assertFalse(
            stash_census.reconcile({"mac1": _census("mac1", 1)}, expected_hosts=())["triage_blocked"]
        )


class PublishTests(unittest.TestCase):
    def test_publish_merges_without_clobbering_other_hosts(self):
        dao = FakeDao(json.dumps({"mac2": _census("mac2", 277)}))
        merged = stash_census.publish(census=_census("mac1", 315), dao=dao)
        self.assertIn("mac1", merged)
        self.assertIn("mac2", merged)
        self.assertEqual(merged["mac2"]["count"], 277)
        stored = json.loads(dao.writes[-1][1])
        self.assertEqual(sorted(stored), ["mac1", "mac2"])

    def test_publish_survives_corrupt_existing_value(self):
        dao = FakeDao("{not json")
        merged = stash_census.publish(census=_census("mac1", 3), dao=dao)
        self.assertEqual(list(merged), ["mac1"])

    def test_publish_is_fail_soft_when_db_is_down(self):
        self.assertEqual(stash_census.publish(census=_census("mac1", 3), dao=ExplodingDao()), {})

    def test_census_key_is_a_safe_fleet_config_key(self):
        """Must be pushable fleet-wide: ORCH_ prefixed, no credential marker."""
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
        self.assertTrue(stash_census.CENSUS_KEY.startswith("ORCH_"))
        for marker in ("KEY", "SECRET", "TOKEN", "PASSWORD", "PWD", "CREDENTIAL", "PAT"):
            self.assertNotIn(marker, stash_census.CENSUS_KEY.replace("ORCH_", "", 1))


class RenderTests(unittest.TestCase):
    def test_blocked_report_says_so_loudly(self):
        text = stash_census.render(stash_census.reconcile({}, expected_hosts=("mac1",)))
        self.assertIn("BULK TRIAGE BLOCKED", text)

    def test_clear_report_permits_triage(self):
        text = stash_census.render(stash_census.reconcile(
            {"mac1": _census("mac1", 2)}, expected_hosts=("mac1",)))
        self.assertIn("may proceed", text)

    def test_render_is_fail_soft_on_garbage(self):
        self.assertIsInstance(stash_census.render(None), str)


if __name__ == "__main__":
    unittest.main()

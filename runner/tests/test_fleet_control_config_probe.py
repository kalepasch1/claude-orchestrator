#!/usr/bin/env python3
"""load_config() must stop reading the whole config table on every tick.

tick() runs each coordination cycle and called load_config(), which read the
ENTIRE fleet_config table plus the entire pending-approvals list — two
unfiltered selects per host per cycle, across every runner in the fleet, to
discover on almost every cycle that nothing had changed. Config changes are
rare; the polling was not.

A one-row probe on the newest `updated_at` now gates the full read. The tests
that matter are the ones about being WRONG in the cheap direction: a skip is
only safe if it cannot hide a real change, cannot outlive a failure, and cannot
override an explicit reload.

Written in pytest style with snake_case fixtures on purpose. unittest's setUp /
tearDown are camelCase, which the convention linter flags and which no author
can rename — the framework dispatches on the exact spelling. Rather than raise
the lint baseline to accommodate two unfixable violations, this file does not
create them.
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fleet_control  # noqa: E402

#: One read for the initial load, one for the change that follows it.
FULL_READS_AFTER_A_CHANGE = 2


class FakeDB:
    """Counts what load_config asks the database for."""

    def __init__(self, stamp="2026-08-26T00:00:00+00:00", rows=None, fail=False):
        self.stamp = stamp
        self.rows = rows if rows is not None else [
            {"key": "ORCH_MAX_WORKERS", "value": "10"}]
        self.fail = fail
        self.probe_calls = 0
        self.full_calls = 0

    def select(self, table, params):
        if table == "approvals":
            return []
        if self.fail:
            raise RuntimeError("postgrest down")
        if params.get("select") == "updated_at":
            self.probe_calls += 1
            return [{"updated_at": self.stamp}] if self.stamp else []
        self.full_calls += 1
        return list(self.rows)


class ProbeBase:
    def setup_method(self, method):
        fleet_control.invalidate_config_cache()
        self.saved_env = dict(os.environ)

    def teardown_method(self, method):
        fleet_control.invalidate_config_cache()
        os.environ.clear()
        os.environ.update(self.saved_env)

    def load(self, fake, **kwargs):
        with patch.object(fleet_control, "db", fake):
            return fleet_control.load_config(**kwargs)


class TestTheRepeatedFullReadIsGone(ProbeBase):
    def test_the_first_call_reads_the_table(self):
        fake = FakeDB()
        self.load(fake)
        assert fake.full_calls == 1

    def test_a_second_call_with_an_unchanged_stamp_does_not(self):
        fake = FakeDB()
        self.load(fake)
        self.load(fake)
        self.load(fake)
        assert fake.full_calls == 1, \
            "the whole config table was re-read despite nothing changing"

    def test_the_skip_path_still_returns_the_key_count(self):
        fake = FakeDB()
        first = self.load(fake)
        second = self.load(fake)
        assert first == second
        assert first > 0


class TestASkipCannotHideARealChange(ProbeBase):
    def test_a_moved_stamp_triggers_a_full_read(self):
        fake = FakeDB()
        self.load(fake)
        fake.stamp = "2026-08-27T00:00:00+00:00"
        fake.rows = [{"key": "ORCH_MAX_WORKERS", "value": "20"}]
        self.load(fake)
        assert fake.full_calls == FULL_READS_AFTER_A_CHANGE
        assert os.environ.get("ORCH_MAX_WORKERS") == "20"

    def test_an_unanswerable_probe_falls_through_to_the_full_read(self):
        # "I could not tell" is not evidence of "nothing changed".
        fake = FakeDB()
        self.load(fake)
        fake.stamp = None          # empty table / missing column / bad response
        self.load(fake)
        assert fake.full_calls == FULL_READS_AFTER_A_CHANGE

    def test_force_bypasses_the_probe(self):
        fake = FakeDB()
        self.load(fake)
        self.load(fake, force=True)
        assert fake.full_calls == FULL_READS_AFTER_A_CHANGE

    def test_a_local_write_invalidates_the_cache(self):
        fake = FakeDB()
        self.load(fake)
        fleet_control.invalidate_config_cache()
        self.load(fake)
        assert fake.full_calls == FULL_READS_AFTER_A_CHANGE


class TestAFailedLoadIsNotCachedAsASuccess(ProbeBase):
    def test_a_failing_read_is_retried_on_the_next_call(self):
        # Caching a failure would leave this host running on whatever it last
        # managed to apply until the TTL expired.
        fake = FakeDB(fail=True)
        self.load(fake)
        fake.fail = False
        self.load(fake)
        assert fake.full_calls >= 1
        assert os.environ.get("ORCH_MAX_WORKERS") == "10"


class TestTheTtlFloorConverges(ProbeBase):
    def test_an_expired_ttl_forces_a_full_read_even_with_a_still_stamp(self):
        # The probe watches fleet_config's newest updated_at, which a DELETE
        # does not move, and blocked_keys() lives in another table entirely.
        # The floor is what makes those cases converge instead of persist.
        fake = FakeDB()
        self.load(fake)
        with patch.object(fleet_control, "CONFIG_PROBE_TTL_S", -1):
            self.load(fake)
        assert fake.full_calls == FULL_READS_AFTER_A_CHANGE

    def test_the_probe_costs_one_row(self):
        fake = FakeDB()
        self.load(fake)
        self.load(fake)
        assert fake.probe_calls >= 1

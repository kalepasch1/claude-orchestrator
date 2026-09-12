#!/usr/bin/env python3
"""
test_dropbox_partner_reconfiguration.py - the reap loop is blind to task metadata.

WHAT THIS FILE CLAIMED TO TEST, AND WHY ALMOST NONE OF IT SURVIVED
------------------------------------------------------------------
The header used to describe "partner-level dropbox reconfiguration": dropbox-specific
runner configurations, partner-level contract validation, smart OS reconfiguration, and
three configuration flags -- ORCH_DROPBOX_RECONFIG_ENABLED, ORCH_PARTNER_CONTRACT_ENABLED,
ORCH_SMART_OS_RECONFIG_ENABLED. None of that exists. The three env vars appear nowhere in
the product; there is no contract, partner or OS-reconfiguration concept anywhere near the
reaper; and `dropbox-` is not a runner-account prefix at all -- it is the SLUG prefix this
fleet uses for product feature specs (see the comment above runner._DISABLED_JOBS). The
file's name is a task slug, not a feature.

What the file actually exercised, once the vocabulary is stripped away, is
`runner._reap_zombie_tasks()` -- and it exercised it wrongly:

  * `sys.modules["runner"] = <runner.py>` plus `@patch("runner.db.select")`. The repo-root
    conftest rebinds sys.modules["runner"] to the runner PACKAGE at every collectstart, so
    mock.patch resolved "runner.db" to the package submodule -- a second copy of db.py the
    reaper never calls -- and patched select() there while the code under test talked to
    the real database. That is what the 19 failures were.
  * Its headline claim, "task on a dead `dropbox-*` runner is reclaimed", is false: the
    dead-runner path is gated on a host-account regex that no `dropbox-` account matches.
  * Eight of its tests had no assertion at all, ending in a comment such as
    "# Dropbox reconfiguration should be enabled". Those passed by construction.

DUPLICATION, AND WHO SHOULD OWN WHAT (nothing here is silently deleted)
----------------------------------------------------------------------
Every remaining behaviour this file touched is already owned, in better form, by the
rewritten zombie-reaper suites. Proposed owners, and what was dropped from here:

  account-pattern matching, unknown accounts, cowork skipping
      -> runner/tests/test_zombie_reaper_integration.py::TestRunnerAccountPatternMatching
         (dropped: test_dropbox_runner_pattern_recognized, test_dropbox_live_runner_not_
         reclaimed, test_existing_account_patterns_still_work, test_cowork_tasks_still_
         skipped, test_scheduler_heartbeats_still_excluded)
  30-minute staleness and dead-runner grace boundaries
      -> runner/test_zombie_reaper.py::TestStaleRunningTasks / TestZombieReaperDeadRunner-
         Detection (dropped: test_multi_tenant_contract_isolation, test_contract_metadata_
         does_not_block_reclaim, test_dropbox_partner_contract_isolation, test_multi_
         partner_environment_remains_isolated -- each was "two or three stale rows produce
         two or three updates" with partner nouns attached)
  batch scale and fail-soft under a dead DB or a bad row
      -> test_zombie_reaper_integration.py::TestLargeScaleRecovery / TestErrorResilience
         (dropped: test_100_tasks_with_mixed_contracts, test_db_error_with_contract_
         metadata_logged, test_malformed_partner_level_handled_gracefully,
         test_missing_contract_id_field_handled)
  the repair signal's two reasons
      -> test_zombie_reaper.py::test_repair_signal_distinguishes_the_two_reclaim_reasons

What is left is the one axis those suites do NOT cover, and it is also the nearest true
statement to this file's stated intent ("contract metadata preservation and propagation"):
the reaper treats a task row as OPAQUE. Extra columns cannot change its decision, cannot be
clobbered by its write, and are handed on intact to the repair context. Two tests about the
`dropbox-` account namespace are kept deliberately -- they are the corrected form of this
file's central, false claim, and deleting them outright would leave nothing on record
saying it was false.
"""
import sys
import os
import datetime
from unittest.mock import patch
import pytest

# runner/ must be importable so runner.py's own flat `import db` resolves, but it is
# APPENDED, never inserted at position 0: at sys.path[0] the module file runner/runner.py
# shadows the runner/ PACKAGE and package-style imports break for the rest of the session
# (the repo-root conftest.py documents this at length).
_RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
if _RUNNER_DIR not in sys.path:
    sys.path.append(_RUNNER_DIR)

import importlib.util  # noqa: E402

# Load runner/runner.py by path under a private name and do NOT publish it in sys.modules
# -- see the module docstring for what publishing it did to every patch in this file.
_spec = importlib.util.spec_from_file_location(
    "_dropbox_partner_runner_under_test", os.path.join(_RUNNER_DIR, "runner.py"))
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


#: Columns a product feature spec might hang off a task row. The reaper must neither read
#: nor write any of them.
METADATA_COLUMNS = {"contract_id", "partner_id", "partner_level", "os_config"}

#: Flags this file's header documented as configuration. They are read by nothing.
DOCUMENTED_BUT_NONEXISTENT_FLAGS = (
    "ORCH_DROPBOX_RECONFIG_ENABLED",
    "ORCH_PARTNER_CONTRACT_ENABLED",
    "ORCH_SMART_OS_RECONFIG_ENABLED",
)


@pytest.fixture(autouse=True)
def _reap_cycle_allowed():
    """`_reap_zombie_tasks()` self-throttles to one cycle per 300s through the module
    global `_ZOMBIE_REAP_T`. Without this reset, every test after the first exercises the
    early return rather than the reaper."""
    saved = runner._ZOMBIE_REAP_T
    runner._ZOMBIE_REAP_T = 0.0
    yield
    runner._ZOMBIE_REAP_T = saved


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def running(task_id="t1", slug="task-1", account="Mac.lan-0", age_min=0, **metadata):
    """A RUNNING row as the reaper's own projection returns it, plus any extra columns."""
    row = {
        "id": task_id,
        "slug": slug,
        "state": "RUNNING",
        "account": account,
        "updated_at": (_now() - datetime.timedelta(minutes=age_min)).isoformat(),
    }
    row.update(metadata)
    return row


def retry(task_id="r1", slug="retry-1", age_sec=0, note="", **metadata):
    row = {
        "id": task_id,
        "slug": slug,
        "state": "RETRY",
        "updated_at": (_now() - datetime.timedelta(seconds=age_sec)).isoformat(),
        "note": note,
    }
    row.update(metadata)
    return row


def heartbeat(runner_id="Mac.lan-0", hostname="Mac.lan", age_sec=0):
    return {
        "runner_id": runner_id,
        "hostname": hostname,
        "last_seen": (_now() - datetime.timedelta(seconds=age_sec)).isoformat(),
    }


def OTHER_LIVE_RUNNER():
    """A heartbeat proving the fleet table is readable and somebody is alive.

    The dead-runner path is gated on `bool(live_runner_ids)`: an empty heartbeat result
    means "no fleet visibility", not "every runner died", so the reaper declines to
    reclaim. Any test about ONE runner being dead has to leave another alive.
    """
    return heartbeat(runner_id="Mac.lan-99", age_sec=5)


def selects(running_rows=(), heartbeat_rows=(), retry_rows=()):
    """The three db.select() calls one reap cycle makes, in order.

    The old tests supplied only two, so every cycle ended in a StopIteration swallowed by
    the reaper's outer handler -- the RETRY promoter never ran in any of them.
    """
    return [list(running_rows), list(heartbeat_rows), list(retry_rows)]


class TestExtraColumnsCannotChangeTheDecision:
    """Reclamation is a function of (account, updated_at) and fleet visibility. Nothing a
    feature spec attaches to the row may add to, or subtract from, that."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_metadata_does_not_block_a_reclaim_that_should_happen(
            self, mock_update, mock_select, mock_repair):
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = selects(
            [running(age_min=31, contract_id="c-1", partner_id="p-1",
                     partner_level="enterprise", os_config="macOS-14.0")])

        runner._reap_zombie_tasks()

        assert mock_update.call_count == 1

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_metadata_does_not_cause_a_reclaim_that_should_not_happen(
            self, mock_update, mock_select, mock_repair):
        """A task one minute old on a live-fleet host is simply not eligible, however much
        contract metadata it carries.

        WAS: `test_dropbox_runner_pattern_recognized` and `test_dropbox_dead_runner_
        reclaimed`, which asserted that this same row IS reclaimed. It is not, and they
        only ever "passed" review because their db mocks were installed on a module the
        reaper does not call.
        """
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = selects(
            [running(age_min=1, contract_id="c-1", partner_level="enterprise")],
            [OTHER_LIVE_RUNNER(), heartbeat(runner_id="Mac.lan-0", age_sec=5)])

        runner._reap_zombie_tasks()

        assert not mock_update.called
        assert not mock_repair.called

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_a_metadata_rich_row_and_a_bare_row_are_treated_identically(
            self, mock_update, mock_select, mock_repair):
        """Same age, same account shape, different column sets -> same outcome. This is
        the whole of what "multi-tenant isolation" can mean for a loop that never looks at
        a tenant."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = selects([
            running(task_id="rich", account="Mac.lan-0", age_min=31,
                    contract_id="c-1", partner_id="p-1", partner_level="enterprise"),
            running(task_id="bare", account="Mac.lan-1", age_min=31),
        ])

        runner._reap_zombie_tasks()

        assert [c.args[1]["id"] for c in mock_update.call_args_list] == ["rich", "bare"]
        assert [c.args[2] for c in mock_update.call_args_list] == [{"state": "QUEUED"}] * 2

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_metadata_values_are_never_parsed(self, mock_update, mock_select, mock_repair):
        """A None, a dict and a list in columns the reaper does not read must be inert --
        not a TypeError that costs the row its reclamation.

        WAS: `test_malformed_partner_level_handled_gracefully`, which wrapped the call in
        try/except and asserted nothing about whether the task survived.
        """
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = selects(
            [running(age_min=31, partner_level=None, contract_id={"nested": True},
                     os_config=["macOS", "14.0"])])

        runner._reap_zombie_tasks()

        assert mock_update.call_count == 1

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_documented_but_nonexistent_flags_change_nothing(
            self, mock_update, mock_select, mock_repair):
        """The three ORCH_*_ENABLED names in this file's old header are read by no code in
        the product. Turning them all on must therefore be indistinguishable from leaving
        them unset -- which is the honest version of the three assertion-free tests that
        used to claim each one "is respected"."""
        mock_repair.return_value = {"state": "QUEUED"}

        # Built once, copied per cycle: two calls to running() would differ in updated_at
        # and the comparison would fail on the clock rather than on the flags.
        stale = running(account="dropbox-prod-0", age_min=31,
                        partner_level="enterprise", os_config="macOS-14.0")
        elapsed = retry(age_sec=300)
        live = OTHER_LIVE_RUNNER()

        def one_cycle():
            runner._ZOMBIE_REAP_T = 0.0
            mock_update.reset_mock()
            mock_repair.reset_mock()
            mock_select.side_effect = selects([dict(stale)], [dict(live)], [dict(elapsed)])
            runner._reap_zombie_tasks()
            return (mock_update.call_args_list[:], mock_repair.call_args_list[:])

        without = one_cycle()
        with patch.dict(os.environ, {f: "true" for f in DOCUMENTED_BUT_NONEXISTENT_FLAGS}):
            with_flags = one_cycle()

        assert without[0], "the cycle under comparison has to do something"
        assert with_flags == without


class TestTheWriteCannotClobberUnrelatedColumns:
    """"Contract metadata is not lost on reclaim" -- expressed against the real mechanism.
    The reaper issues a PATCH keyed on the primary key, so any column it does not name is
    untouched by definition. What has to hold is that it names none of them."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_reclaim_is_a_single_row_patch_keyed_on_id(
            self, mock_update, mock_select, mock_repair):
        produced = {"state": "QUEUED", "account": None, "note": "agentic-repair"}
        mock_repair.return_value = produced
        mock_select.side_effect = selects(
            [running(task_id="t-42", age_min=31, contract_id="c-1")])

        runner._reap_zombie_tasks()

        table, match, sent = mock_update.call_args.args
        assert table == "tasks"
        assert match == {"id": "t-42"}, "a bulk match would rewrite other partners' rows"
        assert sent is produced, "the reaper adds nothing of its own to the patch"

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_the_real_repair_patch_names_no_metadata_column(self, mock_update, mock_select):
        """agentic_repair.repair_patch is left REAL here: the no-clobber guarantee is only
        worth anything if the patch the production helper actually builds is checked.

        The counters are supplied on the row so repair_patch does not go back to the DB to
        resolve them -- that lookup is its own module's business, not this test's.
        """
        mock_select.side_effect = selects(
            [running(task_id="t-42", age_min=31, remediation_count=0, attempt=1,
                     contract_id="c-1", partner_id="p-1", partner_level="enterprise",
                     os_config="macOS-14.0")])

        runner._reap_zombie_tasks()

        sent = mock_update.call_args.args[2]
        assert sent["state"] == "QUEUED"
        assert METADATA_COLUMNS.isdisjoint(sent)

    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_retry_promotion_patch_touches_only_its_own_three_fields(
            self, mock_update, mock_select):
        """The RETRY promoter builds its patch by hand rather than through repair_patch, so
        it needs its own no-clobber check. Nothing in this file ever reached it: every old
        test supplied two db.select results for a three-select cycle."""
        mock_select.side_effect = selects(
            retry_rows=[retry(task_id="r-7", age_sec=300, note="was throttled",
                              partner_level="enterprise", contract_id="c-9")])

        runner._reap_zombie_tasks()

        table, match, sent = mock_update.call_args.args
        assert (table, match) == ("tasks", {"id": "r-7"})
        assert set(sent) == {"state", "updated_at", "note"}
        assert sent["state"] == "QUEUED"
        assert "was throttled" in sent["note"]


class TestRepairContextReceivesTheWholeRow:
    """"Partner metadata is available in repair context" was the one claim in this file
    that is true -- and no test in it checked. repair_patch is handed the row as fetched."""

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_repair_patch_is_handed_the_row_as_fetched(
            self, mock_update, mock_select, mock_repair):
        mock_repair.return_value = {"state": "QUEUED"}
        row = running(age_min=31, contract_id="c-1", partner_id="p-1",
                      partner_level="enterprise", os_config="macOS-14.0")
        mock_select.side_effect = selects([row])

        runner._reap_zombie_tasks()

        assert mock_repair.call_args.args[0] is row
        assert mock_repair.call_args.kwargs["category"] == "orphaned-running"

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_the_signal_names_the_reason_not_the_metadata(
            self, mock_update, mock_select, mock_repair):
        """The recovery signal is one of two fixed strings. A row's columns must not leak
        into it -- the signal is what the repair prompt is built from, and a prompt that
        varies per tenant is a prompt nobody can compare across runs."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = selects(
            [running(age_min=31, partner_level="enterprise", contract_id="c-secret")])

        runner._reap_zombie_tasks()

        signal = mock_repair.call_args.args[1]
        assert signal == "zombie-reaper: stale RUNNING >30min"


class TestTheDropboxAccountNamespace:
    """The corrected form of this file's central claim.

    The general rule -- only `Mac.lan-N` and `Mandys-MacBook-Pro.local-N` accounts are
    eligible for the dead-runner path -- is owned by
    tests/test_zombie_reaper_integration.py::TestRunnerAccountPatternMatching. These two
    tests are kept anyway because this file asserted the opposite for a `dropbox-` account,
    and removing them outright would leave nothing on record saying that was wrong.
    """

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_a_dropbox_account_is_not_eligible_for_the_dead_runner_path(
            self, mock_update, mock_select, mock_repair):
        """`dropbox-` is a task-slug prefix in this fleet, not a runner-account prefix, so
        `dropbox-mac-prod-0` matches no host pattern: absent from a readable fleet table
        and well past the reclaim grace, it is still not reclaimed."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = selects(
            [running(account="dropbox-mac-prod-0", age_min=5)],
            [OTHER_LIVE_RUNNER()])

        runner._reap_zombie_tasks()

        assert not mock_update.called

    @patch.object(runner.agentic_repair, "repair_patch")
    @patch.object(runner.db, "select")
    @patch.object(runner.db, "update")
    def test_a_dropbox_account_is_still_reclaimed_once_stale(
            self, mock_update, mock_select, mock_repair):
        """The 30-minute path has no account gate, so an unrecognised namespace is
        recovered -- just later, and under the stale reason rather than the dead-runner
        one. That difference is the whole practical consequence of the rule above."""
        mock_repair.return_value = {"state": "QUEUED"}
        mock_select.side_effect = selects(
            [running(account="dropbox-mac-prod-0", age_min=31)],
            [OTHER_LIVE_RUNNER()])

        runner._reap_zombie_tasks()

        assert mock_update.call_count == 1
        assert mock_repair.call_args.args[1] == "zombie-reaper: stale RUNNING >30min"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

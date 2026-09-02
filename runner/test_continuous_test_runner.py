"""Tests for the continuous_test_runner module.

WHAT THIS FILE USED TO TEST
---------------------------
Nothing that exists. Every one of its 21 tests addressed a class-based API --
`ctr.TestResult(...)`, `ctr._parse_test_counts()`, `ctr.detect_changed_files()`,
`ctr.run_test_command()`, `ctr.aggregate_results()`, `ctr.stats()`, `ctr.reset_stats()` --
and continuous_test_runner.py has never had any of them. It is a flat, function-level
module whose public surface is `run_tests()`, `merge_gate_check()` and `on_push()`, and
whose results are plain dicts, not objects. All 21 failed with AttributeError at the first
line of each test body, so the file asserted nothing about the product for its whole life.

Rather than inventing the missing API to satisfy the spec, each section below is aimed at
the real behaviour nearest to the section's original intent, and says so:

  TestResult          -> the result DICT run_tests() actually returns
  _parse_test_counts  -> _result_hash(), the module's only output-analysis function and the
                         thing flake detection is built on
  detect_changed_files-> no equivalent exists; branch/worktree selection is the closest
                         real behaviour and is already owned by
                         tests/test_continuous_test_runner_branch.py, so this file leaves
                         _test_tree alone rather than duplicating it
  run_test_command    -> run_tests()'s command, timeout and exit-code handling
  aggregate_results   -> the flake-retry loop, which is the module's only aggregation
  stats/reset_stats   -> _record_test_run(), the module's only persistence

PRODUCT BUG FOUND HERE. _record_test_run() called
`db.insert(..., on_conflict=..., merge_patch=...)`; db.insert's signature is
(table, row, upsert=False), so every call raised TypeError inside the fail-soft `except`
and no test run was ever persisted. Fixed to db.upsert(); pinned by
TestRecordTestRun::test_the_write_matches_the_real_db_signature.

REACHABILITY. continuous_test_runner is NOT reached from production: merge_train.py does
not import it, nothing calls merge_gate_check() or on_push(), and it has no entry in
runner._SCHEDULE or periodic.JOBS. Its only importers are this file and
tests/test_continuous_test_runner_branch.py.
"""
import inspect
import os
import sys

import pytest

# runner/ appended rather than inserted at position 0: at sys.path[0] the module file
# runner/runner.py shadows the runner/ package for the rest of the session (see the
# repo-root conftest.py).
_RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
if _RUNNER_DIR not in sys.path:
    sys.path.append(_RUNNER_DIR)

import continuous_test_runner as ctr  # noqa: E402
import db as real_db  # noqa: E402


class RecordingDB:
    """A db stand-in with the REAL db module's signatures.

    Signature fidelity is the point: the bug this file uncovered was a call site passing
    kwargs db.insert does not accept. A permissive MagicMock would have accepted them
    happily and the regression could come straight back.
    """

    def __init__(self):
        self.calls = []
        self.rows = []
        self.fail_with = None

    def insert(self, table, row, upsert=False):
        return self._write("insert", table, row, {"upsert": upsert})

    def upsert(self, table, row):
        return self._write("upsert", table, row, {})

    def update(self, table, match, patch):
        self.calls.append(("update", table, match, patch))
        if self.fail_with is not None:
            raise self.fail_with
        return patch

    def _write(self, kind, table, row, extra):
        self.calls.append((kind, table, row, extra))
        if self.fail_with is not None:
            raise self.fail_with
        self.rows.append(row)
        return row


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """No real DB writes, no real backoff sleeps, and a test command that is not `npm test`.

    TEST_CMD is read live from the environment on every run, and its default is
    "npm test" -- which in this container would shell out to a missing binary and make
    every result here depend on node's absence rather than on the module.
    """
    db = RecordingDB()
    monkeypatch.setattr(ctr, "db", db)
    monkeypatch.setattr(ctr.time, "sleep", lambda _s: None)
    monkeypatch.setenv("TEST_CMD", "true")
    monkeypatch.delenv("CONTINUOUS_TEST_TIMEOUT", raising=False)
    monkeypatch.delenv("CONTINUOUS_TEST_FLAKE_RETRIES", raising=False)
    return db


@pytest.fixture()
def repo(tmp_path):
    """A plain directory is enough: every test here runs with branch=None, so no git is
    involved (branch materialisation is tests/test_continuous_test_runner_branch.py's)."""
    d = tmp_path / "repo"
    d.mkdir()
    return str(d)


# ---------------------------------------------------------------------------
# The result dict  (was: TestResult)
# ---------------------------------------------------------------------------
class TestResultShape:
    def test_ok_when_zero_exit(self, repo, monkeypatch):
        monkeypatch.setenv("TEST_CMD", "exit 0")
        r = ctr.run_tests(repo, mode="merge-gate")
        assert r["passed"] is True
        assert r["exit_code"] == 0
        assert r["flake"] is False

    def test_not_ok_with_nonzero_exit(self, repo, monkeypatch):
        monkeypatch.setenv("TEST_CMD", "exit 1")
        monkeypatch.setenv("CONTINUOUS_TEST_FLAKE_RETRIES", "0")
        r = ctr.run_tests(repo, mode="merge-gate")
        assert r["passed"] is False
        assert r["exit_code"] == 1

    def test_result_keys(self, repo):
        """The documented return contract, since callers index it directly."""
        r = ctr.run_tests(repo, mode="merge-gate")
        assert set(r) == {
            "passed", "exit_code", "output", "output_hash", "duration_s",
            "flake", "mode", "task_id", "slug", "timestamp",
        }
        assert isinstance(r["duration_s"], float)
        assert isinstance(r["output_hash"], str) and len(r["output_hash"]) == 16

    def test_task_context_is_carried_into_the_result(self, repo):
        r = ctr.run_tests(repo, task={"id": "t-9", "slug": "add-widget"},
                          mode="push-trigger")
        assert r["task_id"] == "t-9"
        assert r["slug"] == "add-widget"
        assert r["mode"] == "push-trigger"

    def test_missing_task_context_defaults_to_unknown(self, repo):
        r = ctr.run_tests(repo, task=None)
        assert r["task_id"] == "unknown"
        assert r["slug"] == "unknown"

    def test_output_truncation(self, repo, monkeypatch):
        """Output is tailed to 4000 chars -- a runaway suite must not become a 200MB row.

        (Was: an assertion about a 2000-char `output_tail` key on a class that does not
        exist. Same intent, real constant.)
        """
        monkeypatch.setenv("TEST_CMD", "python3 -c \"print('x' * 5000)\"")
        r = ctr.run_tests(repo)
        assert len(r["output"]) == 4000
        # the TAIL is kept, so the trailing newline the child printed survives
        assert r["output"].endswith("x\n")

    def test_stdout_and_stderr_are_both_captured(self, repo, monkeypatch):
        monkeypatch.setenv("TEST_CMD", "echo out; echo err 1>&2")
        r = ctr.run_tests(repo)
        assert "out" in r["output"]
        assert "err" in r["output"]

    def test_tests_run_in_the_repo_directory(self, repo, monkeypatch):
        monkeypatch.setenv("TEST_CMD", "pwd")
        r = ctr.run_tests(repo)
        assert os.path.realpath(repo) == os.path.realpath(r["output"].strip())


# ---------------------------------------------------------------------------
# _result_hash  (was: _parse_test_counts, which does not exist)
# ---------------------------------------------------------------------------
class TestResultHash:
    """The hash is the flake oracle: same hash on a retry means the same failure, which
    means a real one. Anything that varies run-to-run without the code changing has to be
    normalised out of it, or every failure would look like a flake."""

    def test_identical_output_hashes_identically(self):
        assert ctr._result_hash("FAILED test_a") == ctr._result_hash("FAILED test_a")

    def test_different_failures_hash_differently(self):
        assert ctr._result_hash("FAILED test_a") != ctr._result_hash("FAILED test_b")

    def test_timing_noise_is_normalised_away(self):
        """"5 passed in 3.21s" and "... in 9.80s" are the same result."""
        assert (ctr._result_hash("===== 1 failed in 3.21s =====")
                == ctr._result_hash("===== 1 failed in 9.80s ====="))

    def test_timestamps_are_normalised_away(self):
        assert (ctr._result_hash("run at 2026-08-24 11:00:01 on host-a")
                == ctr._result_hash("run at 2026-01-02 23:59:59 on host-b"))

    def test_hash_is_a_short_stable_hex_digest(self):
        h = ctr._result_hash("anything")
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_undecodable_bytes_do_not_raise(self):
        """Test output is whatever the child printed; a lone surrogate must not take the
        gate down (the module passes errors="replace" for exactly this)."""
        assert len(ctr._result_hash("bad \udcff byte")) == 16


# ---------------------------------------------------------------------------
# command, timeout, exit codes  (was: run_test_command)
# ---------------------------------------------------------------------------
class TestCommandExecution:
    def test_test_cmd_is_read_live_from_the_environment(self, repo, monkeypatch):
        """Read per-call, not at import, so fleet_config can retune it without a redeploy."""
        monkeypatch.setenv("TEST_CMD", "echo first")
        assert "first" in ctr.run_tests(repo)["output"]
        monkeypatch.setenv("TEST_CMD", "echo second")
        assert "second" in ctr.run_tests(repo)["output"]

    def test_default_test_cmd(self, monkeypatch):
        monkeypatch.delenv("TEST_CMD", raising=False)
        assert ctr._test_cmd() == "npm test"

    def test_timeout(self, repo, monkeypatch):
        monkeypatch.setenv("TEST_CMD", "sleep 30")
        monkeypatch.setenv("CONTINUOUS_TEST_TIMEOUT", "1")
        monkeypatch.setenv("CONTINUOUS_TEST_FLAKE_RETRIES", "0")
        r = ctr.run_tests(repo)
        assert r["passed"] is False
        assert r["exit_code"] == 124
        assert "timed out after 1s" in r["output"]

    def test_timeout_default_and_bad_value(self, monkeypatch):
        monkeypatch.delenv("CONTINUOUS_TEST_TIMEOUT", raising=False)
        assert ctr._test_timeout() == 300
        monkeypatch.setenv("CONTINUOUS_TEST_TIMEOUT", "not-a-number")
        assert ctr._test_timeout() == 300, "a malformed knob must not crash the gate"

    def test_flake_retry_count_default_and_bad_value(self, monkeypatch):
        monkeypatch.delenv("CONTINUOUS_TEST_FLAKE_RETRIES", raising=False)
        assert ctr._max_flake_retries() == 2
        monkeypatch.setenv("CONTINUOUS_TEST_FLAKE_RETRIES", "")
        assert ctr._max_flake_retries() == 2

    def test_duration_is_recorded(self, repo, monkeypatch):
        monkeypatch.setenv("TEST_CMD", "true")
        r = ctr.run_tests(repo)
        assert r["duration_s"] >= 0.0

    def test_unrunnable_repo_is_reported_not_raised(self, monkeypatch, tmp_path):
        """A missing worktree is a red result with the reason in `output`, not a traceback
        out of the merge gate."""
        monkeypatch.setenv("CONTINUOUS_TEST_FLAKE_RETRIES", "0")
        r = ctr.run_tests(str(tmp_path / "does-not-exist"))
        assert r["passed"] is False
        assert r["exit_code"] == -1
        assert r["output"]


# ---------------------------------------------------------------------------
# flake retries  (was: aggregate_results)
# ---------------------------------------------------------------------------
class TestFlakeRetries:
    def _flaky_cmd(self, tmp_path, fail_times):
        """A command that fails its first `fail_times` invocations, then passes."""
        counter = tmp_path / "n"
        counter.write_text("0")
        return (
            f"n=$(cat {counter}); echo $((n+1)) > {counter}; "
            f"if [ $n -lt {fail_times} ]; then echo 'boom'; exit 1; fi; echo 'ok'"
        )

    def test_a_pass_on_retry_is_reported_as_a_flake(self, repo, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_CMD", self._flaky_cmd(tmp_path, fail_times=1))
        r = ctr.run_tests(repo, mode="merge-gate")
        assert r["passed"] is True
        assert r["flake"] is True
        assert "passed on retry 1" in r["output"]

    def test_a_consistent_failure_is_not_a_flake(self, repo, monkeypatch):
        monkeypatch.setenv("TEST_CMD", "echo 'assert 1 == 2'; exit 1")
        r = ctr.run_tests(repo, mode="merge-gate")
        assert r["passed"] is False
        assert r["flake"] is False

    def test_changing_output_across_retries_is_flagged_as_a_flake(self, repo, tmp_path,
                                                                 monkeypatch):
        """Still red -- but a failure that differs every run is not trustworthy signal."""
        counter = tmp_path / "n"
        counter.write_text("0")
        monkeypatch.setenv("TEST_CMD",
                           f"n=$(cat {counter}); echo $((n+1)) > {counter}; "
                           f"echo \"failure variant $n\"; exit 1")
        r = ctr.run_tests(repo, mode="merge-gate")
        assert r["passed"] is False
        assert r["flake"] is True
        assert "different output on retry" in r["output"]

    def test_retries_stop_at_the_configured_limit(self, repo, tmp_path, monkeypatch):
        """Two retries configured, three failures needed to pass -> still red."""
        monkeypatch.setenv("TEST_CMD", self._flaky_cmd(tmp_path, fail_times=3))
        monkeypatch.setenv("CONTINUOUS_TEST_FLAKE_RETRIES", "2")
        r = ctr.run_tests(repo, mode="merge-gate")
        assert r["passed"] is False

    def test_retries_are_disabled_by_the_env_knob(self, repo, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_CMD", self._flaky_cmd(tmp_path, fail_times=1))
        monkeypatch.setenv("CONTINUOUS_TEST_FLAKE_RETRIES", "0")
        r = ctr.run_tests(repo, mode="merge-gate")
        assert r["passed"] is False
        assert r["flake"] is False

    def test_push_trigger_mode_never_retries(self, repo, tmp_path, monkeypatch):
        """Retries exist to protect the merge gate. A reporting-only push run must not pay
        for them -- it would triple the cost of every push for a signal nobody blocks on."""
        monkeypatch.setenv("TEST_CMD", self._flaky_cmd(tmp_path, fail_times=1))
        r = ctr.run_tests(repo, mode="push-trigger")
        assert r["passed"] is False
        assert r["flake"] is False
        assert (tmp_path / "n").read_text().strip() == "1"

    def test_a_passing_run_is_not_retried(self, repo, tmp_path, monkeypatch):
        counter = tmp_path / "n"
        counter.write_text("0")
        monkeypatch.setenv("TEST_CMD",
                           f"n=$(cat {counter}); echo $((n+1)) > {counter}; true")
        ctr.run_tests(repo, mode="merge-gate")
        assert counter.read_text().strip() == "1"


class TestRunOnce:
    def test_run_once_reports_pass_fail_and_hash(self, repo):
        ok = ctr._run_once(repo, "echo hello", 10)
        assert ok["passed"] is True
        assert ok["exit_code"] == 0
        assert "hello" in ok["output"]
        assert len(ok["output_hash"]) == 16

    def test_run_once_never_raises(self, tmp_path):
        """The retry loop calls this with no guard of its own."""
        bad = ctr._run_once(str(tmp_path / "missing"), "true", 10)
        assert bad["passed"] is False
        assert bad["exit_code"] == -1


# ---------------------------------------------------------------------------
# persistence  (was: stats / reset_stats)
# ---------------------------------------------------------------------------
class TestRecordTestRun:
    def test_every_run_is_recorded_once(self, repo, _isolated):
        ctr.run_tests(repo, task={"id": "t-1", "slug": "s-1"}, mode="merge-gate")
        writes = [c for c in _isolated.calls if c[0] in ("insert", "upsert")]
        assert len(writes) == 1
        assert writes[0][1] == "fleet_config"

    def test_the_write_matches_the_real_db_signature(self, repo, _isolated):
        """REGRESSION. _record_test_run() used to call

            db.insert(row, on_conflict="key", merge_patch={"value": "EXCLUDED.value"})

        and db.insert takes (table, row, upsert=False). Every call raised TypeError inside
        the function's own fail-soft `except`, so the "so the fleet can learn which tests
        flake" ledger had never contained a single row. Binding the recorded call against
        the REAL db module's signature is what keeps that from silently returning.
        """
        ctr.run_tests(repo, task={"id": "t-1", "slug": "s-1"})
        kind, table, row, extra = [c for c in _isolated.calls
                                   if c[0] in ("insert", "upsert")][0]
        signature = inspect.signature(getattr(real_db, kind))
        signature.bind(table, row, **extra)  # raises TypeError if the call site drifts

    def test_recorded_payload_carries_the_learning_signal(self, repo, _isolated,
                                                          monkeypatch):
        monkeypatch.setenv("TEST_CMD", "exit 1")
        monkeypatch.setenv("CONTINUOUS_TEST_FLAKE_RETRIES", "0")
        ctr.run_tests(repo, task={"id": "t-7", "slug": "widget"}, mode="merge-gate")

        row = _isolated.rows[0]
        assert row["key"].startswith("test_run:t-7:")
        for field in ("passed", "flake", "hash", "duration_s", "mode", "slug"):
            assert field in row["value"]
        assert "'passed': False" in row["value"]
        assert "widget" in row["value"]

    def test_recorded_value_is_bounded(self, repo, _isolated, monkeypatch):
        monkeypatch.setenv("TEST_CMD", "python3 -c \"print('y' * 5000)\"")
        ctr.run_tests(repo, task={"id": "t-8", "slug": "z" * 4000})
        assert len(_isolated.rows[0]["value"]) <= 500

    def test_recording_failure_never_fails_the_gate(self, repo, _isolated, monkeypatch):
        """Fail-soft is the documented contract: a dead ledger must not turn a green
        branch red."""
        _isolated.fail_with = RuntimeError("supabase down")
        monkeypatch.setenv("TEST_CMD", "true")
        assert ctr.run_tests(repo)["passed"] is True


# ---------------------------------------------------------------------------
# the two entry points
# ---------------------------------------------------------------------------
class TestMergeGateCheck:
    """Branch-vs-checked-out-tree behaviour is owned by
    tests/test_continuous_test_runner_branch.py; what is pinned here is the delegation."""

    def test_returns_the_pass_flag_and_gates_in_merge_gate_mode(self, monkeypatch):
        seen = {}

        def fake_run_tests(repo, branch=None, task=None, mode=None):
            seen.update(repo=repo, branch=branch, task=task, mode=mode)
            return {"passed": True}

        monkeypatch.setattr(ctr, "run_tests", fake_run_tests)
        assert ctr.merge_gate_check("/r", "feature", "master", {"id": "t"}) is True
        assert seen == {"repo": "/r", "branch": "feature", "task": {"id": "t"},
                        "mode": "merge-gate"}

    def test_red_tests_block_the_merge(self, monkeypatch):
        monkeypatch.setattr(ctr, "run_tests",
                            lambda *a, **k: {"passed": False})
        assert ctr.merge_gate_check("/r", "feature", "master", None) is False


class TestOnPush:
    def test_green_push_annotates_nothing(self, repo, _isolated, monkeypatch):
        monkeypatch.setenv("TEST_CMD", "true")
        result = ctr.on_push(repo, "feature", task={"id": "t-1", "note": "hi"})
        assert result["passed"] is True
        assert not [c for c in _isolated.calls if c[0] == "update"]

    def test_red_push_annotates_the_task_but_does_not_gate(self, repo, _isolated,
                                                           monkeypatch):
        monkeypatch.setenv("TEST_CMD", "exit 1")
        result = ctr.on_push(repo, "feature", task={"id": "t-1", "note": "hi"})

        assert result["passed"] is False  # reported, never raised
        updates = [c for c in _isolated.calls if c[0] == "update"]
        assert len(updates) == 1
        _, table, match, patch = updates[0]
        assert (table, match) == ("tasks", {"id": "t-1"})
        assert patch["note"].startswith("hi [push-test-fail: ")
        assert result["output_hash"] in patch["note"]

    def test_the_same_failure_is_not_appended_twice(self, repo, _isolated, monkeypatch):
        """on_push runs on every push; a task that keeps failing the same way must not
        accumulate the same tag until the 500-char note is nothing else."""
        monkeypatch.setenv("TEST_CMD", "echo stable-failure; exit 1")
        first = ctr.on_push(repo, "feature", task={"id": "t-1", "note": ""})
        task = {"id": "t-1", "note": f" [push-test-fail: {first['output_hash']}]"}

        ctr.on_push(repo, "feature", task=task)

        assert len([c for c in _isolated.calls if c[0] == "update"]) == 1

    def test_push_without_a_task_records_but_annotates_nothing(self, repo, _isolated,
                                                               monkeypatch):
        monkeypatch.setenv("TEST_CMD", "exit 1")
        result = ctr.on_push(repo, "feature", task=None)
        assert result["passed"] is False
        assert not [c for c in _isolated.calls if c[0] == "update"]
        assert _isolated.rows, "the run is still recorded for fleet learning"

    def test_annotation_failure_never_propagates(self, repo, _isolated, monkeypatch):
        monkeypatch.setenv("TEST_CMD", "exit 1")
        _isolated.fail_with = RuntimeError("supabase down")
        assert ctr.on_push(repo, "f", task={"id": "t-1"})["passed"] is False

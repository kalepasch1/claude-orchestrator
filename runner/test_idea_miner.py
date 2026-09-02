#!/usr/bin/env python3
"""
test_idea_miner.py - tests for the idea_miner module.

REWRITTEN 2026-08-24. The previous version of this file tested an API idea_miner.py has
never had: it built `idea_miner.IdeaMiner()` and called mine_errors_from_logs(),
mine_analytics(), mine_backlog(), mine_support_issues(), deduplicate(), write_task() and
run(), and reached for module names `_extract_timestamp`, `_extract_error_message`,
`LOOKBACK_HOURS` and `idea_miner.sqlite3`. None of those exist. The real module is
function-based with a single `IdeaMinerState` singleton behind `acquire()`, reads JSON-lines
runner logs and a JSON-lines support queue, and is configured through IDEA_MINER_* env vars.
29 of the 32 tests failed on AttributeError at the first line of their body.

The three that "passed" were worse than the failures: TestEnvironmentConfiguration set an
env var and then asserted on its own `os.getenv` call, and TestDryRun's
test_dry_run_includes_all_required_fields asserted that a dict literal defined two lines
above contained its own keys. Neither imported anything from idea_miner. They are replaced
below with checks against the module's actual configuration constants and actual output.

Two whole classes had no counterpart in the product at all: idea_miner has no analytics/
sqlite funnel mining and no intake/backlog scanning — it has exactly two signal sources,
error logs and the support queue. SUBSTITUTION: TestAnalyticsMining and TestBacklogMining
are replaced by TestSupportQueueSignal, which covers the real second source with the same
intents (a signal above threshold is surfaced, a missing source degrades to [], a malformed
source is skipped, a below-threshold signal is not surfaced).

No test here touches the network or a database; every path is a tmp_path.
"""

import csv
import importlib.util
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

_RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
if _RUNNER_DIR not in sys.path:
    # Append, never insert(0): runner/runner.py shadows the runner/ package at sys.path[0]
    # and takes the whole session's collection down with it. See the repo-root conftest.
    sys.path.append(_RUNNER_DIR)

import idea_miner

#: Config globals idea_miner reads at call time from module scope. Every test that points
#: the miner at a tmp_path mutates one of these, so they are snapshotted and restored.
_CONFIG_NAMES = (
    "IDEA_MINER_MODE",
    "IDEA_MINER_LOG_PATH",
    "IDEA_MINER_DEDUP_DAYS",
    "IDEA_MINER_MIN_CONFIDENCE",
    "IDEA_MINER_SUPPORT_QUEUE",
    "GENERATED_TASKS_PATH",
    "GENERATED_TASKS_CSV_PATH",
)


@pytest.fixture(autouse=True)
def _isolate_idea_miner():
    """Restore every process-global the module owns: config, singleton, and its logger.

    idea_miner.acquire() memoises an IdeaMinerState forever, and its counters (
    duplicates_skipped, errors_encountered) accumulate across generate() calls — so a
    leaked singleton makes a later test's stats() assertion depend on which tests ran
    before it. _get_logger() likewise attaches a StreamHandler to the process-wide
    logging registry, which would stack one handler per test.
    """
    saved = {name: getattr(idea_miner, name) for name in _CONFIG_NAMES}
    idea_miner._state = None
    idea_miner._logger = None
    log = logging.getLogger("idea_miner")
    handlers_before = list(log.handlers)
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(idea_miner, name, value)
        idea_miner._state = None
        idea_miner._logger = None
        log.handlers[:] = handlers_before


@pytest.fixture
def miner_paths(tmp_path):
    """Point every file the miner reads or writes at tmp_path. Returns the paths."""
    paths = {
        "log": tmp_path / "runner.log",
        "queue": tmp_path / "support_queue.jsonl",
        "tasks": tmp_path / "generated_tasks.jsonl",
        "csv": tmp_path / "generated_tasks.csv",
    }
    idea_miner.IDEA_MINER_LOG_PATH = str(paths["log"])
    idea_miner.IDEA_MINER_SUPPORT_QUEUE = str(paths["queue"])
    idea_miner.GENERATED_TASKS_PATH = str(paths["tasks"])
    idea_miner.GENERATED_TASKS_CSV_PATH = str(paths["csv"])
    return paths


def _error_lines(message, count, level="ERROR", timestamp="2026-08-24T10:00:00Z"):
    return "".join(
        json.dumps({"level": level, "message": message, "timestamp": timestamp}) + "\n"
        for _ in range(count)
    )


#: An ERROR-level signal needs six occurrences to clear IDEA_MINER_MIN_CONFIDENCE (0.5):
#: _compute_confidence is (frequency - 1) * 0.15 * severity, and ERROR severity is 0.7,
#: so five occurrences score 0.42 and six score 0.525. Derived from the product, not chosen.
_ABOVE_THRESHOLD = 6
_BELOW_THRESHOLD = 5


class TestErrorLogParsing:
    """_read_logs: JSON-lines runner logs in, error entries out."""

    def test_json_error_lines_are_extracted_with_line_numbers(self, miner_paths):
        miner_paths["log"].write_text(_error_lines("Connection timeout", 3), encoding="utf-8")

        entries = idea_miner._read_logs()

        assert [e["line_number"] for e in entries] == [1, 2, 3]
        assert {e["error_msg"] for e in entries} == {"Connection timeout"}
        assert all(e["timestamp"] == "2026-08-24T10:00:00Z" for e in entries)

    def test_info_and_debug_levels_are_not_signals(self, miner_paths):
        miner_paths["log"].write_text(
            _error_lines("noise", 5, level="INFO") + _error_lines("real", 2, level="ERROR"),
            encoding="utf-8",
        )

        entries = idea_miner._read_logs()

        assert [e["error_msg"] for e in entries] == ["real", "real"]

    @pytest.mark.parametrize("level,severity", [("CRITICAL", 1.0), ("ERROR", 0.7), ("WARNING", 0.5)])
    def test_severity_is_graded_by_level(self, miner_paths, level, severity):
        miner_paths["log"].write_text(_error_lines("x", 1, level=level), encoding="utf-8")

        assert idea_miner._read_logs()[0]["severity"] == severity

    def test_a_missing_log_file_degrades_to_no_signals(self, miner_paths):
        assert not miner_paths["log"].exists()
        assert idea_miner._read_logs() == []

    def test_non_json_lines_fall_back_to_keyword_matching(self, miner_paths):
        miner_paths["log"].write_text(
            "a perfectly ordinary line\n"
            "Traceback (most recent call last)\n"
            "ERROR could not connect\n",
            encoding="utf-8",
        )

        entries = idea_miner._read_logs()

        # Line 1 carries no error keyword and is dropped; lines 2 and 3 are kept at the
        # plain-text severity of 0.7.
        assert [e["line_number"] for e in entries] == [2, 3]
        assert all(e["severity"] == 0.7 for e in entries)

    def test_blank_lines_do_not_consume_line_numbers_incorrectly(self, miner_paths):
        miner_paths["log"].write_text(
            "\n\n" + json.dumps({"level": "ERROR", "message": "boom"}) + "\n", encoding="utf-8"
        )

        entries = idea_miner._read_logs()

        assert [e["line_number"] for e in entries] == [3]
        assert entries[0]["error_msg"] == "boom"

    def test_an_oversized_message_is_capped_at_500_characters(self, miner_paths):
        miner_paths["log"].write_text(
            json.dumps({"level": "ERROR", "message": "x" * 5000}) + "\n", encoding="utf-8"
        )

        assert len(idea_miner._read_logs()[0]["error_msg"]) == 500


class TestErrorSignature:
    """_extract_error_signature: collapse per-occurrence noise so recurrences group."""

    def test_variable_parts_are_canonicalised(self):
        sig = idea_miner._extract_error_signature(
            '2026-08-24T10:00:00Z failed at line 42 pid=991 addr 0x7ffab12 opening "/var/log/x"'
        )
        assert sig == "TIMESTAMP failed at line N pid=PID addr 0xADDR opening PATH"

    def test_two_occurrences_differing_only_in_noise_share_a_signature(self):
        a = idea_miner._extract_error_signature("boom at line 7 pid=1 (0xdeadbeef)")
        b = idea_miner._extract_error_signature("boom at line 999 pid=4242 (0xcafe)")
        assert a == b

    def test_genuinely_different_errors_do_not_collide(self):
        assert idea_miner._extract_error_signature("disk full") != \
            idea_miner._extract_error_signature("connection refused")

    def test_the_signature_is_capped_at_200_characters(self):
        assert len(idea_miner._extract_error_signature("y" * 4000)) == 200


class TestConfidenceAndPriority:
    """_compute_confidence / _compute_priority: the scoring the threshold filter uses."""

    def test_a_single_occurrence_scores_zero_confidence(self):
        assert idea_miner._compute_confidence(1, 1.0) == 0.0

    def test_confidence_rises_with_frequency_and_is_bounded_at_one(self):
        scores = [idea_miner._compute_confidence(f, 1.0) for f in (1, 2, 5, 10, 100)]
        assert scores == sorted(scores)
        assert all(0.0 <= s <= 1.0 for s in scores)
        assert scores[-1] == 1.0

    def test_severity_scales_confidence_down(self):
        assert idea_miner._compute_confidence(6, 0.5) < idea_miner._compute_confidence(6, 1.0)

    def test_priority_stays_inside_one_to_five(self):
        for confidence in (0.0, 0.25, 0.5, 0.75, 1.0):
            for frequency in (1, 4, 20, 5000):
                assert 1 <= idea_miner._compute_priority(confidence, frequency) <= 5

    def test_priority_rises_with_confidence(self):
        assert idea_miner._compute_priority(0.0, 1) < idea_miner._compute_priority(1.0, 1)


class TestTimestampNormalisation:
    """_parse_iso_timestamp — regression cover for the offset bug fixed 2026-08-24."""

    @pytest.mark.parametrize("raw,expected", [
        ("2026-08-24T10:00:00Z", "2026-08-24T10:00:00Z"),
        ("2026-08-24T10:00:00+00:00", "2026-08-24T10:00:00Z"),
        ("2026-08-24T03:00:00-07:00", "2026-08-24T10:00:00Z"),
        ("2026-08-24 10:00:00", "2026-08-24T10:00:00Z"),
        ("2026-08-24T10:00:00.500000Z", "2026-08-24T10:00:00.500000Z"),
    ])
    def test_supported_shapes_normalise_to_utc_with_a_z_suffix(self, raw, expected):
        assert idea_miner._parse_iso_timestamp(raw) == expected

    def test_the_module_can_reparse_the_timestamps_it_generates(self):
        """The bug: _read_logs defaults a missing timestamp to datetime.now().isoformat(),
        which renders '+00:00' — and the parser had no offset format, so it returned None."""
        now = datetime.now(timezone.utc)
        produced = now.isoformat()
        assert produced.endswith("+00:00"), "the module emits offsets, not 'Z'"

        # Exact round trip, not merely "not None": the same instant, in the 'Z' form the
        # rest of the module reads back.
        assert idea_miner._parse_iso_timestamp(produced) == produced.replace("+00:00", "Z")

    @pytest.mark.parametrize("raw", [None, "", "not a timestamp", "24/08/2026", 5])
    def test_unparseable_input_is_none_rather_than_an_exception(self, raw):
        assert idea_miner._parse_iso_timestamp(raw) is None


class TestTaskGenerationFromErrors:
    """_generate_tasks_from_errors: grouped signals become evidence-anchored tasks."""

    def test_a_recurring_error_above_threshold_becomes_one_task(self, miner_paths):
        miner_paths["log"].write_text(
            _error_lines("Connection timeout", _ABOVE_THRESHOLD), encoding="utf-8"
        )

        tasks = idea_miner._generate_tasks_from_errors(idea_miner._read_logs())

        assert len(tasks) == 1
        task = tasks[0]
        assert task["signal_type"] == "error"
        assert task["frequency"] == _ABOVE_THRESHOLD
        assert task["error_signature"] == "Connection timeout"
        assert task["source_id"] == 1  # the first line the signature was seen on
        assert task["source_timestamp"] == "2026-08-24T10:00:00Z"
        assert task["confidence"] >= idea_miner.IDEA_MINER_MIN_CONFIDENCE
        assert 1 <= task["priority"] <= 5
        assert "Connection timeout" in task["title"]

    def test_an_error_below_threshold_is_not_worth_a_task(self, miner_paths):
        miner_paths["log"].write_text(
            _error_lines("Rare hiccup", _BELOW_THRESHOLD), encoding="utf-8"
        )

        assert idea_miner._generate_tasks_from_errors(idea_miner._read_logs()) == []

    def test_distinct_errors_produce_distinct_tasks(self, miner_paths):
        miner_paths["log"].write_text(
            _error_lines("Connection timeout", _ABOVE_THRESHOLD)
            + _error_lines("Database is locked", _ABOVE_THRESHOLD),
            encoding="utf-8",
        )

        tasks = idea_miner._generate_tasks_from_errors(idea_miner._read_logs())

        assert {t["error_signature"] for t in tasks} == {"Connection timeout", "Database is locked"}

    def test_the_title_is_capped_for_a_very_long_signature(self, miner_paths):
        miner_paths["log"].write_text(
            _error_lines("z" * 300, _ABOVE_THRESHOLD), encoding="utf-8"
        )

        title = idea_miner._generate_tasks_from_errors(idea_miner._read_logs())[0]["title"]

        assert len(title) <= 100
        assert title.endswith("...")


class TestSupportQueueSignal:
    """SUBSTITUTION for the old TestAnalyticsMining / TestBacklogMining.

    idea_miner has no sqlite analytics funnel and no intake/backlog scanner; its second and
    only other signal source is the JSON-lines support queue. The four intents of the
    removed classes — a signal above threshold is surfaced, a missing source degrades to [],
    a broken source does not raise, a healthy/low signal is not surfaced — are kept here
    against that real source.
    """

    def test_a_frequent_ticket_becomes_a_task(self, miner_paths):
        miner_paths["queue"].write_text(
            json.dumps({"id": "T-1", "title": "Export keeps timing out",
                        "created_at": "2026-08-24T09:00:00+00:00", "frequency": 9}) + "\n",
            encoding="utf-8",
        )

        tasks = idea_miner._generate_tasks_from_tickets(idea_miner._read_support_queue())

        assert len(tasks) == 1
        assert tasks[0]["signal_type"] == "ticket_pattern"
        assert tasks[0]["source_id"] == "T-1"
        assert tasks[0]["source_timestamp"] == "2026-08-24T09:00:00Z"
        assert "Export keeps timing out" in tasks[0]["title"]

    def test_a_missing_queue_degrades_to_no_signals(self, miner_paths):
        assert not miner_paths["queue"].exists()
        assert idea_miner._read_support_queue() == []

    def test_a_malformed_line_is_skipped_without_losing_the_rest(self, miner_paths):
        miner_paths["queue"].write_text(
            "{ this is not json\n"
            + json.dumps({"ticket_id": "T-2", "summary": "Slow search", "count": 9}) + "\n",
            encoding="utf-8",
        )

        tickets = idea_miner._read_support_queue()

        assert [t["ticket_id"] for t in tickets] == ["T-2"]
        assert tickets[0]["title"] == "Slow search"
        assert tickets[0]["frequency"] == 9

    def test_a_one_off_ticket_is_below_threshold(self, miner_paths):
        miner_paths["queue"].write_text(
            json.dumps({"id": "T-3", "title": "Typo on settings page", "count": 1}) + "\n",
            encoding="utf-8",
        )

        assert idea_miner._generate_tasks_from_tickets(idea_miner._read_support_queue()) == []


class TestDeduplication:
    """_compute_task_hash / _load_existing_tasks and the generate-mode dedup pass."""

    def test_the_hash_keys_on_signature_and_source_hour(self):
        base = {"error_signature": "boom", "source_timestamp": "2026-08-24T10:00:00Z"}
        same_hour = {"error_signature": "boom", "source_timestamp": "2026-08-24T10:59:59Z"}
        next_hour = {"error_signature": "boom", "source_timestamp": "2026-08-24T11:00:00Z"}
        other_sig = {"error_signature": "crunch", "source_timestamp": "2026-08-24T10:00:00Z"}

        assert idea_miner._compute_task_hash(base) == idea_miner._compute_task_hash(same_hour)
        assert idea_miner._compute_task_hash(base) != idea_miner._compute_task_hash(next_hour)
        assert idea_miner._compute_task_hash(base) != idea_miner._compute_task_hash(other_sig)

    def test_existing_tasks_load_keyed_by_that_same_hash(self, miner_paths):
        task = {"error_signature": "boom", "source_timestamp": "2026-08-24T10:00:00Z",
                "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
        miner_paths["tasks"].write_text(json.dumps(task) + "\n", encoding="utf-8")

        existing = idea_miner._load_existing_tasks()

        assert idea_miner._compute_task_hash(task) in existing

    def test_tasks_older_than_the_dedup_window_stop_blocking(self, miner_paths):
        stale = datetime.now(timezone.utc) - timedelta(days=idea_miner.IDEA_MINER_DEDUP_DAYS + 1)
        task = {"error_signature": "boom", "source_timestamp": "2026-08-24T10:00:00Z",
                "generated_at": stale.isoformat().replace("+00:00", "Z")}
        miner_paths["tasks"].write_text(json.dumps(task) + "\n", encoding="utf-8")

        assert idea_miner._load_existing_tasks() == {}

    def test_a_missing_task_file_is_an_empty_dedup_set(self, miner_paths):
        assert idea_miner._load_existing_tasks() == {}

    def test_a_second_generate_run_appends_nothing_new(self, miner_paths):
        miner_paths["log"].write_text(
            _error_lines("Connection timeout", _ABOVE_THRESHOLD), encoding="utf-8"
        )

        first = idea_miner.acquire().generate(mode="generate")
        idea_miner._state = None
        state = idea_miner.acquire()
        second = state.generate(mode="generate")

        assert len(first) == 1
        assert second == []
        assert state.duplicates_skipped == 1
        assert miner_paths["tasks"].read_text().strip().count("\n") == 0  # still one line

    def test_the_same_error_does_not_re_emit_an_hour_later(self, miner_paths):
        """Regression for the _parse_iso_timestamp offset bug.

        The dedup hash keys on the SOURCE hour. While offset timestamps parsed as None the
        source timestamp fell back to *generation* time, so the hash moved with the clock and
        an unchanged, still-recurring error produced a brand-new task on every hourly run.
        """
        miner_paths["log"].write_text(
            _error_lines("Connection timeout", _ABOVE_THRESHOLD,
                         timestamp="2026-08-24T10:00:00+00:00"),
            encoding="utf-8",
        )
        idea_miner.acquire().generate(mode="generate")

        later = datetime.now(timezone.utc) + timedelta(hours=3)

        class _LaterClock(idea_miner.datetime):
            @classmethod
            def now(cls, tz=None):
                return later if tz else later.replace(tzinfo=None)

        idea_miner._state = None
        with patch.object(idea_miner, "datetime", _LaterClock):
            state = idea_miner.acquire()
            emitted = state.generate(mode="generate")

        assert emitted == []
        assert state.duplicates_skipped == 1
        assert len(miner_paths["tasks"].read_text().strip().splitlines()) == 1


class TestDryRun:
    """dry-run must produce the tasks without touching the task file."""

    def test_dry_run_returns_tasks_and_writes_nothing(self, miner_paths):
        miner_paths["log"].write_text(
            _error_lines("Connection timeout", _ABOVE_THRESHOLD), encoding="utf-8"
        )

        tasks = idea_miner.generate(mode="dry-run")

        assert len(tasks) == 1
        assert not miner_paths["tasks"].exists()
        assert not miner_paths["csv"].exists()

    def test_the_cli_prints_one_valid_json_object_per_task(self, miner_paths, capsys):
        miner_paths["log"].write_text(
            _error_lines("Connection timeout", _ABOVE_THRESHOLD)
            + _error_lines("Database is locked", _ABOVE_THRESHOLD),
            encoding="utf-8",
        )

        with patch.object(sys, "argv", ["idea_miner.py", "--mode", "dry-run"]):
            idea_miner.main()

        lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
        assert len(lines) == 2
        emitted = [json.loads(l) for l in lines]
        assert {e["error_signature"] for e in emitted} == {"Connection timeout", "Database is locked"}
        assert not miner_paths["tasks"].exists()

    def test_every_emitted_task_carries_the_documented_fields(self, miner_paths):
        """Asserted against generate()'s OUTPUT, not against a literal defined in the test."""
        miner_paths["log"].write_text(
            _error_lines("Connection timeout", _ABOVE_THRESHOLD), encoding="utf-8"
        )

        task = idea_miner.generate(mode="dry-run")[0]

        for field in ("title", "signal_type", "source_id", "source_timestamp",
                      "confidence", "priority", "frequency", "generated_at"):
            assert field in task, field
            assert task[field] not in (None, "")


class TestGenerateModeOutputs:
    """generate mode appends JSONL, and --csv exports the flat columns."""

    def test_tasks_are_appended_as_json_lines(self, miner_paths):
        miner_paths["log"].write_text(
            _error_lines("Connection timeout", _ABOVE_THRESHOLD), encoding="utf-8"
        )
        miner_paths["tasks"].write_text(json.dumps({"pre": "existing"}) + "\n", encoding="utf-8")

        idea_miner.generate(mode="generate")

        lines = miner_paths["tasks"].read_text().strip().splitlines()
        assert len(lines) == 2, "the pre-existing line must be kept: this is an append"
        assert json.loads(lines[0]) == {"pre": "existing"}
        assert json.loads(lines[1])["error_signature"] == "Connection timeout"

    def test_csv_export_writes_a_header_and_a_row_per_task(self, miner_paths):
        miner_paths["log"].write_text(
            _error_lines("Connection timeout", _ABOVE_THRESHOLD), encoding="utf-8"
        )

        idea_miner.acquire().generate(mode="generate", csv_export=True)

        with open(miner_paths["csv"], newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 1
        assert rows[0]["signal_type"] == "error"
        assert rows[0]["frequency"] == str(_ABOVE_THRESHOLD)

    def test_an_unwritable_task_path_is_recorded_not_raised(self, miner_paths, tmp_path):
        """Fail-soft is the module's stated contract; the error must still be counted."""
        miner_paths["log"].write_text(
            _error_lines("Connection timeout", _ABOVE_THRESHOLD), encoding="utf-8"
        )
        blocked = tmp_path / "not_a_dir"
        blocked.write_text("i am a file", encoding="utf-8")
        idea_miner.GENERATED_TASKS_PATH = str(blocked / "sub" / "tasks.jsonl")

        state = idea_miner.acquire()
        tasks = state.generate(mode="generate")

        assert len(tasks) == 1
        assert state.errors_encountered == 1

    def test_both_signal_sources_reach_the_same_output(self, miner_paths):
        miner_paths["log"].write_text(
            _error_lines("Connection timeout", _ABOVE_THRESHOLD), encoding="utf-8"
        )
        miner_paths["queue"].write_text(
            json.dumps({"id": "T-1", "title": "Export keeps timing out", "frequency": 9}) + "\n",
            encoding="utf-8",
        )

        tasks = idea_miner.generate(mode="dry-run")

        assert {t["signal_type"] for t in tasks} == {"error", "ticket_pattern"}


class TestSingletonAndStats:
    """acquire()/stats(): the module-level singleton and its counters."""

    def test_acquire_returns_the_same_state_object(self):
        assert idea_miner.acquire() is idea_miner.acquire()

    def test_stats_reports_the_last_run(self, miner_paths):
        miner_paths["log"].write_text(
            _error_lines("Connection timeout", _ABOVE_THRESHOLD)
            + _error_lines("noise", 2, level="INFO"),
            encoding="utf-8",
        )

        idea_miner.generate(mode="dry-run")
        stats = idea_miner.stats()

        assert stats["tasks_generated"] == 1
        assert stats["signals_read"] == _ABOVE_THRESHOLD  # INFO lines are not signals
        assert stats["duplicates_skipped"] == 0
        assert stats["errors_encountered"] == 0

    def test_stats_on_a_fresh_singleton_is_all_zero(self):
        assert idea_miner.stats() == {
            "tasks_generated": 0,
            "signals_read": 0,
            "duplicates_skipped": 0,
            "errors_encountered": 0,
        }


class TestEnvironmentConfiguration:
    """The IDEA_MINER_* env vars are read at import, so this loads a fresh module object.

    The previous version of this class set an env var and then asserted on its own
    os.getenv() call — it never referenced idea_miner and would have passed against an
    empty file. This reads the module's actual constants instead.
    """

    _SETTINGS = ("IDEA_MINER_MODE", "IDEA_MINER_LOG_PATH", "IDEA_MINER_DEDUP_DAYS",
                 "IDEA_MINER_MIN_CONFIDENCE", "IDEA_MINER_SUPPORT_QUEUE")

    @classmethod
    def _load_with_env(cls, env):
        path = os.path.join(_RUNNER_DIR, "idea_miner.py")
        spec = importlib.util.spec_from_file_location("_idea_miner_env_probe", path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, env, clear=False):
            # Start from a known-empty slate so an ambient IDEA_MINER_* in the developer's
            # shell cannot decide the outcome of the defaults test.
            for name in cls._SETTINGS:
                if name not in env:
                    os.environ.pop(name, None)
            spec.loader.exec_module(module)  # deliberately not registered in sys.modules
        return module

    def test_defaults_when_nothing_is_set(self):
        fresh = self._load_with_env({})
        assert fresh.IDEA_MINER_MODE == "dry-run"
        assert fresh.IDEA_MINER_DEDUP_DAYS == 7
        assert fresh.IDEA_MINER_MIN_CONFIDENCE == 0.5
        assert fresh.IDEA_MINER_LOG_PATH == "runner/logs/runner.log"
        assert fresh.IDEA_MINER_SUPPORT_QUEUE == "runner/support_queue.jsonl"

    def test_every_setting_is_overridable(self, tmp_path):
        fresh = self._load_with_env({
            "IDEA_MINER_MODE": "generate",
            "IDEA_MINER_DEDUP_DAYS": "3",
            "IDEA_MINER_MIN_CONFIDENCE": "0.8",
            "IDEA_MINER_LOG_PATH": str(tmp_path / "custom.log"),
            "IDEA_MINER_SUPPORT_QUEUE": str(tmp_path / "custom.jsonl"),
        })
        assert fresh.IDEA_MINER_MODE == "generate"
        assert fresh.IDEA_MINER_DEDUP_DAYS == 3
        assert fresh.IDEA_MINER_MIN_CONFIDENCE == 0.8
        assert fresh.IDEA_MINER_LOG_PATH == str(tmp_path / "custom.log")
        assert fresh.IDEA_MINER_SUPPORT_QUEUE == str(tmp_path / "custom.jsonl")

    def test_raising_min_confidence_actually_suppresses_a_borderline_signal(self, miner_paths):
        """The setting is only worth having if it changes what comes out."""
        miner_paths["log"].write_text(
            _error_lines("Connection timeout", _ABOVE_THRESHOLD), encoding="utf-8"
        )
        assert len(idea_miner.generate(mode="dry-run")) == 1

        idea_miner._state = None
        idea_miner.IDEA_MINER_MIN_CONFIDENCE = 0.95
        assert idea_miner.generate(mode="dry-run") == []


class TestProductionReachability:
    """idea_miner is not wired into anything. Pin that, so the next reader is not misled.

    `grep -rn idea_miner` over the repo finds this file, the module itself, and recovery
    ledgers. It is in no PERIODIC entry in runner/runner.py and no dispatch entry in
    runner/periodic.py (the scheduler's "improve" job runs improvement_miner, a different
    module). Nothing imports it. It runs only when someone types `python3 idea_miner.py`.
    """

    def test_the_module_is_importable_and_exposes_its_cli_surface(self):
        for name in ("main", "generate", "stats", "acquire", "IdeaMinerState"):
            assert hasattr(idea_miner, name), name

    def test_no_runner_module_imports_idea_miner(self):
        importers = []
        for path in Path(_RUNNER_DIR).glob("*.py"):
            if path.name in ("idea_miner.py", "test_idea_miner.py"):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "import idea_miner" in text:
                importers.append(path.name)
        assert importers == [], (
            "idea_miner just gained an importer; it is no longer dead code and its "
            "scheduling/config assumptions need a second look"
        )

    def test_the_scheduler_has_no_idea_miner_job(self):
        periodic = Path(_RUNNER_DIR, "periodic.py").read_text(encoding="utf-8", errors="replace")
        assert "idea_miner" not in periodic


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

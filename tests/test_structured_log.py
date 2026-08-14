"""Tests for runner/structured_log.py — JSON formatting and context injection."""

import json
import logging
import os
import sys
from io import StringIO

import pytest

_RUNNER_DIR = os.path.join(os.path.dirname(__file__), "..", "runner")
sys.path.insert(0, _RUNNER_DIR)

import structured_log  # noqa: E402
from structured_log import (  # noqa: E402
    DEFAULT_LEVEL,
    JsonFormatter,
    StructuredLoggerAdapter,
    child_logger,
    get_logger,
    resolve_level,
)


@pytest.fixture
def capture():
    """A logger whose JSON output is captured, isolated from other tests."""
    counter = capture.counter = getattr(capture, "counter", 0) + 1
    logger = logging.getLogger(f"structlogtest{counter}")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG)

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)

    def records():
        return [json.loads(line) for line in stream.getvalue().splitlines() if line]

    yield logger, records
    logger.handlers.clear()


class TestResolveLevel:
    def test_defaults_to_info(self):
        assert resolve_level({}) == logging.INFO
        assert DEFAULT_LEVEL == "INFO"

    def test_reads_orch_log_level(self):
        assert resolve_level({"ORCH_LOG_LEVEL": "DEBUG"}) == logging.DEBUG

    def test_orch_log_level_wins_over_log_level(self):
        env = {"ORCH_LOG_LEVEL": "ERROR", "LOG_LEVEL": "DEBUG"}
        assert resolve_level(env) == logging.ERROR

    def test_falls_back_to_log_level(self):
        assert resolve_level({"LOG_LEVEL": "WARNING"}) == logging.WARNING

    def test_is_case_insensitive_and_trims(self):
        assert resolve_level({"ORCH_LOG_LEVEL": "  warning "}) == logging.WARNING

    def test_unknown_level_falls_back_to_default(self):
        assert resolve_level({"ORCH_LOG_LEVEL": "LOUD"}) == logging.INFO

    def test_reads_real_environment_by_default(self, monkeypatch):
        monkeypatch.setenv("ORCH_LOG_LEVEL", "CRITICAL")
        assert resolve_level() == logging.CRITICAL


class TestJsonFormatting:
    def test_emits_one_json_object_per_record(self, capture):
        logger, records = capture
        logger.info("first")
        logger.warning("second")

        assert [r["message"] for r in records()] == ["first", "second"]

    def test_includes_required_fields(self, capture):
        logger, records = capture
        logger.info("hello")

        record = records()[0]
        assert set(record) >= {"timestamp", "severity", "logger", "message", "context"}
        assert record["severity"] == "INFO"
        assert record["message"] == "hello"
        assert record["context"] == {}

    def test_timestamp_is_iso8601_utc_millis(self, capture):
        logger, records = capture
        logger.info("t")

        timestamp = records()[0]["timestamp"]
        assert timestamp.endswith("Z")
        assert len(timestamp) == len("2026-08-06T20:41:03.412Z")
        # Parses back as a real datetime.
        import datetime

        datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")

    def test_severity_tracks_level(self, capture):
        logger, records = capture
        logger.debug("d")
        logger.error("e")
        logger.critical("c")

        assert [r["severity"] for r in records()] == ["DEBUG", "ERROR", "CRITICAL"]

    def test_interpolates_message_args(self, capture):
        logger, records = capture
        logger.info("claimed task %s at step %d", "abc", 3)

        assert records()[0]["message"] == "claimed task abc at step 3"

    def test_serialises_unjsonable_values_instead_of_dropping_the_line(self, capture):
        logger, records = capture

        class Opaque:
            def __repr__(self):
                return "<opaque>"

        logger.info("weird", extra={"context": {"thing": Opaque()}})

        assert records()[0]["context"]["thing"] == "<opaque>"

    def test_exception_block_carries_type_message_and_traceback(self, capture):
        logger, records = capture
        try:
            raise ValueError("bad input")
        except ValueError:
            logger.exception("failed", extra={"context": {"task_id": "t1"}})

        record = records()[0]
        assert record["exception"]["type"] == "ValueError"
        assert record["exception"]["message"] == "bad input"
        assert "ValueError: bad input" in record["exception"]["traceback"]
        assert record["context"]["task_id"] == "t1"

    def test_no_exception_key_on_normal_records(self, capture):
        logger, records = capture
        logger.info("fine")
        assert "exception" not in records()[0]


class TestContextInjection:
    def test_explicit_context_extra_lands_in_context(self, capture):
        logger, records = capture
        logger.info("m", extra={"context": {"task_id": "t1", "step": 2}})

        assert records()[0]["context"] == {"task_id": "t1", "step": 2}

    def test_loose_extra_keys_are_folded_into_context(self, capture):
        logger, records = capture
        logger.info("m", extra={"iteration": 7})

        assert records()[0]["context"]["iteration"] == 7

    def test_child_logger_binds_context_to_every_call(self, capture):
        logger, records = capture
        task_log = child_logger(logger, task_id="t1", step="decompose")

        task_log.info("start")
        task_log.warning("slow")

        for record in records():
            assert record["context"]["task_id"] == "t1"
            assert record["context"]["step"] == "decompose"

    def test_per_call_context_merges_with_bound_context(self, capture):
        logger, records = capture
        task_log = child_logger(logger, task_id="t1")

        task_log.info("iterating", extra={"context": {"iteration": 4}})

        assert records()[0]["context"] == {"task_id": "t1", "iteration": 4}

    def test_per_call_context_overrides_bound_field_without_mutating_adapter(self, capture):
        logger, records = capture
        task_log = child_logger(logger, task_id="t1", step="a")

        task_log.info("override", extra={"context": {"step": "b"}})
        task_log.info("restored")

        emitted = records()
        assert emitted[0]["context"]["step"] == "b"
        assert emitted[1]["context"]["step"] == "a"
        assert task_log.context == {"task_id": "t1", "step": "a"}

    def test_child_contexts_nest(self, capture):
        logger, records = capture
        base = child_logger(logger, service="runner")
        task = child_logger(base, task_id="t1")
        step = child_logger(task, step="decompose")

        step.info("nested")

        assert records()[0]["context"] == {
            "service": "runner",
            "task_id": "t1",
            "step": "decompose",
        }

    def test_child_of_child_does_not_leak_back_to_parent(self, capture):
        logger, records = capture
        base = child_logger(logger, service="runner")
        child_logger(base, task_id="t1")

        base.info("parent only")

        assert records()[0]["context"] == {"service": "runner"}

    def test_bind_is_equivalent_to_child_logger(self, capture):
        logger, records = capture
        bound = child_logger(logger, service="runner").bind(task_id="t1")

        bound.info("bound")

        assert records()[0]["context"] == {"service": "runner", "task_id": "t1"}

    def test_context_property_returns_a_copy(self, capture):
        logger, _ = capture
        task_log = child_logger(logger, task_id="t1")

        task_log.context["task_id"] = "mutated"

        assert task_log.context == {"task_id": "t1"}

    def test_adapter_forwards_exceptions_with_context(self, capture):
        logger, records = capture
        task_log = child_logger(logger, task_id="t1")

        try:
            raise RuntimeError("boom")
        except RuntimeError:
            task_log.exception("failed")

        record = records()[0]
        assert record["exception"]["type"] == "RuntimeError"
        assert record["context"]["task_id"] == "t1"


class TestGetLogger:
    def test_returns_plain_logger_without_context(self):
        logger = get_logger("structlog_getlogger_plain")
        assert isinstance(logger, logging.Logger)
        assert not isinstance(logger, StructuredLoggerAdapter)

    def test_returns_adapter_when_context_supplied(self):
        logger = get_logger("structlog_getlogger_ctx", service="runner")
        assert isinstance(logger, StructuredLoggerAdapter)
        assert logger.context == {"service": "runner"}

    def test_attaches_exactly_one_json_handler_per_tree(self):
        get_logger("structlog_tree_a.one")
        get_logger("structlog_tree_a.two")
        get_logger("structlog_tree_a.three")

        root = logging.getLogger("structlog_tree_a")
        json_handlers = [h for h in root.handlers if isinstance(h.formatter, JsonFormatter)]
        assert len(json_handlers) == 1

    def test_does_not_touch_the_root_logger(self):
        before = list(logging.getLogger().handlers)
        get_logger("structlog_isolated_tree")
        assert list(logging.getLogger().handlers) == before

    def test_output_is_parseable_json_end_to_end(self, monkeypatch, capsys):
        monkeypatch.setattr(structured_log, "_configured_roots", set())
        monkeypatch.setenv("ORCH_LOG_LEVEL", "INFO")

        logger = get_logger("structlog_e2e", service="runner")
        logger.info("end to end", extra={"context": {"task_id": "t9"}})

        line = capsys.readouterr().err.strip().splitlines()[-1]
        record = json.loads(line)
        assert record["message"] == "end to end"
        assert record["context"] == {"service": "runner", "task_id": "t9"}

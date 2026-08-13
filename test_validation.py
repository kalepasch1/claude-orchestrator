#!/usr/bin/env python3
"""Exit-code contract for the canary validator, asserted through the logs.

`canary.main()` is what the scheduled workflow gates on: exit 0 means the marker was
present, exit 1 means it was not. Both branches also emit a log line, and the log is the
only thing an operator reads at 05:00 — so the code and the message are tested together.
A run that exits 1 while logging "validation passed" would be worse than either failure
alone, because the exit code and the log would disagree about what happened.

`caplog` is used rather than capturing stderr: the module logs through a named logger, so
whichever handler happens to own the stream is irrelevant to what was actually recorded.

Run: pytest test_validation.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import canary


def test_marker_present_exits_zero_and_logs_success(caplog):
    """The healthy path: marker found -> exit 0, and the log says so."""
    with caplog.at_level(logging.INFO, logger=canary.logger.name):
        exit_code = canary.main(["this response is a canary"])

    assert exit_code == 0
    assert any("validation passed" in record.message for record in caplog.records), \
        f"expected a success line, got {[r.message for r in caplog.records]}"
    # The two branches must never both appear — that would mean the verdict was ambiguous.
    assert not any("validation failed" in record.message for record in caplog.records)


def test_marker_absent_exits_one_and_logs_failure(caplog):
    """The gating path: no marker -> exit 1, logged at ERROR.

    Severity matters as much as the text. A failure logged at INFO is invisible to any
    log-level alert, which is how a dead canary goes unnoticed while the workflow
    dutifully reports red.
    """
    with caplog.at_level(logging.INFO, logger=canary.logger.name):
        exit_code = canary.main(["gemini returned nothing useful"])

    assert exit_code == 1
    failures = [r for r in caplog.records if "validation failed" in r.message]
    assert failures, f"expected a failure line, got {[r.message for r in caplog.records]}"
    assert failures[0].levelno >= logging.ERROR, \
        f"failure logged at {failures[0].levelname}; must be ERROR or higher"

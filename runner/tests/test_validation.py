#!/usr/bin/env python3
"""Exit-code contract for the canary validator, asserted through the logs.

`canary.main()` is what the scheduled workflow gates on: exit 0 means the marker was
present, exit 1 means it was not. Both branches also emit a log line, and the log is the
only thing an operator reads at 05:00 — so the code and the message are tested together.
A run that exits 1 while logging "validation passed" would be worse than either failure
alone, because the exit code and the log would disagree about what happened.

`caplog` is used rather than capturing stderr: the module logs through a named logger, so
whichever handler happens to own the stream is irrelevant to what was actually recorded.

Run: pytest runner/tests/test_validation.py
"""
import importlib.util
import logging
import os
import sys

# Moved from the repo root into runner/tests/ (write_guard: tests do not live
# at the root). The repo root is now two directories up, and that is what these
# tests resolve against — not the directory the file happens to sit in.
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _REPO)

# TWO FILES, ONE NAME. There is a canary.py at the repo root and another at
# runner/canary.py, and half this suite puts <repo> on sys.path while the other
# half puts <repo>/runner there — so whichever is imported FIRST in a session wins
# the bare name `canary` for every later importer. This file used to do
# `import canary`; alone it got the root module and passed, but
# test_canary_cli_exit_code.py sorts earlier and binds sys.modules["canary"] to
# runner/canary.py, whose main() is a different program. Both tests here then
# failed in-suite and passed on their own.
#
# Loading the file we actually mean BY PATH is order-independent, and registering
# it under a private name means this file neither depends on nor contributes to
# the collision. Same fix, same reasoning, as
# runner/tests/test_canary_gemini_response_parse.py.
_spec = importlib.util.spec_from_file_location(
    "_repo_root_canary_for_validation", os.path.join(_REPO, "canary.py"))
canary = importlib.util.module_from_spec(_spec)
sys.modules["_repo_root_canary_for_validation"] = canary
_spec.loader.exec_module(canary)


#: The exact verdict lines canary.main() emits. Named once so a future
#: rewording fails in one place with an obvious message, rather than in two
#: tests that look like the validator broke.
_VERDICT_OK = "Validation result: success"
_VERDICT_BAD = "Validation result: failure"


def test_marker_present_exits_zero_and_logs_success(caplog):
    """The healthy path: marker found -> exit 0, and the log says so."""
    with caplog.at_level(logging.INFO, logger=canary.logger.name):
        exit_code = canary.main(["this response is a canary"])

    assert exit_code == 0
    # The verdict line is "Validation result: <success|failure>". This used to look
    # for "validation passed"/"validation failed", wording canary.py stopped using
    # on 2026-08-24 — two hours after this test was last touched. The contract the
    # docstring describes never changed; only the sentence did.
    assert any(_VERDICT_OK in record.message for record in caplog.records), \
        f"expected a success line, got {[r.message for r in caplog.records]}"
    # The two branches must never both appear — that would mean the verdict was ambiguous.
    assert not any(_VERDICT_BAD in record.message for record in caplog.records)


def test_marker_absent_exits_one_and_logs_failure(caplog):
    """The gating path: no marker -> exit 1, logged at ERROR.

    Severity matters as much as the text. A failure logged at INFO is invisible to any
    log-level alert, which is how a dead canary goes unnoticed while the workflow
    dutifully reports red.
    """
    with caplog.at_level(logging.INFO, logger=canary.logger.name):
        exit_code = canary.main(["gemini returned nothing useful"])

    assert exit_code == 1
    failures = [r for r in caplog.records if _VERDICT_BAD in r.message]
    assert failures, f"expected a failure line, got {[r.message for r in caplog.records]}"
    assert failures[0].levelno >= logging.ERROR, \
        f"failure logged at {failures[0].levelname}; must be ERROR or higher"

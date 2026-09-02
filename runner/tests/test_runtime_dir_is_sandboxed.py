#!/usr/bin/env python3
"""No test may write into the repo's real .runtime/.

The guard modules resolve their log path from CLAUDE_ORCH_HOME. Until 2026-08-30
nothing set it under pytest, so every guard test appended its fixtures to the
production JSONL that an operator reads to see what the fleet did — rows naming
/tmp repos, branch "topic", project "test". This pins the sandbox so the pollution
cannot come back the next time a guard grows a test.
"""
import json
import os
import sys

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(RUNNER)
LIVE_RUNTIME = os.path.join(REPO, ".runtime")

sys.path.insert(0, RUNNER)


def test_claude_orch_home_points_somewhere_temporary():
    home = os.environ.get("CLAUDE_ORCH_HOME")
    assert home, "the session fixture must set CLAUDE_ORCH_HOME"
    assert os.path.realpath(home) != os.path.realpath(LIVE_RUNTIME)
    assert "orch-runtime" in home, "expected the pytest tmp sandbox, got %r" % home


def test_a_guard_logging_an_event_writes_into_the_sandbox_not_the_repo():
    import automerge_discard_guard as guard

    before = _live_log_size("automerge-discard-guard.log")
    guard._log_event({"event": "gate", "repo": "/tmp/sandbox-probe",
                      "branch": "topic", "discards": 0})
    after = _live_log_size("automerge-discard-guard.log")
    assert after == before, "the guard wrote into the repo's live .runtime/logs"

    written = os.path.join(os.environ["CLAUDE_ORCH_HOME"], "logs",
                           "automerge-discard-guard.log")
    assert os.path.exists(written), "the event went nowhere at all"
    rows = [json.loads(line) for line in open(written) if line.strip()]
    assert any(r.get("repo") == "/tmp/sandbox-probe" for r in rows)


def test_without_the_fixture_the_default_really_is_the_live_repo_dir():
    """Proves the fixture is load-bearing, without writing a byte to prove it.

    The mutation check for this one cannot be "delete the fixture and watch the
    logs grow" — that pollutes the very files the fix protects. Instead, assert
    the unset default resolves to the repo's own .runtime/, which is what every
    guard test was silently using before.
    """
    import automerge_discard_guard as guard

    saved = os.environ.pop("CLAUDE_ORCH_HOME", None)
    try:
        assert os.path.realpath(guard._home()) == os.path.realpath(LIVE_RUNTIME)
    finally:
        if saved is not None:
            os.environ["CLAUDE_ORCH_HOME"] = saved


def _live_log_size(name):
    path = os.path.join(LIVE_RUNTIME, "logs", name)
    return os.path.getsize(path) if os.path.exists(path) else 0

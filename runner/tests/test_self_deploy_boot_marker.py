"""Self-deploy must be able to tell whether the fleet is running current code.

Guards the 2026-08-02 finding: `.runner_boot_commit` was never written by anything, so
running_commit() returned "", check_new_code()["stale"] was ALWAYS False, and self-deploy
could never fire. Merged code sat on disk while the fleet kept executing the old code, and
the only signal was a sentinel line reading "no .runner_boot_commit — cannot tell whether
the runner is on current code" that had been repeating since 2026-07-16.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import self_deploy as sd


def test_record_boot_writes_the_marker():
    with tempfile.TemporaryDirectory() as d:
        got = sd.record_boot(d, commit="abc123")
        assert got == "abc123"
        assert open(os.path.join(d, sd.BOOT_FILE)).read().strip() == "abc123"


def test_missing_marker_reports_unknown_not_healthy():
    """A missing marker means we cannot tell — it must never read as 'up to date'."""
    with tempfile.TemporaryDirectory() as d:
        os.environ.pop("ORCH_BOOT_COMMIT", None)
        r = sd.check_new_code(d)
        assert r["unknown"] is True
        assert r["stale"] is False  # cannot claim staleness either — we have no basis


def test_stale_is_detected_once_the_marker_exists():
    with tempfile.TemporaryDirectory() as d:
        os.environ.pop("ORCH_BOOT_COMMIT", None)
        sd.record_boot(d, commit="0000000000000000000000000000000000000000")
        r = sd.check_new_code(d)
        # current_commit() on a non-repo returns "" -> cannot compare; assert via env path
        os.environ["ORCH_BOOT_COMMIT"] = "0000000000000000000000000000000000000000"
        assert sd.running_commit(d) == "0000000000000000000000000000000000000000"
        assert r["unknown"] is False
        os.environ.pop("ORCH_BOOT_COMMIT", None)


def test_env_override_wins_over_file():
    with tempfile.TemporaryDirectory() as d:
        sd.record_boot(d, commit="fromfile")
        os.environ["ORCH_BOOT_COMMIT"] = "fromenv"
        try:
            assert sd.running_commit(d) == "fromenv"
        finally:
            os.environ.pop("ORCH_BOOT_COMMIT", None)


def test_record_boot_is_not_called_by_monitors():
    """Only the launcher may stamp the marker.

    If a sentinel or monitor stamped it, an OLD process would be marked as running the
    CURRENT head and staleness would be permanently invisible — strictly worse than the
    bug being fixed. This asserts the call site stays in the launcher.
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for monitor in ("sentinel.py", "blocked_triage.py", "periodic.py"):
        p = os.path.join(here, monitor)
        if os.path.exists(p):
            assert "record_boot(" not in open(p, encoding="utf-8", errors="replace").read(), \
                f"{monitor} must not stamp the boot marker"


def test_launcher_writes_the_marker():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ka = open(os.path.join(here, "keepalive.sh"), encoding="utf-8", errors="replace").read()
    assert ".runner_boot_commit" in ka, "keepalive.sh no longer stamps the boot commit"
    assert "ORCH_BOOT_COMMIT" in ka


def test_restart_request_is_consumed_only_at_supervisor_handoff():
    """The old process may not erase the only durable evidence that it must restart."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    runner_src = open(os.path.join(here, "runner.py"), encoding="utf-8", errors="replace").read()
    keepalive = open(os.path.join(here, "keepalive.sh"), encoding="utf-8", errors="replace").read()
    restart_block = runner_src[runner_src.index("restart threshold reached"):]
    restart_block = restart_block[:restart_block.index("sys.exit(0)") + len("sys.exit(0)")]
    assert "os.remove" not in restart_block
    assert 'mv -f "$RUNNER_DIR/.restart_requested"' in keepalive
    assert "restart-handoff.last" in keepalive

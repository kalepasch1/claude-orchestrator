"""A swarm bot that is not on the schedule is a bot that never runs.

Bots #3 (canary_triage) and #5 (self_deploy_watchdog) landed pure, injectable and
completely unreferenced: nothing called them, so a red self-deploy canary — which holds
the running version and therefore blocks EVERY merged change from deploying — was never
triaged automatically. These tests pin the two halves of "wired": present in
periodic.JOBS, and present in runner.py's scheduler table.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import periodic  # noqa: E402
import swarm_enqueue  # noqa: E402

_RUNNER_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "runner.py")

VERDICT = """
self_deploy: BLOCKED — tests failing; filing approvals card
{
  "deployed": false,
  "reason": "canary_failed",
  "running_commit": "aaaaaaaaaaaa",
  "head_commit": "bbbbbbbbbbbbcccc"
}
"""


@pytest.mark.parametrize("job", ["markersentinel", "canarywatch"])
def test_job_is_registered_in_periodic(job):
    assert job in periodic.JOBS
    assert callable(periodic.JOBS[job])


@pytest.mark.parametrize("job", ["markersentinel", "canarywatch"])
def test_job_is_on_the_runner_schedule(job):
    """periodic.JOBS alone is not enough — runner.py's table is what actually fires it."""
    source = open(_RUNNER_PY, encoding="utf-8").read()
    assert f'"{job}"' in source, f"{job} is in JOBS but nothing schedules it"


def _capture(monkeypatch, log_path):
    filed = []
    monkeypatch.setattr(periodic, "SELF_DEPLOY_LOG", str(log_path))
    monkeypatch.setattr(swarm_enqueue, "enqueue", lambda rec: filed.append(rec))
    return filed


def test_canarywatch_triages_a_failed_canary_and_files_remediation(tmp_path, monkeypatch):
    log = tmp_path / "self-deploy.log"
    log.write_text("ModuleNotFoundError: No module named 'nope'\n" + VERDICT)
    filed = _capture(monkeypatch, log)

    res = periodic.run_canarywatch()

    assert res["action"] == "triaged"
    assert res["class"] == "missing-module"
    assert res["filed"] is True
    assert len(filed) == 1
    assert filed[0]["kind"] == "remediation"


def test_canarywatch_is_quiet_when_the_last_verdict_is_healthy(tmp_path, monkeypatch):
    log = tmp_path / "self-deploy.log"
    log.write_text(VERDICT + '\n{\n  "reason": "up-to-date"\n}\n')
    filed = _capture(monkeypatch, log)

    res = periodic.run_canarywatch()

    assert res["action"] == "none"
    assert filed == []


def test_canarywatch_reads_only_the_tail_of_a_huge_log(tmp_path, monkeypatch):
    """The real log is 3MB+ and append-only; only the LAST verdict matters."""
    log = tmp_path / "self-deploy.log"
    log.write_text(("noise line\n" * 200_000)
                   + "ModuleNotFoundError: No module named 'nope'\n" + VERDICT)
    assert log.stat().st_size > periodic.CANARYWATCH_TAIL_BYTES
    filed = _capture(monkeypatch, log)

    res = periodic.run_canarywatch()

    assert res["action"] == "triaged"
    assert len(filed) == 1


def test_a_missing_log_is_reported_not_raised(tmp_path, monkeypatch):
    filed = _capture(monkeypatch, tmp_path / "does-not-exist.log")

    assert periodic.run_canarywatch() is None
    assert filed == []

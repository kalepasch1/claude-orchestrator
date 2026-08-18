"""Process-fixture tests for single-owner supervisor semantics.

The five cases the brief names — missing launchd service, duplicate supervisor,
stale lock, maintenance appearing after startup, clean handoff — plus the one that
matters most in practice: a coder subprocess must survive an ownership dispute.

Every process, lock and launchd fact is a fixture. No machine needs to be in any of
these states for the tests to mean something.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from supervisor_ownership import (  # noqa: E402
    CANONICAL_LABEL,
    LaunchdService,
    LockState,
    OwnershipObservation,
    ProcessInfo,
    assess_ownership,
    build_incident,
    may_restart,
    parse_launchctl_list,
    parse_plist_program_arguments,
    plan_takeover,
    service_points_at_repo,
)

REPO = "/Users/kpasch/Documents/beethoven/claude-orchestrator"


def service(**over):
    base = dict(
        label=CANONICAL_LABEL,
        program_arguments=(f"{REPO}/.app/Contents/MacOS/ClaudeRunner",),
        loaded=True,
        pid=4242,
    )
    base.update(over)
    return LaunchdService(**base)


def lock(**over):
    base = dict(path=f"{REPO}/.runtime/runner.lock", exists=True, holder_pid=100, holder_alive=True)
    base.update(over)
    return LockState(**base)


def observation(**over):
    base = dict(
        service=service(),
        repo_path=REPO,
        supervisor_lock=lock(path=f"{REPO}/.runtime/keepalive.lock", holder_pid=50),
        runner_lock=lock(holder_pid=100),
        keepalive_processes=(ProcessInfo(50, "zsh keepalive.sh"),),
        runner_processes=(ProcessInfo(100, "python3 runner.py"),),
        coder_processes=(),
        maintenance_lock_present=False,
    )
    base.update(over)
    return OwnershipObservation(**base)


# --------------------------------------------------------------------------- #
# The healthy baseline
# --------------------------------------------------------------------------- #


def test_healthy_state_is_owned():
    verdict = assess_ownership(observation())
    assert verdict.owned is True
    assert verdict.incident is False
    assert verdict.findings == ()


def test_healthy_state_permits_restart():
    assert may_restart(observation()).allowed is True


# --------------------------------------------------------------------------- #
# Case 1 — missing launchd service
# --------------------------------------------------------------------------- #


def test_missing_launchd_service_is_an_incident():
    verdict = assess_ownership(observation(service=None))
    assert verdict.incident is True
    codes = [f.code for f in verdict.findings]
    assert "launchd_service_missing" in codes


def test_a_runner_with_no_service_is_flagged_unowned():
    # "the launchd label disappeared while a runner later started outside the
    # expected service ownership path" — the exact state in the brief.
    verdict = assess_ownership(observation(service=None))
    assert "unowned_runner" in [f.code for f in verdict.findings]


def test_missing_service_blocks_restart_rather_than_adding_a_process():
    decision = may_restart(observation(service=None))
    assert decision.allowed is False
    assert "nobody can currently reason about" in decision.reason


def test_label_drift_is_an_incident():
    verdict = assess_ownership(observation(service=service(label="com.someone.else.runner")))
    assert "launchd_label_drift" in [f.code for f in verdict.findings]


def test_path_drift_is_an_incident():
    drifted = service(program_arguments=("/tmp/some-other-checkout/run.sh",))
    verdict = assess_ownership(observation(service=drifted))
    assert "launchd_path_drift" in [f.code for f in verdict.findings]


def test_service_registered_but_unloaded_is_an_incident():
    verdict = assess_ownership(observation(service=service(loaded=False)))
    assert "launchd_service_unloaded" in [f.code for f in verdict.findings]


def test_path_match_tolerates_the_app_wrapper_indirection():
    # The plist launches __APP_DIR__/Contents/MacOS/ClaudeRunner rather than naming
    # the repo directly. Demanding an exact argv match would report drift on a
    # correctly-registered service and train everyone to ignore the check.
    assert service_points_at_repo(service(), REPO) is True
    assert service_points_at_repo(service(program_arguments=("/elsewhere/x",)), REPO) is False


# --------------------------------------------------------------------------- #
# Case 2 — duplicate supervisor
# --------------------------------------------------------------------------- #


def test_duplicate_supervisor_is_an_incident():
    obs = observation(
        keepalive_processes=(ProcessInfo(50, "zsh keepalive.sh"), ProcessInfo(51, "zsh keepalive.sh")),
    )
    verdict = assess_ownership(obs)
    assert verdict.incident is True
    finding = next(f for f in verdict.findings if f.code == "duplicate_supervisor")
    assert "restart/SIGTERM loop" in finding.detail


def test_duplicate_supervisor_blocks_restart():
    obs = observation(
        keepalive_processes=(ProcessInfo(50, "keepalive"), ProcessInfo(51, "keepalive")),
    )
    assert may_restart(obs).allowed is False


def test_no_supervisor_is_a_warning_not_an_incident():
    # Nothing is watching, which is bad — but it is not the ambiguous multi-owner
    # state that must block a restart.
    verdict = assess_ownership(observation(keepalive_processes=()))
    assert verdict.incident is False
    assert "no_supervisor" in [f.code for f in verdict.findings]


def test_duplicate_runner_is_an_incident():
    obs = observation(
        runner_processes=(ProcessInfo(100, "runner.py"), ProcessInfo(101, "runner.py")),
    )
    assert "duplicate_runner" in [f.code for f in assess_ownership(obs).findings]


# --------------------------------------------------------------------------- #
# Case 3 — stale lock
# --------------------------------------------------------------------------- #


def test_stale_supervisor_lock_is_reported():
    obs = observation(
        supervisor_lock=lock(path="keepalive.lock", holder_pid=999, holder_alive=False),
    )
    finding = next(
        f for f in assess_ownership(obs).findings if f.code == "stale_supervisor_lock"
    )
    assert "nothing will clear it on its own" in finding.detail


def test_stale_runner_lock_is_reported():
    obs = observation(runner_lock=lock(holder_pid=999, holder_alive=False))
    assert "stale_runner_lock" in [f.code for f in assess_ownership(obs).findings]


def test_lock_held_by_a_live_process_that_is_not_a_runner_is_an_incident():
    # Something else is holding it — which a liveness check alone would call fine.
    obs = observation(runner_lock=lock(holder_pid=777, holder_alive=True))
    verdict = assess_ownership(obs)
    assert verdict.incident is True
    assert "runner_lock_holder_is_not_a_runner" in [f.code for f in verdict.findings]


def test_a_stale_lock_alone_does_not_block_a_restart():
    # A stale lock is exactly the condition a restart is supposed to resolve.
    obs = observation(runner_lock=lock(holder_pid=999, holder_alive=False))
    assert may_restart(obs).allowed is True


# --------------------------------------------------------------------------- #
# Case 4 — maintenance appearing AFTER startup
# --------------------------------------------------------------------------- #


def test_maintenance_present_at_observation_blocks_restart():
    assert may_restart(observation(maintenance_lock_present=True)).allowed is False


def test_maintenance_appearing_after_startup_still_blocks():
    # The fence is re-read at DECISION time. A fence read once at boot is a fence
    # that does not exist: maintenance is declared during an incident, which is
    # when the supervisor is most likely to be restarting things.
    obs = observation(maintenance_lock_present=False)  # clean when observed
    decision = may_restart(obs, maintenance_check=lambda: True)  # declared since
    assert decision.allowed is False
    assert "Re-checked at decision time" in decision.reason


def test_live_check_overrides_a_stale_observation_in_both_directions():
    obs = observation(maintenance_lock_present=True)
    assert may_restart(obs, maintenance_check=lambda: False).allowed is True


def test_maintenance_beats_ownership_checks():
    # Ordering matters: a maintenance fence during an ownership incident must
    # report the fence, not the incident, or an operator fixes the wrong thing.
    obs = observation(service=None, maintenance_lock_present=True)
    assert "maintenance fence" in may_restart(obs).reason


# --------------------------------------------------------------------------- #
# Case 5 — clean handoff
# --------------------------------------------------------------------------- #


def test_clean_handoff_terminates_only_the_competing_supervisor():
    obs = observation(
        keepalive_processes=(ProcessInfo(50, "keepalive"), ProcessInfo(51, "keepalive")),
    )
    plan = plan_takeover(obs, self_pid=50)
    assert plan.proceed is True
    assert plan.terminate == (51,)
    # The runner is the thing being supervised, not the thing being argued over.
    assert 100 in [pid for pid, _ in plan.protected]


def test_sole_supervisor_needs_no_takeover():
    plan = plan_takeover(observation(), self_pid=50)
    assert plan.proceed is True
    assert plan.terminate == ()


def test_an_active_coder_subprocess_is_NEVER_terminated():
    obs = observation(
        keepalive_processes=(ProcessInfo(50, "keepalive"), ProcessInfo(51, "keepalive")),
        coder_processes=(ProcessInfo(900, "claude --agentic"),),
    )
    plan = plan_takeover(obs, self_pid=50)
    assert plan.proceed is False
    assert plan.terminate == ()
    assert 900 in [pid for pid, _ in plan.protected]
    assert "costs more than the dispute" in plan.reason


def test_takeover_waits_for_the_coder_even_with_a_duplicate_supervisor():
    # The duplicate is a real problem and is still reported — it is just not worth
    # destroying in-flight work to fix this second.
    obs = observation(
        keepalive_processes=(ProcessInfo(50, "keepalive"), ProcessInfo(51, "keepalive")),
        coder_processes=(ProcessInfo(900, "coder"),),
    )
    plan = plan_takeover(obs, self_pid=50)
    assert plan.proceed is False
    assert "duplicate_supervisor" in [f.code for f in plan.findings]


# --------------------------------------------------------------------------- #
# Health incidents
# --------------------------------------------------------------------------- #


def test_incident_emitted_when_the_service_is_missing():
    incident = build_incident(assess_ownership(observation(service=None)), "host-a")
    assert incident is not None
    assert incident.status == "ownership_incident"
    assert "launchd_service_missing" in incident.codes


def test_incident_emitted_on_drift_even_though_everything_looks_fine():
    # Drift is the harder case: a runner is running, a service is registered, and
    # it points at the wrong checkout.
    drifted = service(program_arguments=("/tmp/other/run.sh",))
    incident = build_incident(assess_ownership(observation(service=drifted)), "host-a")
    assert incident is not None
    assert "launchd_path_drift" in incident.codes


def test_no_incident_when_ownership_is_clean():
    assert build_incident(assess_ownership(observation()), "host-a") is None


def test_warnings_alone_do_not_raise_an_incident():
    verdict = assess_ownership(observation(runner_lock=lock(holder_pid=9, holder_alive=False)))
    assert verdict.severity == "warning"
    assert build_incident(verdict, "host-a") is None


# --------------------------------------------------------------------------- #
# Parsers
# --------------------------------------------------------------------------- #


def test_parse_launchctl_list_finds_the_canonical_label():
    out = "PID\tStatus\tLabel\n4242\t0\tcom.orchestrator.runner\n-\t0\tcom.other.thing\n"
    svc = parse_launchctl_list(out)
    assert svc is not None
    assert svc.pid == 4242


def test_parse_launchctl_list_returns_none_when_absent():
    # Which the caller must treat as the incident it is, not as "probably fine".
    assert parse_launchctl_list("PID\tStatus\tLabel\n-\t0\tcom.other.thing\n") is None


def test_parse_launchctl_handles_an_unstarted_service():
    svc = parse_launchctl_list("-\t0\tcom.orchestrator.runner\n")
    assert svc is not None
    assert svc.pid is None


def test_parse_plist_program_arguments():
    xml = """
    <key>ProgramArguments</key>
    <array>
      <string>/repo/.app/Contents/MacOS/ClaudeRunner</string>
      <string>--flag</string>
    </array>
    """
    assert parse_plist_program_arguments(xml) == (
        "/repo/.app/Contents/MacOS/ClaudeRunner",
        "--flag",
    )


def test_parse_plist_returns_empty_when_absent():
    assert parse_plist_program_arguments("<plist></plist>") == ()


# --------------------------------------------------------------------------- #
# The gap this closes
# --------------------------------------------------------------------------- #


def test_supervisor_restart_path_now_has_a_fence_available():
    """keepalive.sh checks the maintenance fence; supervisor.py's _restart did not.

    That asymmetry is the defect: the fence held against one path into a restart
    and was silently absent from the other. This module supplies the missing gate,
    and this test pins the property that made it necessary.
    """
    obs = observation(maintenance_lock_present=True)
    assert may_restart(obs).allowed is False
    assert may_restart(observation()).allowed is True


# --------------------------------------------------------------------------- #
# The wiring — an engine with no caller is not done
# --------------------------------------------------------------------------- #


def test_supervisor_module_actually_calls_the_gate():
    """supervisor.py must consult the gate, not merely have it available."""
    here = os.path.dirname(__file__)
    source = open(os.path.join(here, "..", "supervisor.py")).read()
    assert "from supervisor_ownership import" in source
    assert "may_restart(" in source
    assert "build_incident(" in source
    # And the fence must be re-read at decision time rather than captured once.
    assert "maintenance_check=_maintenance_present" in source


def test_supervisor_returns_without_starting_anything_when_withheld():
    here = os.path.dirname(__file__)
    source = open(os.path.join(here, "..", "supervisor.py")).read()
    gate = source[source.index("def _restart("):]
    withheld = gate.index("restart withheld")
    popen = gate.index("subprocess.Popen")
    # The early return must come BEFORE the spawn, or the gate reports and proceeds.
    assert withheld < popen
    assert "return" in gate[withheld:popen]

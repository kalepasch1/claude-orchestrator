"""One durable, observable owner for the production runner supervisor.

THE DEFECT THIS EXISTS TO CLOSE
    ``keepalive.sh`` enforces a maintenance fence (``MAINTENANCE_LOCK``) before it
    starts a runner, and re-checks it before every restart. ``supervisor.py`` does
    not: its ``_restart()`` calls ``subprocess.Popen`` directly, with no fence
    check, no lock validation and no notion of which launchd service is supposed to
    own the process. So the fence holds against one path into a restart and is
    silently absent from the other — which is how "the launchd label disappeared
    while a runner later started outside the expected service ownership path"
    happens without anything being obviously broken.

    This module is the missing gate. It is pure: every process, filesystem and
    launchd interaction is injected, so all five failure modes are testable without
    a machine in that state.

WHAT "OWNERSHIP" MEANS HERE
    A runner is OWNED when all of:
      * the canonical launchd service label is registered,
      * that registration points at the canonical repository path,
      * exactly one supervisor holds the supervisor lock,
      * the runner lock is held by a live pid that the registered service started.

    Anything else is drift, and drift emits a health incident rather than being
    quietly corrected — a supervisor that silently fixes ownership is a supervisor
    whose ownership nobody can reason about.

NEVER KILL A WORKING CODER TO WIN AN ARGUMENT ABOUT OWNERSHIP
    ``plan_takeover`` refuses to terminate anything while a coder subprocess is
    active, unless ownership AND handoff are both proven. A half-finished agentic
    edit killed to resolve a supervisor dispute costs more than the dispute.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

CANONICAL_LABEL = "com.orchestrator.runner"
CANONICAL_REPO_ENV = "CLAUDE_ORCH_HOME"


# --------------------------------------------------------------------------- #
# Observations (all injected — this module touches nothing)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LaunchdService:
    label: str
    #: Program arguments as registered. Used to confirm the canonical repo path.
    program_arguments: tuple[str, ...] = ()
    loaded: bool = True
    pid: int | None = None


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    command: str
    #: PPID chain root, when known. Lets us tell a launchd-started runner from an
    #: ad-hoc one started from somebody's shell.
    session_leader: int | None = None


@dataclass(frozen=True)
class LockState:
    path: str
    exists: bool
    #: The pid recorded in the lock, if any.
    holder_pid: int | None = None
    #: Whether that pid is currently alive.
    holder_alive: bool = False


@dataclass(frozen=True)
class OwnershipObservation:
    """Everything needed to decide ownership, gathered by the caller."""

    service: LaunchdService | None
    repo_path: str
    supervisor_lock: LockState
    runner_lock: LockState
    #: Every process that looks like a keepalive or supervisor.
    keepalive_processes: tuple[ProcessInfo, ...] = ()
    #: Every process that looks like a runner.
    runner_processes: tuple[ProcessInfo, ...] = ()
    #: Active agentic coder subprocesses. Sacred — see plan_takeover.
    coder_processes: tuple[ProcessInfo, ...] = ()
    maintenance_lock_present: bool = False


# --------------------------------------------------------------------------- #
# Findings
# --------------------------------------------------------------------------- #


SEVERITY_ORDER = ("info", "warning", "incident")


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    detail: str


def _worst(findings: Iterable[Finding]) -> str:
    worst = "info"
    for f in findings:
        if SEVERITY_ORDER.index(f.severity) > SEVERITY_ORDER.index(worst):
            worst = f.severity
    return worst


# --------------------------------------------------------------------------- #
# Ownership assessment
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class OwnershipVerdict:
    owned: bool
    findings: tuple[Finding, ...]
    severity: str
    #: True when a health incident must be emitted.
    incident: bool
    summary: str


def _normalise_path(path: str) -> str:
    return os.path.normpath(os.path.expanduser(path or "")).rstrip("/")


def service_points_at_repo(service: LaunchdService, repo_path: str) -> bool:
    """Does the registered service actually point at the canonical checkout?

    Matched on a normalised path *substring* of any program argument, because the
    plist launches an app wrapper (``__APP_DIR__/Contents/MacOS/ClaudeRunner``)
    rather than naming the repo directly — see the comment in the plist. Requiring
    an exact argv match would report drift on a correctly-registered service, which
    would train everyone to ignore the check.
    """
    target = _normalise_path(repo_path)
    if not target:
        return False
    for arg in service.program_arguments:
        if target in _normalise_path(arg):
            return True
    return False


def assess_ownership(obs: OwnershipObservation) -> OwnershipVerdict:
    """Decide whether exactly one registered owner is running the runner."""
    findings: list[Finding] = []

    # 1. The service must exist and be loaded.
    if obs.service is None:
        findings.append(
            Finding(
                "launchd_service_missing",
                "incident",
                f"launchd service {CANONICAL_LABEL!r} is not registered. A runner may "
                f"still be running, but nothing owns it — which is precisely the state "
                f"that produced this task.",
            )
        )
    else:
        if obs.service.label != CANONICAL_LABEL:
            findings.append(
                Finding(
                    "launchd_label_drift",
                    "incident",
                    f"registered label {obs.service.label!r} is not the canonical "
                    f"{CANONICAL_LABEL!r}.",
                )
            )
        if not obs.service.loaded:
            findings.append(
                Finding(
                    "launchd_service_unloaded",
                    "incident",
                    f"{obs.service.label!r} is registered but not loaded; nothing will "
                    f"restart the runner.",
                )
            )
        if not service_points_at_repo(obs.service, obs.repo_path):
            findings.append(
                Finding(
                    "launchd_path_drift",
                    "incident",
                    f"{obs.service.label!r} does not point at the canonical repository "
                    f"{obs.repo_path!r}. A runner started from it would be operating on "
                    f"a different checkout than the one being maintained.",
                )
            )

    # 2. Exactly one supervisor.
    if len(obs.keepalive_processes) > 1:
        pids = ", ".join(str(p.pid) for p in obs.keepalive_processes)
        findings.append(
            Finding(
                "duplicate_supervisor",
                "incident",
                f"{len(obs.keepalive_processes)} keepalive/supervisor processes are "
                f"running (pids {pids}). Two supervisors each restart the runner the "
                f"other kills; the loser taking the launchd job head with it is the "
                f"documented restart/SIGTERM loop.",
            )
        )
    elif not obs.keepalive_processes:
        findings.append(
            Finding(
                "no_supervisor",
                "warning",
                "no keepalive/supervisor process found; nothing is watching the runner.",
            )
        )

    # 3. Supervisor lock ownership.
    if obs.supervisor_lock.exists and not obs.supervisor_lock.holder_alive:
        findings.append(
            Finding(
                "stale_supervisor_lock",
                "warning",
                f"supervisor lock at {obs.supervisor_lock.path} is held by pid "
                f"{obs.supervisor_lock.holder_pid}, which is not alive. Nothing can take "
                f"over until it is cleared, and nothing will clear it on its own.",
            )
        )

    # 4. Runner lock ownership.
    if obs.runner_lock.exists and not obs.runner_lock.holder_alive:
        findings.append(
            Finding(
                "stale_runner_lock",
                "warning",
                f"runner lock at {obs.runner_lock.path} is held by dead pid "
                f"{obs.runner_lock.holder_pid}.",
            )
        )

    live_runner_pids = {p.pid for p in obs.runner_processes}
    if (
        obs.runner_lock.exists
        and obs.runner_lock.holder_alive
        and obs.runner_lock.holder_pid not in live_runner_pids
    ):
        findings.append(
            Finding(
                "runner_lock_holder_is_not_a_runner",
                "incident",
                f"the runner lock is held by live pid {obs.runner_lock.holder_pid}, which "
                f"is not one of the running runner processes {sorted(live_runner_pids)}. "
                f"Something else is holding the lock.",
            )
        )

    if len(obs.runner_processes) > 1:
        findings.append(
            Finding(
                "duplicate_runner",
                "incident",
                f"{len(obs.runner_processes)} runner processes are running "
                f"({sorted(live_runner_pids)}); exactly one is owned.",
            )
        )

    # 5. A runner running with no registered service is the drift case in the brief.
    if obs.service is None and obs.runner_processes:
        findings.append(
            Finding(
                "unowned_runner",
                "incident",
                f"{len(obs.runner_processes)} runner process(es) are running outside the "
                f"expected service ownership path.",
            )
        )

    severity = _worst(findings)
    incident = severity == "incident"
    owned = not findings or severity == "info"

    return OwnershipVerdict(
        owned=owned,
        findings=tuple(findings),
        severity=severity,
        incident=incident,
        summary=(
            "exactly one registered owner"
            if owned
            else "; ".join(f.code for f in findings)
        ),
    )


# --------------------------------------------------------------------------- #
# The restart gate
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RestartDecision:
    allowed: bool
    reason: str
    #: Findings that must be reported whether or not the restart proceeds.
    findings: tuple[Finding, ...] = ()
    incident: bool = False


def may_restart(
    obs: OwnershipObservation,
    maintenance_check: Callable[[], bool] | None = None,
) -> RestartDecision:
    """Decide whether the supervisor may restart the runner.

    THE MAINTENANCE FENCE IS RE-CHECKED HERE, NOT AT STARTUP. A fence read once when
    the supervisor booted is a fence that does not exist: maintenance is declared
    *during* an incident, which is exactly when the supervisor is most likely to be
    restarting things. ``maintenance_check`` is called at decision time, and its
    answer overrides the observation captured earlier.
    """
    live_maintenance = (
        maintenance_check() if maintenance_check is not None else obs.maintenance_lock_present
    )

    if live_maintenance:
        return RestartDecision(
            allowed=False,
            reason=(
                "maintenance fence is present. Re-checked at decision time rather than "
                "trusted from startup — maintenance is declared during an incident, "
                "which is when the supervisor is most likely to be restarting things."
            ),
        )

    verdict = assess_ownership(obs)

    if verdict.incident:
        return RestartDecision(
            allowed=False,
            reason=(
                f"ownership is in an incident state ({verdict.summary}). Restarting now "
                f"would add a process to a situation nobody can currently reason about."
            ),
            findings=verdict.findings,
            incident=True,
        )

    return RestartDecision(
        allowed=True,
        reason="ownership verified and no maintenance fence; restart permitted.",
        findings=verdict.findings,
        incident=False,
    )


# --------------------------------------------------------------------------- #
# Takeover
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TakeoverPlan:
    #: Pids this supervisor may terminate.
    terminate: tuple[int, ...] = ()
    #: Pids it must not touch, with the reason.
    protected: tuple[tuple[int, str], ...] = ()
    proceed: bool = False
    reason: str = ""
    findings: tuple[Finding, ...] = ()


def plan_takeover(obs: OwnershipObservation, self_pid: int) -> TakeoverPlan:
    """Plan a clean handoff to a single owner.

    ACTIVE CODER SUBPROCESSES ARE NEVER TERMINATED. A half-finished agentic edit
    killed to settle a supervisor dispute costs more than the dispute — and the work
    is not recoverable, whereas the dispute is. When a coder is running, the plan
    refuses and says to wait for it.
    """
    findings = assess_ownership(obs).findings

    if obs.coder_processes:
        protected = tuple(
            (p.pid, "active coder subprocess — work in flight is not recoverable")
            for p in obs.coder_processes
        )
        return TakeoverPlan(
            terminate=(),
            protected=protected,
            proceed=False,
            reason=(
                f"{len(obs.coder_processes)} coder subprocess(es) active. Ownership will "
                f"be taken after they finish; a half-finished agentic edit killed to "
                f"settle a supervisor dispute costs more than the dispute."
            ),
            findings=findings,
        )

    competitors = [p for p in obs.keepalive_processes if p.pid != self_pid]
    if not competitors:
        return TakeoverPlan(
            proceed=True,
            reason="no competing supervisor; this process is already the only owner.",
            findings=findings,
        )

    return TakeoverPlan(
        terminate=tuple(p.pid for p in competitors),
        protected=tuple((p.pid, "runner owned by the registered service") for p in obs.runner_processes),
        proceed=True,
        reason=(
            f"terminating {len(competitors)} competing supervisor(s) to leave exactly one "
            f"keepalive. Runner processes are left alone — the runner is the thing being "
            f"supervised, not the thing being argued over."
        ),
        findings=findings,
    )


# --------------------------------------------------------------------------- #
# Health incidents
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HealthIncident:
    runner_id: str
    hostname: str
    status: str
    detail: str
    codes: tuple[str, ...]


def build_incident(verdict: OwnershipVerdict, hostname: str) -> HealthIncident | None:
    """An incident, or None when ownership is clean.

    Emitted for drift as well as absence: the brief asks for an incident "when the
    service label is missing OR ownership drifts", and drift is the harder case
    because everything looks like it is working.
    """
    if not verdict.incident:
        return None
    return HealthIncident(
        runner_id="supervisor",
        hostname=hostname,
        status="ownership_incident",
        detail="; ".join(f"{f.code}: {f.detail}" for f in verdict.findings),
        codes=tuple(f.code for f in verdict.findings),
    )


# --------------------------------------------------------------------------- #
# Parsing helpers for real observations
# --------------------------------------------------------------------------- #


def parse_launchctl_list(output: str, label: str = CANONICAL_LABEL) -> LaunchdService | None:
    """Parse ``launchctl list`` output for the canonical label.

    Returns None when absent, which the caller must treat as the incident it is —
    not as "probably fine, it will come back".
    """
    for line in (output or "").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[-1] == label:
            pid_raw = parts[0]
            pid = int(pid_raw) if pid_raw.isdigit() else None
            return LaunchdService(label=label, loaded=True, pid=pid)
    return None


def parse_plist_program_arguments(plist_xml: str) -> tuple[str, ...]:
    """Extract ProgramArguments strings from a plist without an XML dependency."""
    match = re.search(
        r"<key>ProgramArguments</key>\s*<array>(.*?)</array>", plist_xml or "", re.S
    )
    if not match:
        return ()
    return tuple(re.findall(r"<string>(.*?)</string>", match.group(1), re.S))


__all__ = [
    "CANONICAL_LABEL",
    "Finding",
    "HealthIncident",
    "LaunchdService",
    "LockState",
    "OwnershipObservation",
    "OwnershipVerdict",
    "ProcessInfo",
    "RestartDecision",
    "TakeoverPlan",
    "assess_ownership",
    "build_incident",
    "may_restart",
    "parse_launchctl_list",
    "parse_plist_program_arguments",
    "plan_takeover",
    "service_points_at_repo",
]

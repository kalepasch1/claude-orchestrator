#!/usr/bin/env python3
"""
merge_train_liveness.py — answer the question ``merge_stall_monitor`` cannot:
is the merge train BROKEN, or is nothing running it at all?

Why this module exists (2026-08-24 relapse)
-------------------------------------------
``merge_stall_monitor`` detects the symptom (no MERGED transitions while a DONE
backlog piles up) and points the operator at ``merge_train.py`` / ``repo_lock.py``
— the 2026-07-08 root cause. On 2026-08-24 that pointer sent three separate
priority-1000 fix tasks at merge_train's *internals*. All three reached DONE and
the stall continued, because the actual condition was different in kind:

    the merge train had no consumer process at all.

Measured on the host during that relapse: every ``com.claudeorchestrator.*``
launchd agent except ``chatgptbridge`` was absent from ``launchctl list``, and
``~/Library/Logs/claude-orchestrator/merge-train.log`` had not been written to in
weeks. ``merge_train.run()`` is invoked from ``runner/periodic.py`` inside the
``com.claudeorchestrator.runner`` agent — so with that agent unloaded, no amount
of correct code inside merge_train can produce a merge. Worse, the monitor that
was supposed to page about it lives in the same dead process, so the fleet went
~18h with zero merges and zero alerts.

The structural lesson: a liveness check must not be able to be silenced by the
very outage it is meant to report. Everything here reads host-level evidence
(launchd registration, log mtime) rather than in-process state, so it produces a
correct answer even when the runner is completely down — and it is safe to call
from anywhere (a cowork session, a watchdog, CI) rather than only from inside the
process being diagnosed.

Diagnoses
---------
``OK``               a consumer is registered and has run recently.
``NO_CONSUMER``      nothing is running the merge train (agent unloaded, or its
                     log is stale beyond the threshold). Fixing merge_train's
                     internals cannot help; load the agent.
``CONSUMER_STALLED`` a consumer is registered and writing logs, but merges are
                     not landing — this is the case where merge_train/repo_lock
                     really is the suspect.
``UNKNOWN``          evidence could not be gathered (fail-soft; never raises).

Fail-soft contract: every public function returns a sensible default on any
error and never raises, so a broken liveness probe cannot wedge a caller.
Configuration is by ``ORCH_``-prefixed env vars so it is fleet-pushable via
``fleet_control.py``.
"""
import os
import subprocess
import time

# --- configuration (ORCH_-prefixed so fleet_control.py can push it) ---------
LAUNCHD_LABEL = os.environ.get(
    "ORCH_MERGE_TRAIN_LAUNCHD_LABEL", "com.claudeorchestrator.runner"
)
LOG_PATH = os.environ.get(
    "ORCH_MERGE_TRAIN_LOG_PATH",
    os.path.expanduser("~/Library/Logs/claude-orchestrator/merge-train.log"),
)
# A consumer that has not touched its log in this many hours is not consuming.
LOG_STALE_HOURS = float(os.environ.get("ORCH_MERGE_TRAIN_LOG_STALE_HOURS", "6"))
LAUNCHCTL_TIMEOUT_S = float(os.environ.get("ORCH_LAUNCHCTL_TIMEOUT_S", "10"))

OK = "OK"
NO_CONSUMER = "NO_CONSUMER"
CONSUMER_STALLED = "CONSUMER_STALLED"
UNKNOWN = "UNKNOWN"


def launchd_agent_loaded(label=None):
    """True/False if the agent's registration state is known, None if it is not.

    None means "could not tell" (launchctl missing, timed out, non-macOS host) and
    must never be treated as False — reporting NO_CONSUMER on a Linux CI box would
    be a false alarm, which is how monitors get muted.
    """
    # None means "use the configured label"; an explicitly empty label is not a
    # label at all, and answering False for it would report a phantom outage.
    if label is None:
        label = LAUNCHD_LABEL
    if not label:
        return None
    try:
        proc = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
            timeout=LAUNCHCTL_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout or ""
    for line in out.splitlines():
        # `launchctl list` rows are: PID<TAB>STATUS<TAB>LABEL
        if line.rsplit("\t", 1)[-1].strip() == label:
            return True
    return False


def log_age_hours(path=None):
    """Hours since the merge-train log was last written; None if unknowable."""
    if path is None:
        path = LOG_PATH
    if not path:
        return None
    try:
        mtime = os.path.getmtime(path)
    except (OSError, TypeError):
        return None
    age = (time.time() - mtime) / 3600.0
    return age if age >= 0 else 0.0


def diagnose(label=None, log_path=None, merges_recent=None):
    """Classify why merges are not landing.

    ``merges_recent`` is the caller's own answer to "has anything reached MERGED
    inside the alert window" (True/False/None). It is passed in rather than
    queried so this module stays dependency-free and testable without a DB.
    """
    result = {
        "diagnosis": UNKNOWN,
        "agent_label": label or LAUNCHD_LABEL,
        "agent_loaded": None,
        "log_path": log_path or LOG_PATH,
        "log_age_hours": None,
        "reason": "",
        "remedy": "",
    }
    try:
        loaded = launchd_agent_loaded(label)
        age = log_age_hours(log_path)
        result["agent_loaded"] = loaded
        result["log_age_hours"] = round(age, 2) if age is not None else None

        log_stale = age is not None and age > LOG_STALE_HOURS

        if loaded is False or log_stale:
            result["diagnosis"] = NO_CONSUMER
            bits = []
            if loaded is False:
                bits.append(
                    f"launchd agent {result['agent_label']} is not registered"
                )
            if log_stale:
                bits.append(
                    f"{result['log_path']} has not been written in {age:.1f}h "
                    f"(> {LOG_STALE_HOURS}h)"
                )
            result["reason"] = (
                "nothing is running the merge train: " + "; ".join(bits) + ". "
                "Changes to merge_train.py internals cannot affect this — the code "
                "is not being executed."
            )
            result["remedy"] = (
                f"launchctl load -w ~/Library/LaunchAgents/{result['agent_label']}.plist "
                "(and confirm the log starts moving), then re-check merges."
            )
            return result

        if loaded is None and age is None:
            result["reason"] = (
                "no host evidence available (launchctl unreadable and no merge-train "
                "log); cannot distinguish a dead consumer from a broken one"
            )
            return result

        if merges_recent is False:
            result["diagnosis"] = CONSUMER_STALLED
            result["reason"] = (
                "a consumer is registered and writing logs, but no task has reached "
                "MERGED in the alert window — this is the case where merge_train.py / "
                "repo_lock.py contention really is the suspect."
            )
            result["remedy"] = (
                "read the tail of the merge-train log for conflict/testfail outcomes "
                "and check repo_lock contention."
            )
            return result

        result["diagnosis"] = OK
        result["reason"] = "a merge-train consumer is registered and recently active"
        return result
    except Exception as e:  # fail-soft: a broken probe must not wedge the caller
        print(f"[merge_train_liveness] diagnose failed (fail-soft): {e}")
        result["diagnosis"] = UNKNOWN
        result["reason"] = f"probe error: {e}"
        return result


def summary_line(label=None, log_path=None, merges_recent=None):
    """One-line, alert-embeddable rendering of ``diagnose``. Never raises."""
    try:
        d = diagnose(label=label, log_path=log_path, merges_recent=merges_recent)
        return f"[merge-train liveness: {d['diagnosis']}] {d['reason']}"
    except Exception:
        return "[merge-train liveness: UNKNOWN] probe unavailable"


if __name__ == "__main__":
    import json

    print(json.dumps(diagnose(), indent=2, default=str))

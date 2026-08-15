#!/usr/bin/env python3
"""stale_host_guard.py — who is allowed to CLAIM a task.

The authority is the database trigger in
`supabase/migrations/20260806120000_stale_host_claim_guard.sql`. It has to be, because the whole
problem is that a host far enough behind is running code that predates any client-side guard —
it cannot self-police, and the further it drifts the less able it is to obey.

This module is the same rule expressed in Python, for two uses the trigger cannot serve:

  * a fast local pre-check, so a runner fails early with a clear message instead of eating a
    database exception mid-claim;
  * a testable specification of the rule, since the trigger's own behaviour needs a live
    Postgres to exercise.

The trigger remains the enforcement point. If the two ever disagree, the trigger wins — this
module is allowed to be more permissive (a missed local check just defers to the DB) but must
never be more permissive in a way that lets a paused host through, which is what
`test_stale_host_guard.py` pins.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional, Sequence

REMOTE_QUARANTINE_BY = "remote-quarantine"


def _strip_local(name: str) -> str:
    return name[:-6] if name.endswith(".local") else name


def _aliases(name: str) -> set:
    base = _strip_local(name or "")
    return {base, base + ".local"} - {""}


def account_hostname(account: str, host_controls: Iterable[Mapping]) -> Optional[str]:
    """The host implied by a `tasks.account` claim string, or None if it is not a host account.

    Accounts look like ``<hostname>-<pid>`` (``Mandys-MacBook-Pro.local-7146``).

    Resolution is a LOOKUP against hostnames that actually appear in controls(scope='host') —
    deliberately not a regex for "things shaped like a hostname". `cowork-executor-v6-1786031596`
    parses perfectly well as host `cowork-executor-v6` with pid `1786031596`, and a shape-based
    guard would have started rejecting the fleet's most productive workers. Only a host the
    operator has actually registered a control row for can be guarded.
    """
    if not account:
        return None
    candidates = []
    for row in host_controls or []:
        if (row.get("scope") or "") != "host":
            continue
        project = (row.get("project") or "").strip()
        if not project:
            continue
        candidates.append(project)

    # Longest first, so a shorter hostname can never shadow a longer one that also matches.
    for project in sorted(set(candidates), key=len, reverse=True):
        for alias in _aliases(project):
            if account == alias or account.startswith(alias + "-"):
                return project
    return None


def latest_host_decision(host: str, controls: Sequence[Mapping]) -> Optional[Mapping]:
    """The most recent controls decision for `host`, alias-tolerant.

    Latest wins. `controls` is not append-only in practice, and an old paused row must never
    outvote a newer resume — the same rule kill_switch.is_paused() applies.
    """
    wanted = _aliases(host or "")
    rows = [
        r for r in (controls or [])
        if (r.get("scope") or "") == "host"
        and (r.get("updated_by") or "") != REMOTE_QUARANTINE_BY
        and _aliases(r.get("project") or "") & wanted
    ]
    if not rows:
        return None
    return sorted(rows, key=lambda r: (r.get("updated_at") or ""), reverse=True)[0]


def claim_rejection(
    account: str,
    controls: Sequence[Mapping],
    *,
    host_code_sha: Optional[str] = None,
    fleet_code_sha: Optional[str] = None,
) -> Optional[str]:
    """Why this account may not claim a task, or None if the claim is allowed.

    Staleness is CORROBORATION, never authority: a host running an old `code_sha` is not rejected
    unless it is also paused. During any rollout every host is briefly stale, and rejecting on
    that alone would stop the fleet. The operator's pause is the decision; the sha only sharpens
    the message.
    """
    host = account_hostname(account, controls)
    if host is None:
        return None                      # not a registered host account -> never guarded

    decision = latest_host_decision(host, controls)
    if not decision or not decision.get("paused"):
        return None

    reason = (decision.get("reason") or "").strip() or "no reason recorded"
    detail = ""
    if host_code_sha and fleet_code_sha and host_code_sha != fleet_code_sha:
        detail = f" Host code_sha {host_code_sha[:8]} differs from fleet {fleet_code_sha[:8]}."
    return (
        f"stale-host guard: host {host} is paused and may not claim tasks. "
        f"Reason: {reason}.{detail}"
    )


def may_claim(account: str, controls: Sequence[Mapping], **kw) -> bool:
    return claim_rejection(account, controls, **kw) is None


def is_claim(old_account: Optional[str], new_account: Optional[str]) -> bool:
    """A claim is an account CHANGE to a non-null value.

    Progress updates and releases are not claims. Guarding them would strand work a paused host
    already holds — a worse outcome than the bug being fixed, since the task would be neither
    finishable nor releasable.
    """
    return new_account is not None and new_account != old_account

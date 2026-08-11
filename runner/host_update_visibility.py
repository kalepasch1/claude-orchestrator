"""host_update_visibility.py - a host that cannot update itself must SAY SO.

THE DEFECT THIS FIXES (2026-08-06). Mandys-MacBook-Pro.local sat pinned at code_sha
10d9e408 from 2026-08-05 while master moved 40+ commits. It heartbeated normally the
whole time, claimed work, reported active_tasks>0 — and completed 0 of 46 tasks over
48h while executing two-day-old code. Searching run_logs and runner_alerts for that
window produced ZERO rows explaining why its pull failed. Worse, `cowork-pull-attempt`
resumed it from a pause at 18:36 and the SHA did not move: the resume was recorded on
DISPATCH of a pull rather than on EVIDENCE that the pull landed.

The silence is the bug. Nothing outside the host could see the failure, so nothing
outside the host could remediate it. This module makes every self-update outcome
observable within one cycle:

  * success            -> old->new sha recorded.
  * failure            -> git stderr VERBATIM (bounded), current sha, commits_behind,
                          and a NAMED diagnosis drawn from this fleet's own history.
  * auto-pull disabled -> said explicitly, once per host per day. A host that is never
                          going to update must not look identical to one that just did.
  * N consecutive      -> escalates to an unresolved runner_alerts row (deduped), so a
                          stuck host gets louder instead of repeating quietly.

It deliberately does NOT try to fix the stuck machine. A macOS trust dialog cannot be
accepted remotely by anything. The point is that the NEXT host to freeze is visible in
one cycle instead of two days, and that the operator is told WHICH known cause it is.

Everything here is fail-soft: observability must never wedge the runner.
"""
import os
import sys
import datetime
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

ALERT_KIND = "host_update"

# How many consecutive failed cycles before we open an unresolved escalation row.
DEFAULT_ESCALATE_AFTER = 3

# Per-process consecutive-failure counters, keyed by host. Reset on success.
_consecutive = {}
# Per-process "already said it today" markers for the disabled notice, keyed by host.
_disabled_notice = {}


# ---------------------------------------------------------------------------
# diagnosis
# ---------------------------------------------------------------------------
# These are not guesses. Each pattern is a failure this fleet has actually hit, so
# naming the cause is strictly better than reporting "git pull failed" and making the
# operator go read the machine.
_DIAGNOSES = (
    ("trust-dialog",
     ("has not been trusted", "workspace has not been trusted", "do you trust",
      "trust this folder", "trust the files in this workspace"),
     "Claude Code is waiting on an unaccepted workspace-trust dialog. "
     "A human must accept it AT THE KEYBOARD on this host; it cannot be done remotely."),
    ("not-logged-in",
     ("not logged in", "please run /login", "invalid api key", "authentication_error",
      "oauth token has expired", "credentials could not be", "could not read username",
      "terminal prompts disabled", "authentication failed"),
     "Credentials are expired or absent. Re-authenticate on this host "
     "(Claude Code: /login; git: refresh the credential helper)."),
    ("dirty-checkout",
     ("local changes would be overwritten", "please commit your changes or stash them",
      "your local changes to the following files", "cannot pull with rebase",
      "unstaged changes", "entry .* not uptodate"),
     "The local checkout has blocking tracked modifications. Commit, stash, or discard "
     "them (only regenerable artifacts are auto-discarded)."),
    ("diverged",
     ("not possible to fast-forward", "diverged", "non-fast-forward", "refusing to merge"),
     "The local branch has diverged from origin and cannot fast-forward. "
     "It needs a rebase or a reset to origin."),
    ("network",
     ("could not resolve host", "connection timed out", "network is unreachable",
      "failed to connect", "operation timed out", "temporary failure in name resolution"),
     "The host cannot reach the git remote. Check connectivity/VPN/DNS."),
)


def classify_pull_failure(stderr):
    """Return (code, human_explanation) naming WHICH known cause this is.

    Falls back to ('git-error', ...) rather than pretending to know. Order matters:
    trust-dialog and auth are checked before the generic git families because a trust
    prompt frequently surfaces alongside noisier git output.
    """
    text = (stderr or "").lower()
    if not text.strip():
        return "unknown", ("The pull failed but produced no output. Run the pull manually "
                           "on this host to capture the real error.")
    for code, needles, explanation in _DIAGNOSES:
        for needle in needles:
            if needle in text:
                return code, explanation
    return "git-error", ("Unrecognized git failure. The verbatim stderr is recorded above; "
                        "it needs a human read.")


def classify_disabled():
    """Diagnosis for the 'this host will never update' case."""
    return ("auto-pull-disabled",
            "ORCH_AUTO_PULL is not enabled on this host, so it will never self-update. "
            "Set ORCH_AUTO_PULL=true (fleet_config or runner/.env) or accept that this "
            "host must be updated by hand.")


# ---------------------------------------------------------------------------
# staleness measurement
# ---------------------------------------------------------------------------
def _git(repo, *args, timeout=30):
    return subprocess.run(("git",) + args, cwd=repo, capture_output=True,
                          text=True, timeout=timeout)


def commits_behind(repo=None, default_branch=None, fetch=False):
    """How many commits HEAD is behind origin/<default branch>. None if unknowable.

    Before this existed, the ONLY way to learn a host was stale was to fetch the repo
    and compare SHAs by hand — which is precisely why a two-day freeze went unnoticed.
    Never fetches by default: this runs on the heartbeat path and must stay cheap.
    """
    repo = repo or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    branch = default_branch or os.environ.get("ORCH_DEFAULT_BRANCH", "master")
    try:
        if fetch:
            _git(repo, "fetch", "origin", "--quiet")
        out = _git(repo, "rev-list", "--count", f"HEAD..origin/{branch}")
        if out.returncode != 0:
            return None
        return int((out.stdout or "").strip())
    except Exception:
        return None


def local_sha(repo=None):
    repo = repo or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        out = _git(repo, "rev-parse", "HEAD")
        return (out.stdout or "").strip() or None
    except Exception:
        return None


def origin_sha(repo=None, default_branch=None):
    repo = repo or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    branch = default_branch or os.environ.get("ORCH_DEFAULT_BRANCH", "master")
    try:
        out = _git(repo, "rev-parse", f"origin/{branch}")
        return (out.stdout or "").strip() or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# recording
# ---------------------------------------------------------------------------
def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _insert_alert(detail, resolved):
    """Fail-soft runner_alerts insert. runner_alerts has no host column, so the host is
    carried in `detail` (and matched with ilike for dedupe)."""
    try:
        db.insert("runner_alerts", {"kind": ALERT_KIND, "detail": detail,
                                    "resolved": bool(resolved)})
        return True
    except Exception:
        return False


def _escalation_exists(host):
    try:
        rows = db.select("runner_alerts", {
            "select": "id", "kind": f"eq.{ALERT_KIND}",
            "detail": f"ilike.*host={host}*ESCALATED*", "resolved": "eq.false", "limit": "1",
        }) or []
        return bool(rows)
    except Exception:
        return False


def _resolve_open(host):
    """A host that just updated successfully must not leave its old alarm ringing."""
    try:
        rows = db.select("runner_alerts", {
            "select": "id", "kind": f"eq.{ALERT_KIND}",
            "detail": f"ilike.*host={host}*", "resolved": "eq.false", "limit": "50",
        }) or []
        for row in rows:
            db.update("runner_alerts", {"id": row["id"]}, {"resolved": True})
        return len(rows)
    except Exception:
        return 0


def record_success(host, old_sha, new_sha, alert=True):
    """Record a pull that actually moved the SHA. Clears the failure streak."""
    _consecutive[host] = 0
    detail = (f"host={host} outcome=success "
              f"sha={(old_sha or '?')[:8]}->{(new_sha or '?')[:8]}")
    print(f"[host_update] {detail}", flush=True)
    resolved = _resolve_open(host) if alert else 0
    if alert:
        _insert_alert(detail, resolved=True)
    return {"outcome": "success", "old_sha": old_sha, "new_sha": new_sha,
            "detail": detail, "resolved_prior": resolved}


def record_failure(host, stderr, current_sha=None, behind=None, alert=True,
                   escalate_after=None):
    """Record a pull that did NOT land, verbatim, with a named diagnosis.

    Returns a dict including `escalated` so callers can heartbeat the streak. Never
    claims success — that conflation is the `cowork-pull-attempt` bug.
    """
    limit = int(os.environ.get("ORCH_HOST_UPDATE_STDERR_MAX", "1200"))
    verbatim = (stderr or "").strip()
    if len(verbatim) > limit:
        verbatim = verbatim[:limit] + f"...[truncated {len(stderr.strip()) - limit} chars]"
    code, explanation = classify_pull_failure(stderr)
    n = _consecutive.get(host, 0) + 1
    _consecutive[host] = n
    threshold = int(escalate_after if escalate_after is not None
                    else os.environ.get("ORCH_HOST_UPDATE_ESCALATE_AFTER",
                                        DEFAULT_ESCALATE_AFTER))
    behind_txt = "unknown" if behind is None else str(behind)
    detail = (f"host={host} outcome=failure diagnosis={code} consecutive={n} "
              f"sha={(current_sha or 'unknown')[:8]} commits_behind={behind_txt}\n"
              f"cause: {explanation}\n"
              f"git stderr (verbatim):\n{verbatim}")
    escalated = False
    if n >= threshold:
        if alert and not _escalation_exists(host):
            escalated = _insert_alert(f"ESCALATED after {n} consecutive cycles — {detail}",
                                      resolved=False)
        else:
            escalated = bool(alert)
    elif alert:
        _insert_alert(detail, resolved=True)
    print(f"[host_update] FAILURE host={host} diagnosis={code} consecutive={n} "
          f"behind={behind_txt} sha={(current_sha or 'unknown')[:8]}", flush=True)
    return {"outcome": "failure", "diagnosis": code, "explanation": explanation,
            "stderr": verbatim, "consecutive": n, "escalated": escalated,
            "commits_behind": behind, "current_sha": current_sha, "detail": detail}


def record_auto_pull_disabled(host, behind=None, alert=True, today=None):
    """Say 'this host will never update' explicitly, at most once per host per day."""
    day = (today or _now().date()).isoformat()
    if _disabled_notice.get(host) == day:
        return {"outcome": "disabled", "emitted": False, "day": day}
    _disabled_notice[host] = day
    code, explanation = classify_disabled()
    behind_txt = "unknown" if behind is None else str(behind)
    detail = (f"host={host} outcome=disabled diagnosis={code} day={day} "
              f"commits_behind={behind_txt}\ncause: {explanation}")
    print(f"[host_update] {detail}", flush=True)
    if alert:
        _insert_alert(detail, resolved=True)
    return {"outcome": "disabled", "emitted": True, "day": day, "diagnosis": code,
            "detail": detail, "commits_behind": behind}


# ---------------------------------------------------------------------------
# resume gate
# ---------------------------------------------------------------------------
def resume_allowed(current_sha, expected_sha):
    """VERIFY, THEN RESUME — never the reverse.

    `cowork-pull-attempt` resumed a paused host because a pull had been ATTEMPTED. The
    pull had failed, the SHA had not moved, and the host went straight back to claiming
    work with two-day-old code. A resume is only legitimate once the host's code_sha
    actually matches origin.

    Returns (allowed, reason). Unknown SHAs are treated as NOT allowed: a resume we
    cannot justify is exactly the failure being fixed.
    """
    if not current_sha or not expected_sha:
        return False, ("cannot verify code_sha against origin "
                       f"(local={current_sha or 'unknown'}, origin={expected_sha or 'unknown'})")
    if current_sha != expected_sha:
        return False, (f"code_sha still stale: local={current_sha[:8]} "
                       f"origin={expected_sha[:8]} — pull did not land, refusing resume")
    return True, f"code_sha verified at {current_sha[:8]}"


def heartbeat_fields(repo=None, default_branch=None):
    """The staleness fields every heartbeat should carry."""
    behind = commits_behind(repo=repo, default_branch=default_branch)
    return {"commits_behind": behind} if behind is not None else {}


def reset_state():
    """Test helper: clear per-process streak and once-per-day memory."""
    _consecutive.clear()
    _disabled_notice.clear()

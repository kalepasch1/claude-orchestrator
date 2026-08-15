"""Auto-resume a dead-host pause once the host proves it is back on current code.

orch-operator-bootstrap pauses a host's `controls` row (scope=host) when it sees no
runner_heartbeats entry and a stale runner_health snapshot (>7 days). Its own reason
text says resume "requires human verification the host is live on current code" --
until this module existed, that meant someone (a human, or an operator session) had
to remember to run the query by hand. On 2026-08-07 that is literally what happened
for "Mac.lan": a human/operator session confirmed it was on master at 1ffc1082
(matching origin/master) and flipped the row.

This module automates exactly that same check, using the same evidence bar, so a
host that comes back online gets reactivated within one 5-minute janitor tick
instead of sitting paused indefinitely:

  1. Only touches rows that were auto-paused by the dead-host detector (updated_by
     startswith one of ORCH_AUTOPAUSE_ACTORS). A pause a human set by hand for any
     other reason (security, cost, an active incident) is never touched here --
     this module only ever flips paused=false, and only for that one pause reason.
  2. Requires >=2 heartbeats from the EXACT paused hostname (controls.project for a
     scope=host row), spanning >= HOST_RESUME_MIN_SPAN_MIN minutes, with the most
     recent one fresher than HOST_RESUME_FRESH_MIN minutes. One heartbeat could be a
     reboot blip; two spaced apart is a host that is actually staying up.
  3. Every one of those heartbeats' code_sha must equal the current origin/<branch>
     HEAD sha -- stale-but-alive is exactly the state the pause exists to keep off
     the fleet (see host_update_visibility.py's commits_behind), so a live host on
     old code still stays paused.

On success the controls row is flipped paused=false with a reason string that names
the evidence (mirrors the human-written resume note format), and a notification is
queued either way isn't needed -- only on actual resume, so it doesn't add noise.
Nothing in this module ever sets paused=true; it only ever resumes.
"""
import os
import time
import datetime
import subprocess

import db

FRESH_MIN = float(os.environ.get("HOST_RESUME_FRESH_MIN", "5"))
MIN_SPAN_MIN = float(os.environ.get("HOST_RESUME_MIN_SPAN_MIN", "3"))
MIN_HEARTBEATS = int(os.environ.get("HOST_RESUME_MIN_HEARTBEATS", "2"))
AUTOPAUSE_ACTORS = tuple(
    a.strip() for a in os.environ.get(
        "ORCH_AUTOPAUSE_ACTORS", "orch-operator,orch-operator-bootstrap,codex-remediation"
    ).split(",") if a.strip()
)
NOTIFY_EMAIL = os.environ.get("APPROVAL_PUSH_EMAIL", "kalepasch@gmail.com")


def _git(repo, *args, timeout=30):
    return subprocess.run(("git",) + args, cwd=repo, capture_output=True, text=True, timeout=timeout)


def current_master_sha(repo=None, default_branch=None, fetch=False):
    """Same resolution strategy as host_update_visibility.commits_behind(): never
    fetches by default (this can run on the hot janitor path), returns None (never
    a stale/blank sha) if git can't answer."""
    repo = repo or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    branch = default_branch or os.environ.get("ORCH_DEFAULT_BRANCH", "master")
    try:
        if fetch:
            _git(repo, "fetch", "origin", "--quiet")
        out = _git(repo, "rev-parse", f"origin/{branch}")
        if out.returncode != 0:
            return None
        sha = (out.stdout or "").strip()
        return sha or None
    except Exception:
        return None


def _parse_ts(v):
    try:
        return datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _autopaused_host_rows():
    rows = db.select("controls", {"select": "*", "scope": "eq.host", "paused": "eq.true"}) or []
    return [r for r in rows if str(r.get("updated_by") or "").startswith(AUTOPAUSE_ACTORS)]


def check_and_resume(master_sha=None, repo=None):
    """Run one pass. Returns (resumed_count, checked_count). Never raises -- a
    failure here must not take down the janitor job that calls it."""
    try:
        master_sha = master_sha or current_master_sha(repo=repo)
        if not master_sha:
            return 0, 0
        rows = _autopaused_host_rows()
        resumed = 0
        now = time.time()
        for row in rows:
            host = row.get("project")
            if not host:
                continue
            heartbeats = db.select(
                "runner_heartbeats",
                {"select": "*", "hostname": f"eq.{host}", "order": "last_seen.desc", "limit": "5"},
            ) or []
            if len(heartbeats) < MIN_HEARTBEATS:
                continue
            fresh = _parse_ts(heartbeats[0].get("last_seen"))
            oldest = _parse_ts(heartbeats[-1].get("last_seen"))
            if fresh is None or oldest is None:
                continue
            if (now - fresh) > FRESH_MIN * 60:
                continue
            if (fresh - oldest) < MIN_SPAN_MIN * 60:
                continue
            shas = {str(h.get("code_sha") or "") for h in heartbeats}
            if len(shas) != 1 or next(iter(shas)) != str(master_sha):
                continue
            reason = (
                f"auto-resumed by host_resume_watch: {len(heartbeats)} heartbeats from '{host}' "
                f"spanning {(fresh - oldest) / 60:.1f}m, latest {(now - fresh) / 60:.1f}m ago, all "
                f"at code_sha {str(master_sha)[:12]} (matches current origin/master). "
                f"Prior pause reason: {str(row.get('reason') or '')[:300]}"
            )[:900]
            try:
                db.update("controls", {"id": row["id"]}, {
                    "paused": False,
                    "reason": reason,
                    "updated_by": "host_resume_watch",
                    "updated_at": "now()",
                })
            except Exception:
                continue
            try:
                db.insert("notifications", {
                    "channel": "digest", "audience": NOTIFY_EMAIL, "kind": "host-resume",
                    "title": f"[host-resume-watch] resumed '{host}' -- verified live on current master",
                    "body": reason, "sent": False,
                })
            except Exception:
                pass
            resumed += 1
        return resumed, len(rows)
    except Exception as e:
        print(f"host_resume_watch: check_and_resume failed: {e}")
        return 0, 0


if __name__ == "__main__":
    n, checked = check_and_resume()
    print(f"host_resume_watch: resumed={n} checked={checked}")

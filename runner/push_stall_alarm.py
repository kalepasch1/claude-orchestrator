#!/usr/bin/env python3
"""
push_stall_alarm.py — PUSH VISIBILITY (CORE INTEGRITY AUDIT section 6).

Two failure modes, both previously invisible, both of which silently destroy
work while every dashboard stays green:

  1. PUSH STALL. A commit lands on a protected branch (master/dev/main) and the
     push fails — bad credentials, network, a rejected non-fast-forward. Nothing
     in the fleet notices. The commit exists only on this Mac, so the merge
     train, CI and Vercel all see the OLD tip and report success. The work is
     one `rm -rf` from gone, and the longer it sits the more likely a later
     reset/rebase silently discards it. Alarms when the oldest local-only commit
     on a protected branch is older than ORCH_PUSH_STALL_S (default 1800s/30min).

  2. CREDENTIAL IN REMOTE URL. `origin` historically embedded the GitHub PAT
     directly in the URL, so `git remote -v` — and every log line, every crash
     dump, every `set -x` trace that ever printed a git command — leaked it.
     That is the 2026-08-02 plaintext-credential incident. Auth now belongs in a
     credential helper. This scans every remote of every project repo and files
     a CRITICAL alarm the moment a credential reappears in a URL, so a
     regression is caught on the next tick instead of at the next audit.

Both checks are read-only. This module never pushes, never rewrites a remote,
never touches a working tree — an alarm that mutates the thing it watches is how
you turn a reportable problem into an unreportable one.

State (first-seen timestamp per repo/branch, last-alert date) lives in a local
JSON file, not the DB, so the alarm still works when Supabase is degraded —
same rationale as fleet_stuck_alarm.py.

Env vars:
    ORCH_PUSH_STALL_S        seconds before an unpushed commit alarms (default 1800)
    ORCH_PUSH_STALL_BRANCHES comma-separated protected branches (default master,main,dev)
"""
import os
import sys
import json
import time
import re
import subprocess
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
STATE_FILE = os.path.join(HOME, "push_stall_alarm_state.json")
STALL_THRESHOLD_S = int(os.environ.get("ORCH_PUSH_STALL_S", "1800"))
PROTECTED = [b.strip() for b in
             os.environ.get("ORCH_PUSH_STALL_BRANCHES", "master,main,dev").split(",")
             if b.strip()]
TIMEOUT = 15

# A credential embedded in a remote URL: scheme://<something>@host. Matches both
# https://TOKEN@github.com/... and https://user:TOKEN@github.com/... . SSH
# remotes (git@github.com:owner/repo) are NOT credentials — the identity is the
# key agent, nothing secret is in the string — so the scheme is required.
CRED_IN_URL = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://[^/@\s]+@")


def _load_state():
    """Load alarm state from local JSON (survives DB outages)."""
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state):
    """Persist alarm state to local JSON (fail-soft on permission errors)."""
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def _git(repo, *args):
    """Run git in repo. Returns (rc, stdout, stderr), never raises."""
    try:
        r = subprocess.run(["git"] + list(args), cwd=repo,
                           capture_output=True, text=True, timeout=TIMEOUT)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def redact(text):
    """
    Strip any embedded credential from a URL before it is printed or persisted.

    The alarm reports WHICH remote leaked, never the secret itself — writing the
    PAT into an approvals row or a log line to prove the PAT is in a log line
    would just be a second copy of the same incident.
    """
    return re.sub(r"(://)[^/@\s]+@", r"\1***@", text or "")


def scan_remotes(repo_path):
    """
    Return the remotes of repo_path whose URL embeds a credential.

    Each entry is {"remote": name, "url": <redacted url>}. Empty list == clean,
    which is the proof artifact section 6 asks for ("PAT absent from remotes").
    """
    rc, out, _ = _git(repo_path, "remote", "-v")
    if rc != 0:
        return []
    leaks, seen = [], set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        name, url = parts[0], parts[1]
        if CRED_IN_URL.match(url) and name not in seen:
            seen.add(name)
            leaks.append({"remote": name, "url": redact(url)})
    return leaks


def unpushed_commits(repo_path, branch):
    """
    Local-only commits on `branch` — those reachable from the local branch but
    not from origin/<branch>.

    Returns None when the comparison is not meaningful (branch absent, or no
    origin/<branch> — a brand-new branch that was never pushed is the merge
    train's business, not a stall), otherwise
    {"count": int, "oldest_ts": epoch|None, "age_s": float}.

    age_s measures the OLDEST unpushed commit, not the newest. A repo that keeps
    committing while pushes fail has a newest commit that is always seconds old;
    keying on that would keep the alarm silent for exactly as long as the
    breakage kept producing work.
    """
    rc, _, _ = _git(repo_path, "rev-parse", "--verify", f"refs/heads/{branch}")
    if rc != 0:
        return None
    rc, _, _ = _git(repo_path, "rev-parse", "--verify", f"refs/remotes/origin/{branch}")
    if rc != 0:
        return None

    rc, out, _ = _git(repo_path, "rev-list", "--count", f"origin/{branch}..{branch}")
    if rc != 0:
        return None
    try:
        count = int(out or "0")
    except ValueError:
        return None
    if count <= 0:
        return {"count": 0, "oldest_ts": None, "age_s": 0.0}

    # Committer date of the oldest unpushed commit (last line of the range).
    rc, out, _ = _git(repo_path, "log", "--format=%ct", f"origin/{branch}..{branch}")
    oldest_ts = None
    if rc == 0 and out:
        try:
            oldest_ts = int(out.splitlines()[-1])
        except (ValueError, IndexError):
            oldest_ts = None
    age_s = (time.time() - oldest_ts) if oldest_ts else 0.0
    return {"count": count, "oldest_ts": oldest_ts, "age_s": age_s}


def _projects():
    """Project rows with a usable repo_path. Fail-soft to []."""
    try:
        rows = db.select("projects", {"select": "name,repo_path"}) or []
    except Exception:
        return []
    return [r for r in rows if r.get("repo_path") and os.path.isdir(
        os.path.join(r["repo_path"], ".git"))]


def _file_approval(title, why, value, risk):
    """File a single approval card. Fail-soft — an alarm must not raise."""
    try:
        db.insert("approvals", {"project": "PORTFOLIO", "kind": "material",
                                "title": title, "why": why, "value": value,
                                "risk": risk, "command": ""})
        return True
    except Exception as e:
        print(f"push_stall_alarm: failed to file approval: {e}")
        return False


def run():
    """Scan every project repo for push stalls and credential-bearing remotes."""
    state = _load_state()
    today = datetime.date.today().isoformat()
    stalls, leaks, checked = [], [], 0

    for proj in _projects():
        name, repo = proj["name"], proj["repo_path"]
        checked += 1

        for leak in scan_remotes(repo):
            leaks.append({"project": name, **leak})

        for branch in PROTECTED:
            info = unpushed_commits(repo, branch)
            if not info or info["count"] <= 0:
                state.pop(f"{name}:{branch}", None)
                continue
            if info["age_s"] >= STALL_THRESHOLD_S:
                stalls.append({"project": name, "branch": branch,
                               "commits": info["count"],
                               "age_min": round(info["age_s"] / 60, 1)})

    # Credential leaks are unconditional and CRITICAL — never rate-limited.
    if leaks:
        where = ", ".join(f"{l['project']}:{l['remote']} ({l['url']})" for l in leaks)
        _file_approval(
            f"CREDENTIAL IN REMOTE URL: {len(leaks)} remote(s)",
            f"A credential is embedded in a remote URL, so `git remote -v` and every logged "
            f"git invocation leak it. Regression of the 2026-08-02 plaintext-credential "
            f"incident. Affected: {where}",
            "Auth belongs in a credential helper; the URL must carry no secret.",
            "Rotate the exposed credential — it must be assumed public — then reset the "
            "remote to the clean URL.")

    if stalls:
        key = "push_stall:" + today
        if state.get("last_alert_date") != today:
            where = ", ".join(
                f"{s['project']}/{s['branch']} ({s['commits']} commit(s), {s['age_min']}min)"
                for s in stalls)
            if _file_approval(
                f"PUSH STALL: {len(stalls)} protected branch(es) with local-only commits",
                f"Commits exist locally on a protected branch but not on origin for longer "
                f"than {STALL_THRESHOLD_S}s. CI, the merge train and Vercel are all still "
                f"looking at the old tip, so everything reports green while the work is "
                f"unreplicated. Affected: {where}",
                "Surfaces a failed push in ~30 minutes instead of at the next manual audit.",
                "Work exists on exactly one disk. Push it or capture a patch before any "
                "reset/rebase in these repos."
            ):
                state["last_alert_date"] = today
        state[key] = True

    _save_state(state)

    summary = {"ok": not stalls and not leaks, "repos_checked": checked,
               "stalls": stalls, "credential_leaks": leaks,
               "threshold_s": STALL_THRESHOLD_S, "checked_at": time.time()}
    try:
        db.insert("controls", {"key": "push_stall_alarm",
                               "value": json.dumps(summary),
                               "updated_at": "now()"}, upsert=True)
    except Exception:
        pass

    if summary["ok"]:
        print(f"push_stall_alarm: healthy ({checked} repos, no stalls, no credentials in remotes)")
    else:
        print(f"push_stall_alarm: TRIPPED — {len(stalls)} stall(s), {len(leaks)} credential leak(s)")
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))

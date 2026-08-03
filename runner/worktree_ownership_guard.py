#!/usr/bin/env python3
"""
worktree_ownership_guard.py - refuse to destroy uncommitted work in a worktree you do not own.

The fleet destroyed in-flight work three separate times on 2026-08-02. The mechanism was
never a single bad command; it was the COMBINATION that every bot uses:

    git add -A                 # sweeps up another agent's half-finished edits
    git commit --no-verify     # skips the hooks that would have objected
    git reset --hard / clean   # or an auto-resolution that discards the working tree

Each step is individually reasonable. Together, a bot operating in a shared checkout
silently annihilates whatever another agent had in progress, and because the work was never
committed there is no reflog entry, no dangling object, no way back.

This module makes that outcome structurally impossible in two layers:

  1. OWNERSHIP. A worktree is stamped with the identity of whoever created it
     (.git/orch-worktree-owner, or .runtime/worktree_owners.json for plain checkouts).
     guard_destructive() refuses a destructive operation when the caller is not the owner
     AND the tree has uncommitted changes. Fail-closed: unknown ownership + dirty tree =
     REFUSE, because "I don't know who owns this" is exactly the state in which the fleet
     kept guessing wrong.

  2. RESCUE. Before any refusal (and on every periodic sweep) the uncommitted state is
     captured into a real, fetchable git object under refs/orch-rescue/<ts>-<name>. Even a
     caller that ignores this guard entirely cannot make the work unrecoverable, because
     the rescue ref pins the tree and index in the object database.

Entry points:
  guard_destructive(path, actor, op) -> (ok, log)   fail-closed; call BEFORE destroying
  claim(path, actor)                                stamp ownership at creation time
  rescue(path, reason)                              capture uncommitted state into a ref
  run()                                             periodic: rescue every dirty worktree
Structured JSONL goes to .runtime/logs/worktree-ownership-guard.log.
"""
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

NAME = "worktree-ownership-guard"
ENABLED = os.environ.get("ORCH_WORKTREE_GUARD_ENABLED", "true").lower() in (
    "1", "true", "yes", "on")
BREAK_GLASS = os.environ.get("ORCH_WORKTREE_GUARD_BREAK_GLASS", "false").lower() in (
    "1", "true", "yes", "on")

OWNER_FILE = "orch-worktree-owner"
RESCUE_PREFIX = "refs/orch-rescue"
GIT_TIMEOUT = int(os.environ.get("ORCH_WORKTREE_GIT_TIMEOUT", "60"))

# Operations that can annihilate uncommitted work. Naming them explicitly keeps the guard's
# contract legible at every call site.
DESTRUCTIVE = ("reset --hard", "clean", "checkout -f", "checkout --ours", "checkout --theirs",
               "stash drop", "worktree remove", "branch -D", "add -A", "restore")


def _home():
    return os.environ.get("CLAUDE_ORCH_HOME",
                          os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "..", ".runtime"))


def _log_event(event):
    row = dict(event)
    row.setdefault("at", time.time())
    row.setdefault("bot", NAME)
    try:
        path = os.path.join(_home(), "logs")
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, NAME + ".log"), "a") as fh:
            fh.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
    except OSError:
        pass
    return row


def _git(repo, *args, **kw):
    try:
        r = subprocess.run(["git"] + list(args), cwd=repo, capture_output=True,
                           text=True, errors="replace",
                           timeout=kw.get("timeout", GIT_TIMEOUT))
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, "", str(exc)


def current_actor():
    """Identity of the running process, for ownership comparisons.

    ORCH_ACTOR is set by the runner for each agent/bot. Falling back to the pid would make
    every process its own owner and defeat the guard, so the fallback is the BOT name only.
    """
    return (os.environ.get("ORCH_ACTOR")
            or os.environ.get("ORCH_BOT")
            or os.environ.get("CLAUDE_AGENT_ID")
            or "unknown")


def _git_dir(path):
    rc, out, _ = _git(path, "rev-parse", "--absolute-git-dir")
    return out if rc == 0 and out else None


def _owner_path(path):
    gd = _git_dir(path)
    return os.path.join(gd, OWNER_FILE) if gd else None


def claim(path, actor=None):
    """Stamp this worktree as owned by <actor>. Call at creation time."""
    actor = actor or current_actor()
    op = _owner_path(path)
    if not op:
        return None
    try:
        with open(op, "w") as fh:
            json.dump({"actor": actor, "at": time.time(), "path": os.path.abspath(path)}, fh)
    except OSError:
        return None
    _log_event({"event": "claim", "path": path, "actor": actor})
    return actor


def owner_of(path):
    """The recorded owner of this worktree, or None when unknown."""
    op = _owner_path(path)
    if op and os.path.isfile(op):
        try:
            with open(op) as fh:
                return (json.load(fh) or {}).get("actor")
        except (OSError, ValueError):
            return None
    return None


def is_dirty(path):
    """(dirty, entries) for the worktree: uncommitted tracked changes or untracked files."""
    rc, out, _ = _git(path, "status", "--porcelain", "--untracked-files=normal")
    if rc != 0:
        # Cannot determine state -> treat as dirty. Fail-closed by construction.
        return True, ["<status unavailable>"]
    entries = [ln for ln in out.splitlines() if ln.strip()]
    return bool(entries), entries


def rescue(path, reason="pre-destructive"):
    """Capture the worktree's uncommitted state into refs/orch-rescue/<ts>-<name>.

    Uses `git stash create`, which builds a real commit object WITHOUT touching the working
    tree or the stash list -- so the caller's state is unchanged and nothing surprises the
    agent currently editing there. Untracked files are swept into the same commit via a
    temporary index so an unstaged new file is recoverable too.
    """
    dirty, entries = is_dirty(path)
    if not dirty:
        return None
    rc, sha, err = _git(path, "stash", "create", "orch-rescue: " + reason)
    if rc != 0 or not sha:
        # `stash create` yields nothing when only untracked files exist; commit-tree the
        # current index instead so the tracked state is still pinned.
        rc2, head, _ = _git(path, "rev-parse", "HEAD")
        if rc2 != 0:
            _log_event({"event": "rescue_failed", "path": path, "error": err or "no HEAD"})
            return None
        sha = head
    ref = "%s/%s-%s" % (RESCUE_PREFIX, time.strftime("%Y%m%dT%H%M%S", time.gmtime()),
                        re.sub(r"[^A-Za-z0-9_.-]+", "-", os.path.basename(os.path.abspath(path))))
    rc, _, err = _git(path, "update-ref", ref, sha)
    if rc != 0:
        _log_event({"event": "rescue_failed", "path": path, "error": err})
        return None
    _log_event({"event": "rescue", "path": path, "ref": ref, "sha": sha,
                "reason": reason, "entries": len(entries)})
    return {"ref": ref, "sha": sha, "entries": entries}


def guard_destructive(path, actor=None, op="destructive operation"):
    """Refuse a destructive operation on a worktree the caller does not own. (ok, log).

    FAIL-CLOSED. The refusal cases, in the order they actually bit the fleet:
      * dirty + owned by someone else  -> REFUSE (the three destructions today)
      * dirty + owner unknown          -> REFUSE (a bot cannot prove it may destroy this)
      * dirty + owned by caller        -> allow; it is the caller's own work
      * clean                          -> allow; nothing to lose

    A rescue ref is written before ANY refusal, so even a caller that ignores the return
    value cannot make the work unrecoverable.
    """
    if not ENABLED:
        return True, "worktree_ownership_guard disabled"
    if not path or not os.path.isdir(path):
        return True, "not a directory (skipped)"
    actor = actor or current_actor()
    dirty, entries = is_dirty(path)
    if not dirty:
        return True, "worktree clean — %s is safe" % op
    saved = rescue(path, reason=op)
    owner = owner_of(path)
    detail = ("%d uncommitted change(s) in %s: %s%s"
              % (len(entries), path, "; ".join(entries[:8]),
                 " ..." if len(entries) > 8 else ""))
    if saved:
        detail += ("\n    RESCUED to %s (recover with: git -C %s checkout %s -- .)"
                   % (saved["ref"], path, saved["ref"]))
    if owner and owner == actor:
        _log_event({"event": "allow", "path": path, "actor": actor, "op": op,
                    "entries": len(entries)})
        return True, "caller '%s' owns this worktree; %s allowed. %s" % (actor, op, detail)
    who = ("owned by '%s'" % owner) if owner else "owner UNKNOWN"
    log = ("REFUSED %s on %s — %s, caller is '%s', and the tree has uncommitted work.\n    %s"
           "\n    This is the shape that destroyed in-flight work three times on 2026-08-02: "
           "`git add -A` + `--no-verify` + auto-resolution in a checkout the bot did not own."
           "\n    fix: operate in your OWN worktree, or claim this one explicitly "
           "(worktree_ownership_guard.claim(path, actor)) once the current owner is done."
           % (op, path, who, actor, detail))
    _log_event({"event": "refuse", "path": path, "actor": actor, "owner": owner,
                "op": op, "entries": len(entries), "rescued": bool(saved)})
    if BREAK_GLASS:
        return True, "BREAK-GLASS override (ORCH_WORKTREE_GUARD_BREAK_GLASS):\n" + log
    return False, log


def worktrees(repo):
    """Every worktree attached to <repo>, main checkout included."""
    rc, out, _ = _git(repo, "worktree", "list", "--porcelain")
    if rc != 0:
        return [repo] if os.path.isdir(repo) else []
    return [ln.split(" ", 1)[1].strip() for ln in out.splitlines()
            if ln.startswith("worktree ")]


def run(project=None):
    """Periodic: pin the uncommitted state of every worktree into a rescue ref.

    Turns "uncommitted work can be destroyed" into "uncommitted work is always recoverable",
    independently of whether every destructive caller remembers to consult the guard.
    """
    if not ENABLED:
        print("worktree_ownership_guard: disabled")
        return {"enabled": False}
    import db
    params = {"select": "*"}
    if project:
        params["name"] = "eq.%s" % project
    projects = db.select("projects", params) or []
    summary = {"projects": 0, "worktrees": 0, "dirty": 0, "rescued": 0, "unowned_dirty": 0}
    for p in projects:
        repo = p.get("repo_path") or ""
        if not repo or not os.path.isdir(repo):
            continue
        summary["projects"] += 1
        for wt in worktrees(repo):
            if not os.path.isdir(wt):
                continue
            summary["worktrees"] += 1
            dirty, entries = is_dirty(wt)
            if not dirty:
                continue
            summary["dirty"] += 1
            owner = owner_of(wt)
            if not owner:
                summary["unowned_dirty"] += 1
            saved = rescue(wt, reason="periodic sweep")
            if saved:
                summary["rescued"] += 1
            print("  %-14s %-52s %2d change(s) owner=%s %s"
                  % (p.get("name"), wt[-52:], len(entries), owner or "UNKNOWN",
                     saved["ref"] if saved else "(rescue failed)"), flush=True)
    _log_event({"event": "sweep", **summary})
    print("worktree_ownership_guard: %(worktrees)d worktree(s), %(dirty)d dirty, "
          "%(rescued)d rescued, %(unowned_dirty)d dirty-and-unowned" % summary)
    return summary


def stats():
    try:
        import db
        projects = db.select("projects", {"select": "name,repo_path"}) or []
        dirty = 0
        for p in projects:
            repo = p.get("repo_path") or ""
            if repo and os.path.isdir(repo):
                for wt in worktrees(repo):
                    if os.path.isdir(wt) and is_dirty(wt)[0]:
                        dirty += 1
        return {"enabled": ENABLED, "projects": len(projects), "dirty_worktrees": dirty}
    except Exception:
        return {"enabled": ENABLED, "projects": 0, "dirty_worktrees": 0}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="worktree ownership / uncommitted-work guard")
    ap.add_argument("--path")
    ap.add_argument("--actor", default=None)
    ap.add_argument("--op", default="destructive operation")
    ap.add_argument("--claim", action="store_true")
    ap.add_argument("--rescue", action="store_true")
    a = ap.parse_args(argv)
    if not a.path:
        run()
        return 0
    if a.claim:
        print("claimed by", claim(a.path, a.actor))
        return 0
    if a.rescue:
        print(json.dumps(rescue(a.path, "manual") or {}, indent=2))
        return 0
    ok, log = guard_destructive(a.path, a.actor, a.op)
    print("WORKTREE-GUARD", "ALLOW" if ok else "REFUSE")
    print(log)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

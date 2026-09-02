#!/usr/bin/env python3
"""
worktree_gc.py - the fix for the ROOT of the phantom-CONFLICT bug: leftover agent worktrees. Every task
got its own `<repo>-wt/<slug>` worktree, but nothing ever removed them, so branches stayed checked out
and the merge handler's `git rebase` failed with "already checked out" — which it mislabeled as CONFLICT
(93 tasks stuck, 0 merges). This periodically removes worktrees for tasks that are NO LONGER running, so
branches are free to merge and disk stays clean.

Runs ON THE RUNNER MACHINE only (paths must match — never from a sandbox with remapped paths). Safe:
only removes worktrees whose task is in a terminal/queued state, never a RUNNING one.

Safety invariants:
  - RUNNING and RETRY tasks are always protected (see PROTECTED_STATES).
  - Pending/approved merge approvals are also protected to avoid racing the merge handler.
  - Before removing a worktree, the branch is pushed to origin (unless ORCH_SHARE_AGENT_BRANCHES
    is disabled) so work is never lost — this eliminated the recover-missing-branch churn.

Environment variables:
  WORKTREE_GC_GIT_TIMEOUT   Max seconds for any single git subprocess (default: 90).
  WORKTREE_GC_MAX_SECONDS   Wall-clock budget for the WHOLE run() (default: 600, 0 = off).
  ORCH_SHARE_AGENT_BRANCHES Push agent branches to origin before GC (default: true).
"""
import os, re, sys, time, shutil, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


PROTECTED_STATES = ("RUNNING", "RETRY")
# Approval kinds that indicate an in-flight merge; their slugs are protected from GC.
MERGE_KINDS = ("verify", "material", "integrate")
GIT_TIMEOUT = int(os.environ.get("WORKTREE_GC_GIT_TIMEOUT", "90"))
# Never GC a worktree that showed filesystem activity within this window. Cowork/manual
# executors create worktrees that may sit briefly before their task row flips to RUNNING,
# and a fresh checkout has zero commits ahead of base — recency is the only reliable signal.
MIN_AGE_MIN = int(os.environ.get("WORKTREE_GC_MIN_AGE_MIN", "180"))


# --- Whole-job deadline ------------------------------------------------------------
# GIT_TIMEOUT bounds ONE subprocess. It does not bound the job: run() loops over every
# project, and gc_repo/gc_integration_worktrees each loop over every worktree or slot,
# issuing several git/du/lsof calls apiece. With ~40 worktrees per repo across 9 repos,
# the worst case is thousands of calls * 90s — effectively unbounded. That is how
# 'worktreegc' wedged: it held its singleton lock for 1074s, periodic.py skipped three
# consecutive invocations, and each skip exited 0 so nothing downstream noticed.
#
# A wall-clock budget is checked between repos and between items, and every subprocess
# timeout is clamped to whatever is left, so the job cannot outlive the deadline by more
# than one already-running call. Exceeding it is not an error: GC is idempotent and
# resumable, so the sweep simply stops and the next invocation continues where it left
# off — a partial sweep that releases its lock beats a complete one that never returns.
MAX_SECONDS = int(os.environ.get("WORKTREE_GC_MAX_SECONDS", "600"))

_deadline = None  # epoch seconds, or None when no budget is in force


def _start_deadline(budget=None):
    """Begin a wall-clock budget for this run. Returns the previous deadline."""
    global _deadline
    prev = _deadline
    budget = MAX_SECONDS if budget is None else budget
    # 0 means "no budget". A NEGATIVE budget is an already-elapsed deadline, not "off" —
    # callers (and tests) use it to assert that an out-of-time sweep does nothing.
    _deadline = None if budget == 0 else (time.time() + budget)
    return prev


def _clear_deadline(previous=None):
    global _deadline
    _deadline = previous


def _time_left():
    """Seconds remaining in the budget; None when unbounded."""
    if _deadline is None:
        return None
    return _deadline - time.time()


def _expired():
    left = _time_left()
    return left is not None and left <= 0


def _bounded_timeout(default=None):
    """Per-subprocess timeout clamped to the remaining job budget (>= 1s)."""
    default = GIT_TIMEOUT if default is None else default
    left = _time_left()
    if left is None:
        return default
    return max(1, min(default, int(left) if left > 0 else 1))


def _run_git(args, repo):
    """Execute a git command in the given repo, with timeout protection.

    The per-call timeout is clamped to the remaining job budget so a single slow git
    cannot carry the whole sweep past its deadline.
    """
    timeout = GIT_TIMEOUT
    left = _time_left()
    if left is not None:
        if left <= 0:
            return subprocess.CompletedProcess(args, returncode=124, stdout="",
                                               stderr="worktree_gc deadline exceeded")
        timeout = max(1, min(GIT_TIMEOUT, int(left)))
    try:
        return subprocess.run(args, cwd=repo, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        # Return a failed-looking result so callers degrade gracefully instead of crashing.
        return subprocess.CompletedProcess(args, returncode=124, stdout="", stderr="git timeout")
    except TypeError:
        return subprocess.run(args, cwd=repo, capture_output=True, text=True)


def _protected_slugs():
    """Branches in active execution or approved integration must not be garbage-collected.

    Returns a set of slug strings, or None if the DB is unreachable.  Callers MUST
    treat None as "unknown" and skip GC entirely — an empty set means "nothing is
    protected" which is a valid (but dangerous if wrong) answer, while None means
    "we couldn't ask."
    """
    slugs = set()
    for state in PROTECTED_STATES:
        try:
            rows = db.select("tasks", {"select": "slug", "state": f"eq.{state}"})
        except Exception:
            return None
        if rows is None:
            return None
        slugs.update(t["slug"] for t in rows)
    for a in db.select("approvals", {"select": "slug,title,kind,status,decided_by", "status": "in.(pending,approved)"}) or []:
        if a.get("kind") not in MERGE_KINDS:
            continue
        if str(a.get("decided_by") or "").startswith(("merge-handler", "train")):
            continue
        slug = a.get("slug")
        if not slug:
            try:
                slug = __import__("approval_merge")._slug_from(a)
            except Exception:
                slug = None
        if slug:
            slugs.add(slug)
    return slugs


def _is_dirty(path):
    """True if the worktree has uncommitted/staged/untracked changes. Fail closed (dirty)."""
    try:
        r = _run_git(["git", "status", "--porcelain"], path)
        if r.returncode != 0:
            return True
        return bool((r.stdout or "").strip())
    except Exception:
        return True


def _recently_active(path):
    """True if the worktree (or its git admin dir/index) was touched within MIN_AGE_MIN.
    Catches freshly created worktrees and ones an executor is actively using, even when
    the task row isn't (yet/anymore) in a protected state. Fail closed (recent)."""
    if MIN_AGE_MIN <= 0:
        return False
    cands = [path, os.path.join(path, ".git")]
    try:
        with open(os.path.join(path, ".git")) as f:
            g = f.read().strip()
        if g.startswith("gitdir:"):
            admin = g.split(":", 1)[1].strip()
            cands += [admin, os.path.join(admin, "index")]
    except Exception:
        return True
    newest = 0.0
    for c in cands:
        try:
            newest = max(newest, os.path.getmtime(c))
        except Exception:
            pass
    if newest == 0.0:
        return True
    return newest > time.time() - MIN_AGE_MIN * 60


# ---------------------------------------------------------------------------
# Orphaned worktree detection (report only)
#
# ADDED 2026-08-24. docs/recovery/reconcile-ee86a2cff698.md describes this module as
# "gain[ing] is_orphaned_worktree, orphaned_worktrees and report_orphaned_worktrees" and
# runner/tests/test_orphaned_worktrees.py was written against them, but the implementation
# never landed here — so the defect that reconciliation documented was still invisible.
#
# A worktree's `.git` is a FILE reading "gitdir: <admin dir>". When that admin dir is
# deleted but the working directory survives, the worktree becomes invisible to everything
# that would clean it up:
#   - `git worktree prune` only removes admin dirs whose WORKING directory is gone. Here it
#     is the other way round, so prune finds nothing and reports success.
#   - gc_repo() reaches _recently_active(), which cannot stat a gitdir that isn't there and
#     fails CLOSED ("recent") — correct as a safety default, but it means an orphan reads as
#     freshly active forever.
#   - any git command run inside the directory dies with "fatal: not a git repository".
#
# These REPORT ONLY. An orphan's working directory is often the last surviving copy of
# whatever was being built when the admin dir went (the evidence case was 29 MB / 3440
# files), so it stays put until a human says otherwise. Detection fails closed toward NOT an
# orphan: a garbage `.git`, a missing path, or an ordinary checkout is never reported,
# because the only safe response to a false positive here is to do nothing.
# ---------------------------------------------------------------------------
def _gitlink_target(path):
    """The admin dir a worktree's `.git` FILE points at, or None.

    Returns None for anything that is not a gitlink: a missing path, an ordinary checkout
    (`.git` is a directory), an unreadable or non-"gitdir:" file. A relative target is
    resolved against the WORKTREE, never the cwd — resolving against the cwd would report
    healthy slots as orphans depending on where the sweep happened to run from.
    """
    if not path:
        return None
    dotgit = os.path.join(path, ".git")
    if os.path.isdir(dotgit) or not os.path.isfile(dotgit):
        return None
    try:
        with open(dotgit, "r", errors="replace") as fh:
            head = fh.read(4096).strip()
    except OSError:
        return None
    if not head.startswith("gitdir:"):
        return None
    target = head.split(":", 1)[1].strip().splitlines()[0].strip() if ":" in head else ""
    if not target:
        return None
    if not os.path.isabs(target):
        target = os.path.join(path, target)
    return os.path.normpath(target)


def is_orphaned_worktree(path):
    """True when *path* is a worktree whose git admin dir has gone. Never raises.

    False for every other shape — missing path, ordinary checkout, no `.git` at all,
    unreadable/garbage gitlink — because an unreadable slot is not the same as an orphaned
    one and only one of them is safe to act on.
    """
    try:
        if not path or not os.path.isdir(path):
            return False
        target = _gitlink_target(path)
        if target is None:
            return False
        return not os.path.exists(target)
    except Exception:
        return False


def orphaned_worktrees(repo, extra_paths=None):
    """Every orphaned worktree reachable from *repo*, plus any *extra_paths* given.

    Returns a list of {"path", "gitdir", "reason"} dicts sorted by path, duplicates
    collapsed. Candidates come from git's own registry, the fleet's `<repo>-wt/<slug>`
    slot layout, and the caller's extra_paths — the last matters because once the main
    repo's records go too, the directory on disk is the only evidence left. Never raises
    on a bad repo argument: detection that can take down its caller just gets wrapped in
    try/except at every call site.
    """
    candidates = []

    def _add(p):
        if p:
            candidates.append(os.path.abspath(str(p)))

    if repo and os.path.isdir(str(repo)):
        try:
            out = _run_git(["git", "worktree", "list", "--porcelain"], str(repo)).stdout or ""
            for line in out.splitlines():
                if line.startswith("worktree "):
                    _add(line[len("worktree "):].strip())
        except Exception:
            pass
        # The per-task slots this module was written to collect: `<repo>-wt/<slug>`.
        wt_root = os.path.abspath(str(repo)).rstrip(os.sep) + "-wt"
        try:
            for name in os.listdir(wt_root):
                _add(os.path.join(wt_root, name))
        except OSError:
            pass
    for p in (extra_paths or []):
        _add(p)

    found, seen = [], set()
    for path in sorted(set(candidates)):
        if path in seen:
            continue
        seen.add(path)
        if not is_orphaned_worktree(path):
            continue
        found.append({"path": path,
                      "gitdir": _gitlink_target(path),
                      "reason": "gitdir missing"})
    return found


def report_orphaned_worktrees(repo, extra_paths=None):
    """One human-readable line per orphan. Empty list when there are none.

    Each line names BOTH halves — the directory to look at and the admin dir that is
    missing — plus why prune cannot help. Without the second half a reader cannot tell an
    orphan from an ordinary stale slot.
    """
    lines = []
    for o in orphaned_worktrees(repo, extra_paths=extra_paths):
        lines.append(
            f"orphaned worktree: {o['path']} -> gitdir {o['gitdir']} is missing; "
            f"`git worktree prune` cannot see it (report only — nothing removed)")
    return lines


def gc_repo(repo):
    if not repo or not os.path.isdir(repo):
        return 0
    main_worktree = os.path.abspath(repo)
    protected = _protected_slugs()
    if protected is None:
        # DB unreachable — fail closed rather than GC everything.
        return 0
    out = _run_git(["git", "worktree", "list", "--porcelain"], repo).stdout
    removed = 0
    path = branch = None
    locked = False
    for line in out.splitlines() + [""]:
        if line.startswith("worktree "):
            path = line[len("worktree "):].strip()
        elif line.startswith("branch "):
            branch = line[len("branch refs/heads/"):].strip()
        elif line.startswith("locked"):
            locked = True
        elif line == "":
            # end of a worktree block
            if _expired():
                print(f"worktree_gc: deadline reached in {repo}; stopping after "
                      f"{removed} removal(s) — the next run resumes")
                break
            if path and branch and branch.startswith("agent/"):
                slug = branch[len("agent/"):]
                if slug not in protected and os.path.abspath(path) != main_worktree:
                    # RECENCY GUARD. Was an inline os.path.getmtime(path) on the
                    # working directory alone, which misses the case
                    # _recently_active() was written for: an executor working in
                    # a slot touches .git/index and the admin dir, not
                    # necessarily the worktree directory itself. _recently_active
                    # checks all four and fails CLOSED when it cannot stat them;
                    # the inline version fell THROUGH to removal on OSError.
                    if _recently_active(path):
                        path = branch = None
                        locked = False
                        continue
                    # DIRTY GUARD. This did not exist. _is_dirty() has been in
                    # this module, documented "fail closed (dirty)", with no
                    # caller anywhere in the product -- while the comment below
                    # claimed "All guards passed (task terminal, clean, aged)".
                    # "clean" was never checked, and the removal three lines down
                    # is `git worktree remove --force`, which discards
                    # uncommitted and untracked work without asking. An agent's
                    # in-progress edits in a slot whose task row had already gone
                    # terminal were deleted with no record that they existed.
                    if _is_dirty(path):
                        print(f"worktree_gc: keeping {path} — uncommitted changes")
                        path = branch = None
                        locked = False
                        continue
                    # DURABILITY: push the branch to origin before reclaiming the worktree, so the
                    # work survives on the remote even if the runner's fail-soft share push never
                    # landed. This is what stops the recover-missing-branch churn at the source —
                    # a GC'd branch is always fetchable by the other Mac / the merge train.
                    if os.environ.get("ORCH_SHARE_AGENT_BRANCHES", "true").lower() in ("true", "1", "yes", "on"):
                        on_origin = _run_git(["git", "show-ref", "--verify", "--quiet",
                                              f"refs/remotes/origin/{branch}"], repo).returncode == 0
                        if not on_origin:
                            _run_git(["git", "push", "-u", "origin", f"{branch}:{branch}"], repo)
                    # All guards passed (task terminal, clean, aged): clear any stale creation
                    # lock left by the runner so a finished worktree can actually be reclaimed.
                    _run_git(["git", "worktree", "unlock", path], repo)
                    if _run_git(["git", "worktree", "remove", "--force", path], repo).returncode == 0:
                        removed += 1
            path = branch = None
            locked = False
    _run_git(["git", "worktree", "prune"], repo)
    return removed


# ---------------------------------------------------------------------------
# Integration worktree sweep
#
# integration_runtime._temporary_worktree_path() creates a one-run slot named
# "<repokey>-run-<pid>-<time_ns>" under .runtime/integration-worktrees/ whenever the
# persistent slot still holds forensic evidence. Nothing ever reclaimed them, so they
# accumulated (4,895 dirs / 67 GB by 2026-08-02). git cannot help here: the slots are
# unregistered on disk, so `git worktree prune` never sees them.
#
# Removal is gated on FOUR independent guards, each of which fails CLOSED:
#   1. age      - slot must be older than INTEGRATION_MAX_AGE_MIN, using the NEWER of the
#                 name-embedded nanosecond stamp and the directory mtime.
#   2. registered - a slot git still knows about is removed via `git worktree remove`,
#                 never by rmtree; if that fails we leave it alone.
#   3. locked   - a locked worktree is never touched (a train may be mid-merge).
#   4. live cwd - a slot with any running process cwd'd inside it is never touched.
# ---------------------------------------------------------------------------
INTEGRATION_DIRNAME = "integration-worktrees"
# Default 4h: comfortably longer than any single merge/release train pass.
INTEGRATION_MAX_AGE_MIN = int(os.environ.get("WORKTREE_GC_INTEGRATION_MAX_AGE_MIN", "240"))
# Safety cap: never reclaim more than this many slots in a single pass.
INTEGRATION_MAX_REMOVALS = int(os.environ.get("WORKTREE_GC_INTEGRATION_MAX_REMOVALS", "1500"))
# Only ever match the generated one-run slot names — persistent slots ("<repokey>" and
# "<repokey>-wt") are deliberately retained for forensic recovery and never matched here.
_RUN_SLOT_RE = re.compile(r"^[0-9a-f]{8,}-run-(?P<pid>\d+)-(?P<ns>\d{16,25})$")
# Per-slot size accounting is off by default: it costs one `du` subprocess per slot.
_MEASURE_EACH = str(os.environ.get("WORKTREE_GC_INTEGRATION_MEASURE", "")).strip().lower() \
    in ("1", "true", "yes", "on")


def _truthy(val, default=False):
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _active_cwds():
    """Realpaths of every running process's cwd. Returns None if it cannot be determined.

    Callers MUST treat None as "unknown" and skip the sweep — deleting a worktree that a
    merge train is actively sitting in would be far worse than leaving disk unreclaimed.
    """
    try:
        r = subprocess.run(["/usr/sbin/lsof", "-a", "-d", "cwd", "-Fn"],
                           capture_output=True, text=True, timeout=_bounded_timeout())
    except Exception:
        return None
    # lsof exits non-zero when some FDs are unreadable; output is still usable.
    if not (r.stdout or "").strip():
        return None
    out = set()
    for line in r.stdout.splitlines():
        if line.startswith("n/"):
            out.add(os.path.realpath(line[1:]))
    return out or None


def _slot_age_seconds(path, name):
    """Seconds since the slot was created, using the CONSERVATIVE (smaller) age.

    The name carries a time.time_ns() stamp, but a slot can be written long after it was
    created, so we take the newer of name-stamp and mtime. An unparseable name degrades to
    mtime alone; an unstattable path degrades to age 0 (i.e. "too new to touch").
    """
    stamps = []
    m = _RUN_SLOT_RE.match(name)
    if m:
        try:
            stamps.append(int(m.group("ns")) / 1e9)
        except (TypeError, ValueError):
            pass
    try:
        stamps.append(os.path.getmtime(path))
    except OSError:
        return 0.0
    if not stamps:
        return 0.0
    return max(0.0, time.time() - max(stamps))


def _dir_bytes(path):
    """Apparent disk usage of a slot, via du -sk. 0 if it cannot be measured."""
    try:
        r = subprocess.run(["du", "-sk", path], capture_output=True, text=True,
                           timeout=_bounded_timeout())
        if r.returncode == 0:
            return int(r.stdout.split()[0]) * 1024
    except Exception:
        pass
    return 0


def _worktree_registry(repo):
    """(registered_realpaths, locked_realpaths) as known to git. None on failure."""
    r = _run_git(["git", "worktree", "list", "--porcelain"], repo)
    if r.returncode != 0:
        return None, None
    registered, locked, cur = set(), set(), None
    for line in (r.stdout or "").splitlines():
        if line.startswith("worktree "):
            cur = os.path.realpath(line[len("worktree "):].strip())
            registered.add(cur)
        elif line.startswith("locked") and cur:
            locked.add(cur)
        elif not line.strip():
            cur = None
    return registered, locked


def gc_integration_worktrees(repo, dry_run=False):
    """Reclaim orphaned one-run integration slots. Returns (removed, bytes, skipped)."""
    home = os.environ.get(
        "CLAUDE_ORCH_HOME", os.path.join(os.path.abspath(repo), ".runtime"))
    root = os.path.join(home, INTEGRATION_DIRNAME)
    if not os.path.isdir(root):
        return 0, 0, 0

    registered, locked = _worktree_registry(repo)
    if registered is None:
        print("worktree_gc: integration sweep SKIPPED — `git worktree list` failed")
        return 0, 0, 0

    cwds = _active_cwds()
    if cwds is None:
        print("worktree_gc: integration sweep SKIPPED — cannot enumerate process cwds")
        return 0, 0, 0

    try:
        names = sorted(os.listdir(root))
    except OSError as e:
        print(f"worktree_gc: integration sweep SKIPPED — cannot list {root}: {e}")
        return 0, 0, 0

    removed = freed = skipped = 0
    min_age = INTEGRATION_MAX_AGE_MIN * 60
    for name in names:
        if removed >= INTEGRATION_MAX_REMOVALS:
            print(f"worktree_gc: integration sweep hit safety cap "
                  f"({INTEGRATION_MAX_REMOVALS}); re-run to continue")
            break
        if not _RUN_SLOT_RE.match(name):
            continue  # persistent slot — never swept
        if _expired():
            print(f"worktree_gc: deadline reached during the integration sweep of {repo}; "
                  f"stopping after {removed} slot(s) — the next run resumes")
            break
        path = os.path.join(root, name)
        if not os.path.isdir(path) or os.path.islink(path):
            continue
        real = os.path.realpath(path)

        if real in locked:
            skipped += 1
            continue
        if _slot_age_seconds(path, name) < min_age:
            skipped += 1
            continue
        # Any live process sitting in (or under) this slot means a train is using it.
        if any(c == real or c.startswith(real + os.sep) for c in cwds):
            print(f"worktree_gc: integration slot IN USE, keeping {name}")
            skipped += 1
            continue

        # Per-slot `du` costs one subprocess per slot; with thousands of orphans that
        # dominates the sweep. Only measure when we actually want the number (dry-run
        # preview, or an explicit opt-in) — the caller reports the authoritative
        # before/after total for the whole root either way.
        size = _dir_bytes(path) if (dry_run or _MEASURE_EACH) else 0
        if dry_run:
            print(f"worktree_gc: [dry-run] would reclaim {name} ({size / 1e9:.3f} GB)")
            removed += 1
            freed += size
            continue

        if real in registered:
            # Registered: let git do the bookkeeping. If it refuses, leave it be.
            if _run_git(["git", "worktree", "remove", "--force", path], repo).returncode != 0:
                skipped += 1
                continue
        else:
            # True orphan: git has no record, so plain removal is the only option.
            try:
                shutil.rmtree(path)
            except OSError as e:
                print(f"worktree_gc: could not remove {name}: {e}")
                skipped += 1
                continue
        removed += 1
        freed += size

    if removed and not dry_run:
        _run_git(["git", "worktree", "prune"], repo)
    return removed, freed, skipped


#: Pack a repo's refs once it has more than this many LOOSE ones. Every git command that
#: enumerates refs — and the train runs several per candidate — walks the loose ref tree
#: file by file, so the cost is linear in a number that only ever grows.
#:
#: Measured on ~/Documents/smarter on 2026-09-01: 7,463 loose refs, almost all `agent/*`
#: branches from finished tasks. `git for-each-ref` took 15s; after `git pack-refs --all`
#: it took 6s, with 3 loose refs left and all 20,614 refs still resolvable. Nothing in
#: this repo packed refs — `grep -rn pack-refs runner/*.py` found no call site at all,
#: and `git gc --auto` never runs here because the fleet never invokes gc.
#:
#: Packing is not pruning: no ref is deleted, they move from .git/refs/** into
#: .git/packed-refs and resolve identically. Set WORKTREE_GC_PACK_REFS_MIN=0 to disable.
PACK_REFS_MIN_LOOSE = int(os.environ.get("WORKTREE_GC_PACK_REFS_MIN", "500"))


def _loose_ref_count(repo, cap=20000):
    """How many loose refs this repo has, counted cheaply and bounded."""
    root = os.path.join(repo, ".git", "refs")
    if not os.path.isdir(root):
        return 0          # a worktree or a bare/odd layout; not our business
    n = 0
    for _dirpath, _dirnames, filenames in os.walk(root):
        n += len(filenames)
        if n >= cap:
            return n
    return n


def pack_refs(repo, dry_run=False):
    """Pack loose refs when there are enough of them to matter. Returns (before, after).

    Fail-soft in every direction: a repo that is missing, is not a git dir, or whose
    pack-refs fails is left exactly as it was. This is an optimisation, and an
    optimisation must never be the reason a sweep stops.
    """
    if PACK_REFS_MIN_LOOSE <= 0 or not repo or not os.path.isdir(repo):
        return (0, 0)
    before = _loose_ref_count(repo)
    if before < PACK_REFS_MIN_LOOSE or dry_run:
        return (before, before)
    try:
        r = _run_git(["git", "pack-refs", "--all"], repo)
        if getattr(r, "returncode", 1) != 0:
            return (before, before)
    except Exception:
        return (before, before)
    return (before, _loose_ref_count(repo))


def run(dry_run=False, max_seconds=None):
    """Sweep every project's stale worktrees under a hard wall-clock budget.

    `max_seconds` (default WORKTREE_GC_MAX_SECONDS, 600) bounds the WHOLE job, not just
    one subprocess. Pass 0 to disable the budget. The sweep is idempotent and resumable,
    so stopping early is safe: the singleton lock is released and the next invocation
    picks up the projects this one did not reach.
    """
    budget = MAX_SECONDS if max_seconds is None else max_seconds
    previous = _start_deadline(budget)
    started = time.time()
    total = 0
    int_removed = int_freed = 0
    deadline_hit = False
    try:
        for p in db.select("projects", {"select": "name,repo_path"}) or []:
            repo = p.get("repo_path", "")
            if _expired():
                deadline_hit = True
                print(f"worktree_gc: {budget}s budget exhausted before {p.get('name')}; "
                      f"stopping cleanly — the next run continues from here")
                break
            try:
                n = 0 if dry_run else gc_repo(repo)
                if n:
                    print(f"worktree_gc: {p['name']} removed {n} stale worktree(s)")
                total += n
            except Exception as e:
                print(f"worktree_gc: {p.get('name')} error {e}")
            # Orphaned integration slots are a separate leak: unregistered dirs that
            # `git worktree prune` is structurally unable to see.
            try:
                r, b, s = gc_integration_worktrees(repo, dry_run=dry_run)
                if r or s:
                    print(f"worktree_gc: {p['name']} integration slots "
                          f"reclaimed={r} skipped(in-use/young/locked)={s}")
                int_removed += r
                int_freed += b
            except Exception as e:
                print(f"worktree_gc: {p.get('name')} integration sweep error {e}")
            # Loose refs are the third leak in the same family: nothing removes them,
            # every ref-enumerating git command pays for them, and the train runs
            # several per candidate. See pack_refs.
            try:
                _b, _a = pack_refs(repo, dry_run=dry_run)
                if _b != _a:
                    print(f"worktree_gc: {p['name']} packed refs {_b} -> {_a} loose")
            except Exception as e:
                print(f"worktree_gc: {p.get('name')} pack-refs error {e}")
    finally:
        # ALWAYS clear the budget, including on an unexpected raise. A leaked deadline
        # would make every later in-process call believe it had no time left.
        _clear_deadline(previous)
    elapsed = time.time() - started
    print(f"worktree_gc: removed {total} stale worktree(s) across repos "
          f"in {elapsed:.1f}s{' (DEADLINE HIT — partial sweep)' if deadline_hit else ''}")
    if int_removed:
        print(f"worktree_gc: reclaimed {int_removed} integration slot(s)"
              + (f", {int_freed / 1e9:.2f} GB" if int_freed else ""))
    return total


if __name__ == "__main__":
    _dry = "--dry-run" in sys.argv[1:] or _truthy(os.environ.get("WORKTREE_GC_DRY_RUN"))
    # `--integration-only <repo>` sweeps one repo's integration slots without touching
    # agent worktrees or needing the projects table.
    if "--integration-only" in sys.argv[1:]:
        i = sys.argv.index("--integration-only")
        _repo = sys.argv[i + 1] if len(sys.argv) > i + 1 else os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
        _r, _b, _s = gc_integration_worktrees(_repo, dry_run=_dry)
        print(f"worktree_gc: integration slots reclaimed={_r} skipped={_s}"
              + (f" freed={_b / 1e9:.2f} GB" if _b else ""))
    else:
        run(dry_run=_dry)

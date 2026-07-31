#!/usr/bin/env python3
"""sentinel.py — the fleet's self-healing layer. Runs every ~2 min (launchd job on Mac 1,
runner periodic on every machine) and auto-remediates the failure modes that previously
required a human session, so the orchestrator never sits broken:

  1. DB outage       -> detects Supabase down; after 3 consecutive misses switches to OFFLINE
                        MODE: runs the DB-independent git deploy sweep (rate-limited) so
                        deployments continue; on recovery re-ingests intake drops and
                        re-asserts the fleet_config baseline.
  2. Checkout drift  -> main repo parked on an agent branch (aborted rebase etc.): return to
                        the canonical base branch, ff-pull. Stashes TRACKED dirt only if the
                        switch is actually blocked, and never untracked files. Escalates after
                        3 consecutive failures instead of retrying silently forever.
                        (Root cause of the 2026-07-08/09 stale-code incidents; its own -u stash
                        was the root cause of the 07-08..16 intake-drop losses.)
  3. Runner health   -> 0 runners: kickstart the launchd service. >1 runner/keepalive:
                        kill the orphans (SIGKILL; supervisor-lock holder wins).
  4. RAM clamp       -> free RAM under floor+2GB with a big local model loaded: unload the
                        largest Ollama model (the codestral/qwen 'limit=1' clamp).
  5. Stale code      -> origin/base ahead of local: ff-pull; runner booted on an older commit:
                        request cooperative restart; request ignored >45 min: cycle the runner
                        process (keepalive respawns it on current code).
  6. Train silence   -> DB up but no merge_train output for 30+ min: fire one train run.
  7. Stash pileup    -> ALERT ONLY (never auto-pops/drops): checkout_guard and other flows
                        (pre-runner-restart, pre-force-merge, cowork-session auto-pull, ...)
                        stash and never reconcile. Found 592 accumulated 2026-07-29, oldest from
                        2026-07-12 — nobody had ever looked. Logs + emits past a threshold so
                        this can't silently regrow unnoticed; reconciling old stashes against a
                        moved-on codebase is a human/agent triage call, not a bot's to make.

Every action is journaled to .runtime/sentinel.log + .runtime/sentinel_state.json.
Fail-soft everywhere: a sentinel bug must never take the fleet down with it.
"""
import datetime
import glob
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPO = os.path.dirname(HERE)
import events
RUNTIME = os.path.join(REPO, ".runtime")
STATE_PATH = os.path.join(RUNTIME, "sentinel_state.json")
LOG_PATH = os.path.join(RUNTIME, "sentinel.log")
BASE_BRANCH = os.environ.get("ORCH_BASE_BRANCH", "master")
SERVICE = os.environ.get("ORCH_LAUNCHD_SERVICE", "com.claudeorchestrator.runner")
DB_DOWN_THRESHOLD = int(os.environ.get("SENTINEL_DB_DOWN_THRESHOLD", "3"))
SWEEP_MIN_INTERVAL_S = int(os.environ.get("SENTINEL_SWEEP_INTERVAL_S", "2700"))
TRAIN_STALE_S = int(os.environ.get("SENTINEL_TRAIN_STALE_S", "1800"))
RESTART_STALE_S = int(os.environ.get("SENTINEL_RESTART_STALE_S", "2700"))
RAM_GUARD_FREE_GB = float(os.environ.get("SENTINEL_RAM_GUARD_FREE_GB", "6"))


def log(action, detail=""):
    line = f"{datetime.datetime.utcnow().isoformat()}Z sentinel {action} {str(detail)[:240]}"
    print(line, flush=True)
    try:
        os.makedirs(RUNTIME, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def emit(kind, **fields):
    """Emit a structured event to the event stream (along with log)."""
    return events.emit(f"sentinel:{kind}", **fields)


def load_state():
    try:
        return json.load(open(STATE_PATH))
    except Exception:
        return {}


def save_state(st):
    try:
        os.makedirs(RUNTIME, exist_ok=True)
        json.dump(st, open(STATE_PATH, "w"), indent=1)
    except OSError:
        pass


def sh(*args, timeout=60, cwd=REPO):
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, timeout=timeout)


def git(*args, timeout=120):
    return sh("git", *args, timeout=timeout)


# ── 1. DB probe + offline mode ────────────────────────────────────────────────

def db_up():
    try:
        os.environ.setdefault("ORCH_SUPABASE_TIMEOUT", "15")
        import db
        db.select("tasks", {"select": "id", "limit": "1"})
        return True
    except Exception as e:
        log("db-down", str(e)[:80])
        return False


def offline_deploy_sweep(st):
    last = float(st.get("last_sweep_t", 0))
    if time.time() - last < SWEEP_MIN_INTERVAL_S:
        return
    st["last_sweep_t"] = time.time()
    script = os.path.join(REPO, "scripts", "git_deploy_sweep.py")
    if not os.path.isfile(script):
        return
    log("offline-sweep", "DB down — running DB-independent deploy sweep in background")
    subprocess.Popen([sys.executable, script],
                     stdout=open(os.path.join(RUNTIME, "git_deploy_sweep.out"), "a"),
                     stderr=subprocess.STDOUT, cwd=REPO)


def dedupe_queued():
    """Quarantine duplicate QUEUED rows sharing (project, slug) — the intake path is not
    concurrency-safe across two Macs + recovery hooks racing the same drop (observed 5x
    duplication on 2026-07-09). Keep the newest row per slug."""
    import collections
    import db
    rows = db.select("tasks", {"select": "id,slug,project_id,created_at",
                               "state": "eq.QUEUED", "limit": "4000",
                               "order": "created_at.desc"}) or []
    groups = collections.defaultdict(list)
    for r in rows:
        groups[(r.get("project_id"), r.get("slug"))].append(r)
    q = 0
    culprits = []
    for (pid, slug), g in groups.items():
        if len(g) <= 1:
            continue
        # capture the source note of a survivor so the enqueuer that keeps making dupes is named
        src = (g[0].get("note") or "")[:50]
        culprits.append(f"{slug[:32]}(x{len(g)}|{src})")
        for dup in g[1:]:
            db.update("tasks", {"id": dup["id"]},
                      {"state": "QUARANTINED",
                       "note": "sentinel-dedupe: duplicate QUEUED row; kept newest"})
            q += 1
    if q:
        log("dedupe", f"quarantined {q} dup rows; sources: {'; '.join(culprits[:6])}")


def on_db_recovery():
    log("db-recovered", "re-ingesting intake + re-asserting fleet_config baseline")
    try:
        subprocess.run([sys.executable, os.path.join(HERE, "intake_watcher.py")],
                       capture_output=True, timeout=300, cwd=HERE)
    except Exception as e:
        log("intake-ingest-failed", e)
    try:
        dedupe_queued()
    except Exception as e:
        log("dedupe-failed", e)
    try:
        baseline = os.path.join(REPO, "scripts", "fleet_config_baseline.json")
        if os.path.isfile(baseline):
            import db
            for k, v in json.load(open(baseline)).items():
                db.insert("fleet_config", {"key": k, "value": str(v)}, upsert=True)
            log("fleet-config-asserted", "baseline keys pushed")
    except Exception as e:
        log("fleet-config-failed", e)
    try:
        import sweep_reconciler
        result = sweep_reconciler.reconcile()
        log("sweep-reconciled", f"deployed={result['deployed']} annotated={result['annotated']}")
    except Exception as e:
        log("sweep-reconcile-failed", e)


# ── 2. checkout drift guard ───────────────────────────────────────────────────

DRIFT_ALERT_AFTER = int(os.environ.get("SENTINEL_DRIFT_ALERT_AFTER", "3"))


def _base_held_by_worktree(stderr):
    """True when git refused the checkout because another worktree holds the branch."""
    return "already used by worktree" in (stderr or "")


def _worktree_holding(branch):
    """Path of the worktree that has `branch` checked out, or None."""
    out = git("worktree", "list", "--porcelain").stdout
    path = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):].strip()
        elif line.startswith("branch ") and path:
            if line[len("branch "):].strip() in (f"refs/heads/{branch}", branch):
                if os.path.realpath(path) != os.path.realpath(REPO):
                    return path
    return None


def checkout_guard(st=None):
    """Return the primary checkout to BASE_BRANCH after drift.

    NEVER stashes untracked files. `git stash push -u` here destroyed 282 batches of
    queued work (2026-07-08..16): every intake drop landing in the ~2min window between
    a drop and a sentinel tick was swept into a stash and silently lost. Untracked files
    are also not what blocks a branch switch, so -u bought nothing. If a genuine untracked
    collision ever does block the checkout, we now alert instead of destroying the file.
    """
    st = {} if st is None else st
    gitdir = os.path.join(REPO, ".git")
    if any(os.path.isdir(os.path.join(gitdir, d)) for d in ("rebase-merge", "rebase-apply")):
        return  # a rebase is genuinely in progress somewhere — do not interfere
    branch = git("branch", "--show-current").stdout.strip()
    if branch == BASE_BRANCH:
        st.pop("drift_fail_count", None)
        st.pop("drift_branch", None)
        git("pull", "--ff-only", "origin", BASE_BRANCH, timeout=180)
        return
    log("checkout-drift", f"main checkout on '{branch}' — restoring {BASE_BRANCH}")

    # Try the switch first: a clean-enough tree needs no stash at all.
    r = git("checkout", BASE_BRANCH)

    if r.returncode != 0 and _base_held_by_worktree(r.stderr):
        # git refuses: "fatal: 'master' is already used by worktree at <path>".
        # No amount of stashing fixes this, so the old code would have retried
        # forever. Observed 2026-07-16: a leftover worktree holding master blocked
        # every restore for ~10min while drift kept re-parking the tree.
        # A stale admin entry is safely reclaimable; a live one is not ours to yank.
        git("worktree", "prune")
        r = git("checkout", BASE_BRANCH)
        if r.returncode != 0:
            holder = _worktree_holding(BASE_BRANCH)
            emit("base-branch-held", branch=BASE_BRANCH, holder=holder)
            log("base-branch-held",
                f"cannot restore {BASE_BRANCH}: held by worktree at {holder or 'unknown'} — "
                f"remove it (git worktree remove) or the primary checkout stays drifted")
            return

    if r.returncode != 0:
        dirty = git("status", "--porcelain", "--untracked-files=no").stdout.strip()
        if dirty:
            # SELF-MODIFICATION GUARD (2026-07-30): stashing here silently swallowed operator
            # hotfixes to the fleet's own critical path — twice in one night, including the fix
            # for the merge-resolver bug that was actively wiping improvements. Stashes are
            # write-only (nothing in this codebase ever pops one), so a stash IS a loss.
            # New behavior: if any PROTECTED path is dirty, COMMIT the work to a hotfix branch
            # (recoverable, visible, mergeable) instead of stashing it. Only non-protected dirt
            # falls back to the old stash path.
            protected_dirty = [ln[3:] for ln in dirty.splitlines()
                               if ln[3:].startswith(("runner/", "scripts/", "web/server/"))
                               or ln[3:].endswith((".py", ".sh"))]
            if protected_dirty:
                hb = f"hotfix/sentinel-rescue-{int(time.time())}"
                git("stash", "push", "-m", f"pre-rescue-{int(time.time())}")   # atomic handoff
                git("checkout", "-b", hb)
                git("stash", "pop")
                git("add", "-A")
                git("-c", "user.name=kalepasch1", "-c", "user.email=kalepasch@gmail.com",
                    "commit", "-m",
                    f"rescue: operator/agent changes preserved by sentinel ({len(protected_dirty)} file(s))")
                emit("hotfix-rescued", branch=hb, files=len(protected_dirty))
                log("hotfix-rescued",
                    f"preserved {len(protected_dirty)} protected file(s) on {hb} instead of stashing — "
                    f"review and merge (git log {hb})")
                r = git("checkout", BASE_BRANCH)
            else:
                git("stash", "push", "-m", f"sentinel-drift-{branch}-{int(time.time())}")
                r = git("checkout", BASE_BRANCH)

    if r.returncode != 0:
        # Still stuck. Count consecutive failures and escalate rather than spin silently:
        # the old code logged and returned every 2min for 8 days with nobody notified.
        n = int(st.get("drift_fail_count", 0)) + 1 if st.get("drift_branch") == branch else 1
        st["drift_fail_count"] = n
        st["drift_branch"] = branch
        log("checkout-failed", f"attempt {n} on '{branch}': {r.stderr[-160:]}")
        if n >= DRIFT_ALERT_AFTER:
            emit("checkout-wedged", branch=branch, attempts=n, stderr=r.stderr[-400:])
            log("checkout-wedged",
                f"primary checkout stuck on '{branch}' after {n} attempts — human needed")
        return

    st.pop("drift_fail_count", None)
    st.pop("drift_branch", None)
    git("pull", "--ff-only", "origin", BASE_BRANCH, timeout=180)
    log("checkout-restored", BASE_BRANCH)


# ── 2a2. stash drift alarm (never touches stashes — see checkout_guard's stash comment) ─

STASH_ALERT_THRESHOLD = int(os.environ.get("SENTINEL_STASH_ALERT_THRESHOLD", "20"))
STASH_ALERT_INTERVAL_S = int(os.environ.get("SENTINEL_STASH_ALERT_INTERVAL_S", "21600"))


def stash_drift_guard(st=None):
    """Alert (never auto-pop/drop) when unreconciled git stashes pile up.

    checkout_guard creates a named stash whenever a drifted checkout can't switch back to
    BASE_BRANCH cleanly; other flows (pre-runner-restart, pre-force-merge, pre-push-orchestrator,
    cowork-session auto-pull, ...) create their own. Nothing anywhere in this codebase ever pops,
    applies, or drops a stash — it's a write-only pile. Found 592 on 2026-07-29, oldest from
    2026-07-12, none ever reconciled. Auto-popping old stashes against a codebase that's moved on
    is its own hazard (stale/superseded diffs re-landing on top of newer work), so this only
    alerts past a threshold; reconciliation stays a human (or explicitly-requested agent) call.
    """
    st = {} if st is None else st
    r = git("stash", "list")
    if r.returncode != 0:
        return
    count = len([l for l in r.stdout.splitlines() if l.strip()])
    st["stash_count"] = count
    if count >= STASH_ALERT_THRESHOLD:
        last_alert = float(st.get("stash_alert_last", 0))
        if time.time() - last_alert > STASH_ALERT_INTERVAL_S:
            emit("stash-pileup", count=count, threshold=STASH_ALERT_THRESHOLD)
            log("stash-pileup", f"{count} unreconciled git stashes (threshold {STASH_ALERT_THRESHOLD}) "
                                 f"— nothing auto-pops these; needs a human/agent triage pass")
            st["stash_alert_last"] = time.time()


def wip_stash_rescue(st=None):
    """MAKE THE IMPROVEMENT-WIPE CLASS UNLOSEABLE (operator directive 2026-07-30).

    Three times now, some code path stashed dirty operator work on the main checkout and never
    popped it (the third culprit — self_healing_merge's classify — is root-cause-fixed to use
    ephemeral worktrees). But the operator's requirement is that this CANNOT recur, and no grep can
    prove a negative about future code. So: defense in depth. Any anonymous stash on the base
    branch ("WIP on {base}" — the default label of a bare `git stash`, which no legitimate fleet
    flow produces; every intentional stash here is `-m`-labeled) is auto-PRESERVED by pointing a
    branch at the stash commit: `hotfix/stash-rescue-<ts>`. A stash is just an unreachable commit —
    branching it makes the work permanently reachable, visible in `git branch`, diffable, and
    mergeable, even if the stash entry is later dropped. We never pop, never drop, never touch the
    working tree — pure preservation plus a loud alert.

    Idempotent: a stash whose commit already has a rescue branch pointing at it is skipped.
    """
    st = {} if st is None else st
    r = git("stash", "list", "--format=%gd %H %gs")
    if r.returncode != 0:
        return
    rescued = 0
    for line in r.stdout.splitlines():
        parts = line.strip().split(" ", 2)
        if len(parts) < 3:
            continue
        ref, sha, subject = parts
        if not subject.startswith(f"WIP on {BASE_BRANCH}"):
            continue                     # labeled/intentional stashes: alarm-only, never touched
        held = git("branch", "--points-at", sha)
        if "stash-rescue" in (held.stdout or ""):
            continue                     # already preserved
        hb = f"hotfix/stash-rescue-{int(time.time())}-{sha[:8]}"
        b = git("branch", hb, sha)
        if b.returncode == 0:
            rescued += 1
            emit("wip-stash-rescued", branch=hb, stash=ref, sha=sha[:12])
            log("wip-stash-rescued",
                f"anonymous '{subject[:60]}' ({ref}) preserved as {hb} — some code path stashed "
                f"work on {BASE_BRANCH} without a label; find and fix the caller")
    if rescued:
        st["wip_rescued_total"] = int(st.get("wip_rescued_total", 0)) + rescued


def stranded_commit_rescue(st=None):
    """MAKE THE BRANCH-STRANDING CLASS SELF-ANNOUNCING (operator directive 2026-07-31).

    The 5bc36d6a incident: a committer wrote 15 session files to a side branch
    (mac1-wip-*) that nothing ever merged; master advanced independently and the
    working tree silently lost ~10 improvements until a human audit found them.
    wip_stash_rescue preserves STASHES; this covers its blind spot — COMMITS
    reachable only from non-agent side branches. (agent/* branches are the
    merge-train's job and are excluded; it already sweeps them.)

    For every local branch not named agent/* or the base branch whose tip
    (a) is NOT an ancestor of the base branch, (b) touches runner/*.py or web/,
    and (c) is older than SENTINEL_STRANDED_MIN_AGE_H hours: emit a loud alert +
    a coordination event so the triage layer surfaces it in the progress console.
    Alert-only (no auto-merge): the correct merge is 3-way and judgment-laden;
    the alert names the exact branch, tip, and files so remediation is one queued
    task, not an archaeology dig.
    """
    st = {} if st is None else st
    min_age_h = float(os.environ.get("SENTINEL_STRANDED_MIN_AGE_H", "2"))
    base = os.environ.get("ORCH_DEFAULT_BRANCH", "master")
    r = git("for-each-ref", "refs/heads", "--format=%(refname:short) %(objectname) %(committerdate:unix)")
    if r.returncode != 0:
        return
    found = []
    now = time.time()
    for line in (r.stdout or "").splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        name, sha, cdate = parts
        if name == base or name.startswith("agent/"):
            continue
        try:
            if (now - float(cdate)) < min_age_h * 3600:
                continue
        except ValueError:
            continue
        anc = git("merge-base", "--is-ancestor", sha, base)
        if anc.returncode == 0:
            continue  # already merged
        mb = git("merge-base", base, sha).stdout.strip()
        changed = git("diff", "--name-only", mb or base, sha).stdout or ""
        touched = [f for f in changed.splitlines()
                   if f.startswith("runner/") or f.startswith("web/")]
        if not touched:
            continue
        found.append({"branch": name, "tip": sha[:10], "files": len(touched),
                      "sample": touched[:5]})
    if found:
        for f in found:
            log(f"STRANDED-COMMIT ALERT: branch {f['branch']} ({f['tip']}) holds "
                f"{f['files']} runner/web files not in {base} — sample {f['sample']}")
        try:
            import db as _db, json as _json
            _db.insert("coordination_tasks", {
                "task_type": "stranded_commit_alert",
                "payload": _json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                        "base": base, "branches": found[:20]})[:8000]},
                       upsert=False)
        except Exception:
            pass
    st["stranded_branches"] = len(found)


# ── 2b. nested-worktree hygiene ───────────────────────────────────────────────

QUARANTINE = os.path.join(os.path.dirname(REPO), "_quarantine")


SILENT_FAIL_ERR_GROWTH = int(os.environ.get("SENTINEL_SILENT_FAIL_ERR_BYTES", "20000"))
SILENT_FAIL_ALERT_COOLDOWN_S = int(os.environ.get("SENTINEL_SILENT_FAIL_COOLDOWN_S", "21600"))  # 6h


def silent_failure_guard(st=None):
    """Alert when a scheduled job is FAILING SILENTLY: its .err log grows while its .log shows
    no productive work.

    WHY THIS EXISTS (2026-07-30): silent accumulation is this system's signature failure mode.
    Four instances found in a single night, every one of them invisible for days-to-weeks:
      * merge_train crashed on EVERY run for 3 weeks (194 identical tracebacks) — integration
        dead, branches piling up, nothing alerted.
      * committees (the Consilium) crashed every 15 min into a 308KB .err file — a share of all
        expert debates silently dropped.
      * checkout_guard wrote 315 stashes nothing ever popped — real work parked and forgotten.
      * cx_auto_adr re-emitted the same ADRs daily — 49 files for 17 decisions.
    Each looked harmless in isolation; collectively they cost weeks. A job that runs and fails
    quietly is strictly worse than one that never runs, because its logs look reassuring
    ("handled 0") while its error stream grows unread. This guard makes that impossible.

    Alert-only by design (never restarts/disables a job): the failure modes are too varied for a
    safe auto-action, and a wrong auto-action here would be worse than the silence.
    """
    st = st if st is not None else {}
    logs_dir = os.path.join(RUNTIME, "logs")
    if not os.path.isdir(logs_dir):
        return
    prev = st.get("silent_fail_sizes") or {}
    now_sizes, offenders = {}, []
    for err_path in glob.glob(os.path.join(logs_dir, "*.err")):
        job = os.path.basename(err_path)[:-4]
        try:
            err_sz = os.path.getsize(err_path)
        except OSError:
            continue
        now_sizes[job] = err_sz
        grew = err_sz - int(prev.get(job, err_sz))
        if grew < SILENT_FAIL_ERR_GROWTH:
            continue
        # the .err grew materially — did the job also produce productive output?
        out_path = os.path.join(logs_dir, f"{job}.log")
        productive = False
        try:
            with open(out_path, "r", errors="replace") as fh:
                tail = fh.readlines()[-40:]
            # "productive" = any recent line that isn't a zero-work heartbeat
            for ln in tail:
                s = ln.strip().lower()
                if not s:
                    continue
                if re.search(r"\b(handled|processed|found|merged|created|archived)\s+0\b", s):
                    continue
                productive = True
                break
        except OSError:
            productive = False
        if not productive:
            offenders.append((job, grew, err_sz))

    st["silent_fail_sizes"] = now_sizes
    if not offenders:
        return
    last = float(st.get("silent_fail_alert_last", 0))
    if (time.time() - last) < SILENT_FAIL_ALERT_COOLDOWN_S:
        return
    st["silent_fail_alert_last"] = time.time()
    names = ", ".join(f"{j}(+{g//1000}KB)" for j, g, _ in offenders[:6])
    emit("silent-failure", jobs=[j for j, _, _ in offenders], count=len(offenders))
    log("silent-failure",
        f"{len(offenders)} job(s) failing silently — errors growing, no productive output: {names}. "
        f"Check .runtime/logs/<job>.err")


def nested_worktree_guard():
    """Quarantine agent worktrees nested inside the primary checkout.

    A worktree here works until it is pruned; then its `.git` gitlink points at a
    gitdir that no longer exists and EVERY `git status` in the repo dies with
    'fatal: not a git repository'. That silently disables the sentinel's own
    dirty-check, the merge pipeline, and anything else shelling out to git.
    Worktrees belong in the sibling `<repo>-wt/` (see worktree_isolation.py).

    We move rather than delete: a dangling worktree has no gitdir, so git cannot
    tell us whether it holds uncommitted work. Never destroy what we can't inspect.
    """
    for root in (os.path.join(REPO, os.path.basename(REPO) + "-wt"),):
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            wt = os.path.join(root, name)
            link = os.path.join(wt, ".git")
            if not os.path.isfile(link):
                continue
            try:
                with open(link) as f:
                    gitdir = f.read().strip().removeprefix("gitdir:").strip()
            except OSError:
                continue
            if os.path.isdir(gitdir):
                log("nested-worktree-live", f"{wt} is nested but still live — leaving alone")
                emit("nested-worktree-live", path=wt)
                continue
            try:
                os.makedirs(QUARANTINE, exist_ok=True)
                dest = os.path.join(QUARANTINE, f"{name}-{int(time.time())}")
                os.rename(wt, dest)
                log("nested-worktree-quarantined", f"{wt} (dangling gitdir) -> {dest}")
                emit("nested-worktree-quarantined", path=wt, dest=dest)
            except OSError as e:
                log("nested-worktree-quarantine-failed", f"{wt}: {e}")


# ── 3. runner singleton guard ─────────────────────────────────────────────────

def _pids(pattern):
    out = sh("pgrep", "-f", pattern).stdout.split()
    me = str(os.getpid())
    return [p for p in out if p != me]


def runner_guard(st):
    runners = _pids("MacOS/Python runner.py") + _pids("python3 runner.py")
    keepalives = _pids("keepalive.sh")
    if not runners:
        misses = int(st.get("runner_misses", 0)) + 1
        st["runner_misses"] = misses
        if misses >= 2:  # ~4 min without a runner
            log("runner-missing", f"kickstarting {SERVICE}")
            sh("launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{SERVICE}")
            st["runner_misses"] = 0
        return
    st["runner_misses"] = 0
    if len(runners) > 1:
        # keep the newest (freshest code), kill the rest
        by_start = []
        for p in runners:
            et = sh("ps", "-o", "etimes=", "-p", p).stdout.strip()
            try:
                by_start.append((int(et), p))
            except ValueError:
                continue
        by_start.sort()
        for _, p in by_start[1:]:
            log("extra-runner-killed", p)
            sh("kill", "-9", p)
    if len(keepalives) > 1:
        lock_pid = ""
        try:
            lock_pid = open(os.path.join(RUNTIME, "keepalive.lock", "pid")).read().strip()
        except OSError:
            pass
        for p in keepalives:
            if lock_pid and p != lock_pid:
                log("extra-keepalive-killed", p)
                sh("kill", "-9", p)
    # LIVENESS (not just existence): a runner process can be ALIVE but WEDGED — its main
    # claim/heartbeat loop blocked while the periodic scheduler keeps forking jobs. Detect it
    # by heartbeat staleness for THIS host and cycle the process (keepalive respawns fresh).
    # Root cause of the 2026-07-09 incident: runner hung ~9h, no heartbeat, 0 merges, queue grew.
    try:
        import socket, db
        host = socket.gethostname()
        rows = db.select("runner_heartbeats", {"select": "hostname,last_seen",
                                               "order": "last_seen.desc", "limit": "50"}) or []
        mine = [r for r in rows if r.get("hostname") == host]  # primary row (lanes are suffixed)
        stale_s = int(os.environ.get("SENTINEL_HEARTBEAT_STALE_S", "900"))
        if mine:
            last = str(mine[0].get("last_seen") or "").replace("Z", "+00:00")
            try:
                import datetime as _dt
                dt = _dt.datetime.fromisoformat(last)
                nowu = _dt.datetime.now(_dt.timezone.utc) if dt.tzinfo else _dt.datetime.utcnow()
                age = (nowu - dt).total_seconds()
            except Exception:
                age = 0
            if age > stale_s and runners:
                log("runner-wedged", f"heartbeat stale {int(age)}s but process alive — cycling {runners[0]}")
                sh("kill", "-9", runners[0])  # keepalive respawns on current code
    except Exception as e:
        log("liveness-check-error", e)


# ── 3b. zombie agent reaper ───────────────────────────────────────────────────

def zombie_agent_reaper():
    """Kill orphaned coding-agent processes that outran any sane task timeout. A single agent
    task never legitimately runs for hours; a multi-hour gemini/aider/codex/claude-exec is a
    stuck zombie holding RAM (2026-07-09: a gemini ran 35h reserving a 24GB heap). Never touch
    the orchestrator's own python runner or this sentinel."""
    max_min = int(os.environ.get("SENTINEL_AGENT_MAX_MIN", "150"))
    out = sh("ps", "-axo", "pid=,etimes=,command=").stdout.splitlines()
    reaped = 0
    for line in out:
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        pid, etimes, cmd = parts
        try:
            secs = int(etimes)
        except ValueError:
            continue
        if secs < max_min * 60:
            continue
        low = cmd.lower()
        is_agent = any(t in low for t in ("/gemini", "bin/gemini", "aider", "codex exec",
                                          "claude --", "claude exec", " grok"))
        # never reap the fleet's own python processes or ollama server
        if is_agent and "runner.py" not in low and "sentinel.py" not in low and "ollama serve" not in low:
            log("zombie-agent-reaped", f"pid={pid} age={secs//60}min {cmd[:60]}")
            sh("kill", "-9", pid)
            reaped += 1
    return reaped


# ── 4. RAM clamp guard ────────────────────────────────────────────────────────

def _available_ram_gb():
    """Reclaimable-aware availability. macOS parks most RAM as inactive/speculative file
    cache that the kernel returns on demand, so counting only 'Pages free' made this guard
    fire near-constantly (free hovers <1GB on a healthy box) and thrash-unload 9GB models
    that the next local call reloaded (observed 2026-07-09: 5 clamps in 6 min).
    free + inactive + speculative + purgeable approximates what a new allocation can claim."""
    vm = sh("vm_stat").stdout
    page = re.search(r"page size of (\d+) bytes", vm)
    page_bytes = int(page.group(1)) if page else 16384
    total = 0
    for name in ("free", "inactive", "speculative", "purgeable"):
        m = re.search(rf"Pages {name}:\s+(\d+)", vm)
        if m:
            total += int(m.group(1))
    if total == 0:
        return 99.0  # vm_stat parse failure — fail-soft: never clamp on bad data
    return total * page_bytes / 1e9


def ram_guard():
    try:
        free_gb = _available_ram_gb()
        if free_gb >= RAM_GUARD_FREE_GB:
            return
        ps = sh("ollama", "ps").stdout.splitlines()[1:]
        models = []
        for line in ps:
            parts = line.split()
            if len(parts) >= 3:
                try:
                    models.append((float(parts[2]), parts[0]))
                except ValueError:
                    continue
        models.sort(reverse=True)
        if models and models[0][0] >= 8:
            log("ram-clamp", f"avail {free_gb:.1f}GB — unloading {models[0][1]} ({models[0][0]}GB)")
            sh("ollama", "stop", models[0][1], timeout=90)
    except Exception as e:
        log("ram-guard-error", e)


# ── 5. stale code / restart guard ─────────────────────────────────────────────

def stale_code_guard():
    req = os.path.join(HERE, ".restart_requested")
    boot = ""
    for p in (os.path.join(REPO, ".runner_boot_commit"), os.path.join(HERE, ".runner_boot_commit")):
        try:
            boot = open(p).read().strip()
            break
        except OSError:
            continue
    if not boot:
        # No boot marker => the `if boot and ...` below is falsy => this guard silently
        # does NOTHING, forever. Observed 2026-07-16: no .runner_boot_commit existed, the
        # runner sat 14h on code from 04:00 and never learned about fixes landed on master,
        # so the patches to the drift/stash bugs stayed inert until a human noticed the
        # checkout drifting. Fail loudly rather than failing open.
        log("stale-code-unknown",
            "no .runner_boot_commit — cannot tell whether the runner is on current code")
        emit("stale-code-unknown", repo=REPO)
        return
    # Compare against BASE_BRANCH, not HEAD: while the checkout is drifted onto an agent
    # branch, HEAD is that branch's tip and this comparison is meaningless.
    head = git("rev-parse", BASE_BRANCH).stdout.strip()
    if boot and head and boot != head:
        if not os.path.exists(req):
            with open(req, "w") as f:
                f.write(f"reason=sentinel: runner boot {boot[:9]} != HEAD {head[:9]}\n")
            log("restart-requested", f"{boot[:9]} -> {head[:9]}")
        elif time.time() - os.path.getmtime(req) > RESTART_STALE_S:
            runners = _pids("MacOS/Python runner.py") + _pids("python3 runner.py")
            for p in runners:
                log("runner-cycled", f"cooperative restart ignored {RESTART_STALE_S}s; killing {p}")
                sh("kill", p)


# ── 6. merge-train recency (DB up only) ──────────────────────────────────────

def train_guard():
    marker = os.path.join(RUNTIME, "merge_train_pressure.json")
    try:
        age = time.time() - os.path.getmtime(marker)
    except OSError:
        age = 1e9
    if age > TRAIN_STALE_S:
        log("train-stale", f"{int(age)}s since last train pressure write — firing train_run")
        subprocess.Popen([sys.executable, os.path.join(HERE, "merge_train.py")],
                         stdout=open(os.path.join(RUNTIME, "sentinel_train.out"), "a"),
                         stderr=subprocess.STDOUT, cwd=HERE)


def main():
    st = load_state()
    up = db_up()
    was_down = int(st.get("db_misses", 0)) >= DB_DOWN_THRESHOLD
    st["db_misses"] = 0 if up else int(st.get("db_misses", 0)) + 1
    try:
        nested_worktree_guard()  # before checkout_guard: it repairs `git status` itself
    except Exception as e:
        log("nested-worktree-guard-error", e)
    try:
        checkout_guard(st)
    except Exception as e:
        log("checkout-guard-error", e)
    try:
        stash_drift_guard(st)
    except Exception as e:
        log("stash-drift-guard-error", e)
    try:
        wip_stash_rescue(st)   # anonymous WIP-on-base stashes become branches: unloseable
        stranded_commit_rescue(st)  # side-branch commits not in base: self-announcing
    except Exception as e:
        log("wip-stash-rescue-error", e)
    try:
        silent_failure_guard(st)   # catches the "runs but fails quietly" class (see docstring)
    except Exception as e:
        log("stash-drift-guard-error", e)
    try:
        runner_guard(st)
    except Exception as e:
        log("runner-guard-error", e)
    try:
        zombie_agent_reaper()
    except Exception as e:
        log("zombie-reaper-error", e)
    try:
        ram_guard()
    except Exception as e:
        log("ram-guard-error", e)
    try:
        stale_code_guard()
    except Exception as e:
        log("stale-code-error", e)
    if up:
        if was_down:
            try:
                on_db_recovery()
            except Exception as e:
                log("recovery-error", e)
        else:
            # standing dedupe: the intake path is not concurrency-safe across machines even
            # while the DB is up (two watchers racing one drop) — sweep duplicates each cycle.
            try:
                dedupe_queued()
            except Exception as e:
                log("dedupe-error", e)
        try:
            train_guard()
        except Exception as e:
            log("train-guard-error", e)
    elif int(st.get("db_misses", 0)) >= DB_DOWN_THRESHOLD:
        try:
            offline_deploy_sweep(st)
        except Exception as e:
            log("sweep-error", e)
    st["last_run"] = datetime.datetime.utcnow().isoformat() + "Z"
    st["db_up"] = up
    save_state(st)
    log("ok", f"db={'up' if up else 'DOWN'} misses={st['db_misses']}")


if __name__ == "__main__":
    main()

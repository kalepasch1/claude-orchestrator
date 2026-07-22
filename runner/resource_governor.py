#!/usr/bin/env python3
"""
resource_governor.py - keeps the Mac alive. Monitors disk (and RAM if psutil present),
prunes the real space hogs (merged git worktrees, stale logs, build caches, dangling
twins), and THROTTLES concurrency down as pressure rises / up as it eases. Writes an
effective MAX_PARALLEL to a control file the runner reads each loop, so throttling is live.

Predictive: fits a line to recent resource_events disk values; if the trend will breach
DISK_HARD within ~2h, prune and throttle BEFORE it happens. Also prunes node_modules,
Docker images, and ~/Library/Caches behind opt-in flags.
"""
import os, sys, time, shutil, subprocess, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import events


def emit(kind, **fields):
    """Public fail-soft event adapter used by integrations and diagnostics."""
    return events.emit(kind, **fields)

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
THROTTLE_FILE = os.path.join(HOME, "throttle")

# 2026-07-11: CEILING/DISK_*/RAM_* used to be module-level constants snapshotted ONCE at import
# time. fleet_control.load_config() pushes fleet-wide tuning (MAX_PARALLEL_CEILING, PER_TASK_GB,
# RAM_FLOOR_GB, ...) into os.environ live every loop, but a long-running process never re-read
# these frozen constants -- so a machine whose runner started before the last central tuning push
# (e.g. one that hadn't been restarted recently) stayed stuck on whatever conservative defaults
# it booted with, silently diverging from a machine that started fresh. This is the same class of
# bug already fixed for runner.py's MAX_PARALLEL (see runner.py's eff_limit comment: "a stale/low
# value throttled a 48GB box to 4 lanes"). Root-caused here: Mac 2 was clamped to ~4 concurrent
# tasks against a 16-lane ceiling because its resource_governor process never picked up a tuned
# PER_TASK_GB/RAM_FLOOR_GB pushed centrally after it last started. Read all of these live from
# env on every call instead of freezing them at import.
def _ceiling():
    """Max concurrent tasks allowed. Read live from env to support fleet-wide tuning."""
    return int(os.environ.get("MAX_PARALLEL_CEILING", "12"))


def _disk_soft():
    """Disk usage % above which proactive pruning kicks in (worktrees, logs, caches)."""
    return float(os.environ.get("DISK_SOFT_PCT", "80"))


def _disk_hard():
    """Disk usage % at which concurrency throttles to 1 lane and alerts fire."""
    return float(os.environ.get("DISK_HARD_PCT", "90"))


def _ram_hard():
    """RAM usage % ceiling; above this the governor blocks new task claims."""
    return float(os.environ.get("RAM_HARD_PCT", "82"))


def _ram_floor_gb():
    """Minimum free RAM (GB) before pausing new task claims entirely.

    Hard low-memory brake: if fewer than this many GB are available, PAUSE new task claims
    entirely (a single heavy task — e.g. an 8GB typecheck — could otherwise crash the Mac).
    1.5GB was too low — macOS is already swapping/thrashing by then. Default 2GB, and the
    effective floor scales UP with machine size (see effective_floor_gb).
    """
    return float(os.environ.get("RAM_FLOOR_GB", "2.0"))


def _per_task_gb():
    """RAM headroom (GB) reserved per concurrent task.

    A new task is only started if free RAM exceeds (floor + PER_TASK_GB), so concurrency
    is implicitly capped by available memory.
    """
    return float(os.environ.get("PER_TASK_GB", "0.15"))


# --- Pruning knobs (opt-in per category) ---
LOG_KEEP_DAYS = int(os.environ.get("LOG_KEEP_DAYS", "7"))
PRUNE_NODE_MODULES = os.environ.get("PRUNE_NODE_MODULES", "false").lower() == "true"
PRUNE_DOCKER = os.environ.get("PRUNE_DOCKER", "false").lower() == "true"
PRUNE_LIB_CACHES = os.environ.get("PRUNE_LIB_CACHES", "false").lower() == "true"
# Predictive throttling: fit a trend line to recent disk_pct samples and throttle
# preemptively if extrapolation breaches DISK_HARD within this many hours.
PREDICT_WINDOW_H = float(os.environ.get("PREDICT_DISK_WINDOW_H", "2"))
os.makedirs(HOME, exist_ok=True)


def _event(kind, value=None, detail="", action=""):
    """Log a resource event to the database for trending and alerting.

    Fail-soft: swallows all exceptions so monitoring never disrupts the runner.
    Detail is truncated to 500 chars to stay within column limits.
    """
    try:
        db.insert("resource_events", {"kind": kind, "value": value, "detail": detail[:500], "action": action})
    except Exception:
        pass


def disk_pct(path="/"):
    """Return (used_percent, free_gb) for the given mount point."""
    u = shutil.disk_usage(path)
    return round(u.used / u.total * 100, 1), round(u.free / 1e9, 1)


def _vm_stat():
    """macOS memory via vm_stat + sysctl (no psutil dependency). Returns (pct_used, avail_gb).

    CRITICAL FIX (2026-07): macOS keeps almost all RAM committed to reclaimable file
    cache, so the old `free + inactive + speculative` heuristic reported ~3GB "free" on a
    48GB Mac that Activity Monitor showed as having ~19GB available (0 swap, GREEN pressure).
    That starved the runner to 1-2 tasks. True available ≈ total - non-reclaimable, where
    non-reclaimable = anonymous (app) + wired + compressor. Everything else (free space +
    file-backed cache + purgeable) can be handed to a new task instantly."""
    try:
        import re
        total = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())
        out = subprocess.check_output(["vm_stat"]).decode()
        m_page = re.search(r"page size of (\d+) bytes", out)
        page = int(m_page.group(1)) if m_page else 4096
        def f(label):
            m = re.search(re.escape(label) + r":\s+(\d+)", out)
            return int(m.group(1)) * page if m else 0
        wired      = f("Pages wired down")
        compressor = f("Pages occupied by compressor")
        anon       = f("Anonymous pages")
        if anon:  # modern vm_stat: non-reclaimable = app + wired + compressed
            used  = anon + wired + compressor
            avail = max(0, total - used)
        else:     # older vm_stat fallback: add file-backed + purgeable to the old buckets
            used  = f("Pages active") + wired + compressor
            avail = (f("Pages free") + f("Pages inactive") + f("Pages speculative")
                     + f("File-backed pages") + f("Pages purgeable"))
        avail = min(avail, total)
        return round(used / total * 100, 1), round(avail / 1e9, 1)
    except Exception:
        return None, None


def ram_pct():
    """Return RAM usage as a percentage, or None if unavailable."""
    # Prefer our macOS-accurate calc; psutil's macOS `available` also undercounts cache.
    v = _vm_stat()[0]
    if v is not None:
        return v
    try:
        import psutil
        return psutil.virtual_memory().percent
    except Exception:
        return None


def ram_free_gb():
    """Return available RAM in GB, or None if unavailable."""
    # Prefer our macOS-accurate calc (counts reclaimable cache as available).
    v = _vm_stat()[1]
    if v is not None:
        return v
    try:
        import psutil
        return round(psutil.virtual_memory().available / 1e9, 1)
    except Exception:
        return None


def total_gb():
    """Return total physical RAM in GB, or None if it cannot be determined."""
    try:
        import psutil
        return round(psutil.virtual_memory().total / 1e9, 1)
    except Exception:
        try:
            return round(int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip()) / 1e9, 1)
        except Exception:
            return None


def effective_floor_gb():
    """Flat, env-tunable RAM reserve. (Earlier this scaled to 12% of total RAM, but macOS
    normally runs with most RAM committed to cache — on a large-RAM Mac that pushed the floor
    so high the runner never claimed. The kernel memory-pressure brake is the real anti-crash
    guard; this floor just keeps a sane emergency reserve.) Tune via RAM_FLOOR_GB in .env."""
    return _ram_floor_gb()


def mem_pressure_ok():
    """macOS authoritative brake. The free-GB heuristic (free+inactive+speculative) is
    optimistic; the kernel's own pressure level is the reliable signal.
    sysctl kern.memorystatus_vm_pressure_level -> 1=normal, 2=warn, 4=critical."""
    try:
        lvl = int(subprocess.check_output(
            ["sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
            timeout=5, stderr=subprocess.DEVNULL).strip())
        return lvl <= 1
    except Exception:
        return True  # signal unavailable -> don't block on it alone


def pressure_should_block(free_gb=None, floor_gb=None):
    """Treat kernel memory pressure as decisive only when measured headroom is also tight.

    macOS can leave kern.memorystatus_vm_pressure_level at warn/critical after a burst even
    when vm_stat shows tens of GB available. That stale signal collapsed the fleet to one
    lane. Keep it as a crash brake, but require corroborating low headroom before blocking.
    """
    if mem_pressure_ok():
        return False
    if free_gb is None:
        free_gb = ram_free_gb()
    if floor_gb is None:
        floor_gb = effective_floor_gb()
    if free_gb is None:
        return True
    extra_tasks = float(os.environ.get("ORCH_PRESSURE_EXTRA_TASKS", "1.0") or 1.0)
    return free_gb < floor_gb + (_per_task_gb() * extra_tasks)


def can_claim(n_active=0):
    """Real-time gate the runner calls BEFORE starting each new task.

    Protects the Mac in the gaps between the slower periodic govern() ticks.
    Checks, in order:
      1. RAM headroom: free GB must exceed effective_floor_gb() + per-task reserve.
      2. Kernel memory pressure: blocks only when macOS reports warn/critical AND
         measured headroom corroborates (see pressure_should_block).
      3. Disk usage: blocks if disk_pct >= DISK_HARD_PCT.

    Args:
        n_active: number of tasks currently running (reserved for future
                  concurrency-aware gating; not yet used in checks).

    Returns:
        (ok: bool, reason: str) — True/'ok' when safe to start a new task,
        False/description when resource pressure requires waiting.
    """
    free = ram_free_gb()
    floor = effective_floor_gb()
    per_task = _per_task_gb()
    if free is not None and free < floor + per_task:
        return False, f"low RAM {free}GB free < need {floor + per_task}GB (floor {floor}+task {per_task})"
    if pressure_should_block(free, floor):
        return False, "kernel memory pressure warn/critical with low RAM headroom"
    try:
        used, _ = disk_pct()
        hard = _disk_hard()
        if used >= hard:
            return False, f"disk {used}% >= hard {hard}%"
    except Exception:
        pass
    return True, "ok"


def stats():
    """Return a snapshot of current resource state for diagnostics and fleet dashboards."""
    free = ram_free_gb()
    try:
        used_pct, _ = disk_pct()
    except Exception:
        used_pct = None
    ok, reason = can_claim()
    return {
        "ram_free_gb": free,
        "ram_floor_gb": effective_floor_gb(),
        "per_task_gb": _per_task_gb(),
        "disk_used_pct": used_pct,
        "disk_soft_pct": _disk_soft(),
        "disk_hard_pct": _disk_hard(),
        "ceiling": _ceiling(),
        "can_claim": ok,
        "claim_reason": reason,
    }


def _projects():
    try:
        return db.select("projects", {"select": "name,repo_path"}) or []
    except Exception:
        return []


def _predicted_disk_pct(horizon_seconds=None):
    """
    Fit a linear trend to the last 20 disk resource_events to predict when we'll hit DISK_HARD.
    Returns (predicted_pct_at_horizon, hours_to_hard) or (None, None) if insufficient data.
    """
    if horizon_seconds is None:
        horizon_seconds = PREDICT_WINDOW_H * 3600
    try:
        rows = db.select("resource_events", {"select": "value,created_at", "kind": "eq.disk",
                                              "order": "created_at.desc", "limit": "20"}) or []
    except Exception:
        return None, None
    if len(rows) < 4:
        return None, None
    pts = []
    for r in rows:
        try:
            import datetime
            ts = datetime.datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")).timestamp()
            pts.append((ts, float(r["value"])))
        except Exception:
            continue
    if len(pts) < 4:
        return None, None
    pts.sort()
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    den = sum((x - x_mean) ** 2 for x in xs)
    if den == 0:
        return None, None
    slope = num / den          # pct per second
    intercept = y_mean - slope * x_mean
    now = time.time()
    predicted = slope * (now + horizon_seconds) + intercept
    if slope <= 0:
        return predicted, None  # not growing
    secs_to_hard = (_disk_hard() - (slope * now + intercept)) / slope
    return predicted, secs_to_hard / 3600


def _has_uncommitted_changes(wt_path, repo):
    """Return True if worktree has uncommitted changes (safety guard)."""
    try:
        r = subprocess.run(["git", "status", "--porcelain"], cwd=wt_path,
                           capture_output=True, text=True, timeout=10)
        return bool(r.stdout.strip())
    except Exception:
        return True  # assume dirty if we can't check


def _is_branch_unmerged(branch, repo):
    """Return True if branch is NOT merged into main (safety guard). Exact-name match —
    the old substring check could mis-classify a branch as merged when its name was a
    substring of another merged branch."""
    try:
        merged = subprocess.check_output(["git", "branch", "--merged", "main"],
                                         cwd=repo, text=True, timeout=10)
        names = {l.strip().lstrip("* ").strip() for l in merged.splitlines()}
        return branch not in names
    except Exception:
        return True  # assume unmerged if we can't check


def _is_fresh_checkout(branch, repo):
    """True if the branch tip is exactly main's tip. `git branch --merged main` counts a freshly
    created agent branch as 'merged', but a tip identical to main means an executor just created
    it and hasn't committed yet — NOT that its work landed. Deleting such a worktree rips it out
    from under a running executor. (A truly merged branch normally points at its own last commit,
    which main contains but does not equal.) Fail closed (True → caller skips)."""
    try:
        tip = subprocess.run(["git", "rev-parse", "--verify", "--quiet", branch],
                             cwd=repo, capture_output=True, text=True, timeout=10)
        main_tip = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "main"],
                                  cwd=repo, capture_output=True, text=True, timeout=10)
        if tip.returncode != 0 or main_tip.returncode != 0:
            return True
        return tip.stdout.strip() == main_tip.stdout.strip()
    except Exception:
        return True


def _wt_recently_active(path, min_age_min=None):
    """True if the worktree (or its git admin dir/index) was touched recently. Fail closed."""
    if min_age_min is None:
        min_age_min = int(os.environ.get("WORKTREE_GC_MIN_AGE_MIN", "180"))
    if min_age_min <= 0:
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
    return newest > time.time() - min_age_min * 60


def _agent_branch_safe_on_origin(branch, repo):
    """Return True only if it is SAFE to delete this local agent branch — i.e. its work is
    durably on origin. Safe iff the branch itself exists on origin, OR its tip commit is an
    ancestor of an origin integration branch (already merged upstream). This is the fix for the
    recover-missing-branch churn: a fail-soft branch-share push (runner.py) can leave a branch
    local-only; deleting it here then loses the work fleet-wide. Never delete unshared work."""
    try:
        tip = subprocess.run(["git", "rev-parse", "--verify", "--quiet", branch],
                             cwd=repo, capture_output=True, text=True, timeout=10).stdout.strip()
        if not tip:
            return True  # no such local branch / no commits — nothing to protect
        # 1) branch present on origin as-is?
        if subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}"],
                          cwd=repo, capture_output=True, timeout=10).returncode == 0:
            return True
        # 2) tip already integrated into an origin branch (dev/staging/prod)?
        targets = [t for t in (os.environ.get("ORCH_STAGING_BRANCH", "orchestrator/dev"),
                               os.environ.get("ORCH_CODE_MERGE_TARGET", "dev"),
                               "main", "master") if t]
        for tgt in targets:
            ref = f"refs/remotes/origin/{tgt}"
            if subprocess.run(["git", "show-ref", "--verify", "--quiet", ref],
                              cwd=repo, capture_output=True, timeout=10).returncode == 0:
                if subprocess.run(["git", "merge-base", "--is-ancestor", tip, ref],
                                  cwd=repo, capture_output=True, timeout=10).returncode == 0:
                    return True
        return False
    except Exception:
        return False  # fail-closed: if unsure, do NOT delete


def prune():
    """Reclaim disk by removing merged worktrees, old logs, and stale caches.  Returns freed-item notes."""
    freed_notes = []
    # 1) merged agent worktrees + git worktree prune
    for p in _projects():
        repo = p["repo_path"]
        if not os.path.isdir(os.path.join(repo, ".git")):
            continue
        subprocess.run(["git", "worktree", "prune"], cwd=repo, capture_output=True)
        try:
            merged = subprocess.check_output(["git", "branch", "--merged", "main"], cwd=repo, text=True)
        except Exception:
            merged = ""
        wt_root = os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-wt")
        for b in [l.strip().lstrip("* ").strip() for l in merged.splitlines()]:
            if b.startswith("agent/"):
                wt = os.path.join(wt_root, b.split("/", 1)[1])
                if os.path.isdir(wt):
                    # SAFETY: never delete a worktree with uncommitted changes
                    if _has_uncommitted_changes(wt, repo):
                        freed_notes.append(f"SKIPPED (dirty) {b}")
                        continue
                    # SAFETY: double-check branch is truly merged
                    if _is_branch_unmerged(b, repo):
                        freed_notes.append(f"SKIPPED (unmerged) {b}")
                        continue
                    # SAFETY: a branch whose tip == main's tip looks 'merged' but is really a
                    # FRESH checkout an executor just created and hasn't committed to — skip it.
                    if _is_fresh_checkout(b, repo):
                        freed_notes.append(f"SKIPPED (fresh checkout) {b}")
                        continue
                    # SAFETY: skip worktrees with recent filesystem/git activity (active executor)
                    if _wt_recently_active(wt):
                        freed_notes.append(f"SKIPPED (recently active) {b}")
                        continue
                    # SAFETY: never delete a local agent branch whose work isn't durably on origin
                    # (fail-soft share push can leave it local-only → deleting loses work fleet-wide).
                    origin_safe = _agent_branch_safe_on_origin(b, repo)
                    # All guards passed: clear any creation lock so the worktree can be reclaimed.
                    subprocess.run(["git", "worktree", "unlock", wt], cwd=repo, capture_output=True)
                    subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=repo, capture_output=True)
                    if origin_safe:
                        subprocess.run(["git", "branch", "-D", b], cwd=repo, capture_output=True)
                        freed_notes.append(f"worktree {b}")
                    else:
                        # keep the branch ref (cheap), just reclaim the worktree dir
                        freed_notes.append(f"worktree {b} (branch kept: not on origin)")

        # 2) build caches (safe to delete; rebuilt on demand)
        for cache in ("**/.nuxt", "**/.output", "**/dist", "**/.next"):
            for d in glob.glob(os.path.join(repo, cache), recursive=True):
                if os.path.isdir(d) and "-wt" not in d:
                    shutil.rmtree(d, ignore_errors=True); freed_notes.append(os.path.relpath(d, repo))

        # 3) node_modules (opt-in — large but rebuildable with npm install)
        if PRUNE_NODE_MODULES:
            for d in glob.glob(os.path.join(repo, "**/node_modules"), recursive=True):
                if os.path.isdir(d) and "-wt" not in d:
                    shutil.rmtree(d, ignore_errors=True); freed_notes.append("node_modules:" + os.path.relpath(d, repo))

    # 4) stale logs
    cutoff = time.time() - LOG_KEEP_DAYS * 86400
    for f in glob.glob(os.path.join(HOME, "logs", "*")):
        try:
            if os.path.getmtime(f) < cutoff:
                os.remove(f); freed_notes.append("log " + os.path.basename(f))
        except Exception:
            pass

    # 5) Docker (opt-in — removes dangling images + stopped containers)
    if PRUNE_DOCKER:
        try:
            subprocess.run(["docker", "system", "prune", "-f", "--filter", "until=48h"],
                           capture_output=True, timeout=60)
            freed_notes.append("docker prune")
        except Exception:
            pass

    # 6) ~/Library/Caches (opt-in — aggressive, removes Xcode DerivedData etc.)
    if PRUNE_LIB_CACHES:
        lib_cache = os.path.expanduser("~/Library/Caches")
        safe_targets = ["com.apple.dt.Xcode", "Homebrew"]
        for target in safe_targets:
            d = os.path.join(lib_cache, target)
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True); freed_notes.append(f"Library/Caches/{target}")

    _event("prune", detail=f"{len(freed_notes)} items", action="; ".join(freed_notes[:15]))
    return freed_notes


def _throttle_floor():
    return int(os.environ.get("ORCH_THROTTLE_FLOOR", "1"))


def set_throttle(n):
    """Clamp *n* to [1, ceiling] and persist it to the throttle file.

    The runner reads this file each loop to decide how many concurrent tasks
    to allow.  Returns the clamped value actually written."""
    n = max(1, min(n, _ceiling()))
    with open(THROTTLE_FILE, "w") as f:
        f.write(str(n))
    return n


def current_limit():
    """Read the persisted throttle limit, falling back to ceiling on any error.

    Always returns a value in [1, ceiling] so the runner never stalls at zero
    or overshoots the configured maximum."""
    try:
        with open(THROTTLE_FILE) as f:
            return max(1, min(int(f.read().strip()), _ceiling()))
    except Exception:
        return _ceiling()


def dashboard_gauge():
    """Return a dict suitable for the dashboard Resources gauge."""
    used, free_gb = disk_pct()
    ram = ram_pct()
    pred_pct, hours_to_hard = _predicted_disk_pct()
    ollama_loaded = []
    try:
        import local_model_slots
        ollama_loaded = local_model_slots.loaded_models()
    except Exception:
        pass
    return {
        "disk_pct": used, "free_gb": free_gb,
        "ram_pct": ram, "throttle": current_limit(), "ceiling": _ceiling(),
        "ram_free_gb": ram_free_gb(), "ollama_loaded": ollama_loaded,
        "predicted_disk_pct_2h": pred_pct, "hours_to_hard": hours_to_hard,
        "disk_soft": _disk_soft(), "disk_hard": _disk_hard(),
    }


def _global_pause_reason():
    try:
        rows = db.select("controls", {"select": "paused,reason", "scope": "eq.global",
                                      "order": "updated_at.desc", "limit": "1"}) or []
        if rows and rows[0].get("paused"):
            return rows[0].get("reason") or ""
    except Exception:
        pass
    return None


def govern():
    """Periodic resource sweep — the main loop calls this every tick.

    Checks disk and RAM, prunes stale worktrees when disk exceeds DISK_SOFT,
    auto-resumes cost-circuit pauses once the rolling hour clears, unloads
    heavy Ollama models under memory pressure, and adjusts the throttle file
    so concurrency scales with available headroom.
    """
    used, free_gb = disk_pct()
    ram = ram_pct()
    free_ram = ram_free_gb()
    _t_sample = time.monotonic()
    _event("disk", used, f"{free_gb}GB free")
    action = "ok"

    # ── MEMORY BRAKE: protect the Mac from a crash/restart ──────────────────────
    # If available RAM is critically low, PAUSE all new task claims (the running task
    # finishes; nothing new starts) until memory recovers. Uses the kill switch so the
    # whole runner + scheduler honor it. Auto-resumes only what IT auto-paused.
    # ── SELF-HEAL cost/call-circuit trips ───────────────────────────────────────
    # The call/$ breaker hard-pauses globally on a trip; without this it stays paused until a
    # human un-pauses (which stalled the fleet repeatedly). Auto-resume once the rolling hour
    # has cleared. Only lifts AUTO pauses (claude_cli/governor) — never a human STOP button.
    try:
        gc = db.select("controls", {"select": "paused,reason,updated_by", "scope": "eq.global",
                                    "order": "updated_at.desc", "limit": "1"}) or []
        if gc and gc[0].get("paused") and gc[0].get("updated_by") in ("claude_cli", "governor"):
            reason = (gc[0].get("reason") or "").lower()
            if any(k in reason for k in ("call cap", "cost circuit", "$ cap", "hourly")):
                import claude_cli, kill_switch
                st = claude_cli.status()
                if (st["calls_last_hour"] < claude_cli.MAX_CALLS_HOUR
                        and st["usd_last_hour"] < claude_cli.MAX_USD_HOUR):
                    kill_switch.resume(scope="global", by="governor")
                    print(f"governor: cost-circuit cleared "
                          f"(calls {st['calls_last_hour']}/{claude_cli.MAX_CALLS_HOUR}) -> resumed")
    except Exception:
        pass

    eff_floor = effective_floor_gb()
    per_task = _per_task_gb()
    ceiling = _ceiling()
    disk_soft = _disk_soft()
    disk_hard = _disk_hard()
    ram_hard = _ram_hard()
    pressure_bad = pressure_should_block(free_ram, eff_floor)
    if free_ram is not None:
        cur_reason = _global_pause_reason()
        if free_ram < eff_floor or pressure_bad:
            try:
                import local_model_slots
                unloaded = []
                for m in local_model_slots.loaded_models():
                    if local_model_slots.is_heavy(m) and local_model_slots.unload(m):
                        unloaded.append(m)
                if not unloaded and local_model_slots._kill_llama_servers():
                    unloaded.append("orphaned-llama-server")
                if unloaded:
                    _event("ollama_unload", free_ram, f"low memory unloaded {', '.join(unloaded)}", "unload heavy local models")
            except Exception:
                pass
            # The heavy-model unload can free 8-25GB immediately. Re-measure before pausing or
            # clamping the fleet, otherwise the governor leaves throughput at 1 even though the
            # pressure was already relieved.
            free_ram = ram_free_gb()
            ram = ram_pct()
            pressure_bad = pressure_should_block(free_ram, eff_floor)
            if free_ram is not None and free_ram >= eff_floor + per_task and not pressure_bad:
                cur_reason = _global_pause_reason()
                if cur_reason == "auto:low-memory":
                    try:
                        import kill_switch
                        kill_switch.resume(scope="global", by="governor")
                        print(f"governor: memory recovered after local-model unload ({free_ram}GB free) -> resumed")
                    except Exception:
                        pass
            else:
                # CLAMP, don't global-PAUSE. A global memory pause proved to be a sticky,
                # oscillating fleet-killer (2026-07-10): it latched on a transient load spike and
                # the resume never caught the recovery window, freezing everything for hours even
                # at 30GB free. Clamping throttle to 1 is self-correcting, and the per-task
                # can_claim() gate already blocks new claims when RAM is genuinely low — so a hard
                # global pause is redundant AND dangerous. Never global-pause for memory again;
                # lift any stale auto:low-memory pause instead.
                set_throttle(1)
                if cur_reason == "auto:low-memory":
                    try:
                        import kill_switch
                        kill_switch.resume(scope="global", by="governor")
                        print("governor: lifting stale auto:low-memory pause — clamping instead")
                    except Exception:
                        pass
                print(f"governor: LOW MEMORY {free_ram}GB free (floor {eff_floor}, "
                      f"pressure_bad={pressure_bad}) -> paused new claims")
                return dashboard_gauge()
        elif cur_reason == "auto:low-memory" and free_ram > eff_floor + 3 and not pressure_bad:
            try:
                import kill_switch
                kill_switch.resume(scope="global", by="governor")
                print(f"governor: memory recovered ({free_ram}GB free) -> resumed")
            except Exception:
                pass

    # Predictive check: prune now if trend says we'll hit DISK_HARD within the window
    pred_pct, hours_to_hard = _predicted_disk_pct()
    if hours_to_hard is not None and 0 < hours_to_hard < PREDICT_WINDOW_H and used < disk_hard:
        print(f"governor: predictive prune — at trend rate disk will hit {disk_hard}% in {hours_to_hard:.1f}h")
        _event("predict", pred_pct, f"will breach {disk_hard}% in {hours_to_hard:.1f}h", "predictive prune")
        prune()
        used, free_gb = disk_pct()

    if used >= disk_soft:
        prune()
        used, free_gb = disk_pct()                      # recheck after prune
    if used >= disk_hard or (ram is not None and ram >= ram_hard):
        set_throttle(1); action = "throttle->1"
        _event("throttle", used, f"disk {used}% ram {ram}", "throttle to 1")
        try:
            db.insert("approvals", {"project": "ORCHESTRATOR", "kind": "self",
                "title": f"Resource pressure: disk {used}% / ram {ram}",
                "why": "Near storage/memory limit; throttled to 1 and pruned to protect the Mac.",
                "value": "Prevents a crash.", "risk": "Throughput reduced until pressure eases."})
        except Exception:
            pass
    elif used < disk_soft - 10 and (ram is None or ram < ram_hard - 5) and (free_ram is None or free_ram > eff_floor + 1):
        set_throttle(ceiling); action = f"throttle->{ceiling}"
    elif (ram is None or ram < ram_hard - 3) and (free_ram is None or free_ram > eff_floor + 0.5):
        set_throttle(current_limit() + 1); action = "ease up"
    else:
        action = "hold (memory elevated)"
    # Memory-budget clamp: never allow more concurrent tasks than free RAM can hold,
    # regardless of what the disk/ram branches above decided.
    if free_ram is not None:
        mem_budget = max(1, int((free_ram - eff_floor) / per_task))
        if current_limit() > mem_budget:
            set_throttle(mem_budget)
            action += f"; mem-clamp->{mem_budget}"
    g = dashboard_gauge()
    latest_free = g.get("ram_free_gb")
    latest_ram = g.get("ram_pct")
    if (latest_free is not None
            and used < disk_soft - 10
            and (latest_ram is None or latest_ram < ram_hard - 5)
            and not pressure_should_block(latest_free, eff_floor)):
        recovered_budget = max(1, int((latest_free - eff_floor) / per_task))
        recovered_target = min(ceiling, recovered_budget)
        if recovered_target > current_limit():
            set_throttle(recovered_target)
            action += f"; mem-recover->{recovered_target}"
            g = dashboard_gauge()
    _t_end = time.monotonic()
    _elapsed_ms = (_t_end - _t0) * 1000
    _sample_ms = (_t_sample - _t0) * 1000
    print(f"governor: disk {used}% ({free_gb}GB free) ram {ram} free_ram {free_ram}GB "
          f"floor {eff_floor} -> {action}, limit={current_limit()} "
          f"[{_elapsed_ms:.0f}ms total, {_sample_ms:.0f}ms sampling]")
    return g


def stats() -> dict:
    """Return a snapshot of current resource state for observability."""
    g = dashboard_gauge()
    g["current_limit"] = current_limit()
    g["ceiling"] = _ceiling()
    return g


def stats():
    """Return a dict of governor state for operators and tests.

    Combines the dashboard gauge with claim-gate status and tuning parameters
    so callers can observe the full governor picture in one call.
    """
    gauge = dashboard_gauge()
    ok, reason = can_claim()
    gauge.update({
        "can_claim": ok,
        "claim_reason": reason,
        "per_task_gb": _per_task_gb(),
        "ram_floor_gb": _ram_floor_gb(),
        "effective_floor_gb": effective_floor_gb(),
    })
    return gauge

if __name__ == "__main__":
    print(json.dumps(govern()))

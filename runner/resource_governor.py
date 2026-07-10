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

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
THROTTLE_FILE = os.path.join(HOME, "throttle")
CEILING = int(os.environ.get("MAX_PARALLEL_CEILING", "12"))
DISK_SOFT = float(os.environ.get("DISK_SOFT_PCT", "80"))   # prune above this
DISK_HARD = float(os.environ.get("DISK_HARD_PCT", "90"))   # throttle to 1 + alert
RAM_HARD = float(os.environ.get("RAM_HARD_PCT", "82"))
# Hard low-memory brake: if fewer than this many GB are available, PAUSE new task claims
# entirely (a single heavy task — e.g. an 8GB typecheck — could otherwise crash the Mac).
# 1.5GB was too low — macOS is already swapping/thrashing by then. Default 3GB, and the
# effective floor scales UP with machine size (see effective_floor_gb).
RAM_FLOOR_GB = float(os.environ.get("RAM_FLOOR_GB", "6.0"))
# Headroom to reserve per concurrent task. A new task is only started if free RAM exceeds
# (floor + PER_TASK_GB), so concurrency is implicitly capped by available memory.
PER_TASK_GB = float(os.environ.get("PER_TASK_GB", "1.5"))
LOG_KEEP_DAYS = int(os.environ.get("LOG_KEEP_DAYS", "7"))
PRUNE_NODE_MODULES = os.environ.get("PRUNE_NODE_MODULES", "false").lower() == "true"
PRUNE_DOCKER = os.environ.get("PRUNE_DOCKER", "false").lower() == "true"
PRUNE_LIB_CACHES = os.environ.get("PRUNE_LIB_CACHES", "false").lower() == "true"
PREDICT_WINDOW_H = float(os.environ.get("PREDICT_DISK_WINDOW_H", "2"))
os.makedirs(HOME, exist_ok=True)


def _event(kind, value=None, detail="", action=""):
    try:
        db.insert("resource_events", {"kind": kind, "value": value, "detail": detail[:500], "action": action})
    except Exception:
        pass


def disk_pct(path="/"):
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
    return RAM_FLOOR_GB


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
    return free_gb < floor_gb + (PER_TASK_GB * extra_tasks)


def can_claim(n_active=0):
    """Real-time gate the runner calls BEFORE starting each new task — protects the Mac in
    the gaps between the slower periodic govern() ticks. Returns (ok, reason)."""
    free = ram_free_gb()
    floor = effective_floor_gb()
    if free is not None and free < floor + PER_TASK_GB:
        return False, f"low RAM {free}GB free < need {floor + PER_TASK_GB}GB (floor {floor}+task {PER_TASK_GB})"
    if pressure_should_block(free, floor):
        return False, "kernel memory pressure warn/critical with low RAM headroom"
    try:
        used, _ = disk_pct()
        if used >= DISK_HARD:
            return False, f"disk {used}% >= hard {DISK_HARD}%"
    except Exception:
        pass
    return True, "ok"


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
    secs_to_hard = (DISK_HARD - (slope * now + intercept)) / slope
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
    """Return True if branch is NOT merged into main (safety guard)."""
    try:
        merged = subprocess.check_output(["git", "branch", "--merged", "main"],
                                         cwd=repo, text=True, timeout=10)
        return branch not in merged
    except Exception:
        return True  # assume unmerged if we can't check


def prune():
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
                    subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=repo, capture_output=True)
                    subprocess.run(["git", "branch", "-D", b], cwd=repo, capture_output=True)
                    freed_notes.append(f"worktree {b}")

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


def set_throttle(n):
    n = max(1, min(n, CEILING))
    open(THROTTLE_FILE, "w").write(str(n))
    return n


def current_limit():
    try:
        return max(1, min(int(open(THROTTLE_FILE).read().strip()), CEILING))
    except Exception:
        return CEILING


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
        "ram_pct": ram, "throttle": current_limit(), "ceiling": CEILING,
        "ram_free_gb": ram_free_gb(), "ollama_loaded": ollama_loaded,
        "predicted_disk_pct_2h": pred_pct, "hours_to_hard": hours_to_hard,
        "disk_soft": DISK_SOFT, "disk_hard": DISK_HARD,
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
    used, free_gb = disk_pct()
    ram = ram_pct()
    free_ram = ram_free_gb()
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
            if free_ram is not None and free_ram >= eff_floor + PER_TASK_GB and not pressure_bad:
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
    if hours_to_hard is not None and 0 < hours_to_hard < PREDICT_WINDOW_H and used < DISK_HARD:
        print(f"governor: predictive prune — at trend rate disk will hit {DISK_HARD}% in {hours_to_hard:.1f}h")
        _event("predict", pred_pct, f"will breach {DISK_HARD}% in {hours_to_hard:.1f}h", "predictive prune")
        prune()
        used, free_gb = disk_pct()

    if used >= DISK_SOFT:
        prune()
        used, free_gb = disk_pct()                      # recheck after prune
    if used >= DISK_HARD or (ram is not None and ram >= RAM_HARD):
        set_throttle(1); action = "throttle->1"
        _event("throttle", used, f"disk {used}% ram {ram}", "throttle to 1")
        try:
            db.insert("approvals", {"project": "ORCHESTRATOR", "kind": "self",
                "title": f"Resource pressure: disk {used}% / ram {ram}",
                "why": "Near storage/memory limit; throttled to 1 and pruned to protect the Mac.",
                "value": "Prevents a crash.", "risk": "Throughput reduced until pressure eases."})
        except Exception:
            pass
    elif used < DISK_SOFT - 10 and (ram is None or ram < RAM_HARD - 12) and (free_ram is None or free_ram > RAM_FLOOR_GB + 3):
        set_throttle(CEILING); action = f"throttle->{CEILING}"
    elif (ram is None or ram < RAM_HARD - 8) and (free_ram is None or free_ram > RAM_FLOOR_GB + 2):
        set_throttle(current_limit() + 1); action = "ease up"
    else:
        action = "hold (memory elevated)"
    # Memory-budget clamp: never allow more concurrent tasks than free RAM can hold,
    # regardless of what the disk/ram branches above decided.
    if free_ram is not None:
        mem_budget = max(1, int((free_ram - eff_floor) / PER_TASK_GB))
        if current_limit() > mem_budget:
            set_throttle(mem_budget)
            action += f"; mem-clamp->{mem_budget}"
    g = dashboard_gauge()
    latest_free = g.get("ram_free_gb")
    latest_ram = g.get("ram_pct")
    if (latest_free is not None
            and used < DISK_SOFT - 10
            and (latest_ram is None or latest_ram < RAM_HARD - 12)
            and not pressure_should_block(latest_free, eff_floor)):
        recovered_budget = max(1, int((latest_free - eff_floor) / PER_TASK_GB))
        recovered_target = min(CEILING, recovered_budget)
        if recovered_target > current_limit():
            set_throttle(recovered_target)
            action += f"; mem-recover->{recovered_target}"
            g = dashboard_gauge()
    print(f"governor: disk {used}% ({free_gb}GB free) ram {ram} free_ram {free_ram}GB "
          f"floor {eff_floor} -> {action}, limit={current_limit()}")
    return g


if __name__ == "__main__":
    print(json.dumps(govern()))

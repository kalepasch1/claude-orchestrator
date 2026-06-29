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
CEILING = int(os.environ.get("MAX_PARALLEL_CEILING", "4"))
DISK_SOFT = float(os.environ.get("DISK_SOFT_PCT", "80"))   # prune above this
DISK_HARD = float(os.environ.get("DISK_HARD_PCT", "90"))   # throttle to 1 + alert
RAM_HARD = float(os.environ.get("RAM_HARD_PCT", "88"))
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


def ram_pct():
    try:
        import psutil
        return psutil.virtual_memory().percent
    except Exception:
        return None


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
    return {
        "disk_pct": used, "free_gb": free_gb,
        "ram_pct": ram, "throttle": current_limit(), "ceiling": CEILING,
        "predicted_disk_pct_2h": pred_pct, "hours_to_hard": hours_to_hard,
        "disk_soft": DISK_SOFT, "disk_hard": DISK_HARD,
    }


def govern():
    used, free_gb = disk_pct()
    ram = ram_pct()
    _event("disk", used, f"{free_gb}GB free")
    action = "ok"

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
    elif used < DISK_SOFT - 10:
        set_throttle(CEILING); action = f"throttle->{CEILING}"
    else:
        set_throttle(current_limit() + 1); action = "ease up"
    g = dashboard_gauge()
    print(f"governor: disk {used}% ({free_gb}GB free) ram {ram} -> {action}, limit={current_limit()}")
    return g


if __name__ == "__main__":
    print(json.dumps(govern()))

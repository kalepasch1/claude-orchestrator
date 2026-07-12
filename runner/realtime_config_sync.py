#!/usr/bin/env python3
"""
realtime_config_sync.py - push fleet-wide config changes in real-time via polling.

Uses frequent polling of the fleet_config table with change detection (ETag/hash)
to apply configuration changes to all machines with minimal delay, reducing the
need for manual pushes.

Integrates with fleet_control.py's existing safe-key filtering. Config changes
are detected by comparing a hash of all config rows against the last known hash.

Usage:
    import realtime_config_sync
    realtime_config_sync.start()   # starts background thread
    realtime_config_sync.stop()    # stops it
    realtime_config_sync.stats()   # monitoring
"""
import os, sys, time, threading, hashlib, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("realtime_config_sync")

_ENABLED = os.environ.get("ORCH_REALTIME_CONFIG_SYNC", "true").lower() == "true"
_POLL_INTERVAL = float(os.environ.get("ORCH_CONFIG_POLL_INTERVAL", "5"))  # seconds
_MIN_INTERVAL = 2.0

_lock = threading.Lock()
_thread = None
_running = False
_last_hash = ""
_stats_data = {
    "syncs": 0,
    "changes_applied": 0,
    "errors": 0,
    "last_sync_ts": 0.0,
    "last_change_ts": 0.0,
}


def _config_hash(rows):
    """Compute a deterministic hash of config rows for change detection."""
    if not rows:
        return ""
    canonical = json.dumps(sorted(
        [(r.get("key", ""), r.get("value", "")) for r in rows]
    ), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _apply_config(rows):
    """Apply config rows to environment, using fleet_control's safe-key filter."""
    try:
        import fleet_control
    except ImportError:
        _log.warning("fleet_control not importable; skipping apply")
        return 0
    applied = 0
    for row in (rows or []):
        k = row.get("key", "")
        v = row.get("value", "")
        if fleet_control._safe_key(k):
            old = os.environ.get(k)
            if old != v:
                os.environ[k] = v
                applied += 1
                _log.info("realtime config applied: %s = %s", k, v[:50])
    return applied


def _poll_loop():
    """Background thread: poll fleet_config and apply changes."""
    global _last_hash, _running
    import db
    interval = max(_MIN_INTERVAL, _POLL_INTERVAL)
    while _running:
        try:
            rows = db.select("fleet_config", {"select": "key,value"}) or []
            h = _config_hash(rows)
            with _lock:
                _stats_data["syncs"] += 1
                _stats_data["last_sync_ts"] = time.time()
            if h != _last_hash and _last_hash:
                applied = _apply_config(rows)
                with _lock:
                    _stats_data["changes_applied"] += applied
                    if applied:
                        _stats_data["last_change_ts"] = time.time()
                _log.info("config change detected, applied %d keys", applied)
            _last_hash = h
        except Exception as exc:
            with _lock:
                _stats_data["errors"] += 1
            _log.warning("realtime config poll error: %s", exc)
        time.sleep(interval)


def start():
    """Start the background config sync thread."""
    global _thread, _running
    if not _ENABLED:
        _log.info("realtime config sync disabled")
        return
    with _lock:
        if _running:
            return
        _running = True
    _thread = threading.Thread(target=_poll_loop, daemon=True, name="realtime-config-sync")
    _thread.start()
    _log.info("realtime config sync started (interval=%.1fs)", _POLL_INTERVAL)


def stop():
    """Stop the background config sync thread."""
    global _running
    _running = False
    if _thread:
        _thread.join(timeout=10)
    _log.info("realtime config sync stopped")


def stats():
    """Return sync statistics."""
    with _lock:
        return dict(_stats_data)


# ---------------------------------------------------------------------------
# Git-commit / merge-event triggered config sync
# ---------------------------------------------------------------------------

_GIT_TRIGGER_ENABLED = os.environ.get("ORCH_CONFIG_GIT_TRIGGER", "true").lower() == "true"
_CONFIG_FILE_PATTERNS = ("fleet_config.json", "fleet_config.yaml", ".env.fleet")


def sync_from_git_event(repo_path, commit_sha=None):
    """Sync fleet config after a git commit or merge event.

    Checks if the commit touched any config files. If so, reads the updated
    config and pushes it to Supabase's fleet_config table via db.upsert.

    Returns {"synced": int, "skipped": int, "error": str|None}.
    """
    if not _GIT_TRIGGER_ENABLED:
        return {"synced": 0, "skipped": 0, "error": "git trigger disabled"}

    import subprocess
    try:
        # Determine which files changed in the commit
        sha = commit_sha or "HEAD"
        r = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha],
            cwd=repo_path, capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return {"synced": 0, "skipped": 0, "error": f"git diff-tree failed: {r.stderr.strip()}"}

        changed = set(r.stdout.strip().splitlines())
        config_changed = [f for f in changed if os.path.basename(f) in _CONFIG_FILE_PATTERNS]

        if not config_changed:
            return {"synced": 0, "skipped": 0, "error": None}

        # Parse config from the first matching file
        synced = 0
        skipped = 0
        for cfg_file in config_changed:
            full_path = os.path.join(repo_path, cfg_file)
            if not os.path.isfile(full_path):
                skipped += 1
                continue
            pairs = _parse_config_file(full_path)
            pushed = _push_config_to_db(pairs)
            synced += pushed
            skipped += len(pairs) - pushed

        with _lock:
            _stats_data["changes_applied"] += synced
            if synced:
                _stats_data["last_change_ts"] = time.time()

        _log.info("git-triggered config sync: %d synced, %d skipped", synced, skipped)
        return {"synced": synced, "skipped": skipped, "error": None}

    except Exception as exc:
        _log.warning("sync_from_git_event failed: %s", exc)
        return {"synced": 0, "skipped": 0, "error": str(exc)}


def _parse_config_file(path):
    """Parse a config file into a list of {key, value} dicts.

    Supports JSON objects and simple KEY=VALUE .env format.
    """
    pairs = []
    try:
        content = ""
        with open(path, "r", errors="replace") as f:
            content = f.read(64 * 1024)  # cap at 64KB

        if path.endswith(".json"):
            import json as _json
            data = _json.loads(content)
            if isinstance(data, dict):
                pairs = [{"key": k, "value": str(v)} for k, v in data.items()]
        elif path.endswith(".yaml") or path.endswith(".yml"):
            # Simple key: value parsing (no full YAML dep)
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    k, _, v = line.partition(":")
                    pairs.append({"key": k.strip(), "value": v.strip()})
        else:
            # .env format: KEY=VALUE
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, _, v = line.partition("=")
                    pairs.append({"key": k.strip(), "value": v.strip()})
    except Exception as exc:
        _log.warning("_parse_config_file(%s) failed: %s", path, exc)
    return pairs


def _push_config_to_db(pairs):
    """Push config pairs to fleet_config table. Returns count pushed."""
    try:
        import db
        import fleet_control
    except ImportError:
        return 0
    pushed = 0
    for p in pairs:
        k = p.get("key", "")
        v = p.get("value", "")
        if not k or not fleet_control._safe_key(k):
            continue
        try:
            db.upsert("fleet_config", {"key": k, "value": v})
            pushed += 1
        except Exception:
            pass
    return pushed

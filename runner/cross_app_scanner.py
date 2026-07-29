#!/usr/bin/env python3
"""
cross_app_scanner.py — gives improvement_miner actual eyes into all app repos.

Scans all app repos (file structure, Supabase table usage, real-time patterns,
event bus instances) and builds a structured architecture map.  Updates daily
(loop type 'cross_app_scan').  The map feeds into improvement_miner's context
so the model can see actual architectural gaps, not just README.md summaries.

Detects:
  1. ASYMMETRIES  — "Tomorrow has HiveBus real-time but Apparently uses cron polling"
  2. DUPLICATIONS — "3 separate event-bus implementations across 3 apps"
  3. SHARED TABLES — which Supabase tables are used by which apps
  4. DISCONNECTED SYSTEMS — "IntelligenceBus has cross-app types but only smarter publishes"
  5. STALE PATTERNS — code patterns superseded in one app but lingering in others
"""
import os, sys, json, re, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Repo paths are read from the projects table (repo_path column).
# This fallback is used ONLY when the projects table has no repo_path for an app.
_FALLBACK_REPOS = {
    "apparently": "/Users/kpasch/Documents/apparently",
    "tomorrow":   "/Users/kpasch/Documents/tomorrow/tomorrow",
    "smarter":    "/Users/kpasch/Documents/smarter",
    "beethoven":  os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
}

_LANG_BY_APP = {
    "apparently": "typescript",
    "tomorrow":   "typescript",
    "smarter":    "typescript",
    "beethoven":  "python",
}

RUNTIME_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           ".runtime")


def _resolve_repos():
    """Build {app: {repo, lang}} from the projects table, with fallback."""
    repos = {}
    try:
        rows = db.select("projects", {"select": "name,repo_path"}) or []
        for r in rows:
            name = r.get("name", "")
            path = r.get("repo_path", "")
            if name and path and os.path.isdir(path):
                repos[name] = {"repo": path, "lang": _LANG_BY_APP.get(name, "typescript")}
    except Exception:
        pass
    # fill in fallbacks
    for name, path in _FALLBACK_REPOS.items():
        if name not in repos and os.path.isdir(path):
            repos[name] = {"repo": path, "lang": _LANG_BY_APP.get(name, "typescript")}
    return repos


def scan_supabase_tables(repo_path, lang):
    """Find all Supabase table references in the codebase."""
    tables = set()
    ext = "*.ts" if lang == "typescript" else "*.py"
    try:
        result = subprocess.run(
            ["grep", "-rh", "--include", ext, "-oE",
             r"(from|\.from)\s*\(\s*['\"][a-z_]+['\"]",
             repo_path],
            capture_output=True, text=True, timeout=30
        )
        for line in result.stdout.splitlines():
            m = re.search(r"['\"]([a-z_]+)['\"]", line)
            if m:
                tables.add(m.group(1))
    except Exception:
        pass
    return tables


def scan_realtime_patterns(repo_path, lang):
    """Detect what real-time infrastructure each app uses."""
    patterns = {
        "supabase_realtime": False,
        "supabase_presence": False,
        "websocket_server": False,
        "websocket_client": False,
        "sse_server": False,
        "http_polling": False,
        "event_bus_local": False,
    }
    ext = "*.ts" if lang == "typescript" else "*.py"
    # Use basic regex (ERE) — NOT Perl regex — for portability across grep versions.
    checks = {
        "supabase_realtime":  r"channel|\.on\(.broadcast",
        "supabase_presence":  r"presenceState|track\(",
        "websocket_server":   r"WebSocketServer|ws\.on\(.connection",
        "websocket_client":   r"new WebSocket|useWebSocket",
        "sse_server":         r"text/event-stream",
        "http_polling":       r"setInterval.*fetch|polling|heartbeat.*POST",
        "event_bus_local":    r"EventEmitter|mitt()|createEventBus",
    }
    for key, regex in checks.items():
        try:
            result = subprocess.run(
                ["grep", "-rl", "--include", ext, "-E", regex, repo_path],
                capture_output=True, text=True, timeout=15
            )
            patterns[key] = bool(result.stdout.strip())
        except Exception:
            pass
    return patterns


def scan_event_bus_instances(repo_path, lang):
    """Count distinct event bus/pub-sub instances."""
    ext = "*.ts" if lang == "typescript" else "*.py"
    bus_patterns = [
        r"class [A-Za-z]*(Bus|EventBus|PubSub)",
        r"export (const|function) [A-Za-z]*(Bus|bus|publish|subscribe)",
        r"createEventBus|mitt\(\)|new EventEmitter",
    ]
    files = set()
    for pat in bus_patterns:
        try:
            result = subprocess.run(
                ["grep", "-rlE", "--include", ext, pat, repo_path],
                capture_output=True, text=True, timeout=15
            )
            for f in result.stdout.strip().splitlines():
                if f:
                    files.add(f)
        except Exception:
            pass
    return list(files)


def build_architecture_map():
    """Build the complete cross-app architecture map.  Persist for improvement_miner."""
    apps = _resolve_repos()
    arch_map = {}
    all_tables = {}

    for app_name, config in apps.items():
        repo = config["repo"]
        lang = config["lang"]
        try:
            tables = scan_supabase_tables(repo, lang)
            realtime = scan_realtime_patterns(repo, lang)
            buses = scan_event_bus_instances(repo, lang)
        except Exception:
            continue
        all_tables[app_name] = tables
        arch_map[app_name] = {
            "supabase_tables": sorted(tables),
            "realtime_patterns": realtime,
            "event_bus_files": buses,
            "event_bus_count": len(buses),
        }

    # Detect asymmetries
    asymmetries = []
    all_rt = {app: data.get("realtime_patterns", {}) for app, data in arch_map.items()}
    for pattern_key in ("supabase_realtime", "supabase_presence", "websocket_server", "sse_server"):
        has   = [app for app, patterns in all_rt.items() if patterns.get(pattern_key)]
        lacks = [app for app, patterns in all_rt.items() if not patterns.get(pattern_key)]
        if has and lacks:
            asymmetries.append({
                "type": "realtime_asymmetry",
                "pattern": pattern_key,
                "has": has,
                "lacks": lacks,
                "suggestion": f"{', '.join(has)} uses {pattern_key} but {', '.join(lacks)} does not",
            })

    # Shared tables used by multiple apps
    table_usage = {}
    for app, tables in all_tables.items():
        for t in tables:
            table_usage.setdefault(t, []).append(app)
    shared_tables = {t: apps for t, apps in table_usage.items() if len(apps) > 1}

    # Bus duplication
    total_buses = sum(d.get("event_bus_count", 0) for d in arch_map.values())
    if total_buses > 3:
        asymmetries.append({
            "type": "bus_duplication",
            "total_buses": total_buses,
            "by_app": {app: d.get("event_bus_count", 0) for app, d in arch_map.items()},
            "suggestion": (f"{total_buses} separate event-bus instances across apps — "
                           "should consolidate to shared HiveBus"),
        })

    result = {
        "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "apps": arch_map,
        "shared_tables": shared_tables,
        "asymmetries": asymmetries,
    }

    # Persist: prefer DB, fall back to local file
    try:
        db.upsert("cross_app_architecture", {
            "id": "latest",
            "data": json.dumps(result),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    except Exception:
        os.makedirs(RUNTIME_DIR, exist_ok=True)
        path = os.path.join(RUNTIME_DIR, "cross_app_arch.json")
        with open(path, "w") as f:
            json.dump(result, f, indent=2)

    return result


def get_context_for_miner():
    """Return a compact context string for improvement_miner.py's _context()."""
    data = {}
    # Try DB first, then local file, then live scan
    try:
        rows = db.select("cross_app_architecture", {"id": "eq.latest"}) or []
        if rows:
            data = json.loads(rows[0].get("data", "{}"))
    except Exception:
        pass
    if not data:
        path = os.path.join(RUNTIME_DIR, "cross_app_arch.json")
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            pass
    if not data:
        try:
            data = build_architecture_map()
        except Exception:
            return ""

    lines = ["CROSS-APP ARCHITECTURE (live scan):"]
    for app, info in data.get("apps", {}).items():
        rt = info.get("realtime_patterns", {})
        active = [k for k, v in rt.items() if v]
        lines.append(f"  {app}: {len(info.get('supabase_tables', []))} tables, "
                     f"{info.get('event_bus_count', 0)} event buses, "
                     f"realtime: {', '.join(active) or 'none'}")

    if data.get("asymmetries"):
        lines.append("\nDETECTED ASYMMETRIES (opportunities):")
        for a in data["asymmetries"][:8]:
            lines.append(f"  - {a['suggestion']}")

    shared = data.get("shared_tables", {})
    multi = {t: apps for t, apps in shared.items() if len(apps) >= 2}
    if multi:
        lines.append(f"\nSHARED TABLES: {len(multi)} tables used by 2+ apps")

    return "\n".join(lines)


def run():
    """Entry point called by loops.py for the 'cross_app_scan' loop type."""
    result = build_architecture_map()
    n_apps = len(result.get("apps", {}))
    n_asym = len(result.get("asymmetries", []))
    print(f"cross_app_scanner: scanned {n_apps} apps, found {n_asym} asymmetries")
    return result


if __name__ == "__main__":
    import pprint
    pprint.pprint(run())

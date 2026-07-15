#!/usr/bin/env python3
"""
toolchain_gate.py — Verify project build toolchain before allowing task execution.

Instead of 100 tasks individually discovering that tsc/npm/python is broken, this module
runs a single toolchain check per project on startup (and every 30 minutes), caching the
result. If the toolchain is broken, tasks for that project are held in QUEUED state with
a note, and a single recovery task is queued to fix the toolchain.

This is a pre-run hook: runner.run_task() calls is_ready_cached(project_id) (no subprocess,
reads the cache written here) right after claiming and bails back to QUEUED before spending
any model tokens or setting up a worktree if the toolchain is known broken. The actual
`npm --version`/`tsc --version`/node_modules probing only happens in the periodic run()
below (every 30 min), never inline in the hot path.
"""
import os, sys, json, time, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
STATE_FILE = os.path.join(HOME, "toolchain_state.json")
CHECK_INTERVAL = 1800  # 30 minutes between checks per project
RECOVERY_COOLDOWN = 3600  # don't re-queue recovery within 1 hour

# Build commands to probe per project type
PROBES = [
    {"files": ["package.json"], "cmd": ["npm", "--version"], "name": "npm"},
    {"files": ["tsconfig.json"], "cmd": ["npx", "tsc", "--version"], "name": "tsc"},
    {"files": ["requirements.txt", "setup.py", "pyproject.toml"], "cmd": ["python3", "--version"], "name": "python3"},
    {"files": ["Cargo.toml"], "cmd": ["cargo", "--version"], "name": "cargo"},
    # Additional build tool probes added for broader coverage
    {"files": ["yarn.lock"], "cmd": ["yarn", "--version"], "name": "yarn"},
    {"files": ["pnpm-lock.yaml"], "cmd": ["pnpm", "--version"], "name": "pnpm"},
    {"files": ["nuxt.config.ts", "nuxt.config.js"], "cmd": ["npx", "nuxi", "--version"], "name": "nuxt"},
    {"files": ["next.config.js", "next.config.mjs", "next.config.ts"], "cmd": ["npx", "next", "--version"], "name": "next"},
    {"files": ["vite.config.ts", "vite.config.js"], "cmd": ["npx", "vite", "--version"], "name": "vite"},
    {"files": ["go.mod"], "cmd": ["go", "version"], "name": "go"},
    {"files": ["Makefile"], "cmd": ["make", "--version"], "name": "make"},
]


def _load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def check_project(project_id, repo_path):
    """Run toolchain probes for a project. Returns {"ready": bool, "failures": [...]}."""
    if not repo_path or not os.path.isdir(repo_path):
        return {"ready": True, "failures": []}  # can't check, assume OK

    failures = []
    probe_path = repo_path
    try:
        import dependency_prewarm
        probe_path = dependency_prewarm.runtime_root(repo_path)
    except Exception:
        pass
    for probe in PROBES:
        # Only check if the project has the relevant config files
        if not any(os.path.isfile(os.path.join(repo_path, f)) for f in probe["files"]):
            continue
        try:
            r = subprocess.run(probe["cmd"], capture_output=True, timeout=30, cwd=probe_path)
            if r.returncode != 0:
                failures.append({"tool": probe["name"],
                                 "error": (r.stderr.decode()[:200] if r.stderr else "exit code " + str(r.returncode))})
        except FileNotFoundError:
            failures.append({"tool": probe["name"], "error": f"{probe['cmd'][0]} not found in PATH"})
        except subprocess.TimeoutExpired:
            failures.append({"tool": probe["name"], "error": "timeout (>30s)"})
        except Exception as e:
            failures.append({"tool": probe["name"], "error": str(e)[:200]})

    # "build RED: npm not installed" is usually node_modules missing, not the npm binary
    # itself — that's a cheap filesystem check (no subprocess), so run it unconditionally.
    if os.path.isfile(os.path.join(repo_path, "package.json")):
        try:
            import dependency_prewarm
            # Shared immutable snapshots can be inspected concurrently by
            # version probes/activation. Require repeated negatives before
            # publishing a project-wide red verdict from a transient read.
            deps_ok = False
            for _ in range(3):
                if dependency_prewarm.deps_ready(repo_path):
                    deps_ok = True
                    break
                time.sleep(0.2)
            if not deps_ok:
                failures.append({"tool": "node_modules",
                                 "error": "dependencies not installed/warmed (dependency_prewarm.deps_ready=False)"})
        except Exception:
            pass  # best-effort; a broken prewarm check must never itself block claiming

    return {"ready": len(failures) == 0, "failures": failures}


def is_ready(project_id, repo_path=None, force=False):
    """Check if a project's toolchain is ready. Uses cached result within CHECK_INTERVAL."""
    state = _load_state()
    entry = state.get(project_id, {})

    # Use cached result if fresh enough
    if not force and time.time() - entry.get("checked_at", 0) < CHECK_INTERVAL:
        return entry.get("ready", True)

    # Need a fresh check
    if not repo_path:
        try:
            projects = db.select("projects", {"select": "id,repo_path", "id": f"eq.{project_id}"}) or []
            if projects:
                repo_path = projects[0].get("repo_path")
        except Exception:
            return True  # can't determine, don't block

    result = check_project(project_id, repo_path)
    state[project_id] = {
        "ready": result["ready"],
        "failures": result["failures"],
        "checked_at": time.time(),
        "recovery_queued_at": entry.get("recovery_queued_at", 0)
    }

    if not result["ready"]:
        # Queue a single recovery task if we haven't recently
        if time.time() - entry.get("recovery_queued_at", 0) > RECOVERY_COOLDOWN:
            _queue_recovery(project_id, result["failures"])
            state[project_id]["recovery_queued_at"] = time.time()
        print(f"[toolchain] project {project_id} NOT READY: {result['failures']}")

    _save_state(state)
    return result["ready"]


def is_ready_cached(project_id):
    """Read-only, no-subprocess check for the hot claim/run path. Returns the last cached
    verdict from the periodic probe (run() below, every 30 min); fails OPEN (True) when there
    is no cached entry yet so a cold start or brand-new project never gets stuck blocked on
    missing data. This is what makes it safe to call on every claimed task without adding
    subprocess latency to the poll loop — the actual `npm --version`/`tsc --version` probing
    only ever happens in the periodic job, never inline."""
    try:
        state = _load_state()
        entry = state.get(project_id)
        if not entry:
            return True
        return bool(entry.get("ready", True))
    except Exception:
        return True


def _queue_recovery(project_id, failures):
    """Queue a single task to fix the broken toolchain."""
    tool_names = ", ".join(f["tool"] for f in failures)
    errors = "; ".join(f"{f['tool']}: {f['error']}" for f in failures)
    try:
        db.insert("tasks", {
            "project_id": project_id,
            "slug": f"toolchain-repair-{project_id[:8]}",
            "prompt": (f"The project's build toolchain has failures that must be fixed before "
                       f"any other tasks can run. Fix these issues:\n\n{errors}\n\n"
                       f"Tools affected: {tool_names}. Ensure the relevant install command "
                       f"(npm install / yarn install / pnpm install / pip install / cargo build) "
                       f"and version checks all succeed after your fix."),
            "state": "QUEUED",
            "kind": "toolchain-repair",
            "material": True,
            "note": f"auto-queued: toolchain broken ({tool_names})"
        })
        print(f"[toolchain] queued repair task for {project_id}: {tool_names}")
    except Exception as e:
        print(f"[toolchain] failed to queue repair: {e}")


def run():
    """Periodic check: re-verify all projects."""
    try:
        projects = db.select("projects", {"select": "id,repo_path"}) or []
    except Exception:
        return
    for p in projects:
        is_ready(p["id"], p.get("repo_path"), force=True)


if __name__ == "__main__":
    run()

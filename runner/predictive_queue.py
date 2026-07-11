#!/usr/bin/env python3
"""
predictive_queue.py - Pre-generates queue items by analyzing project state, dependency
graphs, and patterns in past task sequences. When a human confirms a direction, the
work is already partially prepped.

Predictions use simple heuristics (not AI) for speed:
  - Sequential patterns: if "add-field-X" just merged, "add-tests-for-X" often follows
  - Dependency chains: if task A blocks B and A just finished, B is next
  - File-change patterns: recently modified files often need companion updates
  - TODO/FIXME scanning in recently changed files
  - Missing test files for recently added modules
  - Broken imports from recently renamed files

Predicted tasks are created in state SPECULATIVE (not QUEUED) — they require human
confirmation before execution.

Thread-safe, fail-soft throughout.
"""
import sys, os, json, time, threading, subprocess, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("predictive_queue")
import db

# ── Configuration ─────────────────────────────────────────────────────────────

ENABLED = os.environ.get("ORCH_PREDICTIVE_QUEUE_ENABLED", "false").lower() in ("true", "1", "yes")
PREDICT_MAX = int(os.environ.get("ORCH_PREDICT_MAX", "5"))

# ── Thread-safe stats ────────────────────────────────────────────────────────

_lock = threading.Lock()
_stats = {"predictions_made": 0, "confirmed": 0, "dismissed": 0}


def stats():
    """Return prediction stats including accuracy."""
    with _lock:
        s = dict(_stats)
    total_resolved = s["confirmed"] + s["dismissed"]
    s["accuracy"] = round(s["confirmed"] / total_resolved, 3) if total_resolved > 0 else 0.0
    return s


# ── TODO/FIXME scanner ───────────────────────────────────────────────────────

def scan_todos(repo_path):
    """Grep for TODO/FIXME/HACK/XXX in the repo. Returns structured list."""
    if not repo_path or not os.path.isdir(repo_path):
        return []
    results = []
    try:
        proc = subprocess.run(
            ["grep", "-rn", "-E", r"\b(TODO|FIXME|HACK|XXX)\b", "--include=*.py",
             "--include=*.js", "--include=*.ts", "--include=*.tsx", "--include=*.jsx",
             "--include=*.go", "--include=*.rs", "--include=*.rb", repo_path],
            capture_output=True, text=True, timeout=30
        )
        for line in (proc.stdout or "").splitlines()[:200]:
            # format: filepath:lineno:text
            parts = line.split(":", 2)
            if len(parts) >= 3:
                try:
                    results.append({
                        "file": parts[0],
                        "line": int(parts[1]),
                        "text": parts[2].strip()[:300]
                    })
                except (ValueError, IndexError):
                    continue
    except Exception as exc:
        _log.warning("scan_todos failed: %s", exc)
    return results


# ── Internal helpers ──────────────────────────────────────────────────────────

def _recent_outcomes(project_id, limit=20):
    """Fetch recently completed tasks for a project."""
    try:
        rows = db.select("tasks", {
            "select": "id,slug,state,prompt,note,updated_at",
            "project_id": f"eq.{project_id}",
            "state": "in.(DONE,MERGED)",
            "order": "updated_at.desc",
            "limit": str(limit),
        }) or []
        return rows
    except Exception as exc:
        _log.warning("_recent_outcomes query failed: %s", exc)
        return []


def _existing_slugs(project_id):
    """Return set of all slug strings for a project in live/settled states."""
    try:
        rows = db.select("tasks", {
            "select": "slug",
            "project_id": f"eq.{project_id}",
            "state": "in.(QUEUED,RUNNING,RETRY,DONE,MERGED,BLOCKED,DECOMPOSED,SPECULATIVE)",
        }) or []
        return {r.get("slug") for r in rows if r.get("slug")}
    except Exception:
        return set()


def _recently_changed_files(repo_path, limit=30):
    """Get files changed in recent commits."""
    if not repo_path or not os.path.isdir(repo_path):
        return []
    try:
        proc = subprocess.run(
            ["git", "-C", repo_path, "log", "--name-only", "--pretty=format:",
             f"-{limit}", "--diff-filter=ACMR"],
            capture_output=True, text=True, timeout=15
        )
        files = []
        seen = set()
        for line in (proc.stdout or "").splitlines():
            f = line.strip()
            if f and f not in seen:
                seen.add(f)
                files.append(f)
        return files[:100]
    except Exception as exc:
        _log.warning("_recently_changed_files failed: %s", exc)
        return []


def _find_missing_tests(repo_path, changed_files):
    """For recently added/modified source files, check if test files exist."""
    missing = []
    for f in changed_files:
        if not f.endswith(".py"):
            continue
        basename = os.path.basename(f)
        if basename.startswith("test_") or "/tests/" in f:
            continue
        # Check for a corresponding test file
        test_name = "test_" + basename
        dirname = os.path.dirname(f)
        # Look in same dir, tests/ subdir, and top-level tests/
        candidates = [
            os.path.join(repo_path, dirname, test_name),
            os.path.join(repo_path, dirname, "tests", test_name),
            os.path.join(repo_path, "tests", test_name),
        ]
        if not any(os.path.isfile(c) for c in candidates):
            missing.append(f)
    return missing


def _detect_sequential_patterns(recent_tasks):
    """Detect common sequential task patterns from completed work."""
    predictions = []
    for task in recent_tasks[:10]:
        slug = task.get("slug") or ""
        prompt = task.get("prompt") or ""

        # Pattern: add-X completed -> add-tests-for-X often follows
        m = re.match(r"^add-(.+)$", slug)
        if m and "test" not in slug:
            predictions.append({
                "slug": f"add-tests-for-{m.group(1)}",
                "prompt": f"Write comprehensive tests for the recently added {m.group(1)} feature. "
                          f"Cover normal paths, edge cases, and error handling.",
                "confidence": 0.75,
                "reason": f"Sequential pattern: '{slug}' completed, tests typically follow",
            })

        # Pattern: fix-X completed -> add-regression-test-X often follows
        m = re.match(r"^fix-(.+)$", slug)
        if m:
            predictions.append({
                "slug": f"add-regression-test-{m.group(1)}",
                "prompt": f"Add a regression test for the {m.group(1)} fix to prevent recurrence.",
                "confidence": 0.65,
                "reason": f"Sequential pattern: bug fix '{slug}' completed, regression test follows",
            })

        # Pattern: refactor-X -> update-docs-X
        m = re.match(r"^refactor-(.+)$", slug)
        if m:
            predictions.append({
                "slug": f"update-docs-{m.group(1)}",
                "prompt": f"Update documentation to reflect the {m.group(1)} refactor.",
                "confidence": 0.55,
                "reason": f"Sequential pattern: refactor '{slug}' completed, docs update follows",
            })

        # Pattern: implement-X -> integrate-X
        m = re.match(r"^implement-(.+)$", slug)
        if m:
            predictions.append({
                "slug": f"integrate-{m.group(1)}",
                "prompt": f"Integrate {m.group(1)} into the main codebase: wire up imports, "
                          f"add to runner startup, update configuration.",
                "confidence": 0.60,
                "reason": f"Sequential pattern: '{slug}' completed, integration step follows",
            })

    return predictions


def _detect_dependency_chains(project_id, recent_tasks):
    """Check if completed tasks unblock downstream dependencies."""
    predictions = []
    done_slugs = {t.get("slug") for t in recent_tasks if t.get("slug")}

    try:
        blocked = db.select("tasks", {
            "select": "id,slug,prompt,note,state",
            "project_id": f"eq.{project_id}",
            "state": "eq.BLOCKED",
            "limit": "20",
        }) or []
    except Exception:
        blocked = []

    for task in blocked:
        note = task.get("note") or ""
        # Check if the blocking task is now done
        for done_slug in done_slugs:
            if done_slug in note:
                predictions.append({
                    "slug": task.get("slug"),
                    "prompt": task.get("prompt") or f"Continue blocked task: {task.get('slug')}",
                    "confidence": 0.85,
                    "reason": f"Dependency chain: blocker '{done_slug}' is now DONE/MERGED",
                })
                break

    return predictions


def _detect_file_change_patterns(repo_path, changed_files):
    """Detect companion files that often need updating together."""
    predictions = []
    for f in changed_files[:15]:
        basename = os.path.basename(f)
        name_no_ext = os.path.splitext(basename)[0]

        # auth.py changed -> middleware.py might need updating
        companion_map = {
            "auth": ["middleware", "permissions", "session"],
            "models": ["serializers", "views", "admin"],
            "schema": ["migration", "validators"],
            "routes": ["middleware", "handlers"],
            "config": ["settings", "env"],
        }
        for trigger, companions in companion_map.items():
            if trigger in name_no_ext.lower():
                for comp in companions:
                    slug = f"review-{comp}-after-{name_no_ext}-change"
                    predictions.append({
                        "slug": slug,
                        "prompt": f"Review and update {comp}-related code after changes to {f}. "
                                  f"Check for compatibility, missing updates, and broken references.",
                        "confidence": 0.50,
                        "reason": f"File-change pattern: {basename} modified, {comp} often needs updating",
                    })

    return predictions


def _predictions_from_todos(repo_path, project_name):
    """Generate predictions from TODO/FIXME comments in recently changed files."""
    predictions = []
    todos = scan_todos(repo_path)
    # Only look at high-priority ones
    for todo in todos[:10]:
        text = todo.get("text", "")
        filepath = todo.get("file", "")
        relative = filepath.replace(repo_path, "").lstrip("/")

        # Filter for actionable TODOs (not just notes)
        if any(kw in text.upper() for kw in ["FIXME", "HACK", "XXX"]):
            confidence = 0.60
        elif "TODO" in text.upper():
            confidence = 0.45
        else:
            continue

        slug_base = re.sub(r"[^a-z0-9]+", "-", relative.lower())[:40].strip("-")
        slug = f"resolve-todo-in-{slug_base}"
        predictions.append({
            "slug": slug,
            "prompt": f"Resolve the TODO/FIXME in {relative} (line {todo.get('line', '?')}): "
                      f"{text[:200]}",
            "confidence": confidence,
            "reason": f"TODO/FIXME found in {relative}: {text[:80]}",
        })

    return predictions


def _predictions_from_missing_tests(repo_path, changed_files, project_name):
    """Generate predictions for missing test files."""
    predictions = []
    missing = _find_missing_tests(repo_path, changed_files)
    for f in missing[:5]:
        basename = os.path.basename(f)
        name_no_ext = os.path.splitext(basename)[0]
        slug = f"add-tests-for-{name_no_ext}"
        predictions.append({
            "slug": slug,
            "prompt": f"Create test file for {f}. Cover the public API, edge cases "
                      f"(None, empty string, bad paths), and error handling. Follow existing "
                      f"test conventions in the project.",
            "confidence": 0.65,
            "reason": f"Missing test file for recently modified module: {basename}",
        })
    return predictions


# ── Public API ────────────────────────────────────────────────────────────────

def predict_next_tasks(project_id, project_name, repo_path):
    """Analyze recently completed tasks and project state to predict what comes next.

    Returns at most PREDICT_MAX predictions sorted by confidence, each:
        {"slug": str, "prompt": str, "confidence": float, "reason": str}
    """
    if not project_id:
        return []

    try:
        recent = _recent_outcomes(project_id)
        existing = _existing_slugs(project_id)
        changed_files = _recently_changed_files(repo_path)

        all_predictions = []

        # 1. Dependency chains (highest signal)
        all_predictions.extend(_detect_dependency_chains(project_id, recent))

        # 2. Sequential patterns from recent tasks
        all_predictions.extend(_detect_sequential_patterns(recent))

        # 3. Missing test files
        all_predictions.extend(_predictions_from_missing_tests(repo_path, changed_files, project_name))

        # 4. TODO/FIXME scanning
        all_predictions.extend(_predictions_from_todos(repo_path, project_name))

        # 5. File-change companion patterns
        all_predictions.extend(_detect_file_change_patterns(repo_path, changed_files))

        # Deduplicate by slug, keep highest confidence
        seen = {}
        for pred in all_predictions:
            slug = pred["slug"]
            # Skip if already exists in the task table
            if slug in existing:
                continue
            if slug not in seen or pred["confidence"] > seen[slug]["confidence"]:
                seen[slug] = pred

        result = sorted(seen.values(), key=lambda p: p["confidence"], reverse=True)
        return result[:PREDICT_MAX]

    except Exception as exc:
        _log.warning("predict_next_tasks failed: %s", exc)
        return []


def generate_speculative_tasks(project_id, project_name, repo_path):
    """Generate SPECULATIVE tasks from predictions. Returns count created."""
    if not ENABLED:
        return 0

    predictions = predict_next_tasks(project_id, project_name, repo_path)
    created = 0

    for pred in predictions:
        if pred["confidence"] < 0.7:
            continue
        try:
            row = {
                "project_id": project_id,
                "slug": pred["slug"],
                "prompt": pred["prompt"],
                "state": "SPECULATIVE",
                "note": f"predictive-queue: {pred['reason']}",
                "kind": "code",
            }
            result = db.insert("tasks", row)
            if result:
                created += 1
                _log.info("created SPECULATIVE task: %s (confidence=%.2f)",
                          pred["slug"], pred["confidence"])
        except Exception as exc:
            _log.warning("failed to create speculative task %s: %s", pred["slug"], exc)

    with _lock:
        _stats["predictions_made"] += created

    return created


def confirm_prediction(task_id):
    """Move a SPECULATIVE task to QUEUED for execution."""
    if not task_id:
        return
    try:
        db.update("tasks", {"id": task_id}, {"state": "QUEUED",
                  "note": "predictive-queue: confirmed by operator"})
        with _lock:
            _stats["confirmed"] += 1
        _log.info("confirmed prediction: task %s -> QUEUED", task_id)
    except Exception as exc:
        _log.warning("confirm_prediction failed for task %s: %s", task_id, exc)


def dismiss_prediction(task_id):
    """Move a SPECULATIVE task to DISMISSED (tracks what was wrong)."""
    if not task_id:
        return
    try:
        db.update("tasks", {"id": task_id}, {"state": "DISMISSED",
                  "note": "predictive-queue: dismissed by operator"})
        with _lock:
            _stats["dismissed"] += 1
        _log.info("dismissed prediction: task %s -> DISMISSED", task_id)
    except Exception as exc:
        _log.warning("dismiss_prediction failed for task %s: %s", task_id, exc)

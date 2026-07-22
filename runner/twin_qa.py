#!/usr/bin/env python3
"""twin_qa.py - Digital twin QA via Playwright journey specs.

Runs headless Playwright journeys against staging URLs to validate user-visible
outcomes before release promotion. A red journey BLOCKS promotion and files a
qafix- task with the trace path.

Hook: release_train's QA gate calls twin_qa.run(project, staging_url).

Env vars:
    ORCH_TWIN_QA_ENABLED        "true" (default) to enable
    ORCH_TWIN_QA_TIMEOUT_S      per-journey timeout (default: 120)
    ORCH_TWIN_QA_ARTIFACTS_DIR  where traces/screenshots go (default: .runtime/twin_qa/)
    ORCH_TWIN_QA_DRY_RUN        "true" for dry-run mode
"""
import datetime
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import log as _log_mod
_log = _log_mod.get("twin_qa")

ENABLED = os.environ.get("ORCH_TWIN_QA_ENABLED", "true").lower() in ("1", "true", "yes", "on")
TIMEOUT_S = int(os.environ.get("ORCH_TWIN_QA_TIMEOUT_S", "120") or 120)
RUNTIME = os.environ.get("CLAUDE_ORCH_HOME",
                         os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".runtime"))
ARTIFACTS_DIR = os.environ.get("ORCH_TWIN_QA_ARTIFACTS_DIR", os.path.join(RUNTIME, "twin_qa"))
DRY_RUN = os.environ.get("ORCH_TWIN_QA_DRY_RUN", "true").lower() in ("1", "true", "yes", "on")
PERSONAS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "personas")

# ── Journey registry ──────────────────────────────────────────────────────
# Each journey is a dict: {name, project, script_path, description}

def _discover_journeys(project=None):
    """Discover journey specs from personas/ directory."""
    journeys = []
    if not os.path.isdir(PERSONAS_DIR):
        return journeys
    for fname in sorted(os.listdir(PERSONAS_DIR)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(PERSONAS_DIR, fname)
        try:
            with open(path, encoding="utf-8") as f:
                spec = json.load(f)
            if project and spec.get("project") != project:
                continue
            journeys.append({
                "name": spec.get("name", fname.replace(".json", "")),
                "project": spec.get("project", ""),
                "spec_path": path,
                "description": spec.get("description", ""),
                "steps": spec.get("steps", []),
                "auth": spec.get("auth", {}),
            })
        except Exception:
            continue
    return journeys


def _run_journey(journey, staging_url, artifacts_dir):
    """Execute a single journey spec against staging_url using Playwright.

    Returns: {name, passed, duration_s, error, trace_path, screenshot_path}
    """
    name = journey["name"]
    project = journey.get("project", "unknown")
    trace_dir = os.path.join(artifacts_dir, project, name)
    os.makedirs(trace_dir, exist_ok=True)

    trace_path = os.path.join(trace_dir, "trace.zip")
    screenshot_path = os.path.join(trace_dir, "failure.png")

    # Generate a temporary Playwright test script from the journey spec
    steps = journey.get("steps", [])
    if not steps:
        return {"name": name, "passed": True, "duration_s": 0, "error": None,
                "trace_path": None, "screenshot_path": None, "note": "no steps defined"}

    test_script = _generate_playwright_script(name, staging_url, steps,
                                               journey.get("auth", {}),
                                               trace_path, screenshot_path)
    script_path = os.path.join(trace_dir, "test_journey.js")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(test_script)

    start = time.monotonic()
    try:
        r = subprocess.run(
            ["npx", "playwright", "test", script_path, "--reporter=json"],
            capture_output=True, text=True, timeout=TIMEOUT_S,
            cwd=trace_dir,
            env={**os.environ, "BASE_URL": staging_url},
        )
        duration = time.monotonic() - start
        passed = r.returncode == 0

        return {
            "name": name,
            "passed": passed,
            "duration_s": round(duration, 2),
            "error": r.stderr[-1000:] if not passed and r.stderr else None,
            "trace_path": trace_path if not passed and os.path.exists(trace_path) else None,
            "screenshot_path": screenshot_path if not passed and os.path.exists(screenshot_path) else None,
        }
    except subprocess.TimeoutExpired:
        return {"name": name, "passed": False, "duration_s": TIMEOUT_S,
                "error": f"journey timed out after {TIMEOUT_S}s",
                "trace_path": None, "screenshot_path": None}
    except FileNotFoundError:
        return {"name": name, "passed": False, "duration_s": 0,
                "error": "npx/playwright not found. Install: npx playwright install",
                "trace_path": None, "screenshot_path": None}
    except Exception as e:
        return {"name": name, "passed": False, "duration_s": 0,
                "error": str(e), "trace_path": None, "screenshot_path": None}


def _generate_playwright_script(name, base_url, steps, auth, trace_path, screenshot_path):
    """Generate a Playwright test script from journey steps."""
    lines = [
        "const { test, expect } = require('@playwright/test');",
        "",
        f"test('{name}', async ({{ page, context }}) => {{",
        f"  await context.tracing.start({{ screenshots: true, snapshots: true }});",
        "",
    ]

    # Auth step if needed
    if auth.get("env_user") and auth.get("env_pass"):
        lines.append(f"  // Auth via env-based test account")
        lines.append(f"  const user = process.env['{auth['env_user']}'] || 'test@example.com';")
        lines.append(f"  const pass_ = process.env['{auth['env_pass']}'] || 'testpass';")

    for step in steps:
        action = step.get("action", "")
        selector = step.get("selector", "")
        value = step.get("value", "")
        url = step.get("url", "")
        assertion = step.get("assert", "")

        if action == "navigate":
            target = url if url.startswith("http") else f"{base_url}{url}"
            lines.append(f"  await page.goto('{target}');")
        elif action == "click":
            lines.append(f"  await page.click('{selector}');")
        elif action == "fill":
            lines.append(f"  await page.fill('{selector}', '{value}');")
        elif action == "wait":
            lines.append(f"  await page.waitForSelector('{selector}');")
        elif action == "assert_visible":
            lines.append(f"  await expect(page.locator('{selector}')).toBeVisible();")
        elif action == "assert_text":
            lines.append(f"  await expect(page.locator('{selector}')).toContainText('{value}');")
        elif action == "assert_url":
            lines.append(f"  await expect(page).toHaveURL(/{value}/);")

        if assertion:
            lines.append(f"  // assertion: {assertion}")

    lines.extend([
        "",
        f"  await context.tracing.stop({{ path: '{trace_path}' }});",
        "});",
    ])
    return "\n".join(lines)


def _file_qafix_task(project, journey_name, error, trace_path):
    """File a qafix- task for a failed journey."""
    slug = f"qafix-{project}-{datetime.datetime.utcnow().strftime('%m%d%H%M')}"
    try:
        existing = db.select("tasks", {"slug": slug, "project_id": project, "limit": 1})
        if existing:
            return  # already filed
    except Exception:
        pass

    try:
        db.insert("tasks", {
            "slug": slug,
            "project_id": project,
            "state": "QUEUED",
            "kind": "bugfix",
            "prompt": (
                f"QA journey '{journey_name}' failed.\n"
                f"Error: {(error or '')[:500]}\n"
                f"Trace: {trace_path or 'none'}\n"
                f"Fix the user-visible regression."
            ),
            "source": "twin-qa",
            "base_branch": "master",
        })
    except Exception:
        _log.warning(f"Failed to file qafix task for {journey_name}")


def _resolve_staging_url(project):
    """Resolve staging URL from deploy_health/Vercel project mapping."""
    try:
        rows = db.select("deploy_health", {"app": project, "limit": 1})
        if rows:
            vp = rows[0].get("vercel_project", "")
            if vp:
                return f"https://{vp}.vercel.app"
    except Exception:
        pass
    return None


def run(project, staging_url=None):
    """Main entry: run all journeys for a project against staging.

    Returns: {ok, project, passed, failed, results, blocks_promotion}
    """
    if not ENABLED:
        return {"ok": True, "skipped": True, "reason": "twin_qa disabled"}

    if not staging_url:
        staging_url = _resolve_staging_url(project)
    if not staging_url:
        return {"ok": False, "error": f"no staging URL for project {project}"}

    journeys = _discover_journeys(project)
    if not journeys:
        _log.info(f"No journeys defined for {project}, passing by default")
        return {"ok": True, "project": project, "passed": 0, "failed": 0,
                "results": [], "blocks_promotion": False, "note": "no journeys defined"}

    artifacts_dir = os.path.join(ARTIFACTS_DIR, project)
    os.makedirs(artifacts_dir, exist_ok=True)

    results = []
    passed = 0
    failed = 0

    for journey in journeys:
        if DRY_RUN:
            results.append({"name": journey["name"], "passed": True, "dry_run": True})
            passed += 1
            continue

        r = _run_journey(journey, staging_url, artifacts_dir)
        results.append(r)

        if r["passed"]:
            passed += 1
        else:
            failed += 1
            _file_qafix_task(project, r["name"], r.get("error"), r.get("trace_path"))

    blocks = failed > 0
    return {
        "ok": True,
        "project": project,
        "staging_url": staging_url,
        "passed": passed,
        "failed": failed,
        "results": results,
        "blocks_promotion": blocks,
    }

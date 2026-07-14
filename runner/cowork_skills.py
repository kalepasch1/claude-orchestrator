#!/usr/bin/env python3
"""
cowork_skills.py — On-demand Cowork skill dispatcher.

When the orchestrator determines a task requires capabilities only available
through Cowork sessions (browser automation, document generation, interactive
approval), this module handles dispatching. It constructs skill-specific prompts,
invokes them via claude_cli.run(), and feeds outcomes back to the routing system.

Skills dispatched:
- browser_automation: Claude-in-Chrome for web interaction, visual verification,
  scraping, form filling, testing
- document_generation: docx/pptx/xlsx creation via Cowork document skills
- visual_verification: screenshot-driven deployment/UI verification
- interactive_approval: tasks requiring mid-execution human input (reserved)

Architecture:
- Each skill type has a prompt template that instructs Claude on how to use
  the relevant Cowork tools
- Execution is via claude_cli.run() which handles Agent SDK / API / CLI dispatch
- Outcomes are recorded to db for bandit learning (both a dedicated
  skill_outcomes row and a bandit-compatible outcomes row)
- Shadow mode runs skills in parallel with the main pipeline for validation,
  without ever replacing the primary result

Conventions followed (see runner/CLAUDE.md "Learned from merged work"):
- stdlib only, fail-soft everywhere (never raise on bad input; swallow errors
  that would otherwise wedge a runner loop)
- env var configuration for every tunable
- thread-safe module-level singleton state guarded by a lock, disk/network I/O
  kept outside the critical section
- module-level functions delegate to shared state; no state threaded through
  call chains
"""

import os, sys, json, time, threading, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Configuration ────────────────────────────────────────────────────

ENABLED = os.environ.get("ORCH_COWORK_SKILLS", "true").lower() in ("1", "true", "yes")
SHADOW_MODE = os.environ.get("ORCH_COWORK_SHADOW", "true").lower() in ("1", "true", "yes")
SKILL_TIMEOUT = int(os.environ.get("ORCH_COWORK_SKILL_TIMEOUT", "600") or 600)
SKILL_MODEL = os.environ.get("ORCH_COWORK_SKILL_MODEL", "claude-sonnet-5")
MAX_CONCURRENT = int(os.environ.get("ORCH_COWORK_MAX_CONCURRENT", "3") or 3)

_lock = threading.Lock()
_active_count = 0
_outcomes = []  # recent outcomes, ring-buffered, for stats()

# ── Skill prompt templates ───────────────────────────────────────────

_BROWSER_AUTOMATION_TEMPLATE = """You are executing a browser automation task for the orchestrator.

TASK: {task_description}

INSTRUCTIONS:
1. Use Claude-in-Chrome browser tools to complete this task
2. Navigate to the required URLs and interact with web pages
3. Extract any required data or verify visual elements
4. If you encounter CAPTCHAs or login walls, report them as blockers — do NOT attempt to bypass
5. Return results as structured JSON in your final message

TARGET URL: {target_url}
EXPECTED OUTCOME: {expected_outcome}

Return your results as:
```json
{{"status": "success|failure|blocked", "data": {{}}, "screenshots": [], "errors": []}}
```
"""

_DOCUMENT_GENERATION_TEMPLATE = """You are generating a document for the orchestrator.

TASK: {task_description}

DOCUMENT TYPE: {doc_type}
OUTPUT PATH: {output_path}

INSTRUCTIONS:
1. Use the {skill_name} skill to create this document
2. Follow the skill's formatting and structure guidelines
3. Save the completed document to the specified output path
4. Verify the document was created successfully

CONTENT REQUIREMENTS:
{content_requirements}

Return your results as:
```json
{{"status": "success|failure", "output_path": "", "pages": 0, "errors": []}}
```
"""

_VISUAL_VERIFICATION_TEMPLATE = """You are performing visual verification for the orchestrator.

TASK: Verify the deployment at {target_url}

CHECKS TO PERFORM:
{verification_checks}

INSTRUCTIONS:
1. Navigate to the URL using Claude-in-Chrome
2. Take screenshots of key pages/elements
3. Verify each check item visually
4. Report pass/fail for each check

Return your results as:
```json
{{"status": "pass|fail", "checks": [{{"name": "", "passed": true/false, "notes": ""}}], "errors": []}}
```
"""

# ── Skill type detection ─────────────────────────────────────────────

_SKILL_PATTERNS = {
    "browser_automation": [
        re.compile(r"(?i)\b(browse|scrape|crawl|navigate|click|interact|test)\b.*\b(web\w*|page|site|url|browser|dashboard|app)\b"),
        re.compile(r"(?i)\b(web\w*|page|site|url|browser|dashboard)\b.*\b(browse|scrape|crawl|navigate|click|interact|verify|check|screenshot)\b"),
        re.compile(r"(?i)\bvisual\s+(verification|check|test|inspect)\b"),
        re.compile(r"(?i)\bweb\s+(interaction|test|scrape|automat)\b"),
        re.compile(r"(?i)\bchrome\b"),
        re.compile(r"(?i)\b(navigate|browse)\b.*\bscreenshot\b"),
        re.compile(r"(?i)\bscreenshot\b.*\b(web\w*|page|site|dashboard|deploy)\b"),
    ],
    "document_generation": [
        re.compile(r"(?i)\b(create|generate|make|build|produce|write)\b.*\b(docx|pptx|xlsx|word|presentation|spreadsheet|slide|powerpoint|excel)\b"),
        re.compile(r"(?i)\.(docx|pptx|xlsx|dotx|potx|xltx)\b"),
    ],
    "visual_verification": [
        re.compile(r"(?i)\b(verify|check|confirm|validate)\b.*\b(deploy|visual|render|display|ui|layout)\b"),
        re.compile(r"(?i)\bscreenshot\b.*\b(compar|verify|check)\b"),
    ],
}

_DOC_TYPE_MAP = {
    "docx": {"skill": "docx", "ext": ".docx"},
    "word": {"skill": "docx", "ext": ".docx"},
    "pptx": {"skill": "pptx", "ext": ".pptx"},
    "presentation": {"skill": "pptx", "ext": ".pptx"},
    "slides": {"skill": "pptx", "ext": ".pptx"},
    "deck": {"skill": "pptx", "ext": ".pptx"},
    "powerpoint": {"skill": "pptx", "ext": ".pptx"},
    "xlsx": {"skill": "xlsx", "ext": ".xlsx"},
    "spreadsheet": {"skill": "xlsx", "ext": ".xlsx"},
    "excel": {"skill": "xlsx", "ext": ".xlsx"},
}


def detect_skill_type(task):
    """
    Determine which Cowork skill(s) a task requires.
    Returns list of (skill_type, confidence) tuples, sorted by confidence desc.
    Fail-soft: returns [] on any error or malformed task.
    """
    try:
        if not isinstance(task, dict):
            return []

        text_parts = []
        for field in ("slug", "title", "description", "prompt", "needs", "kind", "objective"):
            val = task.get(field, "")
            if isinstance(val, str) and val:
                text_parts.append(val)
        combined = " ".join(text_parts)

        if not combined.strip():
            return []

        results = []
        for skill_type, patterns in _SKILL_PATTERNS.items():
            matches = sum(1 for p in patterns if p.search(combined))
            if matches:
                confidence = min(1.0, matches * 0.3 + 0.1)
                results.append((skill_type, confidence))

        # Explicit skill tags override/augment detection
        explicit = task.get("required_skills", [])
        if isinstance(explicit, str):
            explicit = [s.strip() for s in explicit.split(",")]
        if isinstance(explicit, list):
            for sk in explicit:
                if sk in _SKILL_PATTERNS:
                    results.append((sk, 1.0))

        # Deduplicate, keep highest confidence per skill type
        seen = {}
        for st, conf in results:
            if st not in seen or conf > seen[st]:
                seen[st] = conf

        return sorted(seen.items(), key=lambda x: -x[1])
    except Exception:
        return []


def _task_text(task, fields):
    try:
        return " ".join(
            task.get(f, "") for f in fields
            if isinstance(task.get(f, ""), str)
        )
    except Exception:
        return ""


def _detect_doc_type(task):
    """Extract document type from task description. Fail-soft: defaults to docx."""
    try:
        combined = _task_text(task, ("slug", "title", "description", "prompt")).lower()
        for keyword, info in _DOC_TYPE_MAP.items():
            if keyword in combined:
                return info
    except Exception:
        pass
    return {"skill": "docx", "ext": ".docx"}  # default


def _extract_url(task):
    """Extract target URL from task if present. Fail-soft: '' on error/absence."""
    try:
        combined = _task_text(task, ("description", "prompt", "needs", "url"))
        urls = re.findall(r"https?://[^\s<>\"']+", combined)
        return urls[0] if urls else ""
    except Exception:
        return ""


# ── Prompt construction ──────────────────────────────────────────────

def _build_prompt(task, skill_type):
    """Build the skill-specific prompt for Claude. Fail-soft: falls back to raw description."""
    try:
        desc = task.get("description", "") or task.get("prompt", "") or task.get("title", "") or ""
        slug = task.get("slug", "unknown") or "unknown"

        if skill_type == "browser_automation":
            url = _extract_url(task)
            return _BROWSER_AUTOMATION_TEMPLATE.format(
                task_description=desc,
                target_url=url or "(extract from task description)",
                expected_outcome=task.get("expected_outcome", "Complete the web interaction successfully"),
            )

        if skill_type == "document_generation":
            doc_info = _detect_doc_type(task)
            output_path = task.get("output_path") or f"/tmp/orchestrator-output/{slug}{doc_info['ext']}"
            return _DOCUMENT_GENERATION_TEMPLATE.format(
                task_description=desc,
                doc_type=doc_info["ext"],
                output_path=output_path,
                skill_name=doc_info["skill"],
                content_requirements=desc,
            )

        if skill_type == "visual_verification":
            url = _extract_url(task)
            checks = task.get("verification_checks", desc)
            return _VISUAL_VERIFICATION_TEMPLATE.format(
                target_url=url or "(extract from task description)",
                verification_checks=checks,
            )

        return desc
    except Exception:
        return task.get("description", "") if isinstance(task, dict) else ""


# ── Outcome recording (bandit / routing feedback) ────────────────────

def _record_outcome(task, skill_type, result, elapsed_s):
    """Record skill execution outcome for the bandit/routing feedback loop.
    Fail-soft: DB errors never propagate; in-memory ring buffer is best-effort."""
    status = (result or {}).get("status", "unknown")
    try:
        import db
        row = {
            "task_id": task.get("id", ""),
            "project_id": task.get("project_id", ""),
            "skill_type": skill_type,
            "provider": "claude",
            "model": SKILL_MODEL,
            "status": status,
            "elapsed_s": round(elapsed_s, 1),
            "shadow": SHADOW_MODE,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        db.insert("skill_outcomes", row)
    except Exception:
        pass

    # Also feed the bandit's shared `outcomes` table (see runner/bandit.py) so
    # cowork-dispatched work participates in the same model_router learning loop
    # as regular task execution.
    try:
        import db
        db.insert("outcomes", {
            "task_id": task.get("id", ""),
            "model": SKILL_MODEL,
            "kind": f"cowork_{skill_type}",
            "usd": (result or {}).get("cost_usd", 0) or 0,
            "tests_passed": status == "success",
            "integrated": status == "success",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
    except Exception:
        pass

    with _lock:
        _outcomes.append({
            "task_id": task.get("id", "") if isinstance(task, dict) else "",
            "skill_type": skill_type,
            "status": status,
            "elapsed_s": round(elapsed_s, 1),
            "ts": time.time(),
        })
        while len(_outcomes) > 100:  # bounded ring buffer
            _outcomes.pop(0)


# ── Execution ────────────────────────────────────────────────────────

def execute_skill(task, skill_type=None, force=False):
    """
    Execute a Cowork skill for a task.

    Args:
        task: Task dict with standard orchestrator fields
        skill_type: Override skill type detection. If None, auto-detects.
        force: Execute even if ENABLED is False (for testing / shadow mode)

    Returns:
        dict with {status, data, errors, skill_type, elapsed_s}. Never raises.
    """
    if not isinstance(task, dict):
        return {"status": "error", "data": {}, "errors": ["task must be a dict"], "skill_type": skill_type or "", "elapsed_s": 0}

    if not ENABLED and not force:
        return {"status": "disabled", "data": {}, "errors": ["ORCH_COWORK_SKILLS is disabled"], "skill_type": skill_type or "", "elapsed_s": 0}

    try:
        # Detect skill type if not provided
        if not skill_type:
            detected = detect_skill_type(task)
            if not detected:
                return {"status": "no_skill_needed", "data": {}, "errors": [], "skill_type": "", "elapsed_s": 0}
            skill_type = detected[0][0]

        # Concurrency gate — never let a burst of skill dispatches wedge the runner
        global _active_count
        with _lock:
            if _active_count >= MAX_CONCURRENT:
                return {"status": "throttled", "data": {}, "errors": [f"At max concurrent skills ({MAX_CONCURRENT})"], "skill_type": skill_type, "elapsed_s": 0}
            _active_count += 1

        try:
            prompt = _build_prompt(task, skill_type)
            cwd = task.get("worktree") or task.get("cwd") or None

            t0 = time.time()

            try:
                import claude_cli
                raw = claude_cli.run(
                    prompt=prompt,
                    model=SKILL_MODEL,
                    cwd=cwd,
                    project=task.get("project_id") or task.get("project"),
                    timeout=SKILL_TIMEOUT,
                )
            except Exception as e:
                elapsed = time.time() - t0
                result = {"status": "error", "data": {}, "errors": [str(e)]}
                _record_outcome(task, skill_type, result, elapsed)
                return {**result, "skill_type": skill_type, "elapsed_s": round(elapsed, 1)}

            elapsed = time.time() - t0

            result = _parse_skill_result(raw, skill_type)
            result["cost_usd"] = (raw or {}).get("cost_usd", 0) if isinstance(raw, dict) else 0
            _record_outcome(task, skill_type, result, elapsed)

            return {**result, "skill_type": skill_type, "elapsed_s": round(elapsed, 1)}

        finally:
            with _lock:
                _active_count = max(0, _active_count - 1)

    except Exception as e:
        return {"status": "error", "data": {}, "errors": [str(e)], "skill_type": skill_type or "", "elapsed_s": 0}


def _parse_skill_result(raw, skill_type):
    """Parse Claude's response to extract structured result.
    `raw` is claude_cli.run()'s return dict: {text, cost_usd, returncode, raw, ...}.
    Fail-soft: any parse error returns a 'parse_error' status rather than raising."""
    try:
        if isinstance(raw, dict):
            text = raw.get("text", "") or ""
            if not text and raw.get("raw"):
                try:
                    text = json.dumps(raw["raw"])
                except Exception:
                    text = str(raw.get("raw"))
        elif isinstance(raw, str):
            text = raw
        else:
            text = str(raw)

        # Non-zero returncode / skipped calls short-circuit as failure/blocked
        if isinstance(raw, dict):
            if raw.get("skipped"):
                return {"status": "blocked", "data": {"reason": raw["skipped"]}, "errors": [f"skipped: {raw['skipped']}"]}
            if raw.get("returncode") not in (0, None):
                # fall through to text parsing first; only treat as hard failure if no
                # structured status can be recovered from the text below
                pass

        # Try to extract fenced JSON from response
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group(1))
            return {
                "status": parsed.get("status", "unknown"),
                "data": parsed,
                "errors": parsed.get("errors", []),
            }

        # Try raw JSON line parse
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    parsed = json.loads(line)
                    if "status" in parsed:
                        return {"status": parsed["status"], "data": parsed, "errors": parsed.get("errors", [])}
                except json.JSONDecodeError:
                    continue

        # Heuristic fallback: check for success/failure indicators in prose
        lower = text.lower()
        if any(w in lower for w in ("success", "completed", "done", "passed")):
            return {"status": "success", "data": {"raw": text[:2000]}, "errors": []}
        if any(w in lower for w in ("error", "failed", "failure", "blocked")):
            return {"status": "failure", "data": {"raw": text[:2000]}, "errors": [text[:500]]}

        return {"status": "unknown", "data": {"raw": text[:2000]}, "errors": []}

    except Exception:
        return {"status": "parse_error", "data": {}, "errors": ["Failed to parse skill result"]}


# ── Shadow / parallel validation mode ────────────────────────────────

def shadow_execute(task, primary_result=None):
    """
    Execute skill in shadow mode — runs alongside the primary pipeline,
    compares results, but does NOT replace the primary result.

    Used during validation phase before full cutover to Cowork-dispatched
    execution for a given skill class. Fail-soft: returns None on any error
    or when SHADOW_MODE is disabled, so a shadow failure never affects the
    primary task outcome.
    """
    if not SHADOW_MODE:
        return None

    try:
        if not isinstance(task, dict):
            return None

        detected = detect_skill_type(task)
        if not detected:
            return None

        skill_type = detected[0][0]
        result = execute_skill(task, skill_type=skill_type, force=True)

        comparison = None
        if primary_result:
            comparison = {
                "primary_status": primary_result.get("status", "unknown"),
                "shadow_status": result.get("status", "unknown"),
                "match": primary_result.get("status") == result.get("status"),
                "shadow_faster": result.get("elapsed_s", 999) < primary_result.get("elapsed_s", 999),
            }

        try:
            import db
            db.insert("shadow_comparisons", {
                "task_id": task.get("id", ""),
                "skill_type": skill_type,
                "primary_status": (primary_result or {}).get("status", ""),
                "shadow_status": result.get("status", "unknown"),
                "match": (comparison or {}).get("match", False),
                "shadow_elapsed_s": result.get("elapsed_s", 0),
                "primary_elapsed_s": (primary_result or {}).get("elapsed_s", 0),
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
        except Exception:
            pass

        return {"result": result, "comparison": comparison}

    except Exception:
        return None


# ── Stats & diagnostics ──────────────────────────────────────────────

def stats():
    """Return skill execution stats for operator dashboards. Fail-soft: never raises."""
    try:
        with _lock:
            recent = list(_outcomes)
            active = _active_count

        total = len(recent)
        if not total:
            return {"total": 0, "active": active, "enabled": ENABLED, "shadow_mode": SHADOW_MODE}

        by_type = {}
        by_status = {}
        total_elapsed = 0
        for o in recent:
            st = o.get("skill_type", "unknown")
            status = o.get("status", "unknown")
            by_type[st] = by_type.get(st, 0) + 1
            by_status[status] = by_status.get(status, 0) + 1
            total_elapsed += o.get("elapsed_s", 0)

        return {
            "total": total,
            "active": active,
            "enabled": ENABLED,
            "shadow_mode": SHADOW_MODE,
            "by_skill_type": by_type,
            "by_status": by_status,
            "avg_elapsed_s": round(total_elapsed / total, 1),
            "success_rate": round(by_status.get("success", 0) / total, 3),
        }
    except Exception:
        return {"total": 0, "active": 0, "enabled": ENABLED, "shadow_mode": SHADOW_MODE}


# ── Module-level convenience ─────────────────────────────────────────

def needs_skill(task):
    """Quick check: does this task need any Cowork skill? Fail-soft: False on error."""
    try:
        return bool(detect_skill_type(task))
    except Exception:
        return False


def run(task, **kwargs):
    """Module-level entry point matching the codebase's run()/choose() convention."""
    return execute_skill(task, **kwargs)


if __name__ == "__main__":
    print(json.dumps(stats(), indent=2))

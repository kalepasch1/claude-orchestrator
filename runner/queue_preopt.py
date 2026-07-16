"""
queue_preopt.py — Queue Pre-Optimization System.

Background daemon that pre-processes QUEUED tasks while they wait, so when a runner
claims them, expensive hook computations are already cached and execution starts faster.

Pre-computes:
  - context_pack: repo map + conventions block
  - precedent: most-similar merged change
  - unified_knowledge: cross-store knowledge matches
  - ensemble_predictor: failure prediction
  - output_recycling: partial work from prior attempts
  - ai_review: cheap-model (haiku) spec review for completeness

Usage:
  # In runner.py main loop, start the background daemon:
  import queue_preopt
  queue_preopt.start()

  # In run_task(), check for pre-computed results:
  cached = queue_preopt.get(task_id)
  if cached:
      _extras = cached.get("context_pack", "")
      # ... skip expensive re-computation

  # When a task is claimed or state changes:
  queue_preopt.invalidate(task_id)

The daemon is intentionally low-priority: it yields to active task execution and
throttles itself based on system load.
"""

import os
import sys
import time
import json
import threading
import hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("queue_preopt")

# ── Configuration ──────────────────────────────────────────────────────────────

# How often the daemon scans for idle QUEUED tasks (seconds)
SCAN_INTERVAL = float(os.environ.get("ORCH_PREOPT_SCAN_INTERVAL", "30"))

# Max tasks to pre-optimize per scan cycle
MAX_PER_CYCLE = int(os.environ.get("ORCH_PREOPT_MAX_PER_CYCLE", "5"))

# TTL for cached pre-optimizations (seconds) — re-compute if stale
CACHE_TTL = float(os.environ.get("ORCH_PREOPT_CACHE_TTL", "300"))

# Skip pre-opt when system load exceeds this (0.0-1.0)
LOAD_CEILING = float(os.environ.get("ORCH_PREOPT_LOAD_CEILING", "0.85"))

# Enable/disable the daemon entirely
ENABLED = os.environ.get("ORCH_PREOPT_ENABLED", "true").lower() in ("true", "1", "yes")

# Enable AI review of queued task specs (uses cheap model, costs tokens)
AI_REVIEW_ENABLED = os.environ.get("ORCH_PREOPT_AI_REVIEW", "true").lower() in ("true", "1", "yes")

AI_REVIEW_MODEL = os.environ.get("ORCH_PREOPT_AI_MODEL", "claude-haiku-4-5-20251001")

# Enable speculative pre-drafting (haiku writes actual code while task idles)
PREDRAFT_ENABLED = os.environ.get("ORCH_PREOPT_PREDRAFT", "true").lower() in ("true", "1", "yes")

# Enable multi-round spec refinement
SPEC_REFINE_ENABLED = os.environ.get("ORCH_PREOPT_SPEC_REFINE", "true").lower() in ("true", "1", "yes")

# Enable test harness pre-generation
TEST_PREGEN_ENABLED = os.environ.get("ORCH_PREOPT_TEST_PREGEN", "true").lower() in ("true", "1", "yes")

# Enable speculative branch execution (actually run agent on idle tasks)
SPEC_EXEC_ENABLED = os.environ.get("ORCH_PREOPT_SPEC_EXEC", "false").lower() in ("true", "1", "yes")

# Capacity threshold for speculative execution (only when fleet is this idle)
SPEC_EXEC_CAPACITY = float(os.environ.get("ORCH_PREOPT_SPEC_EXEC_CAPACITY", "0.4"))

# Enable queue topology optimizer integration
OPTIMIZER_ENABLED = os.environ.get("ORCH_QUEUE_OPTIMIZER_ENABLED", "true").lower() in ("true", "1", "yes")

# Enable task fusion integration
FUSION_ENABLED = os.environ.get("ORCH_TASK_FUSION_ENABLED", "false").lower() in ("true", "1", "yes")

# Pattern compiler integration (on by default — zero risk, read-only cache)
PATTERN_COMPILER_ENABLED = os.environ.get("ORCH_PATTERN_COMPILER_ENABLED", "true").lower() in ("true", "1", "yes")


# ── Cache ──────────────────────────────────────────────────────────────────────

_cache_lock = threading.Lock()
_cache = {}  # task_id -> {"ts": float, "data": dict, "task_hash": str}

_daemon_thread = None
_stop_event = threading.Event()

# Disk-backed cache so OTHER processes (cowork_assemble.py CLI) can read pre-optimizations.
_DISK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".preopt_cache")


def _disk_path(task_id):
    return os.path.join(_DISK_DIR, "%s.json" % task_id)


def _disk_read(task_id):
    try:
        with open(_disk_path(task_id)) as f:
            entry = json.load(f)
        if time.time() - entry.get("ts", 0) > CACHE_TTL:
            try: os.remove(_disk_path(task_id))
            except OSError: pass
            return None
        return entry
    except Exception:
        return None


def get(task_id):
    """Retrieve pre-computed results for a task. Returns None if no cache or expired."""
    with _cache_lock:
        entry = _cache.get(task_id)
    if not entry:
        entry = _disk_read(task_id)
        if not entry:
            return None
        return entry["data"]
    if time.time() - entry["ts"] > CACHE_TTL:
        invalidate(task_id)
        return None
    return entry["data"]


# Back-compat: cowork_assemble.py calls get_cache(); keep both names working.
get_cache = get


def invalidate(task_id):
    """Remove cached pre-optimization for a task (e.g. when claimed or modified)."""
    with _cache_lock:
        _cache.pop(task_id, None)
    try:
        os.remove(_disk_path(task_id))
    except OSError:
        pass


def invalidate_all():
    """Clear the entire pre-optimization cache."""
    with _cache_lock:
        _cache.clear()
    # The cache is shared across runner processes. Clearing only this process's
    # memory lets another consumer immediately resurrect stale disk entries.
    try:
        for name in os.listdir(_DISK_DIR):
            if name.endswith(".json"):
                try:
                    os.remove(os.path.join(_DISK_DIR, name))
                except OSError:
                    pass
    except OSError:
        pass


def stats():
    """Return cache statistics for monitoring, including all subsystems."""
    with _cache_lock:
        cached_ids = list(_cache.keys())
        now = time.time()
        fresh = sum(1 for e in _cache.values() if now - e["ts"] < CACHE_TTL)
        # Count stages across all cached entries
        stage_counts = {}
        for e in _cache.values():
            for s in e.get("data", {}).get("stages", []):
                stage_counts[s] = stage_counts.get(s, 0) + 1

    result = {
        "cached_tasks": len(cached_ids),
        "fresh": fresh,
        "stale": len(cached_ids) - fresh,
        "enabled": ENABLED,
        "daemon_alive": _daemon_thread is not None and _daemon_thread.is_alive(),
        "stage_counts": stage_counts,
    }

    # Subsystem stats
    for mod_name in ("pattern_compiler", "task_fusion", "queue_optimizer"):
        try:
            mod = __import__(mod_name)
            if hasattr(mod, "stats"):
                result[mod_name] = mod.stats()
        except Exception:
            pass

    return result


def start():
    """Start the background pre-optimization daemon. Idempotent."""
    global _daemon_thread
    if not ENABLED:
        _log.info("queue pre-optimization disabled (ORCH_PREOPT_ENABLED=false)")
        return
    if _daemon_thread is not None and _daemon_thread.is_alive():
        return
    _stop_event.clear()
    _daemon_thread = threading.Thread(target=_daemon_loop, daemon=True, name="queue-preopt")
    _daemon_thread.start()
    _log.info("queue pre-optimization daemon started (interval=%ss, max_per_cycle=%d)",
              SCAN_INTERVAL, MAX_PER_CYCLE)


def stop():
    """Stop the background daemon."""
    _stop_event.set()
    if _daemon_thread is not None:
        _daemon_thread.join(timeout=10)
    _log.info("queue pre-optimization daemon stopped")


# ── Daemon Loop ────────────────────────────────────────────────────────────────

def _daemon_loop():
    """Main daemon loop: scan QUEUED tasks, pre-optimize uncached ones,
    run queue optimizer and task fusion periodically."""
    _optimizer_t = 0.0
    _compiler_t = 0.0
    _fusion_t = 0.0
    _optimizer_interval = float(os.environ.get("ORCH_OPTIMIZER_INTERVAL", "120"))
    _compiler_interval = float(os.environ.get("ORCH_COMPILER_INTERVAL", "180"))
    _fusion_interval = float(os.environ.get("ORCH_FUSION_INTERVAL", "300"))

    while not _stop_event.is_set():
        now = time.time()

        # Core: pre-optimize individual tasks
        try:
            _scan_and_preopt()
        except Exception as e:
            _log.debug("preopt scan cycle failed: %s", e)

        # Periodic: queue topology optimizer
        if OPTIMIZER_ENABLED and now - _optimizer_t > _optimizer_interval:
            _optimizer_t = now
            try:
                import queue_optimizer
                result = queue_optimizer.optimize()
                if result and result.get("total_modifications", 0) > 0:
                    _log.debug("queue_optimizer: %s", result)
            except Exception as e:
                _log.debug("queue_optimizer failed: %s", e)

        # Periodic: pattern compiler refresh
        if PATTERN_COMPILER_ENABLED and now - _compiler_t > _compiler_interval:
            _compiler_t = now
            try:
                import pattern_compiler
                count = pattern_compiler.compile_patterns()
                if count:
                    _log.debug("pattern_compiler: %d patterns compiled", count)
            except Exception as e:
                _log.debug("pattern_compiler failed: %s", e)

        # Periodic: task fusion (only when enabled — default off)
        if FUSION_ENABLED and now - _fusion_t > _fusion_interval:
            _fusion_t = now
            try:
                import task_fusion
                result = task_fusion.scan_and_fuse()
                if result and result.get("fused_clusters", 0) > 0:
                    _log.debug("task_fusion: %s", result)
            except Exception as e:
                _log.debug("task_fusion failed: %s", e)

        _stop_event.wait(SCAN_INTERVAL)


def _scan_and_preopt():
    """One scan cycle: find QUEUED tasks, pre-optimize up to MAX_PER_CYCLE."""
    # Check system load — don't compete with active task execution
    if not _system_has_capacity():
        return

    import db

    # Fetch QUEUED tasks ordered by priority (same ordering as claim_task)
    queued = db.select("tasks", {
        "select": "id,slug,project_id,deps,kind,prompt,note,created_at,confidence",
        "state": "eq.QUEUED",
        "order": "created_at.asc",
        "limit": str(MAX_PER_CYCLE * 3),  # fetch more, filter to uncached
    }) or []

    if not queued:
        return

    # Filter to tasks not already cached (or stale)
    now = time.time()
    to_process = []
    for t in queued:
        tid = t.get("id")
        if not tid:
            continue
        with _cache_lock:
            entry = _cache.get(tid)
        if entry and now - entry["ts"] < CACHE_TTL:
            # Check if task changed since cached (prompt/note hash)
            current_hash = _task_hash(t)
            if entry.get("task_hash") == current_hash:
                continue  # still fresh and unchanged
        to_process.append(t)
        if len(to_process) >= MAX_PER_CYCLE:
            break

    if not to_process:
        return

    # Get project info for repo paths
    projects = {}
    try:
        projs = db.select("projects", {"select": "id,name,repo_path"}) or []
        projects = {p["id"]: p for p in projs}
    except Exception:
        pass

    for t in to_process:
        if _stop_event.is_set():
            break
        try:
            result = _preopt_task(t, projects)
            if result:
                _store(t["id"], result, _task_hash(t))
                _log.debug("pre-optimized task %s (%s)", t["id"], t.get("slug", "?"))
        except Exception as e:
            _log.debug("preopt for task %s failed: %s", t.get("id"), e)


def _preopt_task(t, projects):
    """Pre-compute expensive hook results for a single QUEUED task."""
    result = {"preopt_at": time.time(), "stages": []}
    tid = t.get("id")
    pid = t.get("project_id")
    proj = projects.get(pid, {})
    repo = proj.get("repo_path", "")
    name = proj.get("name", "")

    # Localize repo path for this machine
    try:
        import db as _db
        repo = _db.localize_repo_path(repo) if hasattr(_db, "localize_repo_path") else repo
    except Exception:
        pass

    if not repo or not os.path.isdir(repo):
        return result  # can't pre-optimize without a repo

    # Stage 1: Context pack (repo map + conventions)
    try:
        import context_pack
        result["context_pack"] = context_pack.block(repo)
        result["stages"].append("context_pack")
    except Exception as e:
        _log.debug("preopt context_pack failed for %s: %s", tid, e)

    # Stage 2: Precedent hint (most-similar merged change)
    try:
        import precedent
        result["precedent_hint"] = precedent.hint(t, repo, project_id=pid)
        result["stages"].append("precedent")
    except Exception as e:
        _log.debug("preopt precedent failed for %s: %s", tid, e)

    # Stage 3: Unified knowledge query
    try:
        import unified_knowledge
        uk = unified_knowledge.query(t, name, repo, attempt=0)
        if uk and uk.get("matches"):
            result["unified_knowledge"] = uk
            result["stages"].append("unified_knowledge")
    except Exception as e:
        _log.debug("preopt unified_knowledge failed for %s: %s", tid, e)

    # Stage 4: Ensemble failure prediction
    try:
        import ensemble_predictor, model_portfolios
        _domain = "backend"
        try:
            _domain = model_portfolios.classify(t, [])
        except Exception:
            pass
        ens = ensemble_predictor.predict(t, "claude:claude-sonnet-4-6", _domain, "claude-sonnet-4-6")
        if ens:
            result["ensemble_prediction"] = ens
            result["stages"].append("ensemble_prediction")
    except Exception as e:
        _log.debug("preopt ensemble_predictor failed for %s: %s", tid, e)

    # Stage 5: Output recycling (prior attempt partial work)
    try:
        import output_recycling
        recycled = output_recycling.get_recycled(tid)
        if recycled:
            result["recycled_output"] = recycled
            result["stages"].append("output_recycling")
    except Exception as e:
        _log.debug("preopt output_recycling failed for %s: %s", tid, e)

    # Stage 6: Transfer learning query
    try:
        import transfer_learning
        transfer = transfer_learning.find_transfer(t, current_project=name)
        if transfer:
            result["transfer_learning"] = transfer
            result["stages"].append("transfer_learning")
    except Exception as e:
        _log.debug("preopt transfer_learning failed for %s: %s", tid, e)

    # Stage 7: Prompt distillation lookup
    try:
        import prompt_distillation
        distilled = prompt_distillation.find_distilled(t, current_project=name)
        if distilled:
            result["prompt_distillation"] = distilled
            result["stages"].append("prompt_distillation")
    except Exception as e:
        _log.debug("preopt prompt_distillation failed for %s: %s", tid, e)

    # Stage 8: AI spec review (cheap model reviews task for completeness/issues)
    if AI_REVIEW_ENABLED:
        try:
            ai_review = _ai_review_task(t, repo, name)
            if ai_review:
                result["ai_review"] = ai_review
                result["stages"].append("ai_review")
        except Exception as e:
            _log.debug("preopt ai_review failed for %s: %s", tid, e)

    # Stage 9: Pattern compilation match (deterministic zero-token replay)
    if PATTERN_COMPILER_ENABLED:
        try:
            import pattern_compiler
            pattern_compiler.compile_patterns()  # ensure patterns are fresh
            pm = pattern_compiler.match(t)
            if pm and pm.get("confidence", 0) > 0.6:
                result["pattern_match"] = pm
                result["stages"].append("pattern_match")
        except Exception as e:
            _log.debug("preopt pattern_compiler failed for %s: %s", tid, e)

    # Stage 10: Multi-model spec refinement (3-round haiku loop)
    if SPEC_REFINE_ENABLED:
        try:
            refined = _refine_spec(t, repo, name)
            if refined:
                result["refined_spec"] = refined
                result["stages"].append("spec_refinement")
        except Exception as e:
            _log.debug("preopt spec_refine failed for %s: %s", tid, e)

    # Stage 11: Pre-generate test harness
    if TEST_PREGEN_ENABLED:
        try:
            tests = _pre_generate_tests(t, repo, name)
            if tests:
                result["pre_generated_tests"] = tests
                result["stages"].append("test_harness")
        except Exception as e:
            _log.debug("preopt test_pregen failed for %s: %s", tid, e)

    # Stage 12: Speculative pre-drafting (haiku writes actual code)
    if PREDRAFT_ENABLED:
        try:
            draft = _speculative_draft(t, repo, name, result)
            if draft:
                result["speculative_draft"] = draft
                result["stages"].append("speculative_draft")
        except Exception as e:
            _log.debug("preopt predraft failed for %s: %s", tid, e)

    # Stage 13: Merge validation of speculative draft
    draft = result.get("speculative_draft")
    if draft and draft.get("diff"):
        try:
            import merge_validator
            proj_rows = projects.get(pid, {})
            test_cmd = proj_rows.get("test_cmd") or os.environ.get("ORCH_DEFAULT_TEST_CMD", "")
            if test_cmd:
                validation = merge_validator.validate_draft(
                    t, draft["diff"], repo, proj_rows.get("default_base", "main"), test_cmd)
                if validation.get("valid"):
                    result["merge_validation"] = validation
                    result["stages"].append("merge_validation")
                    _log.debug("preopt merge_validation passed for %s — fast-track eligible", tid)
                elif validation.get("failures"):
                    result["merge_validation_failures"] = validation["failures"]
                    result["stages"].append("merge_validation_constraints")
        except Exception as e:
            _log.debug("preopt merge_validation failed for %s: %s", tid, e)

    # Stage 14: Hivemind pre-query (warm the cache)
    try:
        import task_memory
        _hive = task_memory.hivemind_query(t, name)
        if _hive and _hive.get("insights"):
            result["hivemind"] = _hive
            result["stages"].append("hivemind")
    except Exception as e:
        _log.debug("preopt hivemind failed for %s: %s", tid, e)

    # Stage 15: Retry budget pre-computation
    try:
        import retry_budget
        _rb_max = retry_budget.max_attempts(t)
        if _rb_max != 4:
            result["retry_budget"] = {"max_attempts": _rb_max}
            result["stages"].append("retry_budget")
    except Exception as e:
        _log.debug("preopt retry_budget failed for %s: %s", tid, e)

    # Stage 16: Prompt compression measurement
    try:
        import prompt_compressor
        _measure = prompt_compressor.measure(t.get("prompt", ""), "")
        if _measure.get("estimated_tokens", 0) > 10000:
            result["prompt_measurement"] = _measure
            result["stages"].append("prompt_measurement")
    except Exception as e:
        _log.debug("preopt prompt_measurement failed for %s: %s", tid, e)

    # Stage 17: Cross-project pattern transfer check
    try:
        import pattern_transfer
        _pid = t.get("project_id")
        if _pid:
            _transferable = pattern_transfer.find_transferable(_pid, _pid)
            if _transferable:
                result["pattern_transfers"] = _transferable[:3]
                result["stages"].append("pattern_transfer")
    except Exception as e:
        _log.debug("preopt pattern_transfer failed for %s: %s", tid, e)

    return result


def _refine_spec(t, repo, project_name):
    """Three-round spec refinement: identify ambiguities → resolve with repo context → produce refined spec."""
    prompt_text = t.get("prompt") or ""
    if not prompt_text or len(prompt_text) < 30:
        return None

    try:
        import claude_cli
    except Exception:
        return None

    # Round 1: Identify ambiguities
    r1_prompt = f"""You are a spec reviewer for an automated coding system. Analyze this task spec and return JSON:
{{"ambiguities": ["list of unclear points"], "missing_acceptance_criteria": ["list"], "unclear_file_scope": true/false, "questions": ["what would you ask the author"]}}

Task: {t.get('slug', '?')}
Spec:
{prompt_text[:3000]}

Return ONLY valid JSON."""

    try:
        r1 = claude_cli.run(r1_prompt, AI_REVIEW_MODEL, timeout=90)
        r1_text = r1.get("text", "")
        import re
        m1 = re.search(r"\{.*\}", r1_text, re.S)
        if not m1:
            return None
        analysis = json.loads(m1.group(0))
    except Exception as e:
        _log.debug("spec refine round 1 failed: %s", e)
        return None

    if not analysis.get("ambiguities") and not analysis.get("missing_acceptance_criteria"):
        return {"refined_prompt": prompt_text, "confidence": 0.9, "rounds": 1,
                "note": "spec already clear — no refinement needed"}

    # Round 2: Resolve ambiguities using repo context
    # Read CLAUDE.md conventions if available
    conventions = ""
    try:
        cmd_path = os.path.join(repo, "CLAUDE.md")
        if os.path.isfile(cmd_path):
            with open(cmd_path) as f:
                conventions = f.read()[:2000]
    except Exception:
        pass

    r2_prompt = f"""You are resolving ambiguities in a coding task spec. Given the analysis and project conventions, produce a refined version of the spec that:
1. Resolves each ambiguity with a concrete decision based on conventions
2. Adds explicit acceptance criteria
3. Specifies exact file paths where possible

Analysis: {json.dumps(analysis)[:1500]}

Project conventions:
{conventions[:1500]}

Original spec:
{prompt_text[:2500]}

Return JSON: {{"refined_prompt": "the improved spec text", "resolutions": ["what you resolved"], "confidence": 0.0-1.0}}"""

    try:
        r2 = claude_cli.run(r2_prompt, AI_REVIEW_MODEL, timeout=120)
        m2 = re.search(r"\{.*\}", r2.get("text", ""), re.S)
        if not m2:
            return None
        refined = json.loads(m2.group(0))
        refined["rounds"] = 2
        refined["analysis"] = analysis
        refined["tokens_used"] = (r1.get("input_tokens", 0) + r1.get("output_tokens", 0) +
                                   r2.get("input_tokens", 0) + r2.get("output_tokens", 0))
        return refined
    except Exception as e:
        _log.debug("spec refine round 2 failed: %s", e)
        return None


def _pre_generate_tests(t, repo, project_name):
    """Pre-generate test cases for the task while it idles."""
    prompt_text = t.get("prompt") or ""
    if not prompt_text or len(prompt_text) < 30:
        return None

    # Find existing test patterns in the repo
    test_examples = ""
    try:
        import subprocess
        result = subprocess.run(
            ["find", repo, "-name", "test_*.py", "-o", "-name", "*.test.ts", "-o", "-name", "*_test.go"],
            capture_output=True, text=True, timeout=10, cwd=repo
        )
        test_files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()][:5]
        for tf in test_files[:2]:
            try:
                with open(tf) as f:
                    content = f.read()[:1000]
                test_examples += f"\n# Example from {os.path.basename(tf)}:\n{content}\n"
            except Exception:
                pass
    except Exception:
        pass

    test_prompt = f"""You are generating tests for an automated coding system. Based on the task spec, write test cases that the implementation must pass.

Follow the project's existing test patterns:
{test_examples[:2000]}

Task: {t.get('slug', '?')}
Spec:
{prompt_text[:3000]}

Return JSON: {{"test_code": "complete test file content", "test_file_path": "suggested/path/test_file.py", "test_count": N, "coverage_areas": ["what aspects are tested"]}}
Return ONLY valid JSON."""

    try:
        import claude_cli, re
        r = claude_cli.run(test_prompt, AI_REVIEW_MODEL, timeout=120)
        m = re.search(r"\{.*\}", r.get("text", ""), re.S)
        if m:
            tests = json.loads(m.group(0))
            tests["tokens_used"] = r.get("input_tokens", 0) + r.get("output_tokens", 0)
            return tests
    except Exception as e:
        _log.debug("test pregen failed: %s", e)
    return None


def _speculative_draft(t, repo, project_name, preopt_result):
    """Have a cheap model write the actual code change. The expensive agent gets this as a warm-start."""
    prompt_text = t.get("prompt") or ""
    if not prompt_text or len(prompt_text) < 30:
        return None

    # Use refined spec if available (from stage 10)
    refined = preopt_result.get("refined_spec", {})
    spec_to_use = refined.get("refined_prompt", prompt_text) if refined else prompt_text

    # Read relevant source files mentioned in the spec
    source_context = ""
    try:
        import re as _re
        file_refs = _re.findall(r'[\w/]+\.(?:py|ts|js|go|rs|java|tsx|jsx)', spec_to_use)
        for fref in file_refs[:3]:
            fpath = os.path.join(repo, fref)
            if os.path.isfile(fpath):
                try:
                    with open(fpath) as f:
                        content = f.read()[:2000]
                    source_context += f"\n# Current content of {fref}:\n```\n{content}\n```\n"
                except Exception:
                    pass
    except Exception:
        pass

    draft_prompt = f"""You are a coding agent. Implement the following task and return your changes as a unified diff.

Project: {project_name}
Task: {t.get('slug', '?')}

{spec_to_use[:4000]}

{source_context[:4000]}

Return ONLY a unified diff (diff -u format) that implements the change. No explanation, just the diff."""

    try:
        import claude_cli
        r = claude_cli.run(draft_prompt, AI_REVIEW_MODEL, timeout=180)
        diff_text = r.get("text", "")
        if not diff_text or len(diff_text) < 20:
            return None
        return {
            "diff": diff_text,
            "model": AI_REVIEW_MODEL,
            "tokens_used": r.get("input_tokens", 0) + r.get("output_tokens", 0),
            "cost_usd": r.get("cost_usd", 0),
            "from_refined_spec": bool(refined),
        }
    except Exception as e:
        _log.debug("speculative draft failed: %s", e)
    return None


def _ai_review_task(t, repo, project_name):
    """Have a cheap model review the task spec for completeness, ambiguity, and issues.
    Returns structured review or None."""
    prompt_text = t.get("prompt") or t.get("slug") or ""
    if not prompt_text or len(prompt_text) < 20:
        return None

    review_prompt = f"""You are a pre-flight reviewer for an automated coding system. Review this task
spec and return a JSON object with:
- "issues": list of potential problems (missing context, ambiguous scope, conflicting requirements)
- "suggestions": list of improvements that would help the coding agent succeed on first pass
- "estimated_complexity": "trivial"|"simple"|"moderate"|"complex"|"very_complex"
- "recommended_model": "haiku"|"sonnet"|"opus" (based on complexity)
- "missing_context": list of files or context the agent will likely need
- "merge_risk": "low"|"medium"|"high" with brief reason

Project: {project_name}
Task slug: {t.get('slug', 'unknown')}
Task kind: {t.get('kind', 'unknown')}

Task spec:
{prompt_text[:4000]}

Return ONLY valid JSON, no markdown fences."""

    try:
        import claude_cli
        r = claude_cli.run(review_prompt, AI_REVIEW_MODEL, timeout=120)
        import re
        m = re.search(r"\{.*\}", r.get("text", ""), re.S)
        if m:
            review = json.loads(m.group(0))
            review["model_used"] = AI_REVIEW_MODEL
            review["tokens"] = {
                "input": r.get("input_tokens", 0),
                "output": r.get("output_tokens", 0),
            }
            return review
    except Exception as e:
        _log.debug("ai_review model call failed: %s", e)
    return None


# ── Integration: runner.py hooks into these ────────────────────────────────────

def apply_cached(task_id, draft_prompt, t, repo, name, attempt):
    """Apply pre-computed results to a task being executed. Returns (modified_prompt, extras, notes).
    Call this early in run_task() to skip redundant hook computations."""
    cached = get(task_id)
    if not cached:
        return draft_prompt, "", []

    notes = []
    extras = ""

    # Apply context pack
    if cached.get("context_pack"):
        extras += cached["context_pack"]
        notes.append("preopt:context_pack")

    # Apply precedent hint
    if cached.get("precedent_hint"):
        extras += cached["precedent_hint"]
        notes.append("preopt:precedent")

    # Apply unified knowledge matches
    uk = cached.get("unified_knowledge")
    if uk and uk.get("matches"):
        try:
            import unified_knowledge as _uk_mod
            draft_prompt = _uk_mod._apply_match(draft_prompt, uk["matches"][0])
            notes.append(f"preopt:unified_knowledge ({len(uk['matches'])} matches)")
        except Exception:
            pass

    # Apply recycled output
    if cached.get("recycled_output"):
        try:
            import output_recycling
            draft_prompt = output_recycling.inject_recycled(draft_prompt, cached["recycled_output"])
            notes.append("preopt:output_recycling")
        except Exception:
            pass

    # Apply transfer learning
    if cached.get("transfer_learning"):
        try:
            import transfer_learning
            draft_prompt = transfer_learning.inject_transfer(draft_prompt, cached["transfer_learning"])
            notes.append(f"preopt:transfer_learning ({cached['transfer_learning'].get('source_project', '?')})")
        except Exception:
            pass

    # Apply prompt distillation
    if cached.get("prompt_distillation"):
        try:
            import prompt_distillation
            draft_prompt = prompt_distillation.apply_distilled(draft_prompt, cached["prompt_distillation"])
            notes.append("preopt:prompt_distillation")
        except Exception:
            pass

    # Log AI review insights (advisory, doesn't change prompt)
    ai = cached.get("ai_review")
    if ai:
        issues = ai.get("issues", [])
        if issues:
            notes.append(f"preopt:ai_review ({len(issues)} issues, risk={ai.get('merge_risk', '?')})")

    # Apply refined spec (replace prompt with improved version)
    refined = cached.get("refined_spec")
    if refined and refined.get("refined_prompt") and refined.get("confidence", 0) > 0.5:
        draft_prompt = refined["refined_prompt"]
        notes.append(f"preopt:spec_refinement (conf={refined['confidence']:.0%}, {refined.get('rounds', 0)} rounds)")

    # Apply pre-generated test harness (append to prompt)
    tests = cached.get("pre_generated_tests")
    if tests and tests.get("test_code"):
        test_block = (f"\n\n## Pre-Generated Test Harness\n"
                      f"The following tests were pre-generated for this task. "
                      f"Ensure your implementation passes them:\n"
                      f"```\n{tests['test_code'][:3000]}\n```\n"
                      f"Suggested test file: {tests.get('test_file_path', 'tests/test_auto.py')}\n")
        extras += test_block
        notes.append(f"preopt:test_harness ({tests.get('test_count', '?')} tests)")

    # Apply speculative pre-draft (give agent a warm-start diff)
    draft = cached.get("speculative_draft")
    if draft and draft.get("diff"):
        draft_block = (f"\n\n## Speculative Pre-Draft (Review & Improve)\n"
                       f"A prior reviewer ({draft.get('model', 'haiku')}) produced this draft diff. "
                       f"Use it as a starting point — validate, fix issues, and extend:\n"
                       f"```diff\n{draft['diff'][:5000]}\n```\n"
                       f"Do NOT blindly apply this diff. Review it critically and improve.\n")
        extras += draft_block
        notes.append(f"preopt:speculative_draft ({'from refined spec' if draft.get('from_refined_spec') else 'from original spec'})")

    # Apply pattern match (if high confidence, runner can use deterministic replay)
    pm = cached.get("pattern_match")
    if pm and pm.get("confidence", 0) > 0.7:
        notes.append(f"preopt:pattern_match (conf={pm['confidence']:.0%}, pattern={pm.get('pattern_id', '?')})")

    # Apply merge validation constraints (test failures from speculative draft)
    mv_failures = cached.get("merge_validation_failures")
    if mv_failures:
        import merge_validator
        constraint_block = merge_validator.constraint_prompt(mv_failures)
        if constraint_block:
            extras += constraint_block
            notes.append(f"preopt:merge_constraints ({len(mv_failures)} failures)")

    # Apply merge validation pass (fast-track eligible)
    mv = cached.get("merge_validation")
    if mv and mv.get("can_fast_track"):
        notes.append("preopt:merge_validated (fast-track eligible)")

    # Apply hivemind insights
    hive = cached.get("hivemind")
    if hive and hive.get("insights"):
        try:
            import task_memory
            draft_prompt = task_memory.inject_hivemind(draft_prompt, hive)
            notes.append(f"preopt:hivemind ({len(hive['insights'])} insights)")
        except Exception:
            pass

    # Invalidate now that we've consumed the cache
    invalidate(task_id)

    return draft_prompt, extras, notes


# ── Helpers ────────────────────────────────────────────────────────────────────

def _task_hash(t):
    """Hash task fields that matter for cache invalidation."""
    key = json.dumps({
        "slug": t.get("slug"),
        "prompt": (t.get("prompt") or "")[:500],
        "note": t.get("note"),
        "kind": t.get("kind"),
    }, sort_keys=True)
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _store(task_id, data, task_hash):
    """Store pre-optimization result in cache (memory + disk for cross-process reads)."""
    entry = {
        "ts": time.time(),
        "data": data,
        "task_hash": task_hash,
    }
    with _cache_lock:
        _cache[task_id] = entry
    try:
        os.makedirs(_DISK_DIR, exist_ok=True)
        with open(_disk_path(task_id), "w") as f:
            json.dump(entry, f, default=str)
    except Exception as e:
        _log.warning("disk cache write failed for %s: %s", task_id, e)


def _system_has_capacity():
    """Check if the system has spare capacity for pre-optimization work."""
    try:
        import resource_governor
        if hasattr(resource_governor, "can_claim") and not resource_governor.can_claim():
            return False
    except Exception:
        pass

    # Check active task count vs capacity
    try:
        import db
        active = db.select("tasks", {
            "select": "id",
            "state": "in.(RUNNING,RETRY)",
            "limit": "50",
        }) or []
        max_parallel = int(os.environ.get("MAX_PARALLEL", "10"))
        # Only pre-opt when less than LOAD_CEILING of capacity is in use
        if len(active) >= int(max_parallel * LOAD_CEILING):
            return False
    except Exception:
        pass  # fail open — allow pre-opt if we can't check

    return True

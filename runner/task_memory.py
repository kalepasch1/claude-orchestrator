#!/usr/bin/env python3
"""
task_memory.py - dual-layer intelligence: per-bot memory + shared hivemind.

Each runner learns from its own execution history (which file combos succeed,
which models work for which task shapes, error patterns, cost efficiency) and
shares those learnings with every other runner via the `bot_learnings` DB table.

Before a task runs, `hivemind_query` aggregates insights from ALL runners and
`inject_hivemind` enriches the agent prompt so every bot benefits from the
fleet's collective experience.

Env vars:
    ORCH_TASK_MEMORY_ENABLED   "true" (default) to record learnings
    ORCH_HIVEMIND_ENABLED      "true" (default) to query cross-runner insights
    ORCH_HIVEMIND_TTL          seconds to cache hivemind results (default 120)
    RUNNER_ID                  identity of this runner (default: hostname)
"""
import sys, os, json, time, threading, hashlib, socket, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("task_memory")
import db

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ENABLED = os.environ.get("ORCH_TASK_MEMORY_ENABLED", "true").lower() in ("1", "true", "yes", "on")
HIVEMIND_ENABLED = os.environ.get("ORCH_HIVEMIND_ENABLED", "true").lower() in ("1", "true", "yes", "on")
HIVEMIND_TTL = int(os.environ.get("ORCH_HIVEMIND_TTL", "120") or 120)
RUNNER_ID = os.environ.get("RUNNER_ID", socket.gethostname())


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
class _TaskMemory:
    def __init__(self):
        self._lock = threading.Lock()
        self._hivemind_cache: dict = {}  # key -> (timestamp, result)
        self._stats = {
            "learnings_stored": 0,
            "hivemind_queries": 0,
            "insights_generated": 0,
            "runners_contributing": 0,
        }

    # -----------------------------------------------------------------------
    # Individual memory — learn_from_outcome
    # -----------------------------------------------------------------------
    def learn_from_outcome(self, task, outcome, model, cost_usd, wall_s,
                           integrated, coder, project, files_changed):
        """Extract patterns from a completed task and persist to bot_learnings."""
        if not ENABLED:
            return
        try:
            slug = (task.get("slug") if isinstance(task, dict) else str(task)) or ""
            prompt = (task.get("prompt") if isinstance(task, dict) else "") or ""
            state = (outcome.get("state") if isinstance(outcome, dict) else str(outcome)) or ""
            success = state in ("DONE", "MERGED")
            files = files_changed if isinstance(files_changed, list) else []
            learnings = []

            # 1. file_combo_success — which sets of files tend to succeed/fail
            if files:
                combo_key = "|".join(sorted(files)[:10])
                learnings.append({
                    "runner_id": RUNNER_ID,
                    "pattern_type": "file_combo_success",
                    "pattern_key": hashlib.sha256(combo_key.encode()).hexdigest()[:16],
                    "pattern_value": json.dumps({
                        "files": files[:10],
                        "success": success,
                        "slug_prefix": _slug_prefix(slug),
                        "project": project or "",
                    }),
                    "confidence": 0.6 if success else 0.4,
                    "created_at": _now(),
                    "uses": 0,
                })

            # 2. model_affinity — which model works for which slug shape
            if model:
                learnings.append({
                    "runner_id": RUNNER_ID,
                    "pattern_type": "model_affinity",
                    "pattern_key": f"{_slug_prefix(slug)}:{model}",
                    "pattern_value": json.dumps({
                        "model": model,
                        "slug_prefix": _slug_prefix(slug),
                        "success": success,
                        "cost_usd": cost_usd,
                        "wall_s": wall_s,
                        "project": project or "",
                    }),
                    "confidence": 0.7 if success else 0.3,
                    "created_at": _now(),
                    "uses": 0,
                })

            # 3. error_pattern — capture failure signals
            if not success:
                error_hint = _extract_error_hint(outcome)
                if error_hint:
                    learnings.append({
                        "runner_id": RUNNER_ID,
                        "pattern_type": "error_pattern",
                        "pattern_key": hashlib.sha256(error_hint.encode()).hexdigest()[:16],
                        "pattern_value": json.dumps({
                            "error_hint": error_hint[:500],
                            "slug_prefix": _slug_prefix(slug),
                            "model": model,
                            "project": project or "",
                        }),
                        "confidence": 0.5,
                        "created_at": _now(),
                        "uses": 0,
                    })

            # 4. task_duration — calibrate time expectations
            if wall_s and wall_s > 0:
                learnings.append({
                    "runner_id": RUNNER_ID,
                    "pattern_type": "task_duration",
                    "pattern_key": _slug_prefix(slug),
                    "pattern_value": json.dumps({
                        "wall_s": wall_s,
                        "model": model,
                        "slug_prefix": _slug_prefix(slug),
                        "file_count": len(files),
                        "project": project or "",
                    }),
                    "confidence": 0.8,
                    "created_at": _now(),
                    "uses": 0,
                })

            # 5. cost_efficiency — track cost per outcome
            if cost_usd is not None and cost_usd >= 0:
                learnings.append({
                    "runner_id": RUNNER_ID,
                    "pattern_type": "cost_efficiency",
                    "pattern_key": f"{_slug_prefix(slug)}:{model}",
                    "pattern_value": json.dumps({
                        "cost_usd": cost_usd,
                        "success": success,
                        "model": model,
                        "wall_s": wall_s,
                        "slug_prefix": _slug_prefix(slug),
                        "project": project or "",
                    }),
                    "confidence": 0.7,
                    "created_at": _now(),
                    "uses": 0,
                })

            # 6. prompt_structure — note effective prompt lengths/shapes
            if prompt and success:
                learnings.append({
                    "runner_id": RUNNER_ID,
                    "pattern_type": "prompt_structure",
                    "pattern_key": _slug_prefix(slug),
                    "pattern_value": json.dumps({
                        "prompt_len": len(prompt),
                        "has_code_block": "```" in prompt,
                        "has_file_refs": bool(re.search(r"\b\w+\.\w{1,5}\b", prompt)),
                        "model": model,
                        "slug_prefix": _slug_prefix(slug),
                        "project": project or "",
                    }),
                    "confidence": 0.5,
                    "created_at": _now(),
                    "uses": 0,
                })

            # Persist
            stored = 0
            for lr in learnings:
                try:
                    db.insert("bot_learnings", lr)
                    stored += 1
                except Exception as e:
                    _log.debug("learn store error: %s", e)
            with self._lock:
                self._stats["learnings_stored"] += stored
            _log.info("learned %d patterns from %s (success=%s)", stored, slug, success)

        except Exception as e:
            _log.debug("learn_from_outcome error: %s", e)

    # -----------------------------------------------------------------------
    # Hivemind — cross-runner intelligence
    # -----------------------------------------------------------------------
    def hivemind_query(self, task, project):
        """Query all runners' learnings for insights relevant to this task."""
        if not HIVEMIND_ENABLED:
            return {"insights": [], "recommended_model": None,
                    "recommended_approach": None, "confidence": 0.0}
        try:
            slug = (task.get("slug") if isinstance(task, dict) else str(task)) or ""
            prefix = _slug_prefix(slug)
            cache_key = f"{prefix}:{project or ''}"

            # Check TTL cache
            with self._lock:
                cached = self._hivemind_cache.get(cache_key)
                if cached and (time.time() - cached[0]) < HIVEMIND_TTL:
                    self._stats["hivemind_queries"] += 1
                    return cached[1]

            # Query bot_learnings for all runners matching slug prefix
            rows = []
            try:
                rows = db.select("bot_learnings", {
                    "select": "*",
                    "pattern_key": f"like.*{prefix}*",
                    "order": "confidence.desc",
                    "limit": "100",
                }) or []
            except Exception:
                pass

            # Also query by project if we got few results
            if len(rows) < 5 and project:
                try:
                    extra = db.select("bot_learnings", {
                        "select": "*",
                        "pattern_value": f"like.*{project}*",
                        "order": "confidence.desc",
                        "limit": "50",
                    }) or []
                    seen_ids = {r.get("id") for r in rows}
                    rows.extend(r for r in extra if r.get("id") not in seen_ids)
                except Exception:
                    pass

            # Aggregate insights
            insights = []
            model_votes: dict = {}  # model -> (success_count, total_count)
            runners_seen: set = set()

            for row in rows:
                rid = row.get("runner_id", "")
                runners_seen.add(rid)
                ptype = row.get("pattern_type", "")
                try:
                    pval = json.loads(row.get("pattern_value", "{}"))
                except Exception:
                    pval = {}

                if ptype == "model_affinity":
                    m = pval.get("model", "")
                    if m:
                        sc, tc = model_votes.get(m, (0, 0))
                        model_votes[m] = (sc + (1 if pval.get("success") else 0), tc + 1)

                if ptype == "error_pattern":
                    hint = pval.get("error_hint", "")
                    if hint:
                        insights.append(f"runner {rid} hit error on similar task: {hint[:120]}")

                if ptype == "file_combo_success":
                    fls = pval.get("files", [])
                    ok = pval.get("success", False)
                    if fls and not ok:
                        insights.append(
                            f"runner {rid} found {','.join(fls[:3])} combo failed — may need careful handling")

                if ptype == "cost_efficiency":
                    m = pval.get("model", "")
                    c = pval.get("cost_usd")
                    if m and c is not None:
                        insights.append(f"{m} cost ${c:.4f} for similar task on {rid}")

            # Determine recommended model from votes
            recommended_model = None
            best_rate = 0.0
            for m, (sc, tc) in model_votes.items():
                if tc >= 2:
                    rate = sc / tc
                    if rate > best_rate:
                        best_rate = rate
                        recommended_model = m

            # Build summary insight
            n_runners = len(runners_seen)
            if recommended_model and n_runners > 1:
                sc, tc = model_votes[recommended_model]
                insights.insert(0,
                    f"{sc} of {tc} runs across {n_runners} runners found "
                    f"{recommended_model} works best for {prefix} tasks")

            # Recommended approach from prompt_structure patterns
            recommended_approach = None
            prompt_rows = [r for r in rows if r.get("pattern_type") == "prompt_structure"]
            if prompt_rows:
                try:
                    pv = json.loads(prompt_rows[0].get("pattern_value", "{}"))
                    parts = []
                    if pv.get("has_code_block"):
                        parts.append("include code examples")
                    if pv.get("has_file_refs"):
                        parts.append("reference specific files")
                    if parts:
                        recommended_approach = "Effective prompts for this task shape: " + ", ".join(parts)
                except Exception:
                    pass

            # Confidence based on volume and agreement
            confidence = min(1.0, len(rows) / 20.0) * (best_rate if best_rate > 0 else 0.5)

            result = {
                "insights": insights[:10],
                "recommended_model": recommended_model,
                "recommended_approach": recommended_approach,
                "confidence": round(confidence, 3),
            }

            # Cache
            with self._lock:
                self._hivemind_cache[cache_key] = (time.time(), result)
                self._stats["hivemind_queries"] += 1
                self._stats["insights_generated"] += len(insights)
                self._stats["runners_contributing"] = max(
                    self._stats["runners_contributing"], n_runners)

            return result

        except Exception as e:
            _log.debug("hivemind_query error: %s", e)
            return {"insights": [], "recommended_model": None,
                    "recommended_approach": None, "confidence": 0.0}

    def inject_hivemind(self, prompt, insights):
        """Enrich an agent prompt with hivemind knowledge."""
        if not insights or not isinstance(insights, dict):
            return prompt or ""
        try:
            lines = insights.get("insights", [])
            rec_model = insights.get("recommended_model")
            rec_approach = insights.get("recommended_approach")
            conf = insights.get("confidence", 0)

            if not lines and not rec_model and not rec_approach:
                return prompt or ""

            parts = ["## Fleet Intelligence"]
            runners_n = self._stats.get("runners_contributing", 0)
            parts.append(f"Based on {len(lines)} insight(s) across {max(1, runners_n)} runner(s) "
                         f"(confidence {conf:.0%}):\n")

            for line in lines[:8]:
                parts.append(f"- {line}")

            if rec_model:
                parts.append(f"\nRecommended model: {rec_model}")
            if rec_approach:
                parts.append(f"Approach: {rec_approach}")

            section = "\n".join(parts)
            return section + "\n\n" + (prompt or "")

        except Exception as e:
            _log.debug("inject_hivemind error: %s", e)
            return prompt or ""

    # -----------------------------------------------------------------------
    # Dependency context
    # -----------------------------------------------------------------------
    def get_dependency_context(self, task):
        """If task has deps, find the parent's outcome for continuity."""
        if not ENABLED:
            return None
        try:
            if not isinstance(task, dict):
                return None
            deps = task.get("depends_on") or task.get("deps") or []
            if isinstance(deps, str):
                try:
                    deps = json.loads(deps)
                except Exception:
                    deps = [d.strip() for d in deps.split(",") if d.strip()]
            if not deps:
                return None

            parts = []
            for dep_slug in deps[:3]:  # cap at 3 parents
                try:
                    pid = task.get("project_id", "")
                    params = {
                        "select": "slug,state,note,branch",
                        "slug": f"eq.{dep_slug}",
                        "limit": "1",
                    }
                    if pid:
                        params["project_id"] = f"eq.{pid}"
                    rows = db.select("tasks", params) or []
                    if not rows:
                        # try outcomes table
                        rows = db.select("outcomes", {
                            "select": "slug,state,summary,branch",
                            "slug": f"eq.{dep_slug}",
                            "limit": "1",
                        }) or []
                    if rows:
                        parent = rows[0]
                        note = parent.get("note") or parent.get("summary") or ""
                        branch = parent.get("branch") or ""
                        state = parent.get("state") or ""
                        entry = f"Parent task '{dep_slug}' ({state})"
                        if branch:
                            entry += f" on branch {branch}"
                        if note:
                            entry += f":\n{note[:600]}"
                        parts.append(entry)
                except Exception as e:
                    _log.debug("dep context lookup error for %s: %s", dep_slug, e)

            if not parts:
                return None
            header = "## Context from parent tasks\n"
            return header + "\n\n".join(parts)

        except Exception as e:
            _log.debug("get_dependency_context error: %s", e)
            return None

    # -----------------------------------------------------------------------
    # Stats
    # -----------------------------------------------------------------------
    def stats(self):
        """Return operational stats."""
        with self._lock:
            return dict(self._stats)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _slug_prefix(slug):
    """Extract the verb-noun prefix from a slug for pattern matching.
    'add-field-users-table-abc123' -> 'add-field'
    """
    parts = (slug or "").split("-")
    return "-".join(parts[:2]) if len(parts) >= 2 else (slug or "")


def _now():
    """ISO timestamp."""
    import datetime
    return datetime.datetime.utcnow().isoformat()


def _extract_error_hint(outcome):
    """Pull a short error description from an outcome dict."""
    if not isinstance(outcome, dict):
        return ""
    for key in ("error", "note", "summary", "stderr"):
        val = outcome.get(key)
        if val and isinstance(val, str) and len(val) > 5:
            # First meaningful line
            for line in val.splitlines():
                line = line.strip()
                if len(line) > 10:
                    return line[:300]
    return ""


# ---------------------------------------------------------------------------
# Module-level singleton + delegation
# ---------------------------------------------------------------------------
_instance = _TaskMemory()


def learn_from_outcome(task, outcome, model, cost_usd, wall_s,
                       integrated, coder, project, files_changed):
    return _instance.learn_from_outcome(task, outcome, model, cost_usd, wall_s,
                                        integrated, coder, project, files_changed)


def hivemind_query(task, project):
    return _instance.hivemind_query(task, project)


def inject_hivemind(prompt, insights):
    return _instance.inject_hivemind(prompt, insights)


def get_dependency_context(task):
    return _instance.get_dependency_context(task)


def stats():
    return _instance.stats()

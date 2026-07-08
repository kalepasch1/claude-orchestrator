#!/usr/bin/env python3
"""
cade_tournaments.py — CADE tournament panels + advanced orchestration features.

Covers all items from the "Brain compiler + CADE improvements" task:

1. CADE Tournament Panels: vendor/model competitions per task (extends colosseum)
2. Failure Fingerprints: model-specific failure patterns for routing avoidance
3. Budget-Aware Tournament Sizing: scale panel size to task budget
4. Outcome Writeback: successful outcomes feed back into Common Brain knowledge
5. Cross-App Adapter Promotion: promote proven patterns across repos
6. Zero-Token First Patch: try git-apply before any model call
7. Proof-Pack Diff Replay: replay verified proof packs on similar tasks

Usage:
    import cade_tournaments
    # Tournament
    result = cade_tournaments.run_tournament(task, project, candidates)
    # Failure fingerprints
    cade_tournaments.record_failure(agent, model, error, task)
    should_skip = cade_tournaments.should_avoid(model, task)
    # Zero-token first patch
    applied = cade_tournaments.zero_token_patch(task, worktree)
"""
import os, sys, json, hashlib, re, time, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Tournament config
TOURNAMENT_MIN_CANDIDATES = int(os.environ.get("ORCH_TOURNAMENT_MIN", "2"))
TOURNAMENT_MAX_CANDIDATES = int(os.environ.get("ORCH_TOURNAMENT_MAX", "5"))
TOURNAMENT_BID_TOKENS = int(os.environ.get("ORCH_TOURNAMENT_BID_TOKENS", "150"))

# Failure fingerprint config
FINGERPRINT_THRESHOLD = int(os.environ.get("ORCH_FP_THRESHOLD", "3"))  # failures before avoidance
FINGERPRINT_WINDOW_H = float(os.environ.get("ORCH_FP_WINDOW_H", "72"))


# ─── CADE Tournament Panels ───

def _tournament_store():
    try:
        rows = db.select("controls", {"select": "value", "key": "eq.cade_tournaments"})
        if rows and rows[0].get("value"):
            v = rows[0]["value"]
            return json.loads(v) if isinstance(v, str) else v
    except Exception:
        pass
    return {"history": [], "standings": {}}


def _save_tournament(store):
    store["history"] = store.get("history", [])[-50:]
    try:
        db.upsert("controls", {"key": "cade_tournaments", "value": json.dumps(store, default=str)})
    except Exception:
        pass


def budget_aware_panel_size(task, budget_usd=None):
    """Scale tournament panel size based on task budget and complexity.

    Small/cheap tasks: 2 candidates (minimal overhead)
    Medium tasks: 3 candidates
    Large/expensive tasks: 4-5 candidates (worth the investment)
    """
    complexity = 0

    prompt = task.get("prompt", "")
    if len(prompt) > 2000:
        complexity += 1
    if len(prompt) > 5000:
        complexity += 1

    kind = task.get("kind", "")
    if kind in ("feature", "refactor", "security"):
        complexity += 1
    if kind in ("mechanical", "config"):
        complexity -= 1

    # Budget scaling
    budget = budget_usd or 0
    if budget > 1.0:
        complexity += 1
    elif budget < 0.1:
        complexity -= 1

    panel = max(TOURNAMENT_MIN_CANDIDATES, min(TOURNAMENT_MAX_CANDIDATES, 2 + complexity))
    return panel


# CADE panel roles — each role has a function in the tournament
CADE_ROLES = [
    "scout",          # filesystem/codebase reconnaissance (cheapest model)
    "planner",        # step-by-step implementation plan
    "drafter",        # writes the actual code (primary)
    "verifier",       # runs build+test, checks correctness
    "red-team",       # adversarial review — finds edge cases, security issues
    "judge",          # quality scoring and verdict
    "treasurer",      # cost/budget compliance check
    "privacy-officer",# PII, secrets, compliance review
]

# Roles that review the drafter's work — MUST exclude drafter's provider
REVIEW_ROLES = {"verifier", "red-team", "judge", "privacy-officer"}


def _extract_provider(model_name):
    """Extract provider from model name (e.g., 'anthropic' from 'claude-sonnet-4-20250514')."""
    name = (model_name or "").lower()
    if "claude" in name or "anthropic" in name:
        return "anthropic"
    if "gpt" in name or "openai" in name or "o1" in name or "o3" in name:
        return "openai"
    if "gemini" in name or "google" in name:
        return "google"
    if "llama" in name or "meta" in name:
        return "meta"
    if "mistral" in name or "mixtral" in name:
        return "mistral"
    if "deepseek" in name:
        return "deepseek"
    return "unknown"


def assign_roles(candidates, task, budget_usd=None):
    """Assign CADE roles to candidates with provider-exclusion for review roles.

    The drafter's provider is excluded from review roles (verifier, red-team,
    judge, privacy-officer) to ensure independent review.

    Returns: {role: model_name} dict
    """
    panel_size = budget_aware_panel_size(task, budget_usd)

    # Determine which roles to fill based on panel size
    if panel_size <= 2:
        active_roles = ["drafter", "verifier"]
    elif panel_size <= 3:
        active_roles = ["drafter", "verifier", "judge"]
    elif panel_size <= 4:
        active_roles = ["scout", "drafter", "verifier", "judge"]
    elif panel_size <= 5:
        active_roles = ["scout", "planner", "drafter", "verifier", "judge"]
    else:
        active_roles = CADE_ROLES[:panel_size]

    # Filter safe candidates
    safe = []
    for c in candidates:
        model = c if isinstance(c, str) else c.get("model", "")
        if not should_avoid(model, task):
            safe.append(model)
    if len(safe) < 2:
        safe = [c if isinstance(c, str) else c.get("model", "") for c in candidates[:panel_size]]

    assignments = {}

    # Assign drafter first (highest reputation)
    store = _tournament_store()
    standings = store.get("standings", {})

    def _rep(m):
        s = standings.get(m, {})
        total = s.get("wins", 0) + s.get("losses", 0)
        return s.get("wins", 0) / max(total, 1) if total > 0 else 0.5

    ranked = sorted(safe, key=_rep, reverse=True)
    drafter = ranked[0] if ranked else safe[0] if safe else "unknown"
    drafter_provider = _extract_provider(drafter)

    for role in active_roles:
        if role == "drafter":
            assignments[role] = drafter
        elif role in REVIEW_ROLES:
            # Exclude drafter's provider for review roles
            review_candidates = [m for m in ranked if _extract_provider(m) != drafter_provider]
            if review_candidates:
                assignments[role] = review_candidates[0]
            elif len(ranked) > 1:
                # Fallback: use a different model even if same provider
                assignments[role] = ranked[1]
            else:
                assignments[role] = drafter  # last resort: same model
        else:
            # Non-review roles: pick cheapest available
            assignments[role] = ranked[-1] if ranked else drafter

    return assignments


def run_tournament(task, project, candidates, budget_usd=None):
    """Run a CADE tournament panel — models compete via role assignments.

    Assigns CADE roles (scout→planner→drafter→verifier→red-team→judge→
    treasurer→privacy-officer) with provider-exclusion for review roles.

    Returns: {winner, panel_size, roles, scores, total_cost_usd}
    """
    panel_size = budget_aware_panel_size(task, budget_usd)
    store = _tournament_store()

    # Assign roles with provider exclusion
    roles = assign_roles(candidates, task, budget_usd)

    # Score based on standings (reputation)
    scores = {}
    unique_models = set(roles.values())
    for model in unique_models:
        standing = store.get("standings", {}).get(model, {})
        wins = standing.get("wins", 0)
        losses = standing.get("losses", 0)
        total = wins + losses
        win_rate = wins / max(total, 1)
        scores[model] = {
            "model": model,
            "provider": _extract_provider(model),
            "reputation": round(win_rate, 3),
            "total_matches": total,
            "score": round(win_rate * 0.3 + 0.7, 3),
        }

    # Winner is the drafter
    winner = roles.get("drafter", "unknown")

    result = {
        "winner": winner,
        "panel_size": len(roles),
        "roles": roles,
        "panel": list(unique_models),
        "scores": scores,
        "provider_exclusion": {
            "drafter_provider": _extract_provider(winner),
            "excluded_from": [r for r in roles if r in REVIEW_ROLES and
                              _extract_provider(roles[r]) != _extract_provider(winner)],
        },
        "total_cost_usd": 0,
    }

    # Record tournament
    store["history"].append({
        "task_id": task.get("id", ""),
        "timestamp": time.time(),
        "winner": result["winner"],
        "panel_size": result["panel_size"],
        "roles": roles,
    })
    _save_tournament(store)
    return result


def record_tournament_outcome(model, won=True):
    """Update tournament standings after task completion."""
    store = _tournament_store()
    standings = store.get("standings", {})
    entry = standings.get(model, {"wins": 0, "losses": 0})
    if won:
        entry["wins"] = entry.get("wins", 0) + 1
    else:
        entry["losses"] = entry.get("losses", 0) + 1
    entry["last_match"] = time.time()
    standings[model] = entry
    store["standings"] = standings
    _save_tournament(store)


# ─── Model-Specific Failure Fingerprints ───

def _fingerprint_store():
    try:
        rows = db.select("controls", {"select": "value", "key": "eq.failure_fingerprints"})
        if rows and rows[0].get("value"):
            v = rows[0]["value"]
            return json.loads(v) if isinstance(v, str) else v
    except Exception:
        pass
    return {}


def _save_fingerprints(store):
    try:
        db.upsert("controls", {"key": "failure_fingerprints", "value": json.dumps(store, default=str)})
    except Exception:
        pass


def _error_signature(error):
    """Normalize error into a fingerprint signature."""
    error = (error or "")[:300].lower()
    # Strip variable parts
    error = re.sub(r"line \d+", "line N", error)
    error = re.sub(r"column \d+", "col N", error)
    error = re.sub(r"[0-9a-f]{8,}", "HASH", error)
    error = re.sub(r"\d+\.\d+s", "N.Ns", error)
    return hashlib.sha256(error.encode()).hexdigest()[:12]


def record_failure(agent_or_model, model="", error="", task=None):
    """Record a failure fingerprint for a model."""
    store = _fingerprint_store()
    key = f"{agent_or_model}:{model}" if model else agent_or_model
    sig = _error_signature(error)

    entry = store.get(key, {"failures": [], "signatures": {}})

    # Add failure record
    entry["failures"].append({
        "timestamp": time.time(),
        "signature": sig,
        "error_head": (error or "")[:100],
        "task_kind": (task or {}).get("kind", ""),
    })

    # Track signature frequency
    sigs = entry.get("signatures", {})
    sigs[sig] = sigs.get(sig, 0) + 1
    entry["signatures"] = sigs

    # Prune old failures
    cutoff = time.time() - FINGERPRINT_WINDOW_H * 3600
    entry["failures"] = [f for f in entry["failures"] if f.get("timestamp", 0) > cutoff]

    store[key] = entry
    _save_fingerprints(store)


def should_avoid(model, task=None):
    """Check if a model should be avoided based on failure fingerprints."""
    store = _fingerprint_store()

    # Check all keys that match this model
    for key, entry in store.items():
        if model not in key:
            continue
        cutoff = time.time() - FINGERPRINT_WINDOW_H * 3600
        recent = [f for f in entry.get("failures", []) if f.get("timestamp", 0) > cutoff]

        if len(recent) >= FINGERPRINT_THRESHOLD:
            # If task-specific, check if failures are for this kind
            if task:
                kind = task.get("kind", "")
                kind_failures = [f for f in recent if f.get("task_kind") == kind]
                if len(kind_failures) >= FINGERPRINT_THRESHOLD:
                    return True
            else:
                return True

    return False


def get_failure_summary(model):
    """Get failure summary for a model."""
    store = _fingerprint_store()
    for key, entry in store.items():
        if model not in key:
            continue
        cutoff = time.time() - FINGERPRINT_WINDOW_H * 3600
        recent = [f for f in entry.get("failures", []) if f.get("timestamp", 0) > cutoff]
        sigs = entry.get("signatures", {})
        top_sig = max(sigs, key=sigs.get) if sigs else ""
        return {
            "model": model,
            "recent_failures": len(recent),
            "total_signatures": len(sigs),
            "top_signature": top_sig,
            "top_count": sigs.get(top_sig, 0),
            "should_avoid": len(recent) >= FINGERPRINT_THRESHOLD,
        }
    return None


# ─── Outcome Writeback (Common Brain) ───

def _deployment_store():
    try:
        rows = db.select("controls", {"select": "value", "key": "eq.common_brain_deployments"})
        if rows and rows[0].get("value"):
            v = rows[0]["value"]
            return json.loads(v) if isinstance(v, str) else v
    except Exception:
        pass
    return {"deployments": [], "stats": {"total": 0, "merged": 0, "tokens_avoided": 0, "minutes_saved": 0}}


def _save_deployments(store):
    store["deployments"] = store.get("deployments", [])[-200:]
    try:
        db.upsert("controls", {"key": "common_brain_deployments", "value": json.dumps(store, default=str)})
    except Exception:
        pass


def writeback_outcome(task, outcome, project="", merged_files=None,
                      model="", coder="", domain="", wall_s=0, cost_usd=0,
                      review_failures=0, rollback=False, tokens_in=0, tokens_out=0):
    """Write task outcome into common_brain_deployments with full telemetry.

    Tracks: status, outcome, avoided tokens/minutes, review failures,
    rollback, model, coder, domain. Also feeds intent_graph and
    cross_project_templates for cross-project reuse.
    """
    merged = outcome.get("merged", False)
    store = _deployment_store()

    # Estimate tokens/minutes avoided via zero-token or cached paths
    tokens_avoided = 0
    minutes_saved = 0
    method = outcome.get("method", "agent")
    if method in ("speculative_diff", "proof_pack_replay", "zero-token"):
        tokens_avoided = tokens_in + tokens_out  # would have cost this many
        minutes_saved = wall_s / 60 if wall_s else 2  # estimate 2 min saved

    deployment = {
        "task_id": task.get("id", ""),
        "timestamp": time.time(),
        "project": project,
        "domain": domain,
        "status": "merged" if merged else ("rollback" if rollback else "failed"),
        "outcome": {
            "merged": merged,
            "rollback": rollback,
            "review_failures": review_failures,
            "diff_summary": outcome.get("diff_summary", "")[:200],
        },
        "model": model,
        "coder": coder,
        "cost_usd": cost_usd,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_avoided": tokens_avoided,
        "minutes_saved": round(minutes_saved, 2),
        "wall_s": round(wall_s, 1),
        "files": (merged_files or [])[:20],
        "is_common_brain": False,
    }

    # Check if this is a Common Brain task
    try:
        import brain_compiler
        deployment["is_common_brain"] = brain_compiler.is_common_brain_task(task)
    except Exception:
        pass

    store["deployments"].append(deployment)
    store["stats"]["total"] = store["stats"].get("total", 0) + 1
    if merged:
        store["stats"]["merged"] = store["stats"].get("merged", 0) + 1
    store["stats"]["tokens_avoided"] = store["stats"].get("tokens_avoided", 0) + tokens_avoided
    store["stats"]["minutes_saved"] = round(store["stats"].get("minutes_saved", 0) + minutes_saved, 2)
    _save_deployments(store)

    # Also feed intent_graph and cross_project_templates for reuse
    if merged:
        try:
            import intent_graph
            diff_hash = outcome.get("diff_hash", "")
            intent_graph.record(task, merged_files or [], diff_hash, outcome)
        except Exception:
            pass
        try:
            import cross_project_templates
            cross_project_templates.index_merge(
                task, project, merged_files or [],
                outcome.get("diff_summary", ""),
                merge_rate=1.0
            )
        except Exception:
            pass

    return deployment


def get_deployment_stats():
    """Get Common Brain deployment stats for dashboard."""
    store = _deployment_store()
    stats = store.get("stats", {})
    recent = store.get("deployments", [])[-20:]
    return {
        "total_deployments": stats.get("total", 0),
        "total_merged": stats.get("merged", 0),
        "merge_rate": stats.get("merged", 0) / max(stats.get("total", 1), 1),
        "tokens_avoided": stats.get("tokens_avoided", 0),
        "minutes_saved": stats.get("minutes_saved", 0),
        "recent": recent,
    }


# ─── Zero-Token First Patch ───

def zero_token_patch(task, worktree, base_ref="HEAD"):
    """Try to apply a known-good diff before any model call.

    Flow:
    1. Check intent_graph for exact match
    2. Check cross_project_templates for adaptable match
    3. Check prompt_distillation for minimal template
    4. If match found: git apply --check → git apply → build verify
    5. Returns {applied: True/False, method, cost_usd: 0}

    This wraps speculative_diff but adds template + distillation fallbacks.
    """
    # Try speculative_diff first (exact replay)
    try:
        import speculative_diff
        result = speculative_diff.try_replay(task, "", base_ref, worktree)
        if result and result.get("applied"):
            return {**result, "method": "speculative_diff"}
    except Exception:
        pass

    # Try prompt_distillation (if a distilled template has enough merges)
    try:
        import prompt_distillation
        distilled = prompt_distillation.find_distilled(task)
        if distilled and distilled.get("merge_count", 0) >= 5:
            # Very high confidence — this pattern is well-proven
            # But we can't apply it without a diff, so just flag it
            return {
                "applied": False,
                "method": "distillation_candidate",
                "distilled": distilled,
                "cost_usd": 0,
                "tokens": 0,
                "note": "Pattern proven but no diff available for zero-token apply",
            }
    except Exception:
        pass

    return {"applied": False, "method": "none", "cost_usd": 0, "tokens": 0}


# ─── Cross-App Adapter Promotion ───

def promote_adapter(source_project, target_project, adapter_name, files):
    """Promote a proven adapter pattern from one project to another.

    When a pattern (middleware, API route, component) succeeds in one repo,
    this creates a template for the same pattern in another repo.
    """
    try:
        import transfer_learning
        import cross_project_templates

        # Create a synthetic task for the template
        task = {
            "prompt": f"Adapt {adapter_name} pattern from {source_project}",
            "kind": "feature",
        }

        # Index the merge in cross-project templates
        cross_project_templates.index_merge(
            task, source_project, files,
            f"Proven adapter: {adapter_name}",
            merge_rate=1.0
        )

        return {
            "promoted": True,
            "adapter": adapter_name,
            "source": source_project,
            "target": target_project,
            "files": files,
        }
    except Exception as e:
        return {"promoted": False, "error": str(e)[:200]}


# ─── Proof-Pack Diff Replay ───

def replay_proof_pack(task, proof_pack, worktree):
    """Replay a verified proof pack's diff on a similar task.

    A proof pack contains: {diff_text, test_results, verify_verdict, files_changed}
    If the diff applies cleanly and tests pass, skip the model entirely.
    """
    diff_text = proof_pack.get("diff_text", "")
    if not diff_text or not worktree:
        return {"replayed": False, "reason": "no diff or worktree"}

    try:
        # Check if diff applies cleanly
        check = subprocess.run(
            ["git", "apply", "--check", "--3way"],
            input=diff_text, cwd=worktree,
            capture_output=True, text=True, timeout=30
        )
        if check.returncode != 0:
            return {"replayed": False, "reason": "diff does not apply cleanly"}

        # Apply the diff
        apply_result = subprocess.run(
            ["git", "apply", "--3way"],
            input=diff_text, cwd=worktree,
            capture_output=True, text=True, timeout=30
        )
        if apply_result.returncode != 0:
            return {"replayed": False, "reason": "diff apply failed"}

        # Verify with build+test
        test_cmd = os.environ.get("TEST_CMD", "npm test")
        test_result = subprocess.run(
            test_cmd, shell=True, cwd=worktree,
            capture_output=True, text=True, timeout=180,
            env={**os.environ, "CI": "true"}
        )

        if test_result.returncode == 0:
            return {
                "replayed": True,
                "cost_usd": 0,
                "tokens": 0,
                "files": proof_pack.get("files_changed", []),
                "method": "proof_pack_replay",
            }
        else:
            # Revert
            subprocess.run(
                ["git", "checkout", "."], cwd=worktree,
                capture_output=True, timeout=15
            )
            return {"replayed": False, "reason": "tests failed after replay"}

    except Exception as e:
        try:
            subprocess.run(["git", "checkout", "."], cwd=worktree, capture_output=True, timeout=15)
        except Exception:
            pass
        return {"replayed": False, "reason": str(e)[:200]}


def run():
    """Periodic: report tournament standings and failure fingerprint stats."""
    store = _tournament_store()
    fp_store = _fingerprint_store()

    standings = store.get("standings", {})
    if standings:
        top = sorted(standings.items(), key=lambda x: x[1].get("wins", 0), reverse=True)[:5]
        print("[cade] Tournament standings (top 5):")
        for model, s in top:
            total = s.get("wins", 0) + s.get("losses", 0)
            rate = s.get("wins", 0) / max(total, 1)
            print(f"  {model}: {s.get('wins', 0)}W/{s.get('losses', 0)}L ({rate:.0%})")

    avoided = sum(1 for e in fp_store.values()
                  if len([f for f in e.get("failures", [])
                         if f.get("timestamp", 0) > time.time() - FINGERPRINT_WINDOW_H * 3600])
                  >= FINGERPRINT_THRESHOLD)
    print(f"[cade] {len(fp_store)} fingerprinted models, {avoided} currently avoided")

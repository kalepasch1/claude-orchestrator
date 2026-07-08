#!/usr/bin/env python3
"""
colosseum.py — Model Colosseum / Agent Market Kernel

A competitive coding economy where every vendor/model becomes an agent with a job,
reputation, budget, and memory. The orchestrator stops "routing to a model" and starts
"running a market for the best implementation."

Borrows from Tomorrow OTC's hive:
  - Tournament structure (negotiationTournament.ts): round-robin on comparable tasks
  - Reputation metrics (botReputation.ts): efficiency, win rate, failure mode, reliability
  - Event bus (hiveBus.ts): models react to build/merge/canary/competitor outcomes
  - IOI pattern (hiveOrderRouter.ts): sensitive work produces indications before execution

Architecture:
  1. Task Receipt → cheap/local model creates scope, acceptance tests, risk
  2. Model Bids → each eligible model bids: confidence, cost, time, approach
  3. Allocation → router picks: implementer, critic, verifier, fallback, judge
  4. Collaborative Debate → 2-4 models negotiate approach before code
  5. Blind Verification → different vendor reviews without seeing author
  6. Outcome Settlement → rewards based on: merged, deployed, rollback-free, cost
  7. Promotion/Demotion → winners get more allocation, losers get canary-only

Tables (in Supabase controls or dedicated tables):
  agent_profiles, agent_bids, agent_assignments, agent_outcomes, agent_reputation
"""
import os, sys, json, time, math, hashlib, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# ── Constants ────────────────────────────────────────────────────────────────

ELO_K = 32                    # Elo K-factor
ELO_DEFAULT = 1200            # Starting Elo
BAYESIAN_PRIOR_TASKS = 5      # Prior merged tasks for Bayesian smoothing
BAYESIAN_PRIOR_COST = 1.50    # Prior total cost for those tasks
MIN_BIDS = 2                  # Minimum bids before assignment
MAX_BIDS = 5                  # Maximum models to solicit bids from
DEMOTION_THRESHOLD = 0.15     # Merge rate below this → canary-only
PROMOTION_THRESHOLD = 0.70    # Merge rate above this → priority allocation
CANARY_SHARE = 0.10           # 10% of tasks go to canary/exploration models
DEBATE_MAX_ROUNDS = 2         # Max pre-implementation debate rounds

TASK_CLASSES = ("recovery", "build-fix", "mechanical", "feature", "security-legal")
ROLES = ("implementer", "critic", "verifier", "repairer", "judge", "scout", "planner", "treasurer")

# Sensitive task markers that force local/enterprise-safe models
SENSITIVE_MARKERS = ("security", "legal", "compliance", "privacy", "credential",
                     "payment", "billing", "financial", "crown-jewel")

# ── Agent Profile ────────────────────────────────────────────────────────────

def _profiles():
    """Load agent profiles from controls or build defaults from model_gateway."""
    try:
        raw = db.select("controls", {"select": "value", "key": "eq.agent_profiles"})
        if raw and raw[0].get("value"):
            return json.loads(raw[0]["value"]) if isinstance(raw[0]["value"], str) else raw[0]["value"]
    except Exception:
        pass

    # Bootstrap from available models
    try:
        import model_gateway
        providers = model_gateway.available()
        profiles = {}
        for prov in providers:
            models = model_gateway.models_for(prov) if hasattr(model_gateway, 'models_for') else []
            for m in (models or [prov]):
                pid = f"{prov}:{m}" if m != prov else prov
                profiles[pid] = {
                    "vendor": prov, "model": m, "roles": list(ROLES),
                    "cost_tier": _infer_cost_tier(prov, m),
                    "sensitivity": "standard",  # standard | enterprise | local-only
                    "elo": ELO_DEFAULT, "merge_rate": 0.5, "tasks_completed": 0,
                    "total_cost": 0, "status": "active",  # active | canary | demoted | suspended
                }
        return profiles
    except Exception:
        return {}


def _infer_cost_tier(provider, model):
    """Infer cost tier from model name."""
    name = (model or "").lower()
    if any(k in name for k in ("haiku", "mini", "flash", "small", "lite")):
        return "cheap"
    if any(k in name for k in ("opus", "pro", "ultra", "large", "70b", "72b")):
        return "expensive"
    return "mid"


def _save_profiles(profiles):
    try:
        db.upsert("controls", {"key": "agent_profiles", "value": json.dumps(profiles)})
    except Exception:
        pass


# ── Reputation & Elo ─────────────────────────────────────────────────────────

def _reputation():
    """Load per-model reputation from controls."""
    try:
        raw = db.select("controls", {"select": "value", "key": "eq.agent_reputation"})
        if raw and raw[0].get("value"):
            return json.loads(raw[0]["value"]) if isinstance(raw[0]["value"], str) else raw[0]["value"]
    except Exception:
        pass
    return {}


def _save_reputation(rep):
    try:
        db.upsert("controls", {"key": "agent_reputation", "value": json.dumps(rep)})
    except Exception:
        pass


def update_elo(winner_id, loser_id, draw=False):
    """Update Elo ratings after a head-to-head comparison."""
    rep = _reputation()
    w = rep.get(winner_id, {"elo": ELO_DEFAULT})
    l = rep.get(loser_id, {"elo": ELO_DEFAULT})

    ew = 1.0 / (1.0 + 10 ** ((l.get("elo", ELO_DEFAULT) - w.get("elo", ELO_DEFAULT)) / 400))
    el = 1.0 - ew

    if draw:
        w["elo"] = round(w.get("elo", ELO_DEFAULT) + ELO_K * (0.5 - ew))
        l["elo"] = round(l.get("elo", ELO_DEFAULT) + ELO_K * (0.5 - el))
    else:
        w["elo"] = round(w.get("elo", ELO_DEFAULT) + ELO_K * (1.0 - ew))
        l["elo"] = round(l.get("elo", ELO_DEFAULT) + ELO_K * (0.0 - el))

    rep[winner_id] = w
    rep[loser_id] = l
    _save_reputation(rep)


def blended_score(agent_id, rep=None):
    """Compute blended score: deployed_value - cost - penalties.

    score = merged_rate × elo_factor - cost_per_merge - retry_penalty
            - review_failure_penalty - rollback_penalty
    """
    if rep is None:
        rep = _reputation()
    r = rep.get(agent_id, {})

    merged = r.get("merged", 0)
    total = r.get("total_tasks", 0) or 1
    merge_rate = merged / total

    elo = r.get("elo", ELO_DEFAULT)
    elo_factor = elo / ELO_DEFAULT  # >1 for above-average, <1 for below

    cost_total = r.get("total_cost_usd", 0)
    cost_per_merge = (cost_total / max(merged, 1))

    retries = r.get("retries", 0)
    review_failures = r.get("review_failures", 0)
    rollbacks = r.get("rollbacks", 0)

    # Bayesian smoothing for cold-start
    smoothed_merge_rate = (merged + BAYESIAN_PRIOR_TASKS * 0.5) / (total + BAYESIAN_PRIOR_TASKS)
    smoothed_cost = (cost_total + BAYESIAN_PRIOR_COST) / (merged + BAYESIAN_PRIOR_TASKS)

    score = (smoothed_merge_rate * elo_factor * 100
             - smoothed_cost * 10
             - retries * 0.5
             - review_failures * 2
             - rollbacks * 10)

    return round(score, 2)


# ── Bidding ──────────────────────────────────────────────────────────────────

def solicit_bids(task, task_class=None, profiles=None):
    """Ask eligible models to bid on a task. Returns sorted bids.

    Each bid: {agent_id, confidence, est_cost, est_time_s, approach, risk, why_me}

    For MVP: bids are computed from reputation data, not by actually asking
    models (that would cost tokens). Live model bidding is Phase 2.
    """
    if profiles is None:
        profiles = _profiles()
    rep = _reputation()

    if not task_class:
        task_class = _classify_task(task)

    is_sensitive = any(m in (task.get("prompt") or "").lower() for m in SENSITIVE_MARKERS)

    bids = []
    for agent_id, prof in profiles.items():
        if prof.get("status") == "suspended":
            continue
        if is_sensitive and prof.get("sensitivity") not in ("enterprise", "local-only"):
            continue
        if prof.get("status") == "demoted" and not _is_canary_slot():
            continue

        r = rep.get(agent_id, {})
        tc_stats = r.get("by_class", {}).get(task_class, {})

        # Estimate from historical performance
        merged = tc_stats.get("merged", r.get("merged", 0))
        total = tc_stats.get("total", r.get("total_tasks", 0)) or 1
        avg_cost = tc_stats.get("avg_cost", r.get("avg_cost", 0.50))
        avg_time = tc_stats.get("avg_time_s", r.get("avg_time_s", 300))

        confidence = (merged + BAYESIAN_PRIOR_TASKS * 0.5) / (total + BAYESIAN_PRIOR_TASKS)
        score = blended_score(agent_id, rep)

        bids.append({
            "agent_id": agent_id,
            "vendor": prof.get("vendor", ""),
            "model": prof.get("model", ""),
            "confidence": round(confidence, 3),
            "est_cost": round(avg_cost, 4),
            "est_time_s": round(avg_time),
            "score": score,
            "cost_tier": prof.get("cost_tier", "mid"),
            "elo": r.get("elo", ELO_DEFAULT),
            "status": prof.get("status", "active"),
            "task_class": task_class,
        })

    # Sort by blended score (higher is better)
    bids.sort(key=lambda b: -b["score"])
    return bids[:MAX_BIDS]


def _classify_task(task):
    """Classify task into one of the 5 task classes."""
    prompt = (task.get("prompt") or "").lower()
    kind = (task.get("kind") or "").lower()
    slug = (task.get("slug") or "").lower()

    if "recover" in slug or "recovery" in kind:
        return "recovery"
    if "build" in slug and "fix" in slug or kind == "build-fix":
        return "build-fix"
    if kind in ("mechanical", "config", "rename", "bump", "docs"):
        return "mechanical"
    if any(k in prompt for k in SENSITIVE_MARKERS):
        return "security-legal"
    return "feature"


def _is_canary_slot():
    """Probabilistically allocate canary slots for demoted models."""
    import random
    return random.random() < CANARY_SHARE


# ── Assignment ───────────────────────────────────────────────────────────────

def assign_roles(task, bids=None):
    """From bids, assign: implementer, critic, verifier, fallback, judge.

    Key rule: verifier MUST be a different vendor than implementer (blind verification).
    """
    if bids is None:
        bids = solicit_bids(task)

    if not bids:
        return None

    assignment = {
        "implementer": None,
        "critic": None,
        "verifier": None,
        "fallback": None,
        "judge": None,
        "task_class": bids[0].get("task_class", "feature"),
        "bids_count": len(bids),
    }

    # Implementer: highest score
    assignment["implementer"] = bids[0]

    impl_vendor = bids[0].get("vendor", "")

    # Verifier: highest-scoring model from a DIFFERENT vendor (blind verification)
    for b in bids[1:]:
        if b.get("vendor") != impl_vendor:
            assignment["verifier"] = b
            break
    if not assignment["verifier"] and len(bids) > 1:
        assignment["verifier"] = bids[1]  # fallback: same vendor but different model

    # Critic: cheapest model (cost-efficient for criticism)
    cheap_bids = sorted(bids, key=lambda b: b.get("est_cost", 999))
    assignment["critic"] = cheap_bids[0] if cheap_bids else None

    # Fallback: second-best implementer
    if len(bids) > 1:
        assignment["fallback"] = bids[1]

    # Judge: if sensitive, pick the model with highest Elo
    is_sensitive = any(m in (task.get("prompt") or "").lower() for m in SENSITIVE_MARKERS)
    if is_sensitive and len(bids) > 2:
        by_elo = sorted(bids, key=lambda b: -b.get("elo", ELO_DEFAULT))
        assignment["judge"] = by_elo[0]

    # Record assignment
    try:
        db.insert("resource_events", {
            "kind": "colosseum_assignment",
            "detail": json.dumps({
                "slug": task.get("slug"),
                "implementer": assignment["implementer"]["agent_id"] if assignment["implementer"] else None,
                "verifier": assignment["verifier"]["agent_id"] if assignment["verifier"] else None,
                "task_class": assignment["task_class"],
                "bids": len(bids),
            }, default=str)[:500],
            "action": "assign",
            "created_at": "now()"
        })
    except Exception:
        pass

    return assignment


# ── Pre-Implementation Debate ────────────────────────────────────────────────

def should_debate(task, assignment):
    """Decide if pre-implementation debate is worthwhile.

    Debate for: feature tasks, security-legal, high-cost estimates.
    Skip for: mechanical, recovery, build-fix (speed > deliberation).
    """
    if os.environ.get("ORCH_COLOSSEUM_DEBATE", "true").lower() not in ("true", "1", "yes"):
        return False

    tc = assignment.get("task_class", "feature")
    if tc in ("mechanical", "recovery", "build-fix"):
        return False

    # Debate if estimated cost is high
    impl = assignment.get("implementer", {})
    if impl.get("est_cost", 0) > 1.0:
        return True

    if tc == "security-legal":
        return True

    return tc == "feature"


def run_debate(task, assignment):
    """Run a compact pre-implementation debate between assigned roles.

    Returns: {approach: str, risks: [str], reuse_hints: [str], scope_notes: str}

    For MVP: the debate is a single cheap-model call that synthesizes the
    implementer's approach vs. the critic's concerns. Full multi-round debate
    is Phase 2.
    """
    try:
        import model_gateway, model_policy

        critic = assignment.get("critic", {})
        if not critic:
            return None

        prov, model, _ = model_policy.choose("review", agentic=False, need=4)

        prompt = f"""You are mediating a pre-implementation debate for this coding task.

TASK: {(task.get('prompt') or '')[:1500]}
TASK CLASS: {assignment.get('task_class', 'feature')}
IMPLEMENTER: {assignment.get('implementer', {}).get('agent_id', 'unknown')} (confidence: {assignment.get('implementer', {}).get('confidence', '?')})

As the CRITIC, identify:
1. The simplest correct approach (<=2 sentences)
2. Top 2 risks
3. Any reusable prior diffs or patterns to adapt
4. Scope-reduction opportunities

Return JSON: {{"approach":"...","risks":["..."],"reuse_hints":["..."],"scope_notes":"..."}}"""

        res = model_gateway.complete(prov, model, prompt,
                                     project=task.get("project_name"),
                                     timeout=60, operation="colosseum_debate",
                                     task_class="review")
        import re
        m = re.search(r"\{.*\}", res["text"], re.S)
        if m:
            return json.loads(m.group(0))
    except Exception:
        pass
    return None


# ── Outcome Settlement ───────────────────────────────────────────────────────

def settle(task, agent_id, outcome):
    """Settle a task outcome and update reputation.

    outcome dict: {merged: bool, deployed: bool, rollback: bool, cost_usd: float,
                   wall_s: float, review_passed: bool, tests_passed: bool,
                   tokens_in: int, tokens_out: int}
    """
    rep = _reputation()
    r = rep.get(agent_id, {
        "elo": ELO_DEFAULT, "merged": 0, "total_tasks": 0, "total_cost_usd": 0,
        "retries": 0, "review_failures": 0, "rollbacks": 0, "avg_cost": 0,
        "avg_time_s": 0, "by_class": {},
    })

    r["total_tasks"] = r.get("total_tasks", 0) + 1
    cost = outcome.get("cost_usd", 0)
    r["total_cost_usd"] = r.get("total_cost_usd", 0) + cost
    r["avg_cost"] = r["total_cost_usd"] / r["total_tasks"]

    wall = outcome.get("wall_s", 0)
    old_avg = r.get("avg_time_s", 0)
    r["avg_time_s"] = old_avg + (wall - old_avg) / r["total_tasks"]

    if outcome.get("merged"):
        r["merged"] = r.get("merged", 0) + 1
    if outcome.get("rollback"):
        r["rollbacks"] = r.get("rollbacks", 0) + 1
    if not outcome.get("review_passed", True):
        r["review_failures"] = r.get("review_failures", 0) + 1
    if not outcome.get("tests_passed", True):
        r["retries"] = r.get("retries", 0) + 1

    # Per-class stats
    tc = _classify_task(task)
    by_class = r.get("by_class", {})
    cls = by_class.get(tc, {"merged": 0, "total": 0, "avg_cost": 0, "avg_time_s": 0})
    cls["total"] = cls.get("total", 0) + 1
    cls["avg_cost"] = (cls.get("avg_cost", 0) * (cls["total"] - 1) + cost) / cls["total"]
    cls["avg_time_s"] = (cls.get("avg_time_s", 0) * (cls["total"] - 1) + wall) / cls["total"]
    if outcome.get("merged"):
        cls["merged"] = cls.get("merged", 0) + 1
    by_class[tc] = cls
    r["by_class"] = by_class

    # Merge rate for promotion/demotion
    merge_rate = r["merged"] / r["total_tasks"] if r["total_tasks"] > 0 else 0.5

    rep[agent_id] = r
    _save_reputation(rep)

    # Promotion/demotion
    profiles = _profiles()
    if agent_id in profiles:
        if r["total_tasks"] >= 10:  # Only after enough data
            if merge_rate < DEMOTION_THRESHOLD:
                profiles[agent_id]["status"] = "demoted"
            elif merge_rate >= PROMOTION_THRESHOLD:
                profiles[agent_id]["status"] = "active"
            elif profiles[agent_id].get("status") == "demoted" and merge_rate > DEMOTION_THRESHOLD * 2:
                profiles[agent_id]["status"] = "canary"  # Probation
        _save_profiles(profiles)

    return {"score": blended_score(agent_id, rep), "merge_rate": merge_rate}


# ── Cross-Model Scoring (the "important twist") ─────────────────────────────

def score_prediction(predictor_id, subject_id, predicted_outcome, actual_outcome):
    """Models score each other's predictions. If GPT predicts Claude will fail
    and Claude fails, GPT's critic reputation rises."""
    rep = _reputation()
    r = rep.get(predictor_id, {"prediction_accuracy": 0, "predictions_made": 0})

    correct = (predicted_outcome == actual_outcome)
    r["predictions_made"] = r.get("predictions_made", 0) + 1
    # EMA for prediction accuracy
    alpha = 0.2
    old = r.get("prediction_accuracy", 0.5)
    r["prediction_accuracy"] = alpha * (1.0 if correct else 0.0) + (1 - alpha) * old

    if correct:
        r["critic_credit"] = r.get("critic_credit", 0) + 1

    rep[predictor_id] = r
    _save_reputation(rep)


# ── Tournament (borrowed from Tomorrow's negotiationTournament.ts) ───────────

def run_tournament(task_class="feature"):
    """Run a round-robin tournament for a task class. Pairs every active model
    against every other on comparable historical tasks, settling by real outcomes.

    Uses historical outcomes rather than live model calls (zero-cost).
    """
    rep = _reputation()
    profiles = _profiles()

    # Get active agents with enough data
    eligible = [aid for aid, p in profiles.items()
                if p.get("status") in ("active", "canary")
                and rep.get(aid, {}).get("total_tasks", 0) >= 3]

    if len(eligible) < 2:
        return {"status": "insufficient_agents", "count": len(eligible)}

    # Round-robin: compare each pair by blended score
    results = []
    for i, a in enumerate(eligible):
        for b in eligible[i+1:]:
            sa = blended_score(a, rep)
            sb = blended_score(b, rep)

            if abs(sa - sb) < 1.0:
                update_elo(a, b, draw=True)
                results.append({"a": a, "b": b, "result": "draw"})
            elif sa > sb:
                update_elo(a, b)
                results.append({"a": a, "b": b, "result": "a_wins"})
            else:
                update_elo(b, a)
                results.append({"a": a, "b": b, "result": "b_wins"})

    # Write standings
    standings = []
    rep = _reputation()  # Re-read after Elo updates
    for aid in eligible:
        r = rep.get(aid, {})
        standings.append({
            "agent_id": aid,
            "elo": r.get("elo", ELO_DEFAULT),
            "score": blended_score(aid, rep),
            "merge_rate": r.get("merged", 0) / max(r.get("total_tasks", 1), 1),
            "cost_per_merge": r.get("total_cost_usd", 0) / max(r.get("merged", 1), 1),
            "status": profiles.get(aid, {}).get("status", "unknown"),
        })
    standings.sort(key=lambda s: -s["elo"])

    try:
        db.upsert("controls", {
            "key": f"colosseum_standings_{task_class}",
            "value": json.dumps(standings, default=str)
        })
    except Exception:
        pass

    return {"status": "completed", "matches": len(results), "standings": standings}


# ── Periodic Entry Point ─────────────────────────────────────────────────────

def run():
    """Periodic job: run tournaments for each task class, update promotions."""
    if os.environ.get("ORCH_COLOSSEUM", "true").lower() not in ("true", "1", "yes"):
        return

    for tc in TASK_CLASSES:
        try:
            result = run_tournament(tc)
            if result.get("standings"):
                top = result["standings"][0]
                print(f"[colosseum] {tc}: champion={top['agent_id']} "
                      f"elo={top['elo']} score={top['score']:.1f} "
                      f"merge={top['merge_rate']:.0%}")
        except Exception as e:
            print(f"[colosseum] {tc} tournament error: {e}")

    # Weekly promotion/demotion sweep
    profiles = _profiles()
    rep = _reputation()
    demoted = promoted = 0
    for aid, prof in profiles.items():
        r = rep.get(aid, {})
        total = r.get("total_tasks", 0)
        if total < 10:
            continue
        merge_rate = r.get("merged", 0) / total

        # $/merged-diff as the ultimate metric
        cost_per_merge = r.get("total_cost_usd", 0) / max(r.get("merged", 1), 1)

        if merge_rate < DEMOTION_THRESHOLD:
            if prof.get("status") != "demoted":
                prof["status"] = "demoted"
                demoted += 1
        elif merge_rate >= PROMOTION_THRESHOLD and cost_per_merge < 5.0:
            if prof.get("status") != "active":
                prof["status"] = "active"
                promoted += 1

    if demoted or promoted:
        _save_profiles(profiles)
        print(f"[colosseum] sweep: promoted={promoted} demoted={demoted}")


# ── Router Integration ───────────────────────────────────────────────────────

def pick_implementer(task):
    """Drop-in replacement for model routing: returns (provider, model) tuple
    based on colosseum standings instead of static routing tables."""
    bids = solicit_bids(task)
    if not bids:
        return None, None

    best = bids[0]
    return best.get("vendor"), best.get("model")


def pick_verifier(task, exclude_vendor=""):
    """Pick a verifier from a different vendor than the implementer."""
    bids = solicit_bids(task)
    for b in bids:
        if b.get("vendor") != exclude_vendor:
            return b.get("vendor"), b.get("model")
    if bids:
        return bids[-1].get("vendor"), bids[-1].get("model")
    return None, None

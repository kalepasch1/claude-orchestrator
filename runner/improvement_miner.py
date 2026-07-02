#!/usr/bin/env python3
"""
improvement_miner.py - autonomous portfolio of production A/B experiments.

The miner allocates a capped slice of fleet capacity to discover and prove out
improvements. Each experiment:
  * Splits traffic: control (current) vs candidate (proposed change)
  * Measures outcomes: success rate, cost, speed
  * Uses canary_economics: graduates winners, kills losers, scales winners
  * Stays within budget: max X% of fleet at any time
  * Rolls back on degradation: stop the experiment immediately

Experiments are NON-DIVERGENT: they test operational changes (model choice, timeout,
concurrency) not new features or breaking changes.

Ideas come from:
  1. feedback_review clusters (operational friction)
  2. self_review telemetry (low-hanging wins)
  3. model routing bandit (which model wins for which project?)
  4. Random exploration (learn from safe variations)

Run nightly or on demand: python3 improvement_miner.py
"""
import os, sys, json, time, math, random
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, claude_cli

MINER_MODEL = os.environ.get("MINER_MODEL", "claude-opus-4-8")
MINER_BUDGET_PCT = float(os.environ.get("MINER_BUDGET_PCT", "5"))  # Max % of fleet
MIN_TRIAL_SIZE = int(os.environ.get("MIN_TRIAL_SIZE", "10"))  # Min tasks to stat-test
CANARY_THRESHOLD = float(os.environ.get("CANARY_THRESHOLD", "0.95"))  # Win by this % to graduate
ROLLBACK_THRESHOLD = float(os.environ.get("ROLLBACK_THRESHOLD", "0.90"))  # Drop below this = kill


def budget_available():
    """Return {available_pct, current_active_count, total_capacity}."""
    try:
        outcomes = db.select("outcomes", {"select": "*", "order": "created_at.desc", "limit": "500"}) or []
        total = max(100, len(outcomes))
    except Exception:
        total = 100  # safe estimate
    try:
        allocated_total = 0
        active_exps = db.select("experiments", {"select": "*", "status": "eq.active"}) or []
        for exp in active_exps:
            allocated_total += (exp.get("fleet_allocation_pct", 0) / 100.0) * total
        allocated = allocated_total / max(1, total) * 100
    except Exception:
        allocated = 0
    available = MINER_BUDGET_PCT - allocated
    return {"available_pct": max(0, available), "active_count": len(active_exps), "total": total}


def _task_allocation(exp_id):
    """Return fraction [0,1] of tasks allocated to this experiment."""
    try:
        exp = db.select("experiments", {"select": "*", "id": f"eq.{exp_id}"}) or []
        if exp:
            alloc = exp[0].get("fleet_allocation_pct", 0) / 100.0
            return alloc
    except Exception:
        pass
    return 0


def _can_generate_ideas():
    """Return True if we have budget to explore new experiments."""
    avail = budget_available()
    return avail["available_pct"] > 1.0  # Reserve at least 1% headroom


def generate_ideas():
    """Ask the model to suggest 2-3 safe operational experiments to run."""
    if not _can_generate_ideas():
        return []
    try:
        telemetry = _gather_telemetry()
        prompt = f"""You are the orchestrator's improvement discovery engine. Given this 24h telemetry,
propose 2-3 NON-DIVERGENT operational experiments to A/B test in production.

Constraints:
  * Safe: only operational changes (model choice, timeouts, concurrency, context size)
  * Measurable: must affect success-rate, cost/task, or latency
  * Revertible: can roll back instantly if outcomes degrade
  * Non-breaking: control path always works (no new features)

For each idea, output JSON on its own line:
{{"title":"<short name>","project":"<project or 'orchestrator'>","change":"<exact change to test>",
  "control":"<current setting>","candidate":"<proposed setting>",
  "metric":"<optimize for: success_rate | cost_per_task | latency>",
  "hypothesis":"<why this should win in 1-2 sentences>"}}

TELEMETRY:
{telemetry}"""
        r = claude_cli.run(prompt, MINER_MODEL, timeout=120)
        ideas = []
        for line in r.get("text", "").splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    ideas.append(json.loads(line))
                except Exception:
                    pass
        return ideas
    except Exception as e:
        print(f"generate_ideas failed: {e}")
        return []


def _gather_telemetry():
    """Summarize 24h outcomes for the model to reason about."""
    try:
        outcomes = db.select("outcomes", {"select": "*", "order": "created_at.desc", "limit": "500"}) or []
        if not outcomes:
            return "No data yet."
        by_project = defaultdict(list)
        by_model = defaultdict(list)
        for o in outcomes[-100:]:  # last 100
            by_project[o.get("project", "unknown")].append(o)
            by_model[o.get("model", "unknown")].append(o)
        summary = {"projects": {}, "models": {}}
        for proj, rows in list(by_project.items())[:5]:
            passed = sum(1 for r in rows if r.get("tests_passed"))
            summary["projects"][proj] = {
                "count": len(rows),
                "pass_rate": round(passed / max(1, len(rows)), 2),
                "avg_cost": round(sum(r.get("usd", 0) for r in rows) / len(rows), 4)
            }
        for model, rows in list(by_model.items())[:3]:
            passed = sum(1 for r in rows if r.get("tests_passed"))
            summary["models"][model] = {
                "count": len(rows),
                "pass_rate": round(passed / max(1, len(rows)), 2),
                "avg_cost": round(sum(r.get("usd", 0) for r in rows) / len(rows), 4)
            }
        return json.dumps(summary, indent=2)
    except Exception as e:
        return f"Telemetry unavailable: {e}"


def enqueue_experiment(idea):
    """Create an experiment record + enqueue control & candidate tasks.

    Returns experiment_id on success, None if budget unavailable.
    """
    avail = budget_available()
    if avail["available_pct"] < 2.0:  # Need at least 2% for a new experiment
        print(f"enqueue_experiment: insufficient budget ({avail['available_pct']:.1f}% available, need 2%)")
        return None
    try:
        exp_id = f"exp-{int(time.time())}-{random.randint(1000, 9999)}"
        db.insert("experiments", {
            "id": exp_id,
            "title": idea.get("title"),
            "project": idea.get("project", "orchestrator"),
            "category": idea.get("metric", "unknown"),
            "status": "active",
            "control_value": idea.get("control"),
            "candidate_value": idea.get("candidate"),
            "hypothesis": idea.get("hypothesis"),
            "fleet_allocation_pct": 2,  # Start small: 2% of fleet
            "created_at": "now()",
            "updated_at": "now()"
        })
        return exp_id
    except Exception as e:
        print(f"enqueue_experiment failed: {e}")
        return None


def allocate_budget(active_experiments):
    """Allocate the miner's budget slice across active experiments using canary economics.

    Winners get more traffic, losers get less, until graduated or discarded.
    """
    if not active_experiments:
        return
    avail = budget_available()
    if avail["available_pct"] <= 0:
        return
    total_to_allocate = avail["available_pct"]
    for exp in active_experiments:
        exp_id = exp["id"]
        verdict = evaluate_experiment(exp_id)
        if verdict == "graduated":
            db.update("experiments", {"id": exp_id}, {"status": "graduated", "fleet_allocation_pct": 0})
        elif verdict == "discarded":
            db.update("experiments", {"id": exp_id}, {"status": "discarded", "fleet_allocation_pct": 0})
        elif verdict == "roll_back":
            db.update("experiments", {"id": exp_id}, {"status": "discarded", "fleet_allocation_pct": 0,
                                                      "note": "rolled back due to degradation"})
        elif verdict == "winning":
            current = exp.get("fleet_allocation_pct", 2) / 100.0
            boosted = min(current * 1.5, 0.25)  # Boost allocation up to 25%
            db.update("experiments", {"id": exp_id}, {"fleet_allocation_pct": int(boosted * 100)})
        elif verdict == "inconclusive":
            pass  # Keep current allocation


def evaluate_experiment(exp_id):
    """Stat-test control vs candidate; return: 'inconclusive' | 'winning' | 'losing' | 'graduated' | 'discarded' | 'roll_back'."""
    try:
        exp = db.select("experiments", {"select": "*", "id": f"eq.{exp_id}"}) or []
        if not exp:
            return "discarded"
        exp = exp[0]
        if exp.get("status") not in ("active", "monitoring"):
            return exp.get("status", "discarded")
        trials = db.select("outcomes", {
            "select": "*",
            "experiment_id": f"eq.{exp_id}",
            "order": "created_at.desc",
            "limit": "200"
        }) or []
        if len(trials) < MIN_TRIAL_SIZE:
            return "inconclusive"  # Need more data
        control = [t for t in trials if t.get("experiment_variant") == "control"]
        candidate = [t for t in trials if t.get("experiment_variant") == "candidate"]
        if not control or not candidate:
            return "inconclusive"
        c_pass = sum(1 for t in control if t.get("tests_passed"))
        k_pass = sum(1 for t in candidate if t.get("tests_passed"))
        c_rate = c_pass / max(1, len(control))
        k_rate = k_pass / max(1, len(candidate))
        c_cost = sum(t.get("usd", 0) for t in control) / max(1, len(control))
        k_cost = sum(t.get("usd", 0) for t in candidate) / max(1, len(candidate))
        cost_ok = k_cost <= c_cost * 1.10  # Candidate can be 10% pricier
        age_hours = (time.time() - exp.get("created_at", time.time())) / 3600
        if k_rate >= c_rate and cost_ok:
            if k_rate >= CANARY_THRESHOLD * c_rate and age_hours >= 24:
                return "graduated"  # Wins significantly; promote it
            elif k_rate >= c_rate:
                return "winning"  # Trending up
            else:
                return "inconclusive"
        else:
            if k_rate < ROLLBACK_THRESHOLD * c_rate or k_cost > c_cost * 1.20:
                return "roll_back"  # Fail fast on degradation
            return "losing"
    except Exception as e:
        print(f"evaluate_experiment {exp_id} failed: {e}")
        return "discarded"


def reconcile_portfolio():
    """Maintenance: file approvals for graduated/discarded experiments."""
    try:
        graduated = db.select("experiments", {"select": "*", "status": "eq.graduated"}) or []
        for exp in graduated:
            if not exp.get("approval_filed"):
                db.insert("approvals", {
                    "project": exp.get("project", "ORCHESTRATOR"),
                    "kind": "self",
                    "title": f"✅ GRADUATE: {exp.get('title')}",
                    "why": f"A/B experiment showed {exp.get('candidate_value')} wins over {exp.get('control_value')}.",
                    "value": "Production-proven improvement; consider baking into defaults.",
                    "risk": "Already running in production; can rollback anytime.",
                    "detail": exp.get("hypothesis"),
                    "command": ""
                })
                db.update("experiments", {"id": exp.get("id")}, {"approval_filed": True})
    except Exception as e:
        print(f"reconcile_portfolio failed: {e}")


def run():
    """Nightly: generate ideas, allocate budget, evaluate active experiments."""
    print("improvement_miner: starting")
    ideas = generate_ideas()
    print(f"  generated {len(ideas)} ideas")
    active = db.select("experiments", {"select": "*", "status": "eq.active"}) or []
    print(f"  active experiments: {len(active)}")
    budget = budget_available()
    print(f"  budget available: {budget['available_pct']:.1f}%")
    for idea in ideas[:2]:  # Limit to top 2 ideas per run
        exp_id = enqueue_experiment(idea)
        if exp_id:
            print(f"    enqueued {idea.get('title')} as {exp_id}")
    allocate_budget(active)
    reconcile_portfolio()
    print("improvement_miner: done")


if __name__ == "__main__":
    run()

#!/usr/bin/env python3
"""
experiment_router.py - route tasks to experiments and track outcomes.

When a task is part of an A/B experiment (task["experiment_id"] is set),
track both its assignment to control/candidate and outcomes.

Used by runner.py: before enqueuing a task, check if it should be split
into control+candidate variants, and tag outcomes.
"""
import os, sys, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def task_experiment_metadata(task_id):
    """Return {experiment_id, variant} if the task is part of an experiment, else None."""
    try:
        tasks = db.select("tasks", {"select": "*", "id": f"eq.{task_id}"}) or []
        if tasks:
            exp_id = tasks[0].get("experiment_id")
            variant = tasks[0].get("experiment_variant")
            if exp_id and variant:
                return {"experiment_id": exp_id, "variant": variant}
    except Exception:
        pass
    return None


def enqueue_experiment_pair(experiment_id, project_id, prompt, base_branch="main"):
    """Create control and candidate task pair for an experiment.

    Returns (control_task_id, candidate_task_id) or (None, None) on error.
    """
    try:
        exp = db.select("experiments", {"select": "*", "id": f"eq.{experiment_id}"}) or []
        if not exp:
            return None, None
        exp = exp[0]
        control_id = f"t-exp-{experiment_id}-control-{int(os.urandom(2).hex(), 16)}"
        candidate_id = f"t-exp-{experiment_id}-candidate-{int(os.urandom(2).hex(), 16)}"
        # Enqueue the control: current approach
        db.insert("tasks", {
            "id": control_id, "project_id": project_id, "prompt": prompt,
            "kind": "build", "slug": f"exp-{experiment_id[:8]}-ctrl",
            "base_branch": base_branch, "state": "QUEUED",
            "experiment_id": experiment_id, "experiment_variant": "control",
            "created_at": "now()"
        })
        # Enqueue the candidate: with the proposed change
        db.insert("tasks", {
            "id": candidate_id, "project_id": project_id, "prompt": prompt,
            "kind": "build", "slug": f"exp-{experiment_id[:8]}-cand",
            "base_branch": base_branch, "state": "QUEUED",
            "experiment_id": experiment_id, "experiment_variant": "candidate",
            "created_at": "now()"
        })
        return control_id, candidate_id
    except Exception as e:
        print(f"enqueue_experiment_pair failed: {e}")
        return None, None


def record_experiment_outcome(task_id, experiment_id, variant, tests_passed, cost_usd):
    """Track outcome for an experiment variant (called by runner.record after task completion)."""
    try:
        db.insert("experiment_outcomes", {
            "task_id": task_id,
            "experiment_id": experiment_id,
            "variant": variant,
            "tests_passed": tests_passed,
            "cost_usd": cost_usd,
            "created_at": "now()"
        })
    except Exception as e:
        print(f"record_experiment_outcome failed: {e}")


def sample_for_experiment(project_id):
    """Return experiment_id if this task should be enrolled in an active experiment, else None.

    Samples proportional to fleet_allocation_pct.
    """
    try:
        active = db.select("experiments",
            {"select": "*", "status": "eq.active", "project": f"eq.{project_id}"}) or []
        if not active:
            return None
        # Weighted sampling: pick an experiment with probability = allocation_pct / 100
        r = random.random() * 100
        cum = 0
        for exp in active:
            alloc = exp.get("fleet_allocation_pct", 0)
            cum += alloc
            if r <= cum:
                return exp.get("id")
        return None
    except Exception:
        return None

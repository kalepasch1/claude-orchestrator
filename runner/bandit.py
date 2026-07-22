#!/usr/bin/env python3
"""
bandit.py - predictive routing. Instead of the static heuristic in model_router,
this learns from real `outcomes` which model actually maximizes
throughput-per-dollar for each task class, and picks accordingly (UCB1 with an
epsilon floor so it keeps exploring). Falls back to the heuristic router when it
has no data yet, so day-1 behavior is sane.

reward = (1.0 if tests_passed and integrated else 0.2 if tests_passed else 0)
         / (usd + 0.01)        # success per dollar; cheap wins score higher

Usage:
    choose(task_class, candidate_models) -> model string
Data comes from db.outcomes (Supabase) and is cached briefly per run.
"""
import math, time, random, os
import model_router

MODELS = [model_router.HAIKU, model_router.SONNET, model_router.OPUS]
EPSILON = float(os.environ.get("BANDIT_EPSILON", "0.1"))
_cache = {"t": 0, "rows": []}


def _outcomes(db):
    """Fetch recent outcomes from Supabase, cached for 60s to avoid per-task DB round-trips."""
    if time.time() - _cache["t"] < 60:
        return _cache["rows"]
    try:
        rows = db.select("outcomes", {"select": "model,usd,tests_passed,integrated,kind",
                                      "order": "created_at.desc", "limit": "2000"}) or []
    except Exception:
        rows = []
    _cache.update(t=time.time(), rows=rows)
    return rows


def _reward(r):
    """Compute success-per-dollar reward for a single outcome row.

    Full credit (1.0) for test-passed + integrated, partial (0.2) for test-passed only,
    zero otherwise. Divided by cost (+0.01 floor) so cheaper wins score higher."""
    base = 1.0 if (r.get("tests_passed") and r.get("integrated")) else (0.2 if r.get("tests_passed") else 0.0)
    return base / (float(r.get("usd") or 0) + 0.01)


def choose(db, task_class, prompt, candidates=None):
    candidates = candidates or MODELS
    rows = [r for r in _outcomes(db) if (r.get("kind") or "build") == task_class]
    if len(rows) < 8:                                  # cold start -> heuristic
        return model_router.route(prompt)["model"]
    if random.random() < EPSILON:                      # explore
        return random.choice(candidates)
    stats = {m: [0.0, 0] for m in candidates}          # [sum_reward, n]
    for r in rows:
        m = r.get("model")
        if m in stats:
            stats[m][0] += _reward(r); stats[m][1] += 1
    total = sum(n for _, n in stats.values()) or 1
    best, best_score = candidates[0], -1
    for m, (s, n) in stats.items():
        if n == 0:
            return m                                   # try the untried arm
        ucb = s / n + math.sqrt(2 * math.log(total) / n)   # UCB1
        if ucb > best_score:
            best, best_score = m, ucb
    return best

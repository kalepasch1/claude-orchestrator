#!/usr/bin/env python3
"""
qpd_bandit.py - learn the QUALITY-PER-DOLLAR of each provider/model per task class and route to the
live best, instead of a fixed tranche order. A Thompson-style bandit over app_operations telemetry:
each (task_class, provider, model) arm tracks avg quality and avg cost; score = quality / (cost + eps)
with an exploration bonus that decays as samples grow. Occasionally explores a cheaper arm to keep the
estimate honest.

best(task_class) -> (provider, model, why)   — the current quality-per-dollar leader (explore sometimes)
This makes model_policy/app_triage routing provably adaptive rather than heuristic. Non-agentic only;
Anthropic agentic work stays on the subscription.
"""
import os, sys, math, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

EPS = 0.0005
EXPLORE = float(os.environ.get("QPD_EXPLORE", "0.10"))


def _arms(task_class):
    rows = db.select("app_operations", {"select": "provider,model,cost_usd,quality_score,task_class",
                                        "task_class": f"eq.{task_class}",
                                        "quality_score": "not.is.null",
                                        "order": "created_at.desc", "limit": "1000"}) or []
    arms = {}
    for r in rows:
        k = (r["provider"], r["model"])
        a = arms.setdefault(k, {"q": 0.0, "c": 0.0, "n": 0})
        a["q"] += float(r.get("quality_score") or 0)
        a["c"] += float(r.get("cost_usd") or 0)
        a["n"] += 1
    return arms


def rank(task_class):
    arms = _arms(task_class)
    scored = []
    total_n = sum(a["n"] for a in arms.values()) or 1
    for (prov, model), a in arms.items():
        if a["n"] == 0:
            continue
        q = a["q"] / a["n"]
        c = a["c"] / a["n"]
        base = q / (c + EPS)
        bonus = math.sqrt(2 * math.log(total_n) / a["n"])   # UCB exploration term
        scored.append({"provider": prov, "model": model, "qpd": base, "score": base * (1 + 0.1 * bonus),
                       "avg_quality": round(q, 2), "avg_cost": round(c, 5), "n": a["n"]})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def best(task_class):
    r = rank(task_class)
    if not r:
        return None, None, "no telemetry yet (fall back to model_policy)"
    if random.random() < EXPLORE and len(r) > 1:
        pick = random.choice(r[1:])
        return pick["provider"], pick["model"], f"explore ({pick['n']} samples)"
    top = r[0]
    return top["provider"], top["model"], f"qpd leader q={top['avg_quality']} ${top['avg_cost']} (n={top['n']})"


if __name__ == "__main__":
    import json
    for tc in ("qa", "review", "rating", "plan"):
        print(tc, "->", best(tc))
        print("   ", json.dumps(rank(tc)[:3]))

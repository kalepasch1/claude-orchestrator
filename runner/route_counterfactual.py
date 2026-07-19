#!/usr/bin/env python3
"""Replay many routing policies against one captured outcome trace, without model calls."""
import json
import os
import time


def evaluate(rows, variants=50):
    import route_value_optimizer as rvo
    providers = sorted({rvo.provider_of(r.get("model")) for r in rows or []})
    metrics = {p: rvo.summarize(rows, p) for p in providers}
    policies = []
    for i in range(max(1, int(variants))):
        value_weight = 1.0 + i / max(1, variants - 1) * 4.0
        cost_weight = 5.0 - i / max(1, variants - 1) * 4.0
        ranked = sorted(providers, key=lambda p: (
            -(metrics[p]["deployment_lower_bound"] * value_weight
              + metrics[p]["value_per_min"]),
            metrics[p]["usd_per_value"] * cost_weight, p))
        policies.append({"variant": i, "value_weight": round(value_weight, 3),
                         "cost_weight": round(cost_weight, 3), "ranking": ranked})
    return {"trace_rows": len(rows or []), "providers": metrics,
            "variants": policies, "experimental_multiplier": len(policies)}


def run(variants=50):
    import route_value_optimizer as rvo
    result = evaluate(rvo.live_rows(), variants)
    home = os.environ.get("CLAUDE_ORCH_HOME", os.path.join(os.path.dirname(__file__), "..", ".runtime"))
    path = os.path.join(home, "route-counterfactual.json")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"at": time.time(), **result}, f, indent=2, default=str)
    except OSError:
        pass
    print(f"route_counterfactual: {result['variants'].__len__()} policies / {result['trace_rows']} outcomes")
    return result


if __name__ == "__main__":
    run()

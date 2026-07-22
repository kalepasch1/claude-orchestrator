"""Metrics-computation layer for the fleet scoreboard.

Exports compute_metrics(outcomes: list) -> dict with keys:
  - overall: aggregate outcome metrics
  - by_model: outcome metrics grouped by model/coder
  - by_project: outcome metrics grouped by project
  - lead_times: objective->prompt and prompt->merged lead times
  - deploy_success_rate: fraction of DONE tasks that deployed successfully
  - knowledge_reuse_rate: fraction of tasks that benefited from context reuse
"""


def _outcome_metrics(rows):
    attempts = len(rows)
    tests_passed = sum(1 for r in rows if r.get("tests_passed"))
    merged = sum(1 for r in rows if r.get("integrated"))
    usd = sum(float(r.get("usd") or 0) for r in rows)
    tokens = sum(int(r.get("input_tokens") or 0) + int(r.get("output_tokens") or 0) for r in rows)
    wall_ms = sum(int(r.get("wall_ms") or 0) for r in rows)
    review_failures = sum(int(r.get("review_failures") or 0) for r in rows)
    first_pass_rate = round(tests_passed / attempts, 4) if attempts else None
    merge_rate = round(merged / attempts, 4) if attempts else None
    return {
        "attempts": attempts,
        "tests_passed": tests_passed,
        "merged": merged,
        "first_pass_rate": first_pass_rate,
        "merge_rate": merge_rate,
        "usd": round(usd, 4),
        "usd_per_merge": round(usd / merged, 4) if merged else None,
        "tokens": tokens,
        "tokens_per_merge": round(tokens / merged, 1) if merged else None,
        "avg_wall_min": round((wall_ms / max(1, attempts)) / 60000, 2) if attempts else None,
        "review_failures": review_failures,
        "review_failures_per_merge": round(review_failures / merged, 3) if merged else None,
    }


def _by_model(rows):
    grouped = {}
    for row in rows:
        key = row.get("model") or row.get("coder") or "unknown"
        grouped.setdefault(str(key), []).append(row)
    return {key: _outcome_metrics(vals) for key, vals in grouped.items()}


def _by_project(rows):
    grouped = {}
    for row in rows:
        key = row.get("project") or "unknown"
        grouped.setdefault(str(key), []).append(row)
    return {key: _outcome_metrics(vals) for key, vals in grouped.items()}


def _lead_times(outcomes):
    """Compute objective->prompt and prompt->merged lead times from outcome rows.

    Each outcome row may carry created_at (objective birth), started_at (prompt
    sent / work started), and completed_at (merged / done). All are ISO strings.
    Returns median and p90 for each leg, in minutes. Missing timestamps are skipped.
    """
    import datetime

    obj_to_prompt = []
    prompt_to_merged = []

    for r in outcomes:
        created = r.get("created_at")
        started = r.get("started_at")
        completed = r.get("completed_at") or r.get("merged_at")

        try:
            if created and started:
                t0 = datetime.datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                t1 = datetime.datetime.fromisoformat(str(started).replace("Z", "+00:00"))
                delta = (t1 - t0).total_seconds() / 60.0
                if 0 <= delta < 10080:  # cap at 7 days
                    obj_to_prompt.append(delta)
        except (ValueError, TypeError):
            pass

        try:
            if started and completed:
                t1 = datetime.datetime.fromisoformat(str(started).replace("Z", "+00:00"))
                t2 = datetime.datetime.fromisoformat(str(completed).replace("Z", "+00:00"))
                delta = (t2 - t1).total_seconds() / 60.0
                if 0 <= delta < 10080:
                    prompt_to_merged.append(delta)
        except (ValueError, TypeError):
            pass

    def _stats(vals):
        if not vals:
            return {"median_min": None, "p90_min": None, "count": 0}
        vals.sort()
        n = len(vals)
        median = vals[n // 2]
        p90 = vals[int(n * 0.9)]
        return {"median_min": round(median, 2), "p90_min": round(p90, 2), "count": n}

    return {
        "objective_to_prompt": _stats(obj_to_prompt),
        "prompt_to_merged": _stats(prompt_to_merged),
    }


def _deploy_success_rate(outcomes):
    """Fraction of completed tasks whose deploy succeeded (deploy_ok flag)."""
    deployed = [r for r in outcomes if r.get("integrated") or r.get("deployed")]
    if not deployed:
        return {"rate": None, "succeeded": 0, "attempted": 0}
    succeeded = sum(1 for r in deployed if r.get("deploy_ok", True))
    return {
        "rate": round(succeeded / len(deployed), 4),
        "succeeded": succeeded,
        "attempted": len(deployed),
    }


def _knowledge_reuse_rate(outcomes):
    """Fraction of tasks that benefited from cross-project knowledge reuse."""
    total = len(outcomes)
    if not total:
        return {"rate": None, "reused": 0, "total": 0}
    reused = sum(1 for r in outcomes if r.get("context_reuse") or r.get("reuse_hit"))
    return {
        "rate": round(reused / total, 4),
        "reused": reused,
        "total": total,
    }


def compute_metrics(outcomes):
    """Compute overall, by_model, by_project, and D1 metrics from outcome rows.

    Returns dict with keys: overall, by_model, by_project, lead_times,
    deploy_success_rate, knowledge_reuse_rate.
    """
    return {
        "overall": _outcome_metrics(outcomes),
        "by_model": _by_model(outcomes),
        "by_project": _by_project(outcomes),
        "lead_times": _lead_times(outcomes),
        "deploy_success_rate": _deploy_success_rate(outcomes),
        "knowledge_reuse_rate": _knowledge_reuse_rate(outcomes),
    }

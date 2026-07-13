"""Metrics-computation layer for the fleet scoreboard.

Exports compute_metrics(outcomes: list) -> dict with keys:
  - overall: aggregate outcome metrics
  - by_model: outcome metrics grouped by model/coder
  - by_project: outcome metrics grouped by project
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


def _lead_times(rows):
    """Compute lead time stats: median time from task creation to merge."""
    times = []
    for r in rows:
        created = r.get("created_at")
        merged_at = r.get("merged_at") or r.get("updated_at")
        if created and merged_at and r.get("integrated"):
            try:
                from datetime import datetime
                c = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                m = datetime.fromisoformat(str(merged_at).replace("Z", "+00:00"))
                times.append((m - c).total_seconds() / 3600)
            except Exception:
                pass
    if not times:
        return {"median_hours": None, "p90_hours": None}
    times.sort()
    mid = len(times) // 2
    p90 = int(len(times) * 0.9)
    return {
        "median_hours": round(times[mid], 2),
        "p90_hours": round(times[min(p90, len(times) - 1)], 2),
    }


def _deploy_rate(rows):
    """Compute deploy rate: merges per hour over the window."""
    if not rows:
        return None
    merged = sum(1 for r in rows if r.get("integrated"))
    hours = max(1, len(set(str(r.get("created_at", ""))[:13] for r in rows)))
    return round(merged / hours, 3)


def _knowledge_reuse(rows):
    """Estimate knowledge reuse: fraction of tasks that leveraged prior patches."""
    if not rows:
        return None
    reused = sum(1 for r in rows if r.get("reused_patch") or r.get("transplant_source"))
    return round(reused / len(rows), 4) if rows else None


def compute_metrics(outcomes):
    """Compute overall, by_model, by_project metrics from a list of outcome rows.

    Returns dict with keys: overall, by_model, by_project, lead_times,
    deploy_rate, knowledge_reuse.
    """
    return {
        "overall": _outcome_metrics(outcomes),
        "by_model": _by_model(outcomes),
        "by_project": _by_project(outcomes),
        "lead_times": _lead_times(outcomes),
        "deploy_rate": _deploy_rate(outcomes),
        "knowledge_reuse": _knowledge_reuse(outcomes),
    }

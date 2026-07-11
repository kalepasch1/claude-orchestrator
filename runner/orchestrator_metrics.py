#!/usr/bin/env python3
"""
orchestrator_metrics.py - KPI computation and competitive comparison for the orchestrator.

Aggregates cost, outcome, and savings data from across the fleet and computes
value-add metrics that quantify orchestrator advantages over single-model and
competitor alternatives.  Generates a full report dict or writes it to JSON.

Usage:
    python orchestrator_metrics.py              # prints report to stdout
    python orchestrator_metrics.py --json out.json  # writes report to file

Fail-soft: every data-loading function returns a sensible empty default on error
so callers always get a usable dict.
"""

import os, sys, json, time, datetime, statistics

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

LAST_UPDATED = "2026-07-10"

# ---------------------------------------------------------------------------
# Competitor pricing (per 1M tokens, USD) — July 2026
# ---------------------------------------------------------------------------

COMPETITOR_PRICING = {
    "orchestrator": {
        "models": {
            "haiku-4.5": {"input": 1.00, "output": 5.00},
            "sonnet-4.6": {"input": 3.00, "output": 15.00},
            "opus-4.8": {"input": 15.00, "output": 75.00},
        }
    },
    "perplexity": {
        "subscription": 20.00,
        "api": {
            "sonar_small": {"input": 0.20, "output": 0.20, "per_request": 5.00},
            "sonar_large": {"input": 1.00, "output": 1.00, "per_request": 5.00},
            "sonar_pro": {"input": 3.00, "output": 15.00, "per_request": 6.00},
        },
        "limitations": [
            "No code execution",
            "No cross-project context",
            "No parallel task execution",
            "No code reuse optimization",
            "No automated merge/test pipeline",
        ],
    },
    "openai": {
        "api": {
            "gpt-4o": {"input": 2.50, "output": 10.00},
            "gpt-4o-mini": {"input": 0.15, "output": 0.60},
            "gpt-4.1": {"input": 2.00, "output": 8.00},
            "o1": {"input": 15.00, "output": 60.00},
        },
        "subscription": 20.00,
        "limitations": [
            "Single-threaded conversations",
            "No fleet orchestration",
            "No automated code integration",
            "No cross-project optimization",
        ],
    },
    "google": {
        "api": {
            "gemini-3.5-flash": {"input": 1.50, "output": 9.00},
            "gemini-3.1-pro": {"input": 2.00, "output": 12.00},
            "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
        },
        "subscription": 20.00,
        "limitations": [
            "No code execution pipeline",
            "No fleet management",
            "No automated testing/merge",
        ],
    },
    "deepseek": {
        "api": {
            "v4-flash": {"input": 0.14, "output": 0.28},
            "v4-pro": {"input": 0.435, "output": 0.87},
        },
        "limitations": [
            "Cheapest tokens but no orchestration",
            "No code integration pipeline",
            "No quality guarantees",
            "Limited availability/reliability",
        ],
    },
    "anthropic_direct": {
        "api": {
            "haiku-4.5": {"input": 1.00, "output": 5.00},
            "sonnet-5": {"input": 2.00, "output": 10.00},
            "opus-4.8": {"input": 5.00, "output": 25.00},
        },
        "subscription": 20.00,
        "limitations": [
            "Single conversation context",
            "Manual code integration",
            "No parallel execution",
            "No automated testing",
            "No cross-project code reuse",
        ],
    },
}

# Context overhead multiplier for competitors lacking cross-project context reuse.
CONTEXT_OVERHEAD = 1.3

# Baseline first-pass rate assumed for unorchestrated single-model usage.
UNORCHESTRATED_FIRST_PASS_RATE = 0.50

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_LEDGER_PATH = os.path.join(
    os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator")),
    "cost.jsonl",
)


def _read_jsonl(path: str) -> list[dict]:
    """Read a JSONL file, returning an empty list on any error."""
    rows: list[dict] = []
    try:
        with open(path, "r", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except (FileNotFoundError, PermissionError, OSError):
        pass
    return rows


def _safe_div(a, b, default=0.0):
    """Division that never raises."""
    try:
        return a / b if b else default
    except (TypeError, ZeroDivisionError):
        return default


def _round_usd(v, places=4):
    try:
        return round(float(v), places)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# 1. load_cost_data
# ---------------------------------------------------------------------------

def load_cost_data() -> dict:
    """Read cost.jsonl and return aggregate stats.

    Returns dict with keys:
        total_spend, total_input_tokens, total_output_tokens,
        by_model, by_project, daily_spend, task_count
    """
    empty = {
        "total_spend": 0.0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "by_model": {},
        "by_project": {},
        "daily_spend": [],
        "task_count": 0,
    }
    rows = _read_jsonl(_LEDGER_PATH)
    if not rows:
        return empty

    total_spend = 0.0
    total_in = 0
    total_out = 0
    by_model: dict[str, dict] = {}
    by_project: dict[str, dict] = {}
    daily: dict[str, float] = {}

    for r in rows:
        usd = float(r.get("usd", 0))
        inp = int(r.get("input_tokens", 0))
        out = int(r.get("output_tokens", 0))
        model = r.get("model", "unknown")
        project = r.get("project", "unknown")
        ts = r.get("ts", "")

        total_spend += usd
        total_in += inp
        total_out += out

        # by_model
        m = by_model.setdefault(model, {"spend": 0.0, "input_tokens": 0, "output_tokens": 0, "tasks": 0})
        m["spend"] += usd
        m["input_tokens"] += inp
        m["output_tokens"] += out
        m["tasks"] += 1

        # by_project
        p = by_project.setdefault(project, {"spend": 0.0, "input_tokens": 0, "output_tokens": 0, "tasks": 0})
        p["spend"] += usd
        p["input_tokens"] += inp
        p["output_tokens"] += out
        p["tasks"] += 1

        # daily
        day = ts[:10] if len(ts) >= 10 else "unknown"
        daily[day] = daily.get(day, 0.0) + usd

    # Round monetary values
    for bucket in list(by_model.values()) + list(by_project.values()):
        bucket["spend"] = _round_usd(bucket["spend"])

    daily_spend = [{"date": d, "spend": _round_usd(s)} for d, s in sorted(daily.items())]

    return {
        "total_spend": _round_usd(total_spend),
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "by_model": by_model,
        "by_project": by_project,
        "daily_spend": daily_spend,
        "task_count": len(rows),
    }


# ---------------------------------------------------------------------------
# 2. load_outcomes_data
# ---------------------------------------------------------------------------

def load_outcomes_data() -> dict:
    """Query outcomes table for task-level quality metrics.

    Returns dict with keys:
        total_tasks, merged, first_pass_rate, merge_rate,
        avg_cost_per_merge, by_model, by_project
    """
    empty = {
        "total_tasks": 0,
        "merged": 0,
        "first_pass_rate": 0.0,
        "merge_rate": 0.0,
        "avg_cost_per_merge": 0.0,
        "by_model": {},
        "by_project": {},
    }
    try:
        import db
        rows = db.select("outcomes", {"select": "*"})
        if not rows:
            return empty
    except Exception:
        return empty

    total = len(rows)
    merged = sum(1 for r in rows if r.get("integrated") or r.get("state") == "MERGED")
    tests_passed = sum(1 for r in rows if r.get("tests_passed"))
    first_pass = sum(1 for r in rows if r.get("tests_passed") and not r.get("retries"))

    by_model: dict[str, dict] = {}
    by_project: dict[str, dict] = {}

    for r in rows:
        model = r.get("model", "unknown")
        project = r.get("project", "unknown")
        is_merged = bool(r.get("integrated") or r.get("state") == "MERGED")
        is_first_pass = bool(r.get("tests_passed") and not r.get("retries"))

        for key, bucket_map in [("model", by_model), ("project", by_project)]:
            name = model if key == "model" else project
            b = bucket_map.setdefault(name, {"tasks": 0, "merged": 0, "first_pass": 0, "spend": 0.0})
            b["tasks"] += 1
            b["merged"] += int(is_merged)
            b["first_pass"] += int(is_first_pass)
            b["spend"] += float(r.get("usd", 0) or 0)

    # Compute rates for sub-buckets
    for bucket_map in (by_model, by_project):
        for b in bucket_map.values():
            b["first_pass_rate"] = _round_usd(_safe_div(b["first_pass"], b["tasks"]))
            b["merge_rate"] = _round_usd(_safe_div(b["merged"], b["tasks"]))
            b["spend"] = _round_usd(b["spend"])
            b["cost_per_merge"] = _round_usd(_safe_div(b["spend"], b["merged"]))

    total_spend = sum(float(r.get("usd", 0) or 0) for r in rows)

    return {
        "total_tasks": total,
        "merged": merged,
        "first_pass_rate": _round_usd(_safe_div(first_pass, total)),
        "merge_rate": _round_usd(_safe_div(merged, total)),
        "avg_cost_per_merge": _round_usd(_safe_div(total_spend, merged)),
        "by_model": by_model,
        "by_project": by_project,
    }


# ---------------------------------------------------------------------------
# 3. load_savings_data
# ---------------------------------------------------------------------------

def load_savings_data() -> dict:
    """Query resource_events where kind='savings'.

    Parses the detail and action fields written by savings_meter.record() to
    extract tokens saved, minutes saved, and a per-category breakdown.

    Returns dict with keys:
        total_tokens_saved, total_minutes_saved, savings_by_category, event_count
    """
    empty = {
        "total_tokens_saved": 0,
        "total_minutes_saved": 0.0,
        "savings_by_category": {},
        "event_count": 0,
    }
    try:
        import db
        rows = db.select("resource_events", {"kind": "eq.savings", "select": "*"})
        if not rows:
            return empty
    except Exception:
        return empty

    total_tokens = 0
    total_minutes = 0.0
    by_category: dict[str, dict] = {}

    for r in rows:
        tokens = int(r.get("value", 0) or 0)
        total_tokens += tokens

        # Parse minutes from action field: "<category>|minutes=<float>"
        action = r.get("action", "") or ""
        category = "unknown"
        minutes = 0.0
        if "|" in action:
            parts = action.split("|", 1)
            category = parts[0].strip() or "unknown"
            rest = parts[1] if len(parts) > 1 else ""
            if "minutes=" in rest:
                try:
                    minutes = float(rest.split("minutes=")[1].split(";")[0].strip())
                except (ValueError, IndexError):
                    pass
        else:
            category = action.strip() or "unknown"

        total_minutes += minutes

        c = by_category.setdefault(category, {"tokens_saved": 0, "minutes_saved": 0.0, "count": 0})
        c["tokens_saved"] += tokens
        c["minutes_saved"] += round(minutes, 2)
        c["count"] += 1

    return {
        "total_tokens_saved": total_tokens,
        "total_minutes_saved": round(total_minutes, 2),
        "savings_by_category": by_category,
        "event_count": len(rows),
    }


# ---------------------------------------------------------------------------
# 4. compute_orchestrator_advantages
# ---------------------------------------------------------------------------

def compute_orchestrator_advantages() -> dict:
    """Calculate orchestrator-specific value metrics.

    Returns dict with keys:
        smart_routing_savings, parallel_execution_value,
        code_reuse_value, first_pass_efficiency, waste_prevention_value,
        total_value_usd
    """
    result = {
        "smart_routing_savings": {"usd_saved": 0.0, "description": ""},
        "parallel_execution_value": {"minutes_saved": 0.0, "description": ""},
        "code_reuse_value": {"tokens_saved": 0, "minutes_saved": 0.0, "description": ""},
        "first_pass_efficiency": {"usd_saved": 0.0, "description": ""},
        "waste_prevention_value": {"usd_saved": 0.0, "description": ""},
        "total_value_usd": 0.0,
    }

    cost_data = load_cost_data()
    outcomes_data = load_outcomes_data()
    savings_data = load_savings_data()

    # --- smart_routing_savings ---
    # Compare actual multi-model spend to hypothetical all-sonnet spend.
    sonnet_input = COMPETITOR_PRICING["orchestrator"]["models"]["sonnet-4.6"]["input"]
    sonnet_output = COMPETITOR_PRICING["orchestrator"]["models"]["sonnet-4.6"]["output"]

    total_in = cost_data.get("total_input_tokens", 0)
    total_out = cost_data.get("total_output_tokens", 0)
    actual_spend = cost_data.get("total_spend", 0.0)

    hypothetical_all_sonnet = (total_in / 1_000_000) * sonnet_input + (total_out / 1_000_000) * sonnet_output
    routing_saved = _round_usd(max(hypothetical_all_sonnet - actual_spend, 0.0))
    result["smart_routing_savings"] = {
        "usd_saved": routing_saved,
        "actual_spend": _round_usd(actual_spend),
        "hypothetical_all_sonnet": _round_usd(hypothetical_all_sonnet),
        "description": (
            "Savings from routing cheap tasks to haiku instead of using "
            "sonnet for everything."
        ),
    }

    # --- parallel_execution_value ---
    # Estimate from scoreboard wall-clock data.
    try:
        import scoreboard
        sb = scoreboard.compute()
        overall = sb.get("overall", {})
        avg_wall_min = float(overall.get("avg_wall_min", 0) or 0)
        task_count = int(overall.get("attempts", 0) or 0)
        total_wall = avg_wall_min * task_count
        # Sequential would be the sum; parallel is max(wall) per batch.
        # Approximate: parallel cuts total wall to 1/3 of sequential (conservative).
        sequential_estimate = total_wall
        parallel_actual = total_wall  # already measured as parallel
        sequential_hypothetical = parallel_actual * 3
        minutes_saved = round(max(sequential_hypothetical - parallel_actual, 0.0), 2)
    except Exception:
        minutes_saved = 0.0
        sequential_hypothetical = 0.0
        parallel_actual = 0.0

    result["parallel_execution_value"] = {
        "minutes_saved": minutes_saved,
        "sequential_estimate_min": round(sequential_hypothetical, 2),
        "parallel_actual_min": round(parallel_actual, 2),
        "description": (
            "Time saved by running tasks in parallel across the fleet "
            "versus sequential single-agent execution."
        ),
    }

    # --- code_reuse_value ---
    tokens_saved = savings_data.get("total_tokens_saved", 0)
    minutes_saved_reuse = savings_data.get("total_minutes_saved", 0.0)
    # Estimate dollar value of saved tokens at blended rate.
    blended_rate = _safe_div(actual_spend, (total_in + total_out), 0.003 / 1_000_000)
    reuse_usd = _round_usd(tokens_saved * blended_rate)

    result["code_reuse_value"] = {
        "tokens_saved": tokens_saved,
        "minutes_saved": minutes_saved_reuse,
        "usd_value": reuse_usd,
        "description": (
            "Tokens and time avoided through cross-project code reuse "
            "and context sharing."
        ),
    }

    # --- first_pass_efficiency ---
    # With orchestrated routing + context, first-pass rate is higher.
    # Each retry costs roughly avg_cost_per_merge. Quantify retries avoided.
    actual_fpr = outcomes_data.get("first_pass_rate", 0.0)
    total_tasks = outcomes_data.get("total_tasks", 0)
    avg_task_cost = _safe_div(actual_spend, total_tasks)

    if total_tasks > 0 and actual_fpr > UNORCHESTRATED_FIRST_PASS_RATE:
        # Extra first-pass successes vs baseline
        extra_passes = (actual_fpr - UNORCHESTRATED_FIRST_PASS_RATE) * total_tasks
        # Each extra pass avoids ~1 retry
        fpr_saved = _round_usd(extra_passes * avg_task_cost)
    else:
        fpr_saved = 0.0
        extra_passes = 0.0

    result["first_pass_efficiency"] = {
        "usd_saved": fpr_saved,
        "actual_first_pass_rate": actual_fpr,
        "baseline_first_pass_rate": UNORCHESTRATED_FIRST_PASS_RATE,
        "retries_avoided": round(extra_passes, 1),
        "description": (
            "Cost of retries avoided due to higher first-pass rate "
            "versus unorchestrated baseline of 50%."
        ),
    }

    # --- waste_prevention_value ---
    # Estimate from waste.py thresholds: projects killed early save their
    # remaining budget allocation.  Conservative: each killed project would
    # have spent another WASTE_USD before a human noticed.
    try:
        import db
        rows = db.select("outcomes", {
            "select": "project,state",
            "state": "eq.WASTE",
        })
        waste_kills = len(rows) if rows else 0
    except Exception:
        waste_kills = 0

    waste_usd_threshold = float(os.environ.get("ORCH_WASTE_USD", 5))
    waste_saved = _round_usd(waste_kills * waste_usd_threshold)

    result["waste_prevention_value"] = {
        "usd_saved": waste_saved,
        "projects_killed_early": waste_kills,
        "avg_saved_per_kill": _round_usd(waste_usd_threshold),
        "description": (
            "Estimated money saved by waste.py killing failing projects "
            "before they burned more budget."
        ),
    }

    # --- total ---
    result["total_value_usd"] = _round_usd(
        routing_saved + reuse_usd + fpr_saved + waste_saved
    )

    return result


# ---------------------------------------------------------------------------
# 5. compute_competitive_comparison
# ---------------------------------------------------------------------------

def compute_competitive_comparison(actual_data: dict | None = None) -> dict:
    """Price out the orchestrator's actual workload on each competitor.

    Args:
        actual_data: dict with at least total_input_tokens and
                     total_output_tokens.  If None, calls load_cost_data().

    Returns dict keyed by competitor name, each containing:
        estimated_cost, cost_delta, percentage_savings, missing_capabilities,
        cheapest_model, model_breakdown
    """
    if actual_data is None:
        actual_data = load_cost_data()

    total_in = actual_data.get("total_input_tokens", 0)
    total_out = actual_data.get("total_output_tokens", 0)
    actual_spend = actual_data.get("total_spend", 0.0)

    if total_in == 0 and total_out == 0:
        return {"note": "No token usage data available for comparison."}

    comparisons: dict[str, dict] = {}

    for name, spec in COMPETITOR_PRICING.items():
        if name == "orchestrator":
            continue

        api_models = spec.get("api", {})
        limitations = spec.get("limitations", [])
        subscription = spec.get("subscription")

        if not api_models:
            continue

        # Price at each of the competitor's models with context overhead.
        model_costs: dict[str, float] = {}
        for mname, prices in api_models.items():
            in_price = prices.get("input", 0)
            out_price = prices.get("output", 0)
            per_req = prices.get("per_request", 0)

            cost = (
                (total_in * CONTEXT_OVERHEAD / 1_000_000) * in_price
                + (total_out * CONTEXT_OVERHEAD / 1_000_000) * out_price
            )
            # Add per-request charges if applicable (estimate 1 request per task).
            task_count = actual_data.get("task_count", 0)
            if per_req and task_count:
                cost += per_req * task_count / 1000  # per_request is per 1K requests
            model_costs[mname] = _round_usd(cost)

        cheapest_model = min(model_costs, key=model_costs.get)
        cheapest_cost = model_costs[cheapest_model]

        # Use cheapest model for headline comparison.
        cost_delta = _round_usd(cheapest_cost - actual_spend)
        pct_savings = _round_usd(
            _safe_div(cost_delta, cheapest_cost) * 100 if cheapest_cost > 0 else 0.0,
            2,
        )

        entry: dict = {
            "estimated_cost_cheapest": cheapest_cost,
            "cheapest_model": cheapest_model,
            "model_breakdown": model_costs,
            "context_overhead_multiplier": CONTEXT_OVERHEAD,
            "cost_delta_vs_orchestrator": cost_delta,
            "percentage_more_expensive": _round_usd(pct_savings, 2),
            "missing_capabilities": limitations,
        }
        if subscription is not None:
            entry["monthly_subscription"] = subscription

        comparisons[name] = entry

    comparisons["orchestrator_actual"] = {
        "total_spend": _round_usd(actual_spend),
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "task_count": actual_data.get("task_count", 0),
    }

    return comparisons


# ---------------------------------------------------------------------------
# 6. generate_report
# ---------------------------------------------------------------------------

def generate_report() -> dict:
    """Generate a comprehensive metrics report.

    Returns dict with sections:
        summary, cost_analysis, quality_metrics, orchestrator_advantages,
        competitive_comparison, generated_at
    """
    cost_data = load_cost_data()
    outcomes_data = load_outcomes_data()
    savings_data = load_savings_data()
    advantages = compute_orchestrator_advantages()
    comparison = compute_competitive_comparison(cost_data)

    summary = {
        "total_spend_usd": cost_data.get("total_spend", 0.0),
        "total_tasks": cost_data.get("task_count", 0),
        "total_merged": outcomes_data.get("merged", 0),
        "merge_rate": outcomes_data.get("merge_rate", 0.0),
        "first_pass_rate": outcomes_data.get("first_pass_rate", 0.0),
        "cost_per_merge": outcomes_data.get("avg_cost_per_merge", 0.0),
        "total_tokens": (
            cost_data.get("total_input_tokens", 0)
            + cost_data.get("total_output_tokens", 0)
        ),
        "tokens_saved_by_reuse": savings_data.get("total_tokens_saved", 0),
        "orchestrator_value_usd": advantages.get("total_value_usd", 0.0),
        "pricing_data_as_of": LAST_UPDATED,
    }

    return {
        "summary": summary,
        "cost_analysis": cost_data,
        "quality_metrics": outcomes_data,
        "savings": savings_data,
        "orchestrator_advantages": advantages,
        "competitive_comparison": comparison,
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# 7. export_json
# ---------------------------------------------------------------------------

def export_json(filepath: str | None = None) -> str:
    """Write full report to a JSON file and return the path.

    Args:
        filepath: destination path.  Defaults to
                  ~/.claude-orchestrator/metrics_report.json
    """
    if filepath is None:
        home = os.environ.get(
            "CLAUDE_ORCH_HOME",
            os.path.expanduser("~/.claude-orchestrator"),
        )
        os.makedirs(home, exist_ok=True)
        filepath = os.path.join(home, "metrics_report.json")

    report = generate_report()

    try:
        with open(filepath, "w") as fh:
            json.dump(report, fh, indent=2, default=str)
    except (OSError, PermissionError) as exc:
        # Fail-soft: print warning but don't crash.
        print(f"[orchestrator_metrics] WARNING: could not write {filepath}: {exc}",
              file=sys.stderr)
        return ""

    return filepath


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Orchestrator metrics report")
    parser.add_argument("--json", metavar="FILE", nargs="?", const="", default=None,
                        help="Write report to JSON file (default path if no FILE given)")
    args = parser.parse_args()

    if args.json is not None:
        path = export_json(args.json if args.json else None)
        if path:
            print(f"Report written to {path}")
        else:
            print("Failed to write report.", file=sys.stderr)
            sys.exit(1)
    else:
        report = generate_report()
        print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()

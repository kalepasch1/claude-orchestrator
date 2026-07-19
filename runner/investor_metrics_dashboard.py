#!/usr/bin/env python3
"""
investor_metrics_dashboard.py — Always-current investor/board dashboard showing
growth, retention, unit economics straight from prod data.

Generates a self-contained HTML dashboard. Metrics:
  - Task throughput / velocity (from tasks table)
  - Cost per task / unit economics (from cost metadata)
  - Retention: active projects over rolling windows
  - Fleet utilization rate
  - Weekly growth rate
"""
import os, sys, json, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

OUTPUT_DIR = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))


def _safe_query(query, default=None):
    """Run a SQL query via db, return rows or default on error."""
    try:
        return db.sql(query) or (default if default is not None else [])
    except Exception:
        return default if default is not None else []


def growth_metrics(days=30):
    """Weekly task volume growth."""
    rows = _safe_query(
        f"SELECT date_trunc('week', created_at) AS week, count(*) AS tasks "
        f"FROM tasks WHERE created_at > now() - interval '{days} days' "
        f"GROUP BY 1 ORDER BY 1", [])
    weeks = [{"week": str(r.get("week", ""))[:10], "tasks": r.get("tasks", 0)} for r in rows]
    if len(weeks) >= 2:
        prev, curr = weeks[-2]["tasks"], weeks[-1]["tasks"]
        growth_pct = ((curr - prev) / max(prev, 1)) * 100
    else:
        growth_pct = 0
    return {"weeks": weeks, "growth_pct": round(growth_pct, 1)}


def retention_metrics(days=90):
    """Active project retention over rolling windows."""
    rows = _safe_query(
        f"SELECT date_trunc('week', t.updated_at) AS week, "
        f"count(DISTINCT t.project_id) AS active_projects "
        f"FROM tasks t WHERE t.updated_at > now() - interval '{days} days' "
        f"GROUP BY 1 ORDER BY 1", [])
    return [{"week": str(r.get("week", ""))[:10],
             "active_projects": r.get("active_projects", 0)} for r in rows]


def unit_economics():
    """Cost per task and efficiency metrics."""
    total_tasks = _safe_query(
        "SELECT count(*) AS cnt FROM tasks WHERE state IN ('DONE','MERGED')", [])
    total = total_tasks[0].get("cnt", 0) if total_tasks else 0
    cost_rows = _safe_query(
        "SELECT coalesce(sum((metadata->>'cost_usd')::numeric), 0) AS total_cost "
        "FROM tasks WHERE state IN ('DONE','MERGED') "
        "AND metadata->>'cost_usd' IS NOT NULL", [])
    total_cost = float(cost_rows[0].get("total_cost", 0)) if cost_rows else 0
    cost_per_task = total_cost / max(total, 1)
    return {"total_completed": total, "total_cost_usd": round(total_cost, 2),
            "cost_per_task_usd": round(cost_per_task, 4)}


def throughput_metrics(days=30):
    """Task throughput: completed per day."""
    rows = _safe_query(
        f"SELECT date_trunc('day', updated_at) AS day, count(*) AS done "
        f"FROM tasks WHERE state IN ('DONE','MERGED') "
        f"AND updated_at > now() - interval '{days} days' "
        f"GROUP BY 1 ORDER BY 1", [])
    return [{"day": str(r.get("day", ""))[:10], "done": r.get("done", 0)} for r in rows]


def fleet_utilization():
    """Current fleet utilization: running vs capacity."""
    running = _safe_query("SELECT count(*) AS cnt FROM tasks WHERE state='RUNNING'", [])
    queued = _safe_query("SELECT count(*) AS cnt FROM tasks WHERE state='QUEUED'", [])
    r = running[0].get("cnt", 0) if running else 0
    q = queued[0].get("cnt", 0) if queued else 0
    capacity = int(os.environ.get("ORCH_FLEET_CAPACITY", "6"))
    return {"running": r, "queued": q, "capacity": capacity,
            "utilization_pct": round(r / max(capacity, 1) * 100, 1)}


def collect_all():
    """Collect all investor metrics into a single dict."""
    return {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "growth": growth_metrics(),
        "retention": retention_metrics(),
        "unit_economics": unit_economics(),
        "throughput": throughput_metrics(),
        "fleet": fleet_utilization(),
    }


def generate_html(data=None):
    """Generate a self-contained investor dashboard HTML page."""
    if data is None:
        data = collect_all()
    econ = data.get("unit_economics", {})
    fleet = data.get("fleet", {})
    growth = data.get("growth", {})
    ts = data.get("generated_at", "")
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<title>Investor Dashboard</title><style>'
        'body{font-family:system-ui;margin:2rem;background:#f8f9fa}'
        '.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem;margin-bottom:2rem}'
        '.card{background:#fff;border-radius:8px;padding:1.5rem;box-shadow:0 1px 3px rgba(0,0,0,.1)}'
        '.card h3{margin:0 0 .5rem;font-size:.85rem;color:#666;text-transform:uppercase}'
        '.card .value{font-size:2rem;font-weight:700;color:#1a1a2e}'
        '.card .sub{font-size:.8rem;color:#888;margin-top:.25rem}'
        'h1{color:#1a1a2e} .ts{color:#aaa;font-size:.75rem}'
        '</style></head><body>'
        f'<h1>Investor Dashboard</h1><p class="ts">Generated: {ts}</p>'
        '<div class="grid">'
        f'<div class="card"><h3>Weekly Growth</h3><div class="value">{growth.get("growth_pct",0)}%</div>'
        '<div class="sub">Task volume WoW</div></div>'
        f'<div class="card"><h3>Tasks Completed</h3><div class="value">{econ.get("total_completed",0)}</div>'
        '<div class="sub">All time</div></div>'
        f'<div class="card"><h3>Cost / Task</h3><div class="value">${econ.get("cost_per_task_usd",0)}</div>'
        '<div class="sub">Unit economics</div></div>'
        f'<div class="card"><h3>Fleet Utilization</h3><div class="value">{fleet.get("utilization_pct",0)}%</div>'
        f'<div class="sub">{fleet.get("running",0)} running / {fleet.get("capacity",0)} capacity</div></div>'
        f'<div class="card"><h3>Queue Depth</h3><div class="value">{fleet.get("queued",0)}</div>'
        '<div class="sub">Waiting tasks</div></div>'
        '</div></body></html>'
    )


def write_dashboard(output_path=None):
    """Generate and write the dashboard HTML file."""
    if output_path is None:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        output_path = os.path.join(OUTPUT_DIR, "investor_dashboard.html")
    html = generate_html()
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        return output_path
    except Exception:
        return ""


if __name__ == "__main__":
    path = write_dashboard()
    if path:
        print(f"Dashboard written to {path}")

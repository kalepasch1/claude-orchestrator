#!/usr/bin/env python3
"""
cade_firstpass.py - Reads persisted FullPassReport from Supabase and emails
a health report on first complete pass, or a NOT-operational alert on failure.

Fire-once with deduplication; re-alerts on regression.
Feature flag: ORCH_CADE_FIRSTPASS_ENABLED (default "true")
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import notify

_ENABLED = os.environ.get("ORCH_CADE_FIRSTPASS_ENABLED", "true").lower() in ("1", "true", "yes", "on")
_ALERT_KEY = "cade_firstpass_alert_state"
_RECIPIENT = "kalepasch@gmail.com"

_calls = {"check": 0, "email_health": 0, "email_alert": 0, "skip_dedup": 0}


# ─── Alert State Persistence ───

def _load_alert_state(db_client=None):
    """Load the last sent alert state from controls table."""
    try:
        rows = (db_client or db).select("controls", {
            "select": "value",
            "key": f"eq.{_ALERT_KEY}",
        })
        if rows and rows[0].get("value"):
            v = rows[0]["value"]
            return json.loads(v) if isinstance(v, str) else v
    except Exception:
        pass
    return {}


def _save_alert_state(state, db_client=None):
    """Persist the alert state to controls table."""
    try:
        (db_client or db).upsert("controls", {
            "key": _ALERT_KEY,
            "value": json.dumps(state, default=str),
        })
    except Exception:
        pass


# ─── Report Loading ───

def _load_report(db_client=None):
    """Load the latest FullPassReport from cade_pass_reports."""
    try:
        rows = (db_client or db).select("cade_pass_reports", {
            "select": "*",
            "order": "created_at.desc",
            "limit": "1",
        })
        if rows:
            return rows[0]
    except Exception:
        pass
    return None


# ─── Formatting ───

def format_health_report(report):
    """Format a complete FullPassReport into email-friendly text."""
    lines = ["CADE First Pass — Health Report", "=" * 40, ""]

    # First result summary
    first = (report.get("first_result") or report.get("results", [None])[0]
             if isinstance(report, dict) else None)
    if isinstance(first, dict):
        lines.append(f"First Result: domain={first.get('domain', '?')}  "
                     f"Brier={first.get('brier', '?')}  "
                     f"correct={first.get('correct', '?')}")
    else:
        lines.append("First Result: (none)")
    lines.append("")

    # Per-stage status
    stages = report.get("stages") or {}
    if stages:
        lines.append("Per-Stage Status:")
        for name, info in stages.items():
            status = info if isinstance(info, str) else (info.get("status", "?") if isinstance(info, dict) else str(info))
            lines.append(f"  {name}: {status}")
        lines.append("")

    # Per-domain accuracy/tier
    domains = report.get("domains") or {}
    if domains:
        lines.append("Per-Domain Accuracy:")
        for dom, info in domains.items():
            if isinstance(info, dict):
                lines.append(f"  {dom}: accuracy={info.get('accuracy', '?')}  "
                             f"tier={info.get('tier', '?')}")
            else:
                lines.append(f"  {dom}: {info}")
        lines.append("")

    # Top experts
    experts = report.get("top_experts") or report.get("experts") or []
    if experts:
        lines.append("Top Experts:")
        for exp in experts[:10]:
            if isinstance(exp, dict):
                lines.append(f"  {exp.get('name', '?')} — score={exp.get('score', '?')}")
            else:
                lines.append(f"  {exp}")
        lines.append("")

    lines.append(f"Report ID: {report.get('id', '?')}")
    lines.append(f"Timestamp: {report.get('created_at', '?')}")
    return "\n".join(lines)


def format_alert(report, failures):
    """Format a NOT-operational alert with failure details and fix directive."""
    lines = ["CADE First Pass — NOT OPERATIONAL", "=" * 40, ""]
    lines.append("The CADE first pass has failed or missing stages.")
    lines.append("")

    if failures:
        lines.append("Failed/Missing Stages:")
        for f in failures:
            if isinstance(f, dict):
                lines.append(f"  {f.get('stage', '?')}: {f.get('error', f.get('status', '?'))}")
            else:
                lines.append(f"  {f}")
        lines.append("")

    lines.append("Fix Directive:")
    lines.append("  1. Check cade_pass_reports in Supabase for the latest report")
    lines.append("  2. Investigate failed stages and their error messages")
    lines.append("  3. Re-run the pass after fixing the underlying issues")
    lines.append("")

    if report:
        lines.append(f"Report ID: {report.get('id', '?')}")
        lines.append(f"Timestamp: {report.get('created_at', '?')}")
    return "\n".join(lines)


# ─── Failure Detection ───

def _detect_failures(report):
    """Return list of failed/missing stages from the report, or empty list if healthy."""
    failures = []
    stages = report.get("stages") or {}
    if not stages:
        failures.append({"stage": "all", "error": "no stages found in report"})
        return failures

    for name, info in stages.items():
        if isinstance(info, dict):
            status = info.get("status", "").lower()
        else:
            status = str(info).lower()
        if status in ("failed", "error", "missing", "timeout"):
            failures.append({"stage": name, "status": status,
                             "error": info.get("error", "") if isinstance(info, dict) else status})
    return failures


# ─── Main Entry Point ───

def check_firstpass(db_client=None):
    """Main entry point: read FullPassReport from Supabase, email health or alert.

    Returns dict with status and action taken.
    """
    _calls["check"] += 1

    if not _ENABLED:
        return {"status": "disabled"}

    client = db_client or db
    report = _load_report(client)
    if not report:
        return {"status": "no_report"}

    alert_state = _load_alert_state(client)
    report_id = str(report.get("id", "unknown"))
    is_complete = bool(report.get("complete", False))
    failures = _detect_failures(report)
    has_failures = len(failures) > 0

    last_sent_type = alert_state.get("last_type")
    last_report_id = alert_state.get("last_report_id")

    if is_complete and not has_failures:
        # Healthy complete report
        if last_report_id == report_id and last_sent_type == "health":
            _calls["skip_dedup"] += 1
            return {"status": "dedup_skip", "report_id": report_id}

        # Regression detection: was previously alerted, now healthy again
        is_regression_recovery = (last_sent_type == "alert")

        body = format_health_report(report)
        subject = "CADE First Pass — Operational"
        if is_regression_recovery:
            subject += " (Recovered)"
        notify.send(f"[CADE FIRSTPASS] {subject}\n\n{body}")
        _calls["email_health"] += 1

        _save_alert_state({
            "last_type": "health",
            "last_report_id": report_id,
            "sent_at": time.time(),
        }, client)
        return {"status": "sent_health", "report_id": report_id}

    if has_failures:
        # Failed/missing stages — alert
        if last_report_id == report_id and last_sent_type == "alert":
            _calls["skip_dedup"] += 1
            return {"status": "dedup_skip", "report_id": report_id}

        # Regression: was healthy, now broken
        is_regression = (last_sent_type == "health")

        body = format_alert(report, failures)
        subject = "CADE First Pass — NOT OPERATIONAL"
        if is_regression:
            subject += " (REGRESSION)"
        notify.send(f"[CADE FIRSTPASS] {subject}\n\n{body}")
        _calls["email_alert"] += 1

        _save_alert_state({
            "last_type": "alert",
            "last_report_id": report_id,
            "sent_at": time.time(),
        }, client)
        return {"status": "sent_alert", "report_id": report_id,
                "failures": failures}

    # Incomplete report, no failures detected — just wait
    return {"status": "incomplete", "report_id": report_id}


# ─── Stats ───

def stats():
    """Module statistics."""
    return {
        "module": "cade_firstpass",
        "enabled": _ENABLED,
        "calls": dict(_calls),
    }


if __name__ == "__main__":
    print(json.dumps(check_firstpass(), indent=2, default=str))

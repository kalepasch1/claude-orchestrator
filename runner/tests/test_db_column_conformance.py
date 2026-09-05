#!/usr/bin/env python3
"""No db.select()/db.insert() may name a column the table does not have.

WHY (2026-08-30)
----------------
Three separate outages in one afternoon, all the same shape — a literal column
name that PostgREST rejects with HTTP 400, in a caller that swallows the error:

  approvals: "summary"/"state"       deploy_silence_detector filed nothing; it had
                                     correctly found vigil 18 days without a deploy
  approvals: "body"                  preview_canary raised no card on a failed build
  approvals: "project_id"/"note"     fast_auto_merge raised out of a function
                                     documented never to raise, on every green test
  tasks:     "branch"                done_to_merged.reconcile_missing_cards scanned
                                     0 DONE tasks. Fixing the name made one run scan
                                     25 and file 20 missing approval cards.

Every one of these is invisible at rest. A wrong column is a runtime 400, and a
caller that catches it looks exactly like a caller with nothing to report. This
test moves the whole class to import time, where it is loud and free.

MAINTENANCE
-----------
SCHEMA mirrors the live tables, captured 2026-08-30. When a migration adds a
column, add it here in the same change — the test failing on a legitimately-new
column is the reminder, and the fix is one line. Tables absent from SCHEMA are
simply not checked, so this never blocks work on a table nobody has mapped yet.
"""
import ast
import os
import glob

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCHEMA = {
    "approvals": {
        "alternatives", "approvals_required", "auto_exec_ok",
        "brief_json", "brief_status", "cluster_key", "command",
        "created_at", "decided_at", "decided_by", "decision_text",
        "decision_type", "detail", "draft", "draft_cmd", "exec_status",
        "executable", "id", "kind", "legal_risk_level", "prebrief",
        "process_spawned", "project", "radar_tag", "risk",
        "second_approver", "slug", "status", "title", "value", "why",
    },
    "controls": {
        "id", "key", "paused", "project", "reason", "scope",
        "updated_at", "updated_by", "value",
    },
    "runner_heartbeats": {
        "active_tasks", "code_sha", "contract_hash", "contract_version",
        "hostname", "last_seen", "runner_id",
    },
    "tasks": {
        "account", "artifact_branch", "artifact_commit", "artifact_id",
        "artifact_ref", "attempt", "base_branch", "batch_id",
        "build_fail_count", "capability_slug", "confidence",
        "counsel_approved_at", "counsel_approved_by", "created_at", "deps",
        "estimated_minutes", "execution_lane", "force_coder", "id", "journey",
        "kind", "log_tail", "material", "model", "note", "operator_approved_at",
        "operator_approved_by", "paired_trial_id", "paired_trial_key",
        "parent_task_id", "pin_rank", "pinned", "priority", "project_id",
        "prompt", "reason", "remediation_count", "sensitivity", "shadow_only",
        "slug", "state", "submitted_by", "submitted_by_label", "thermal_score",
        "transient_retries", "updated_at", "workflow_path",
    },
}

#: PostgREST filter keys that are not columns.
_NOT_COLUMNS = {"select", "order", "limit", "offset", "on_conflict", "and", "or"}


def _table_of(call):
    if not (isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "db"
            and call.func.attr in ("select", "insert", "update", "delete")):
        return None
    if not call.args:
        return None
    first = call.args[0]
    name = first.value if isinstance(first, ast.Constant) else None
    return name if name in SCHEMA else None


def _columns_named(call):
    """Column names this call states literally. Dynamic values are skipped."""
    named = set()
    for arg in call.args[1:]:
        if not isinstance(arg, ast.Dict):
            continue
        for key, value in zip(arg.keys, arg.values):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                continue
            field = key.value
            if field == "select" and isinstance(value, ast.Constant) \
                    and isinstance(value.value, str):
                # "id,slug,note". Anything with "(" or ":" is a PostgREST embed
                # or alias — a related resource, not a column of this table — and
                # splitting one into a bare word invents a column that was never
                # named. Skip those rather than guess.
                for part in value.value.split(","):
                    part = part.strip()
                    if not part or part == "*" or "(" in part or ":" in part:
                        continue
                    named.add(part)
            elif field not in _NOT_COLUMNS:
                named.add(field)
    return named


def _violations():
    out = []
    for path in sorted(glob.glob(os.path.join(RUNNER, "*.py"))):
        name = os.path.basename(path)
        if name.startswith(("test_", "_audit_")):
            continue
        with open(path, errors="replace") as handle:
            source = handle.read()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            table = _table_of(node)
            if not table:
                continue
            unknown = sorted(_columns_named(node) - SCHEMA[table])
            if unknown:
                out.append((name, node.lineno, table, unknown))
    return out


#: Sites that already named a non-existent column when this check was written.
#: Each one is a live HTTP 400 — a query returning nothing, or a write that never
#: lands — so this is a debt list, not an allow-list. Keyed by (file, table,
#: columns) rather than line number so unrelated edits do not churn it. Fix one
#: and delete its entry; the count only goes down.
BASELINE = {
    ("autoscale_signal.py", "tasks", ("finished_at",)),
    ("backlog_batch_processor.py", "tasks", ("status",)),
    ("committees.py", "approvals", ("approver",)),
    ("cx_escalation_sla.py", "approvals", ("materiality",)),
    ("cx_escalation_sla.py", "approvals", ("note",)),
    ("cx_shadow_cade.py", "approvals", ("updated_at",)),
    ("economic_scheduler.py", "tasks", ("economic_score", "lane")),
    ("experiment_router.py", "tasks", ("experiment_id", "experiment_variant")),
    # improvement_miner's intent_key is FIXED — it no longer filters on or writes
    # a column the tasks table does not have. Removed rather than left to rot.
    ("integration_sweeper.py", "tasks", ("verify_attempts",)),
    ("kpi_eval_harness.py", "approvals", ("updated_at",)),
    ("lane_scheduler.py", "tasks", ("lane",)),
    ("parallel_dispatch.py", "tasks", ("result",)),
    ("queue_optimizer.py", "tasks", ("finished_at",)),
    ("realtime_approval_monitor.py", "approvals", ("note",)),
    ("twin_qa.py", "tasks", ("source",)),
    ("voice_mobile.py", "approvals", ("updated_by",)),
    ("work_stealer.py", "tasks", ("runner",)),
}


def test_no_new_call_names_a_column_that_does_not_exist():
    """Ratchet, like convention_lint: the known debt is listed, new debt fails.

    21 sites already named columns that do not exist when this was written. Every
    one is a silent HTTP 400 at runtime. They are recorded rather than fixed here
    because each needs its own judgement — whether the column should be added by
    migration or the query corrected — and a check that fails on 21 pre-existing
    problems is a check somebody deletes.
    """
    new = [row for row in _violations()
           if (row[0], row[2], tuple(row[3])) not in BASELINE]
    assert not new, "NEW columns that do not exist:\n" + "\n".join(
        "  %s:%d  %s -> %s" % row for row in new)


def test_the_baseline_shrinks_and_never_silently_grows():
    """Every baselined site must still exist. Fix one, delete its line."""
    live = {(row[0], row[2], tuple(row[3])) for row in _violations()}
    stale = sorted(BASELINE - live)
    assert not stale, (
        "these are fixed — delete them from BASELINE:\n"
        + "\n".join("  %s  %s -> %s" % row for row in stale))


def test_the_scanner_catches_the_four_real_bugs_it_was_written_for():
    """A checker that cannot fail is not a checker."""
    source = (
        'db.select("tasks", {"select": "id,slug,branch"})\n'
        'db.insert("approvals", {"summary": s, "state": "OPEN"})\n'
        'db.insert("approvals", {"body": b})\n'
        'db.insert("approvals", {"project_id": p, "note": n})\n'
    )
    tree = ast.parse(source)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _table_of(node):
            found.append(sorted(_columns_named(node) - SCHEMA[_table_of(node)]))
    assert found == [["branch"], ["state", "summary"], ["body"],
                     ["note", "project_id"]]


def test_legitimate_shapes_are_not_flagged():
    """Real queries from the codebase must stay clean: filters, embeds, star."""
    source = (
        'db.select("tasks", {"select": "*", "state": "eq.DONE", '
        '"order": "updated_at.desc", "limit": "500"})\n'
        'db.select("tasks", {"select": "id,project:projects(name)"})\n'
        'db.update("controls", {"scope": "global"}, {"paused": False})\n'
    )
    tree = ast.parse(source)
    for node in ast.walk(tree):
        table = _table_of(node) if isinstance(node, ast.Call) else None
        if table:
            assert not (_columns_named(node) - SCHEMA[table])

#!/usr/bin/env python3
"""Every db.insert("approvals", {...}) must write columns the table actually has.

WHY THIS EXISTS
---------------
On 2026-08-30 three call sites were writing columns that do not exist:

  deploy_silence_detector  "summary"/"state"   -> HTTP 400, caught and logged
  preview_canary           "body"              -> HTTP 400, caught and discarded
  fast_auto_merge          "project_id"/"note" -> HTTP 400, NOT caught

The first two silently dropped every alert they raised — deploy_silence_detector
correctly found vigil 18 days without a production deploy and filed nothing. The
third is worse: _create_fast_approval() is called unguarded from
on_test_completion(), so a green test run raised instead of returning a verdict
and the fast-merge gate approved nothing.

None of that was visible. A wrong column name is a runtime 400, and the callers
that swallow it look identical to callers with nothing to say. This test moves
the failure to import time, where it is loud and free.

MAINTENANCE
-----------
COLUMNS mirrors the live `approvals` table. When a migration adds a column, add
it here in the same change; the test failing on a legitimately-new column is the
reminder to do so, and is a one-line fix.
"""
import os
import re
import glob

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COLUMNS = {
    "alternatives", "approvals_required", "auto_exec_ok", "brief_json",
    "brief_status", "cluster_key", "command", "created_at", "decided_at",
    "decided_by", "decision_text", "decision_type", "detail", "draft",
    "draft_cmd", "exec_status", "executable", "id", "kind",
    "legal_risk_level", "prebrief", "process_spawned", "project", "radar_tag",
    "risk", "second_approver", "slug", "status", "title", "value", "why",
}

INSERT = re.compile(r'db\.insert\(\s*["\']approvals["\']\s*,\s*\{')
KEY = re.compile(r'["\']([a-z_]+)["\']\s*:')


def _top_level_keys(src, open_brace):
    """Keys at brace-depth 1 only.

    Several call sites pack extra fields into a nested json.dumps({...}) bound to
    `detail`. Those are payload, not columns. A depth-blind scan reports them as
    violations — it did, on four innocent call sites, before this was written.
    """
    depth = 0
    keys = []
    cursor = open_brace
    while cursor < len(src):
        ch = src[cursor]
        if ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
            if depth == 0:
                break
        elif depth == 1 and ch in "\"'":
            match = KEY.match(src, cursor)
            if match:
                keys.append(match.group(1))
                cursor = match.end() - 1
        cursor += 1
    return keys


def _violations():
    out = []
    for path in sorted(glob.glob(os.path.join(RUNNER, "*.py"))):
        name = os.path.basename(path)
        if name.startswith(("test_", "_audit_")):
            continue
        with open(path, errors="replace") as fh:
            src = fh.read()
        for m in INSERT.finditer(src):
            unknown = sorted(set(_top_level_keys(src, m.end() - 1)) - COLUMNS)
            if unknown:
                out.append((name, src[:m.start()].count("\n") + 1, unknown))
    return out


def test_no_approvals_insert_writes_an_unknown_column():
    bad = _violations()
    assert not bad, "approvals inserts writing non-existent columns:\n" + "\n".join(
        "  %s:%d -> %s" % (f, ln, cols) for f, ln, cols in bad)


def test_fast_auto_merge_card_payload_is_all_real_columns():
    """The static scan reads source; this one reads the dict actually built.

    _create_fast_approval() is called UNGUARDED from on_test_completion(), so a
    rejected payload does not just lose a card — it raises out of a function
    documented to return a verdict, and the fast-merge gate approves nothing.
    Capture the real payload rather than trusting the literal in the file.
    """
    import sys
    sys.path.insert(0, RUNNER)
    import fast_auto_merge

    captured = {}
    real_insert = fast_auto_merge.db.insert
    fast_auto_merge.db.insert = lambda table, row, **kw: captured.update(
        {"table": table, "row": row})
    try:
        fast_auto_merge._create_fast_approval(
            {"slug": "some-task", "project_id": None})
    finally:
        fast_auto_merge.db.insert = real_insert

    assert captured["table"] == "approvals"
    unknown = sorted(set(captured["row"]) - COLUMNS)
    assert not unknown, "payload writes non-existent columns: %s" % unknown
    # The task id must survive somewhere, since it is no longer a column.
    assert "project_id" in captured["row"]["detail"]


def test_detector_finds_a_planted_violation():
    """The check must fail on a bad insert, not just pass on good ones.

    Verifies the parser against the exact shape of the bug it was written for
    (`summary`/`state`) and against a nested json.dumps payload, which must NOT
    be flagged.
    """
    src = (
        'db.insert("approvals", {"kind": "x", "summary": s, "state": "OPEN"})\n'
        'db.insert("approvals", {"kind": "y", "detail": json.dumps('
        '{"note": n, "project_id": p})})\n'
    )
    first = src.index("{", src.index("approvals"))
    assert set(_top_level_keys(src, first)) - COLUMNS == {"summary", "state"}

    second_call = src.index("db.insert", first)
    second = src.index("{", src.index("approvals", second_call))
    assert not set(_top_level_keys(src, second)) - COLUMNS

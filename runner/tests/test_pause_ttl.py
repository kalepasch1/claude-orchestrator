#!/usr/bin/env python3
"""pause_ttl must classify a hold by its stated intent — and must never resume one.

The cases below are the real rows found on 2026-08-30, verbatim, because those are
the ones that fooled everybody: each reads as temporary and none was ever lifted.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pause_ttl  # noqa: E402

NOW = datetime.datetime(2026, 8, 30, 12, 0, 0)

# Ages of the real rows relative to NOW, with a day of slack for clock/tz drift.
APPARENTLY_AGE_DAYS = 22.0
GLOBAL_OUTAGE_AGE_DAYS = 6.0
AGE_TOLERANCE_DAYS = 1.0


def row(scope, project, reason, updated_at, paused=True, by="test"):
    return {"scope": scope, "project": project, "paused": paused,
            "reason": reason, "updated_at": updated_at, "updated_by": by}


LIVE = [
    row("project", "apparently",
        "manual improvement-restart session 2026-08-08: pause runner hold (reversible)",
        "2026-08-08T19:55:21.295875+00:00"),
    row("global", None,
        "executor outage 2026-08-24: every hosted provider is out of credit",
        "2026-08-24T04:16:43.462358+00:00"),
    row("project", "racefeed",
        "controlled fleet verification 2026-08-24: only smoke-test may be claimed. "
        "REVERSIBLE - lifted when the run completes",
        "2026-08-24T03:53:43.355285+00:00"),
]


def test_reversible_language_without_a_ttl_is_unbounded_not_deliberate():
    """'(reversible)' is a promise to come back. 22 days on, that must show."""
    verdict, age, expires = pause_ttl.classify(LIVE[0], NOW)
    assert verdict == pause_ttl.UNBOUNDED
    assert expires is None
    assert abs(age - APPARENTLY_AGE_DAYS) < AGE_TOLERANCE_DAYS


def test_a_plain_reason_older_than_the_review_window_is_flagged():
    verdict, age, _ = pause_ttl.classify(LIVE[1], NOW)
    # 6 days old, no temporary language, no TTL -> a deliberate hold, left alone.
    assert verdict == pause_ttl.DELIBERATE
    assert abs(age - GLOBAL_OUTAGE_AGE_DAYS) < AGE_TOLERANCE_DAYS


def test_ttl_marker_round_trips_and_expires():
    reason = pause_ttl.embed_expiry("load shed for a landing-page push", 2, now=NOW)
    assert pause_ttl.parse_expiry(reason) == NOW + datetime.timedelta(hours=2)

    fresh = row("host", "Mac.lan", reason, NOW.isoformat())
    assert pause_ttl.classify(fresh, NOW)[0] == pause_ttl.WITHIN_TTL
    assert pause_ttl.classify(fresh, NOW + datetime.timedelta(hours=3))[0] == \
        pause_ttl.EXPIRED


def test_embed_expiry_is_idempotent():
    once = pause_ttl.embed_expiry("temporary hold", 4, now=NOW)
    twice = pause_ttl.embed_expiry(once, 4, now=NOW)
    assert once == twice
    assert once.count("[expires") == 1


def test_a_newer_resume_hides_an_older_pause_for_the_same_scope():
    """Latest-decision-wins, matching kill_switch.is_paused().

    Without this, the report would name a pause that is not in effect — and an
    operator who lifts an imaginary hold learns to distrust the whole report.
    """
    rows = [
        row("host", "Mac.lan", "temporary load shed", "2026-08-17T01:00:00+00:00"),
        row("host", "Mac.lan", "resumed by landing-page-push",
            "2026-08-17T03:15:52+00:00", paused=False),
    ]
    assert pause_ttl.stale_pauses(now=NOW, rows=rows) == []


def test_report_lists_every_live_pause_and_counts_the_ones_needing_a_decision():
    text = pause_ttl.report(now=NOW, rows=LIVE)
    assert "apparently" in text and "racefeed" in text
    assert "3 pause(s) in effect" in text
    # apparently + racefeed are UNBOUNDED; the global outage row is DELIBERATE.
    assert "2 of 3 need a decision" in text
    assert "Nothing here resumes on its own" in text


def test_module_never_writes_a_resume():
    """The whole point is that it reports. If it ever learns to write, this fails.

    Parsed, not grepped: the report text tells the operator to run
    `kill_switch.resume(...)` by hand, and a substring check flagged that help
    string as a mutation. Only an actual Call node counts.
    """
    import ast
    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "pause_ttl.py")
    tree = ast.parse(open(path, errors="replace").read())

    forbidden = {("db", "update"), ("db", "insert"), ("db", "delete"),
                 ("kill_switch", "resume"), ("kill_switch", "pause")}
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and isinstance(node.func.value, ast.Name):
            called.add((node.func.value.id, node.func.attr))
    offending = sorted(called & forbidden)
    assert not offending, "pause_ttl must not mutate state: %s" % offending

    # It reads `controls`, so prove the one db call it does make is a select.
    db_calls = {attr for mod, attr in called if mod == "db"}
    assert db_calls <= {"select"}, "unexpected db surface: %s" % sorted(db_calls)

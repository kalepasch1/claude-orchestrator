"""Critical queue alerts must actually be delivered, once per condition per window.

`queue_monitor.detect_alerts` already found prolonged waits, stuck RUNNING tasks and a
stalled queue — and then only wrote them to a log file. These tests pin the delivery
path: criticals go out through notify, warnings do not, a persisting condition pages once
per cooldown, and a failed send is retried rather than silently swallowed.
"""
import json
import os
import sys

import pytest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import queue_monitor as qm  # noqa: E402

CRITICAL = {"severity": "critical", "category": "queue_stalled",
            "message": "Queue stalled: 42 queued, 0 running", "details": {}}
WARNING = {"severity": "warning", "category": "long_wait",
           "message": "7 tasks queued > 4h", "details": []}
STUCK = {"severity": "critical", "category": "stuck_running",
         "message": "3 tasks stuck RUNNING > 2h", "details": []}


def test_fingerprint_ignores_changing_counts():
    a = dict(STUCK, message="3 tasks stuck RUNNING > 2h")
    b = dict(STUCK, message="9 tasks stuck RUNNING > 2h", details=[1, 2])
    assert qm.alert_fingerprint(a) == qm.alert_fingerprint(b)


def test_fingerprint_separates_distinct_conditions():
    assert qm.alert_fingerprint(CRITICAL) != qm.alert_fingerprint(STUCK)


def test_only_critical_severities_are_delivered():
    due, _ = qm.alerts_to_deliver([CRITICAL, WARNING], state={}, now=1000.0)
    assert [a["category"] for a in due] == ["queue_stalled"]


def test_repeated_condition_is_suppressed_inside_the_window():
    due, state = qm.alerts_to_deliver([CRITICAL], state={}, now=1000.0, cooldown_min=60)
    assert len(due) == 1
    again, _ = qm.alerts_to_deliver([CRITICAL], state=state, now=1000.0 + 59 * 60,
                                    cooldown_min=60)
    assert again == []


def test_condition_pages_again_after_the_window():
    _, state = qm.alerts_to_deliver([CRITICAL], state={}, now=1000.0, cooldown_min=60)
    again, _ = qm.alerts_to_deliver([CRITICAL], state=state, now=1000.0 + 61 * 60,
                                    cooldown_min=60)
    assert len(again) == 1


def test_unknown_severity_never_pages():
    weird = {"severity": "banana", "category": "x", "message": "m"}
    due, _ = qm.alerts_to_deliver([weird, None, "not-a-dict"], state={}, now=1.0)
    assert due == []


def test_corrupt_state_does_not_suppress():
    due, _ = qm.alerts_to_deliver([CRITICAL], state={"critical:queue_stalled": "junk"},
                                  now=1000.0)
    assert len(due) == 1, "an unreadable timestamp must not silence an alert"


def test_format_alert_is_readable_and_fail_soft():
    assert "Queue stalled" in qm.format_alert(CRITICAL)
    assert "CRITICAL" in qm.format_alert(CRITICAL)
    assert qm.format_alert(None)
    assert qm.format_alert({"severity": "critical", "category": "c", "message": "  "})


def test_dispatch_sends_and_persists(tmp_path):
    sent = []
    path = str(tmp_path / "alerts.json")
    out = qm.dispatch_alerts([CRITICAL, WARNING], state_path=path, sender=sent.append)
    assert len(out) == 1 and len(sent) == 1
    assert "Queue stalled" in sent[0]
    assert json.loads(open(path).read())


def test_dispatch_is_idempotent_within_the_window(tmp_path):
    sent = []
    path = str(tmp_path / "alerts.json")
    qm.dispatch_alerts([CRITICAL], state_path=path, sender=sent.append)
    qm.dispatch_alerts([CRITICAL], state_path=path, sender=sent.append)
    assert len(sent) == 1, "a persisting condition must not page every run"


def test_failed_send_is_retried_next_run(tmp_path):
    path = str(tmp_path / "alerts.json")

    def failing(_msg):
        raise RuntimeError("slack down")

    assert qm.dispatch_alerts([CRITICAL], state_path=path, sender=failing) == []
    sent = []
    out = qm.dispatch_alerts([CRITICAL], state_path=path, sender=sent.append)
    assert len(out) == 1, "an alert that never left must not be recorded as delivered"


def test_dispatch_never_raises_on_unwritable_state(tmp_path):
    sent = []
    bad_path = str(tmp_path / "nope" / "\0bad" / "alerts.json")
    out = qm.dispatch_alerts([CRITICAL], state_path=bad_path, sender=sent.append)
    assert len(sent) == 1, "delivery must not depend on the bookkeeping file"
    assert out == sent


def test_no_alerts_is_a_noop(tmp_path):
    assert qm.dispatch_alerts([], state_path=str(tmp_path / "a.json"),
                              sender=lambda m: pytest.fail("nothing to send")) == []

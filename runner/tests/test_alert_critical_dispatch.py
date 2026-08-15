#!/usr/bin/env python3
"""A CRITICAL alert has to leave the database.

Slice 3 of the real-time monitoring work was decomposed into "implement critical alert"
(QUARANTINED after 5 attempts), "integrate alert into pipeline" (SUPERSEDED) and "setup
automated alerts" (SUPERSEDED) — so the critical path never landed. What shipped was an
evaluator that writes an `inbox` row and stops there.

An inbox row is a record, not a notification. Nothing pages on it and only someone
already looking at the dashboard ever sees it, which is the fleet's recurring failure
mode in one sentence: "production stopped and NOTHING reported a failure."

These pin the routing and, just as importantly, its limits: warnings must NOT reach the
channel, because a noisy channel gets muted and a muted channel is worse than none.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import alert_rules_engine as engine


def firing(severity="critical", **kw):
    event = {"rule_id": "r1", "name": "Queue stalled", "severity": severity,
             "event": "firing", "metric": "throughput_1h", "value": 0, "threshold": 1}
    event.update(kw)
    return event


class TestCriticalDispatch(unittest.TestCase):
    def test_critical_alert_is_sent(self):
        sent = []
        self.assertTrue(engine.dispatch_critical(firing(), notifier=sent.append))
        self.assertEqual(len(sent), 1)
        self.assertIn("CRITICAL", sent[0])
        self.assertIn("Queue stalled", sent[0])

    def test_the_message_carries_the_number_and_the_threshold(self):
        # "queue stalled" without the value is a page you cannot triage from your phone.
        sent = []
        engine.dispatch_critical(firing(value=0, threshold=1), notifier=sent.append)
        self.assertIn("throughput_1h=0", sent[0])
        self.assertIn("threshold 1", sent[0])

    def test_warnings_and_info_are_not_sent(self):
        for severity in ("warning", "info", "", None):
            with self.subTest(severity=severity):
                sent = []
                self.assertFalse(
                    engine.dispatch_critical(firing(severity=severity), notifier=sent.append))
                self.assertEqual(sent, [])

    def test_severity_match_is_case_insensitive(self):
        sent = []
        self.assertTrue(engine.dispatch_critical(firing(severity="CRITICAL"),
                                                 notifier=sent.append))
        self.assertEqual(len(sent), 1)

    def test_resolved_events_are_not_paged(self):
        # Recovery is good news; it does not need to wake anyone.
        sent = []
        self.assertFalse(engine.dispatch_critical(
            firing(event="resolved"), notifier=sent.append))
        self.assertEqual(sent, [])

    def test_malformed_events_do_not_raise(self):
        for event in (None, {}, {"severity": "critical"}, "not-a-dict"):
            with self.subTest(event=event):
                self.assertFalse(engine.dispatch_critical(event, notifier=lambda _m: None))

    def test_a_broken_notifier_is_reported_not_swallowed(self):
        """Fail-soft, but loud.

        A raising notifier must not break the evaluation loop that produced the alert —
        and must not vanish either, or alerting can be broken for weeks while the board
        stays green.
        """
        def boom(_message):
            raise RuntimeError("slack webhook down")

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertFalse(engine.dispatch_critical(firing(), notifier=boom))
        self.assertIn("critical dispatch failed", stderr.getvalue())


class TestEvaluateRoutesCritical(unittest.TestCase):
    """The integration the SUPERSEDED sub-task was supposed to do."""

    def setUp(self):
        engine._STATE["firing"] = {}

    def test_a_critical_rule_reaches_the_channel_through_evaluate(self):
        sent = []
        original = engine.dispatch_critical
        engine.dispatch_critical = lambda event: sent.append(event) or True
        try:
            events = engine.evaluate(
                rules=[{"id": "queue_stall", "name": "Queue stalled",
                        "metric": "throughput_1h", "operator": "lt", "threshold": 1,
                        "severity": "critical"}],
                metrics={"throughput_1h": 0})
        finally:
            engine.dispatch_critical = original
        self.assertEqual(len(events), 1)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["rule_id"], "queue_stall")

    def test_a_healthy_metric_pages_nobody(self):
        sent = []
        original = engine.dispatch_critical
        engine.dispatch_critical = lambda event: sent.append(event) or True
        try:
            engine.evaluate(
                rules=[{"id": "queue_stall", "name": "Queue stalled",
                        "metric": "throughput_1h", "operator": "lt", "threshold": 1,
                        "severity": "critical"}],
                metrics={"throughput_1h": 42})
        finally:
            engine.dispatch_critical = original
        self.assertEqual(sent, [])

    def test_an_alert_fires_once_not_on_every_evaluation(self):
        # Re-paging every 60s for the same unresolved condition is how a channel gets
        # muted. The firing-state machine already handles this; assert it stays that way.
        rules = [{"id": "queue_stall", "name": "Queue stalled", "metric": "throughput_1h",
                  "operator": "lt", "threshold": 1, "severity": "critical"}]
        sent = []
        original = engine.dispatch_critical
        engine.dispatch_critical = lambda event: sent.append(event) or True
        try:
            engine.evaluate(rules=rules, metrics={"throughput_1h": 0})
            engine.evaluate(rules=rules, metrics={"throughput_1h": 0})
            engine.evaluate(rules=rules, metrics={"throughput_1h": 0})
        finally:
            engine.dispatch_critical = original
        self.assertEqual(len(sent), 1, "a still-firing alert must not re-page")


if __name__ == "__main__":
    unittest.main(verbosity=2)

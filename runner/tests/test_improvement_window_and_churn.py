"""Improvement window + quarantine-remediation churn fixes (2026-09-01).

Context measured from the fleet database, `tomorrow`, 45 days: 384 tasks of kind
`improvement` produced 3 MERGED and 60 QUARANTINED. The quarantine notes were almost all
`semantic-dedupe: 0.98x duplicate of remediate-...`, i.e. quarantine_remediation.py was
regenerating its own output every hour. Three defects made it self-sustaining:

  1. `^remediate-` was not in SKIP_SLUG_PATTERNS, while _normalize_slug strips the prefix,
     so a remediation of a remediation was indistinguishable from a fresh task.
  2. _requeue_task overwrote the child's `note`, destroying the duplicate evidence that
     _is_dupe_note needed to skip it on the next pass.
  3. generator_feedback.should_generate -- the gate written for exactly this -- had no
     callers, and could not see QUARANTINED tasks anyway.
"""
import datetime as dt
import importlib
import os
import sys
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import self_work_gate  # noqa: E402
import quarantine_remediation as qr  # noqa: E402
import generator_feedback as gf  # noqa: E402


class ImprovementWindowTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("ORCH_IMPROVE_WINDOW_ENABLED", None)
        for k in ("ORCH_IMPROVE_WINDOW_START", "ORCH_IMPROVE_WINDOW_END"):
            os.environ.pop(k, None)
        importlib.reload(self_work_gate)

    def test_default_window_is_1am_to_5am(self):
        self.assertEqual(self_work_gate.IMPROVE_WINDOW_START, 1)
        self.assertEqual(self_work_gate.IMPROVE_WINDOW_END, 5)

    def test_inside_and_outside_the_window(self):
        inside = [1, 2, 3, 4]
        outside = [0, 5, 6, 9, 12, 17, 21, 23]
        for h in inside:
            self.assertTrue(
                self_work_gate.in_improvement_window(dt.datetime(2026, 9, 1, h, 30)),
                f"{h:02d}:30 should be inside 01:00-05:00")
        for h in outside:
            self.assertFalse(
                self_work_gate.in_improvement_window(dt.datetime(2026, 9, 1, h, 30)),
                f"{h:02d}:30 should be outside 01:00-05:00")

    def test_boundaries_are_half_open(self):
        self.assertTrue(self_work_gate.in_improvement_window(dt.datetime(2026, 9, 1, 1, 0)))
        self.assertFalse(self_work_gate.in_improvement_window(dt.datetime(2026, 9, 1, 5, 0)))
        self.assertTrue(self_work_gate.in_improvement_window(dt.datetime(2026, 9, 1, 4, 59)))

    def test_window_can_be_disabled(self):
        os.environ["ORCH_IMPROVE_WINDOW_ENABLED"] = "false"
        self.assertTrue(self_work_gate.in_improvement_window(dt.datetime(2026, 9, 1, 13, 0)))

    def test_wraparound_window(self):
        os.environ["ORCH_IMPROVE_WINDOW_START"] = "22"
        os.environ["ORCH_IMPROVE_WINDOW_END"] = "6"
        g = importlib.reload(self_work_gate)
        for h in (22, 23, 0, 3, 5):
            self.assertTrue(g.in_improvement_window(dt.datetime(2026, 9, 1, h, 0)), h)
        for h in (6, 12, 21):
            self.assertFalse(g.in_improvement_window(dt.datetime(2026, 9, 1, h, 0)), h)

    def test_status_reports_the_window(self):
        w = self_work_gate.status()["improvement_window"]
        self.assertEqual((w["start_hour"], w["end_hour"]), (1, 5))
        self.assertTrue(w["enforced"])
        self.assertEqual(w["tz"], "America/New_York")


class GeneratorsRespectWindowTests(unittest.TestCase):
    """The gate must return before any DB or model work happens."""

    def setUp(self):
        self._real = self_work_gate.in_improvement_window
        self_work_gate.in_improvement_window = lambda now=None: False

    def tearDown(self):
        self_work_gate.in_improvement_window = self._real

    def test_quarantine_remediation_returns_early(self):
        out = qr.run()
        self.assertTrue(out.get("window_closed"), f"expected early return, got {out!r}")
        self.assertEqual(out.get("requeued"), 0)

    def test_improvement_miner_returns_early(self):
        import improvement_miner
        out = improvement_miner.run()
        self.assertTrue(out.get("window_closed"), f"expected early return, got {out!r}")
        self.assertEqual(out.get("queued"), 0)


class RemediationChurnTests(unittest.TestCase):
    def test_remediate_slugs_are_skipped(self):
        """A remediation of a remediation is the treadmill."""
        self.assertTrue(qr._is_skip_slug("remediate-cade-tribunal-counterparty-a1b2c3"))
        self.assertTrue(qr._is_skip_slug("remediate-ms-ecp-qualification-wizard"))

    def test_real_work_is_still_eligible(self):
        for slug in ("build-payment-flow", "bugfix-null-deref-in-router",
                     "improvement-cache-the-route-table"):
            self.assertFalse(qr._is_skip_slug(slug), slug)

    def test_normalize_still_strips_the_prefix(self):
        self.assertEqual(qr._normalize_slug("remediate-foo-bar-a1b2c3d4"), "foo-bar")

    def test_dupe_notes_are_recognised(self):
        for note in ("semantic-dedupe: 0.988 duplicate of remediate-cade-tribunal",
                     "GC: queue-bankruptcy: duplicate of remediate-ms-ecp (fp=4170a04b)"):
            self.assertTrue(qr._is_dupe_note(note), note)

    def test_feedback_gate_is_on_by_default(self):
        self.assertTrue(qr._FEEDBACK_GATE)

    def test_requeue_consults_the_feedback_gate(self):
        """The whole point: no insert when the gate says no."""
        calls = {"insert": 0, "gate": 0}

        def fake_should_generate(prompt, project_name="", kind="feature", project_id=""):
            calls["gate"] += 1
            return {"generate": False, "reason": "similar to recent QUARANTINED task (sim=98%)",
                    "similar_to": "remediate-cade-tribunal"}

        real_gate, real_insert = gf.should_generate, qr.db.insert
        gf.should_generate = fake_should_generate
        qr.db.insert = lambda *a, **k: calls.__setitem__("insert", calls["insert"] + 1)
        try:
            ok = qr._requeue_task(
                {"slug": "cade-tribunal-counterparty", "prompt": "x" * 80,
                 "project_id": "p1", "kind": "improvement", "note": ""}, "testfail")
        finally:
            gf.should_generate, qr.db.insert = real_gate, real_insert

        self.assertFalse(ok)
        self.assertEqual(calls["gate"], 1, "the feedback gate was never consulted")
        self.assertEqual(calls["insert"], 0, "a duplicate was inserted despite the gate")

    def test_requeue_preserves_parent_dupe_evidence(self):
        captured = {}

        real_gate, real_insert = gf.should_generate, qr.db.insert
        gf.should_generate = lambda *a, **k: {"generate": True, "reason": "ok"}
        qr.db.insert = lambda table, row: captured.update(row)
        try:
            qr._requeue_task(
                {"slug": "cade-tribunal", "prompt": "y" * 80, "project_id": "p1",
                 "kind": "improvement",
                 "note": "semantic-dedupe: 0.988 duplicate of remediate-cade-tribunal"},
                "testfail")
        finally:
            gf.should_generate, qr.db.insert = real_gate, real_insert

        self.assertIn("parent-note", captured.get("note", ""),
                      "the child lost its parent's duplicate evidence, so _is_dupe_note "
                      "cannot fire on the next pass -- this is the churn bug")
        self.assertIn("duplicate of", captured["note"])


class GeneratorFeedbackScopeTests(unittest.TestCase):
    def test_quarantined_is_in_the_failure_filter(self):
        captured = {}
        real = gf.db.select

        def fake_select(table, params):
            if table == "tasks" and "state" in params:
                captured["state"] = params["state"]
            return []

        gf.db.select = fake_select
        try:
            gf._recent_failures(project_id="p1")
        finally:
            gf.db.select = real
        self.assertIn("QUARANTINED", captured.get("state", ""),
                      "the gate cannot see the state most improvement tasks die in")

    def test_project_id_skips_the_name_lookup(self):
        seen = []
        real = gf.db.select
        gf.db.select = lambda table, params: seen.append(table) or []
        try:
            gf._recent_failures(project_id="p1")
        finally:
            gf.db.select = real
        self.assertNotIn("projects", seen, "project_id should avoid the extra lookup")


if __name__ == "__main__":
    unittest.main()

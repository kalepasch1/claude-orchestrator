"""Contract: operator-submitted work is NEVER refused by throughput admission control.

THE BUG THIS PINS (fixed 2026-08-04). db.insert("tasks", ...) had three gates that each
returned None with no durable record: the queue-depth cap, release back-pressure, and the
prompt gate. None of them exempted operator-origin work. In the measured state (2,181
QUEUED against an 800 ceiling; all six priority projects release-RED) the ONLY tasks that
could still enter the queue were the fleet's own repair prefixes — so every improvement the
operator submitted was silently discarded at the door for ~120 days, while the fleet
continued to report progress on its own churn.

Two invariants:
  1. operator-origin tasks bypass the throughput gates entirely;
  2. anything refused is RECORDED (admission_rejections), never silently dropped.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402


class OperatorOriginDetection(unittest.TestCase):
    def test_dropbox_slug_is_operator(self):
        self.assertTrue(db._is_operator_origin({"slug": "dropbox-apparently-treasury-tab"}))

    def test_submitted_by_is_operator(self):
        """A real submitted_by is evidence. A label is a claim -- see below."""
        self.assertTrue(db._is_operator_origin(
            {"slug": "backlog-batch-x", "submitted_by": "kalepasch@gmail.com"}))

    def test_a_self_written_label_is_not_operator(self):
        """CHANGED 2026-09-02. This file used to assert that submitted_by_label alone
        conferred operator status. submitted_by is a field the database fills in for a
        real submitter; submitted_by_label is free text the CALLER writes about itself,
        and operator status bypasses the recovery-depth cap, release back-pressure and
        producer admission.

        Measured over 30 days: of 5,224 tasks, ONE carried a real submitted_by, 1,847
        carried only a self-written label, and 1,642 of those put the word "operator" in
        it. Forty-seven distinct labels were doing this.

        The operator's OWN work is unaffected, and that is checkable rather than hoped
        for -- every one of her intakes carries the drop-box slug prefix as well:

            kale@smrter.us (operator) via Cowork strategy session   18 tasks, 18 dropbox
            kalepasch@gmail.com (operator decision 2026-08-04)      15 tasks, 15 dropbox
            operator-dropbox-p0                                     10 tasks, 10 dropbox

        while the machine producers carry none:

            ChatGPT local-build audit (operator-directed)         1,543 tasks,  0 dropbox
            Codex operator-directed remediation                     14 tasks,  0 dropbox
        """
        self.assertFalse(db._is_operator_origin(
            {"slug": "backlog-batch-x", "submitted_by_label": "kalepasch@gmail.com"}))
        self.assertFalse(db._is_operator_origin(
            {"slug": "chatgpt-local-reconcile-x",
             "submitted_by_label": "ChatGPT local-build audit (operator-directed)"}))

    def test_the_operators_real_intake_path_is_untouched(self):
        """Every genuine operator submission measured on this fleet also has this prefix."""
        self.assertTrue(db._is_operator_origin(
            {"slug": "dropbox-apparently-treasury-tab",
             "submitted_by_label": "kale@smrter.us (operator) via Cowork strategy session"}))

    def test_a_label_can_be_trusted_explicitly(self):
        """The escape hatch: name one label, not all of them."""
        prev = os.environ.get("ORCH_TRUSTED_SUBMITTER_LABELS")
        os.environ["ORCH_TRUSTED_SUBMITTER_LABELS"] = "my batch intake"
        try:
            self.assertTrue(db._is_operator_origin(
                {"slug": "backlog-batch-x", "submitted_by_label": "My Batch Intake"}))
            self.assertFalse(db._is_operator_origin(
                {"slug": "backlog-batch-x", "submitted_by_label": "some other vendor"}))
        finally:
            if prev is None:
                os.environ.pop("ORCH_TRUSTED_SUBMITTER_LABELS", None)
            else:
                os.environ["ORCH_TRUSTED_SUBMITTER_LABELS"] = prev

    def test_machine_slugs_are_not_operator(self):
        for slug in ("improve-mesh-thing", "relfix-y", "canary-z", "recover-missing-branch-q",
                     "backlog-batch-apparently-0d157dd", "qafix-smarter-123"):
            self.assertFalse(db._is_operator_origin({"slug": slug}), slug)

    def test_blank_submitter_is_not_operator(self):
        self.assertFalse(db._is_operator_origin({"slug": "canary-z", "submitted_by": "   "}))

    def test_non_dict_is_safe(self):
        self.assertFalse(db._is_operator_origin(None))


class QueueDepthGate(unittest.TestCase):
    def setUp(self):
        self._saved = dict(db._QUEUE_DEPTH_CACHE)
        self._env = os.environ.get("ORCH_MAX_QUEUE_DEPTH")
        os.environ["ORCH_MAX_QUEUE_DEPTH"] = "800"
        # Pin the cache far in the future so the gate never queries the DB in tests.
        db._QUEUE_DEPTH_CACHE.update({"at": 9e18, "depth": 99999})

    def tearDown(self):
        db._QUEUE_DEPTH_CACHE.clear()
        db._QUEUE_DEPTH_CACHE.update(self._saved)
        if self._env is None:
            os.environ.pop("ORCH_MAX_QUEUE_DEPTH", None)
        else:
            os.environ["ORCH_MAX_QUEUE_DEPTH"] = self._env

    def test_operator_task_admitted_far_over_ceiling(self):
        self.assertFalse(db._queue_depth_block({"slug": "dropbox-apparently-harvey-parity"}))

    def test_attributed_task_admitted_far_over_ceiling(self):
        self.assertFalse(db._queue_depth_block(
            {"slug": "vigil-absorption-phase-b", "submitted_by": "kalepasch@gmail.com"}))

    def test_machine_task_still_capped(self):
        self.assertTrue(db._queue_depth_block({"slug": "improve-some-churn"}))

    def test_release_fix_prefixes_still_exempt(self):
        self.assertFalse(db._queue_depth_block({"slug": "relfix-tomorrow-build"}))


class RefusalIsRecorded(unittest.TestCase):
    """A refusal must always produce a record — silence is what hid this for 120 days."""

    def setUp(self):
        self.calls = []
        self._real_req = db._req
        db._req = lambda method, path, **kw: self.calls.append((method, path, kw.get("body")))
        db._REFUSAL_LOGGED.clear()

    def tearDown(self):
        db._req = self._real_req
        db._REFUSAL_LOGGED.clear()

    def test_operator_refusal_always_recorded(self):
        db._record_refusal({"slug": "dropbox-x", "submitted_by": "kalepasch@gmail.com"},
                           "queue_depth", "over ceiling")
        self.assertEqual(len(self.calls), 1)
        method, path, body = self.calls[0]
        self.assertEqual(method, "POST")
        self.assertIn("admission_rejections", path)
        self.assertTrue(body["operator_origin"])
        self.assertEqual(body["gate"], "queue_depth")

    def test_operator_refusals_are_not_rate_limited(self):
        for _ in range(3):
            db._record_refusal({"slug": "dropbox-x"}, "queue_depth", "over ceiling")
        self.assertEqual(len(self.calls), 3, "operator refusals must never be suppressed")

    def test_machine_refusals_are_rate_limited_but_not_silent(self):
        for _ in range(5):
            db._record_refusal({"slug": "improve-churn"}, "queue_depth", "over ceiling")
        self.assertEqual(len(self.calls), 1, "machine churn records one summary per window")
        self.assertFalse(self.calls[0][2]["operator_origin"])


if __name__ == "__main__":
    unittest.main()

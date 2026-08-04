#!/usr/bin/env python3
"""Wave-0 operator review gate (review-gate spec item 1): release_train must stop
at a pending kind='release' approval card and promote only after approval.
Also covers: card creation + ready-for-review notification (item 2) and the
attributed steering_events write on decision observation (item 4)."""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import release_train
import steering


class FakeDB:
    def __init__(self, cards=None, steering_rows=None):
        self.cards = list(cards or [])
        self.steering_rows = list(steering_rows or [])
        self.inserted = []

    def select(self, table, params=None):
        if table == "approvals":
            return list(self.cards)
        if table == "steering_events":
            return list(self.steering_rows)
        return []

    def insert(self, table, row, upsert=False):
        self.inserted.append((table, dict(row)))
        if table == "approvals":
            return {**row, "id": "card-new"}
        return row

    def update(self, table, match, patch):
        return patch


class FakeNotify:
    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)


class GateTestBase(unittest.TestCase):
    def setUp(self):
        self._db, self._sdb = release_train.db, steering.db
        self._notify = sys.modules.get("notify")
        self.fake = FakeDB()
        release_train.db = self.fake
        steering.db = self.fake
        self.fake_notify = FakeNotify()
        sys.modules["notify"] = self.fake_notify
        os.environ.pop("ORCH_RELEASE_AUTOPROMOTE", None)
        self.p = {"vercel_project": "web"}

    def tearDown(self):
        release_train.db = self._db
        steering.db = self._sdb
        if self._notify is not None:
            sys.modules["notify"] = self._notify
        else:
            sys.modules.pop("notify", None)
        os.environ.pop("ORCH_RELEASE_AUTOPROMOTE", None)

    def gate(self):
        return release_train._release_approval_gate(
            self.p, "beethoven", "/nonexistent-repo", "master",
            "base-sha-000", "staging-sha-111", 12, qa_note="qa green")


class TestReleaseApprovalGate(GateTestBase):
    def test_no_card_files_card_and_notifies_and_holds(self):
        res = self.gate()
        self.assertIsNotNone(res)
        self.assertEqual(res.get("gate"), "release-approval")
        cards = [r for t, r in self.fake.inserted if t == "approvals"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["kind"], "release")
        self.assertEqual(cards[0]["slug"],
                         release_train._release_gate_slug("beethoven", "staging-sha-111"))
        notes = [r for t, r in self.fake.inserted if t == "notifications"]
        self.assertEqual(len(notes), 2)  # email + smarter mirror
        self.assertEqual({n["channel"] for n in notes}, {"email", "smarter"})
        self.assertTrue(all(n["approval_id"] == "card-new" for n in notes))
        self.assertTrue(self.fake_notify.sent, "direct notify ping expected")

    def test_pending_card_holds_without_refiling(self):
        self.fake.cards = [{"id": "c1", "status": "pending", "slug": "release:beethoven:staging-sha-1"}]
        res = self.gate()
        self.assertIsNotNone(res)
        self.assertIn("awaiting operator", res.get("note", ""))
        self.assertFalse([r for t, r in self.fake.inserted if t == "approvals"])
        self.assertFalse([r for t, r in self.fake.inserted if t == "notifications"])

    def test_approved_card_promotes_and_records_steering(self):
        self.fake.cards = [{"id": "c1", "status": "approved", "decided_by": "kalepasch@gmail.com",
                            "slug": "release:beethoven:staging-sha-1"}]
        res = self.gate()
        self.assertIsNone(res)  # None == proceed with promotion
        rows = [r for t, r in self.fake.inserted if t == "steering_events"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_type"], "release_decision")
        self.assertEqual(rows[0]["actor_label"], "kalepasch@gmail.com")
        self.assertEqual(rows[0]["payload"]["decision"], "approved")

    def test_denied_card_requeues_batch_without_losing_state(self):
        self.fake.cards = [{"id": "c1", "status": "denied", "decided_by": "kalepasch@gmail.com",
                            "slug": "release:beethoven:staging-sha-1"}]
        res = self.gate()
        self.assertIsNotNone(res)
        self.assertIn("denied", res.get("note", ""))
        # nothing destructive: no new card for the same staging SHA
        self.assertFalse([r for t, r in self.fake.inserted if t == "approvals"])
        rows = [r for t, r in self.fake.inserted if t == "steering_events"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["payload"]["decision"], "denied")

    def test_steering_write_is_deduped_across_cycles(self):
        self.fake.cards = [{"id": "c1", "status": "approved", "decided_by": "op",
                            "slug": "release:beethoven:staging-sha-1"}]
        self.fake.steering_rows = [{"id": "existing"}]  # a row already exists for this card
        res = self.gate()
        self.assertIsNone(res)
        self.assertFalse([r for t, r in self.fake.inserted if t == "steering_events"])

    def test_autopromote_escape_hatch_bypasses_gate(self):
        os.environ["ORCH_RELEASE_AUTOPROMOTE"] = "true"
        res = self.gate()
        self.assertIsNone(res)
        self.assertFalse(self.fake.inserted)


if __name__ == "__main__":
    unittest.main()

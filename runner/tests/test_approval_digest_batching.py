"""
test_approval_digest_batching.py - tests for approval digest batching feature.

Tests verify:
1. Only kind=legal with legal_risk_level=novel send immediately
2. Other approvals batch to daily digest
3. Digest includes 3-line portfolio summary
4. Notifications are marked sent after digest
5. Unsent notifications are included in digest
"""
import os, sys, unittest, datetime, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockDB:
    """Mock database for testing without hitting Supabase."""

    def __init__(self):
        self.data = {
            "approvals": [],
            "notifications": [],
            "tasks": [],
            "projects": [],
            "v_project_health": [],
            "v_action_inbox": [],
            "v_spend_mtd": [],
        }
        self.select_calls = []
        self.insert_calls = []
        self.update_calls = []

    def select(self, table, params=None):
        self.select_calls.append((table, params))
        return list(self.data.get(table, []))

    def insert(self, table, row, upsert=False):
        self.data.setdefault(table, []).append(row)
        self.insert_calls.append((table, row))

    def update(self, table, match, patch):
        self.update_calls.append((table, match, patch))
        for row in self.data.get(table, []):
            match_ok = all(row.get(k) == v for k, v in match.items())
            if match_ok:
                row.update(patch)


class TestApprovalPushBatching(unittest.TestCase):
    """Tests for approval_push.py batching logic."""

    def setUp(self):
        self.mock_db = MockDB()
        import db
        self.orig_select = db.select
        self.orig_insert = db.insert
        db.select = self.mock_db.select
        db.insert = self.mock_db.insert

    def tearDown(self):
        import db
        db.select = self.orig_select
        db.insert = self.orig_insert

    def test_novel_legal_sends_immediately(self):
        """kind=legal with legal_risk_level=novel should have sent=True."""
        import approval_push

        # Set up a novel legal approval
        self.mock_db.data["approvals"] = [
            {
                "id": "legal-novel-1",
                "kind": "legal",
                "legal_risk_level": "novel",
                "project": "test-proj",
                "title": "IP agreement review",
                "why": "Third-party IP license terms"
            }
        ]
        approval_push.run(limit=10)

        # Check that a notification was inserted with sent=True
        email_notifs = [n for n in self.mock_db.data["notifications"] if n.get("channel") == "email"]
        self.assertEqual(len(email_notifs), 1, "should insert exactly one email notification")
        self.assertTrue(email_notifs[0]["sent"], "novel legal should be sent immediately")

    def test_routine_legal_skipped(self):
        """kind=legal with legal_risk_level=routine should be skipped."""
        import approval_push

        self.mock_db.data["approvals"] = [
            {
                "id": "legal-routine-1",
                "kind": "legal",
                "legal_risk_level": "routine",
                "project": "test-proj",
                "title": "NDA renewal",
                "why": "Standard vendor NDA"
            }
        ]
        approval_push.run(limit=10)

        # Routine legal should not create a notification
        notifs = self.mock_db.data["notifications"]
        self.assertEqual(len(notifs), 0, "routine legal should be skipped, no notification created")

    def test_material_batches(self):
        """kind=material should batch (sent=False)."""
        import approval_push

        self.mock_db.data["approvals"] = [
            {
                "id": "material-1",
                "kind": "material",
                "legal_risk_level": None,
                "project": "test-proj",
                "title": "Pricing model change",
                "why": "Introduce tiered pricing"
            }
        ]
        approval_push.run(limit=10)

        email_notifs = [n for n in self.mock_db.data["notifications"] if n.get("channel") == "email"]
        self.assertEqual(len(email_notifs), 1)
        self.assertFalse(email_notifs[0]["sent"], "material should batch (sent=False)")

    def test_secret_batches(self):
        """kind=secret should batch (sent=False)."""
        import approval_push

        self.mock_db.data["approvals"] = [
            {
                "id": "secret-1",
                "kind": "secret",
                "legal_risk_level": None,
                "project": "test-proj",
                "title": "Deploy secret",
                "why": "New API credentials"
            }
        ]
        approval_push.run(limit=10)

        email_notifs = [n for n in self.mock_db.data["notifications"] if n.get("channel") == "email"]
        self.assertFalse(email_notifs[0]["sent"], "secret should batch")

    def test_operator_batches(self):
        """kind=operator should batch (sent=False)."""
        import approval_push

        self.mock_db.data["approvals"] = [
            {
                "id": "op-1",
                "kind": "operator",
                "legal_risk_level": None,
                "project": "test-proj",
                "title": "Restart service",
                "why": "Performance degradation"
            }
        ]
        approval_push.run(limit=10)

        email_notifs = [n for n in self.mock_db.data["notifications"] if n.get("channel") == "email"]
        self.assertFalse(email_notifs[0]["sent"], "operator should batch")

    def test_legal_with_non_novel_risk_batches(self):
        """kind=legal with legal_risk_level != novel should batch."""
        import approval_push

        self.mock_db.data["approvals"] = [
            {
                "id": "legal-low-1",
                "kind": "legal",
                "legal_risk_level": "low",
                "project": "test-proj",
                "title": "Terms update",
                "why": "Minor clarification"
            }
        ]
        approval_push.run(limit=10)

        email_notifs = [n for n in self.mock_db.data["notifications"] if n.get("channel") == "email"]
        self.assertEqual(len(email_notifs), 1)
        self.assertFalse(email_notifs[0]["sent"], "non-novel legal should batch")

    def test_dedup_prevents_duplicate_notifications(self):
        """Should not create duplicate notifications for same approval."""
        import approval_push

        self.mock_db.data["approvals"] = [
            {
                "id": "legal-novel-1",
                "kind": "legal",
                "legal_risk_level": "novel",
                "project": "test-proj",
                "title": "IP agreement",
                "why": "Third-party license"
            }
        ]
        # First run
        approval_push.run(limit=10)
        first_run_notifs = len(self.mock_db.data["notifications"])

        # Second run (same approval)
        approval_push.run(limit=10)
        second_run_notifs = len(self.mock_db.data["notifications"])

        # Should not have added new notifications
        self.assertEqual(second_run_notifs, first_run_notifs,
                        "should not create duplicate notifications")


class TestDigestBatching(unittest.TestCase):
    """Tests for digest.py digest building and batching."""

    def setUp(self):
        self.mock_db = MockDB()
        import db, health
        self.orig_db_select = db.select
        self.orig_db_update = db.update
        self.orig_health_summary = health.summary
        self.orig_health_inbox = health.inbox

        db.select = self.mock_db.select
        db.update = self.mock_db.update
        health.summary = lambda: {
            "projects": 5,
            "avg_health": 82.5,
            "inbox_count": 3,
            "needs_attention": [
                {"project": "api", "score": 60, "blocked": 2, "approvals": 1},
                {"project": "web", "score": 70, "blocked": 1, "approvals": 0}
            ]
        }
        health.inbox = lambda: [
            {"label": "Deploy blocked", "detail": "waiting for approval"},
            {"label": "Bug critical", "detail": "production issue"}
        ]

    def tearDown(self):
        import db, health
        db.select = self.orig_db_select
        db.update = self.orig_db_update
        health.summary = self.orig_health_summary
        health.inbox = self.orig_health_inbox

    def test_portfolio_summary_3_lines(self):
        """Portfolio summary should be 3 lines."""
        import digest

        summary = digest._portfolio_summary()
        self.assertEqual(len(summary), 3, "portfolio summary should be exactly 3 lines")
        self.assertIn("Portfolio Health", summary[0])
        self.assertIn("Bottlenecks", summary[1])
        self.assertIn("Action items", summary[2])

    def test_digest_includes_unsent_notifications(self):
        """Digest should include unsent email notifications from last 24h."""
        import digest

        now = datetime.datetime.utcnow()
        self.mock_db.data["notifications"] = [
            {
                "id": "notif-1",
                "title": "Decision: IP agreement review",
                "body": "[proj] Third-party license",
                "approval_id": "a-1",
                "kind": "decision",
                "channel": "email",
                "sent": False,
                "created_at": now.isoformat()
            },
            {
                "id": "notif-2",
                "title": "Action: Deploy API",
                "body": "[api] New service version",
                "approval_id": "a-2",
                "kind": "action",
                "channel": "email",
                "sent": False,
                "created_at": now.isoformat()
            },
            {
                "id": "notif-3",
                "title": "Decision: Already sent",
                "body": "[proj] Old decision",
                "approval_id": "a-3",
                "kind": "decision",
                "channel": "email",
                "sent": True,
                "created_at": now.isoformat()
            }
        ]

        msg, notif_ids = digest.build()
        self.assertIn("IP agreement review", msg, "should include unsent decision")
        self.assertIn("Deploy API", msg, "should include unsent action")
        self.assertEqual(len(notif_ids), 2, "should return 2 unsent notification IDs")
        self.assertNotIn("Already sent", msg, "should not include already-sent notifications")

    def test_digest_marks_sent_after_building(self):
        """Digest.send() should mark notifications as sent."""
        import digest

        now = datetime.datetime.utcnow()
        self.mock_db.data["notifications"] = [
            {
                "id": "notif-1",
                "title": "Decision: IP agreement",
                "body": "[proj] License",
                "approval_id": "a-1",
                "kind": "decision",
                "channel": "email",
                "sent": False,
                "created_at": now.isoformat()
            }
        ]

        msg, notif_ids = digest.build()
        digest._mark_sent(notif_ids)

        # Verify update was called
        self.assertTrue(any("notifications" in call[0] for call in self.mock_db.update_calls),
                       "should call db.update on notifications")

    def test_digest_includes_portfolio_summary_first(self):
        """Digest message should start with portfolio summary."""
        import digest

        msg, _ = digest.build()
        lines = msg.split("\n")
        # First 3 lines should be portfolio summary
        self.assertIn("Portfolio Health", lines[0])
        self.assertIn("Bottlenecks", lines[1])
        self.assertIn("Action items", lines[2])

    def test_digest_includes_shipped_needs_spend(self):
        """Digest should include shipped, needs, and spend sections."""
        import digest

        self.mock_db.data["tasks"] = [
            {"slug": "feature-x", "state": "MERGED"}
        ]
        self.mock_db.data["v_spend_mtd"] = [
            {"project": "api", "spent": 250.50}
        ]

        msg, _ = digest.build()
        self.assertIn("Shipped", msg)
        self.assertIn("Needs you", msg)
        self.assertIn("Spend MTD", msg)

    def test_digest_hour_check(self):
        """should_run() should return True only at configured hour."""
        import digest
        from unittest.mock import patch

        # Mock datetime to a specific hour
        with patch("digest.datetime") as mock_dt:
            mock_dt.datetime.utcnow.return_value.hour = 7
            os.environ["DIGEST_HOUR"] = "07"
            self.assertTrue(digest.should_run(), "should run at 07:00")

            mock_dt.datetime.utcnow.return_value.hour = 8
            self.assertFalse(digest.should_run(), "should not run at 08:00")

    def test_digest_hour_default_07(self):
        """DIGEST_HOUR should default to 07."""
        import digest
        from unittest.mock import patch

        if "DIGEST_HOUR" in os.environ:
            del os.environ["DIGEST_HOUR"]

        with patch("digest.datetime") as mock_dt:
            mock_dt.datetime.utcnow.return_value.hour = 7
            # Default should be 07
            self.assertTrue(digest.should_run(), "default DIGEST_HOUR should be 07")


class TestShouldSendImmediately(unittest.TestCase):
    """Tests for _should_send_immediately helper function."""

    def test_novel_legal_returns_true(self):
        """kind=legal + legal_risk_level=novel should return True."""
        import approval_push

        approval = {
            "kind": "legal",
            "legal_risk_level": "novel",
            "id": "a-1"
        }
        self.assertTrue(approval_push._should_send_immediately(approval))

    def test_routine_legal_returns_false(self):
        """kind=legal + legal_risk_level=routine should return False."""
        import approval_push

        approval = {
            "kind": "legal",
            "legal_risk_level": "routine",
            "id": "a-1"
        }
        self.assertFalse(approval_push._should_send_immediately(approval))

    def test_material_returns_false(self):
        """kind=material should return False."""
        import approval_push

        approval = {
            "kind": "material",
            "legal_risk_level": None,
            "id": "a-1"
        }
        self.assertFalse(approval_push._should_send_immediately(approval))

    def test_secret_returns_false(self):
        """kind=secret should return False."""
        import approval_push

        approval = {
            "kind": "secret",
            "legal_risk_level": None,
            "id": "a-1"
        }
        self.assertFalse(approval_push._should_send_immediately(approval))

    def test_operator_returns_false(self):
        """kind=operator should return False."""
        import approval_push

        approval = {
            "kind": "operator",
            "legal_risk_level": None,
            "id": "a-1"
        }
        self.assertFalse(approval_push._should_send_immediately(approval))


if __name__ == "__main__":
    unittest.main(verbosity=2)

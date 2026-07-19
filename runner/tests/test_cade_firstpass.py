"""
test_cade_firstpass.py - Tests for CADE first-pass health report emailer.
Covers: complete report health email, broken report alert, deduplication,
regression re-alert, stats output, and feature flag disable.
"""
import os, sys, json, unittest
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_complete_report(report_id="rpt-1"):
    return {
        "id": report_id,
        "complete": True,
        "created_at": "2026-07-16T00:00:00Z",
        "first_result": {"domain": "finance", "brier": 0.12, "correct": True},
        "stages": {
            "ingest": {"status": "ok"},
            "score": {"status": "ok"},
            "rank": {"status": "ok"},
        },
        "domains": {
            "finance": {"accuracy": 0.91, "tier": "A"},
            "tech": {"accuracy": 0.85, "tier": "B"},
        },
        "top_experts": [
            {"name": "expert-1", "score": 0.95},
            {"name": "expert-2", "score": 0.88},
        ],
    }


def _make_broken_report(report_id="rpt-2"):
    return {
        "id": report_id,
        "complete": False,
        "created_at": "2026-07-16T01:00:00Z",
        "stages": {
            "ingest": {"status": "ok"},
            "score": {"status": "failed", "error": "timeout contacting scorer"},
            "rank": {"status": "missing"},
        },
        "domains": {},
        "top_experts": [],
    }


class FakeDB:
    """In-memory fake for db module with select/upsert."""
    def __init__(self):
        self._store = {}

    def select(self, table, params=None):
        key = params.get("key", "").replace("eq.", "") if params and "key" in params else table
        if key in self._store:
            return [{"value": json.dumps(self._store[key])}]
        if table == "cade_pass_reports":
            return self._store.get("_reports", [])
        return []

    def upsert(self, table, row):
        if isinstance(row, dict) and "key" in row:
            v = row["value"]
            self._store[row["key"]] = json.loads(v) if isinstance(v, str) else v

    def set_report(self, report):
        self._store["_reports"] = [report] if report else []


class TestCompleteReportTriggersHealthEmail(unittest.TestCase):
    @patch("cade_firstpass.notify")
    def test_complete_sends_health(self, mock_notify):
        import cade_firstpass
        fake = FakeDB()
        fake.set_report(_make_complete_report())
        result = cade_firstpass.check_firstpass(db_client=fake)
        self.assertEqual(result["status"], "sent_health")
        mock_notify.send.assert_called_once()
        msg = mock_notify.send.call_args[0][0]
        self.assertIn("Operational", msg)
        self.assertIn("finance", msg)
        self.assertIn("0.12", msg)


class TestBrokenReportTriggersAlert(unittest.TestCase):
    @patch("cade_firstpass.notify")
    def test_broken_sends_alert(self, mock_notify):
        import cade_firstpass
        fake = FakeDB()
        fake.set_report(_make_broken_report())
        result = cade_firstpass.check_firstpass(db_client=fake)
        self.assertEqual(result["status"], "sent_alert")
        self.assertTrue(len(result["failures"]) > 0)
        mock_notify.send.assert_called_once()
        msg = mock_notify.send.call_args[0][0]
        self.assertIn("NOT OPERATIONAL", msg)


class TestDeduplication(unittest.TestCase):
    @patch("cade_firstpass.notify")
    def test_second_call_no_resend(self, mock_notify):
        import cade_firstpass
        fake = FakeDB()
        fake.set_report(_make_complete_report("rpt-dedup"))
        r1 = cade_firstpass.check_firstpass(db_client=fake)
        self.assertEqual(r1["status"], "sent_health")
        mock_notify.send.reset_mock()

        r2 = cade_firstpass.check_firstpass(db_client=fake)
        self.assertEqual(r2["status"], "dedup_skip")
        mock_notify.send.assert_not_called()

    @patch("cade_firstpass.notify")
    def test_alert_dedup(self, mock_notify):
        import cade_firstpass
        fake = FakeDB()
        fake.set_report(_make_broken_report("rpt-alert-dedup"))
        r1 = cade_firstpass.check_firstpass(db_client=fake)
        self.assertEqual(r1["status"], "sent_alert")
        mock_notify.send.reset_mock()

        r2 = cade_firstpass.check_firstpass(db_client=fake)
        self.assertEqual(r2["status"], "dedup_skip")
        mock_notify.send.assert_not_called()


class TestRegressionReAlert(unittest.TestCase):
    @patch("cade_firstpass.notify")
    def test_healthy_then_broken_realerts(self, mock_notify):
        import cade_firstpass
        fake = FakeDB()
        # First: healthy
        fake.set_report(_make_complete_report("rpt-h"))
        r1 = cade_firstpass.check_firstpass(db_client=fake)
        self.assertEqual(r1["status"], "sent_health")
        mock_notify.send.reset_mock()

        # Second: broken (different report)
        fake.set_report(_make_broken_report("rpt-b"))
        r2 = cade_firstpass.check_firstpass(db_client=fake)
        self.assertEqual(r2["status"], "sent_alert")
        mock_notify.send.assert_called_once()
        msg = mock_notify.send.call_args[0][0]
        self.assertIn("REGRESSION", msg)

    @patch("cade_firstpass.notify")
    def test_broken_then_healthy_recovery(self, mock_notify):
        import cade_firstpass
        fake = FakeDB()
        fake.set_report(_make_broken_report("rpt-b2"))
        cade_firstpass.check_firstpass(db_client=fake)
        mock_notify.send.reset_mock()

        fake.set_report(_make_complete_report("rpt-h2"))
        r2 = cade_firstpass.check_firstpass(db_client=fake)
        self.assertEqual(r2["status"], "sent_health")
        msg = mock_notify.send.call_args[0][0]
        self.assertIn("Recovered", msg)


class TestStats(unittest.TestCase):
    def test_stats_output(self):
        import cade_firstpass
        s = cade_firstpass.stats()
        self.assertEqual(s["module"], "cade_firstpass")
        self.assertIn("enabled", s)
        self.assertIn("calls", s)
        self.assertIsInstance(s["calls"], dict)


class TestDisabledViaEnvFlag(unittest.TestCase):
    @patch("cade_firstpass.notify")
    def test_disabled_returns_disabled(self, mock_notify):
        import cade_firstpass
        original = cade_firstpass._ENABLED
        try:
            cade_firstpass._ENABLED = False
            result = cade_firstpass.check_firstpass()
            self.assertEqual(result["status"], "disabled")
            mock_notify.send.assert_not_called()
        finally:
            cade_firstpass._ENABLED = original


class TestFormatHealthReport(unittest.TestCase):
    def test_format_contains_key_sections(self):
        import cade_firstpass
        report = _make_complete_report()
        text = cade_firstpass.format_health_report(report)
        self.assertIn("Health Report", text)
        self.assertIn("finance", text)
        self.assertIn("0.12", text)
        self.assertIn("Per-Stage", text)
        self.assertIn("Per-Domain", text)
        self.assertIn("Top Experts", text)


class TestFormatAlert(unittest.TestCase):
    def test_format_alert_contains_failures(self):
        import cade_firstpass
        report = _make_broken_report()
        failures = [{"stage": "score", "error": "timeout"}]
        text = cade_firstpass.format_alert(report, failures)
        self.assertIn("NOT OPERATIONAL", text)
        self.assertIn("score", text)
        self.assertIn("timeout", text)
        self.assertIn("Fix Directive", text)


if __name__ == "__main__":
    unittest.main()

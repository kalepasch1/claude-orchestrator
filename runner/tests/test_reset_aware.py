"""Tests for reset_scheduler.py — reset-aware scheduling.
Run: python3 -m pytest runner/tests -q -k reset_aware
"""
import os, sys, datetime, json, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import reset_scheduler


class TestResetAwareBannerParsing(unittest.TestCase):
    def test_parse_simple_banner(self):
        now = datetime.datetime(2026, 7, 7, 12, 0)
        r = reset_scheduler.parse_reset_banner("resets Jul 8 at 6am", now=now)
        self.assertEqual((r.month, r.day, r.hour), (7, 8, 6))

    def test_parse_full_month_name(self):
        now = datetime.datetime(2026, 7, 7, 12, 0)
        r = reset_scheduler.parse_reset_banner("resets July 8 at 6:00 AM", now=now)
        self.assertEqual((r.month, r.day, r.hour, r.minute), (7, 8, 6, 0))

    def test_parse_pm_banner(self):
        now = datetime.datetime(2026, 7, 7, 12, 0)
        r = reset_scheduler.parse_reset_banner("resets Jul 8 at 3pm", now=now)
        self.assertEqual(r.hour, 15)

    def test_parse_relative_hours(self):
        now = datetime.datetime(2026, 7, 7, 12, 0)
        r = reset_scheduler.parse_reset_banner("resets in 3 hours", now=now)
        self.assertEqual(r, now + datetime.timedelta(hours=3))

    def test_parse_none_on_garbage(self):
        self.assertIsNone(reset_scheduler.parse_reset_banner("no reset info"))
        self.assertIsNone(reset_scheduler.parse_reset_banner(""))
        self.assertIsNone(reset_scheduler.parse_reset_banner(None))

    def test_parse_past_date_wraps_to_next_year(self):
        now = datetime.datetime(2026, 7, 10, 12, 0)
        r = reset_scheduler.parse_reset_banner("resets Jul 8 at 6am", now=now)
        self.assertEqual(r.year, 2027)

    def test_parse_12pm(self):
        now = datetime.datetime(2026, 7, 7, 6, 0)
        r = reset_scheduler.parse_reset_banner("resets Jul 8 at 12pm", now=now)
        self.assertEqual(r.hour, 12)

    def test_parse_12am(self):
        now = datetime.datetime(2026, 7, 7, 6, 0)
        r = reset_scheduler.parse_reset_banner("resets Jul 8 at 12am", now=now)
        self.assertEqual(r.hour, 0)


class TestResetAwareDeferBoost(unittest.TestCase):
    def setUp(self):
        self._orig = reset_scheduler.RESET_STATE_FILE
        self._tmpdir = tempfile.mkdtemp()
        reset_scheduler.RESET_STATE_FILE = os.path.join(self._tmpdir, "state.json")

    def tearDown(self):
        reset_scheduler.RESET_STATE_FILE = self._orig

    def test_record_and_get_reset(self):
        now = datetime.datetime(2026, 7, 7, 12, 0)
        dt = reset_scheduler.record_reset_banner("acct1", "resets Jul 8 at 6am", now=now)
        self.assertEqual(dt.day, 8)
        got = reset_scheduler.get_account_reset("acct1")
        self.assertEqual(got.day, 8)

    def test_defer_near_reset_exhausted(self):
        now = datetime.datetime(2026, 7, 7, 12, 0)
        reset_scheduler.record_reset_banner("acct1", "resets Jul 7 at 4pm", now=datetime.datetime(2026, 7, 6, 12, 0))
        # 4 hours until reset, account exhausted, material task -> defer
        defer, reason = reset_scheduler.should_defer_task("acct1", "build", True, now=now)
        self.assertTrue(defer)
        self.assertIn("defer_near_reset", reason)

    def test_no_defer_when_not_exhausted(self):
        now = datetime.datetime(2026, 7, 7, 12, 0)
        reset_scheduler.record_reset_banner("acct1", "resets Jul 7 at 4pm", now=datetime.datetime(2026, 7, 6, 12, 0))
        defer, reason = reset_scheduler.should_defer_task("acct1", "build", False, now=now)
        self.assertFalse(defer)

    def test_no_defer_for_easy_task(self):
        now = datetime.datetime(2026, 7, 7, 12, 0)
        reset_scheduler.record_reset_banner("acct1", "resets Jul 7 at 4pm", now=datetime.datetime(2026, 7, 6, 12, 0))
        defer, _ = reset_scheduler.should_defer_task("acct1", "mechanical", True, now=now)
        self.assertFalse(defer)

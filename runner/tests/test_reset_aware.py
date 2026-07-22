"""Tests for reset_scheduler.py -- reset-aware scheduling.
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

    def test_night_window_defers(self):
        now = datetime.datetime(2026, 7, 7, 23, 0)
        defer, reason = reset_scheduler.should_defer_task("acct1", "build", False, now=now)
        self.assertTrue(defer)
        self.assertEqual(reason, "night_window")

    def test_daytime_no_night_defer(self):
        now = datetime.datetime(2026, 7, 7, 14, 0)
        defer, _ = reset_scheduler.should_defer_task("acct1", "build", False, now=now)
        self.assertFalse(defer)

    def test_boost_after_reset(self):
        now_record = datetime.datetime(2026, 7, 6, 12, 0)
        reset_scheduler.record_reset_banner("acct1", "resets Jul 7 at 10am", now=now_record)
        now = datetime.datetime(2026, 7, 7, 10, 30)
        share = reset_scheduler.get_claude_share("acct1", now=now)
        self.assertEqual(share, reset_scheduler.BOOST_CLAUDE_SHARE)

    def test_normal_share_outside_boost(self):
        now_record = datetime.datetime(2026, 7, 6, 12, 0)
        reset_scheduler.record_reset_banner("acct1", "resets Jul 7 at 10am", now=now_record)
        now = datetime.datetime(2026, 7, 7, 15, 0)
        share = reset_scheduler.get_claude_share("acct1", now=now)
        self.assertEqual(share, reset_scheduler.NORMAL_CLAUDE_SHARE)

    def test_night_share_zero(self):
        now = datetime.datetime(2026, 7, 7, 23, 0)
        share = reset_scheduler.get_claude_share("acct1", now=now)
        self.assertEqual(share, 0.0)


class TestResetAwareNightWindow(unittest.TestCase):
    def test_night_wrapping_midnight(self):
        self.assertTrue(reset_scheduler.is_night_window(datetime.datetime(2026, 1, 1, 22, 0)))
        self.assertTrue(reset_scheduler.is_night_window(datetime.datetime(2026, 1, 1, 0, 0)))
        self.assertTrue(reset_scheduler.is_night_window(datetime.datetime(2026, 1, 1, 5, 59)))
        self.assertFalse(reset_scheduler.is_night_window(datetime.datetime(2026, 1, 1, 6, 0)))
        self.assertFalse(reset_scheduler.is_night_window(datetime.datetime(2026, 1, 1, 12, 0)))
        self.assertFalse(reset_scheduler.is_night_window(datetime.datetime(2026, 1, 1, 21, 59)))

    def test_unknown_account_returns_none(self):
        self.assertIsNone(reset_scheduler.get_account_reset("nonexistent"))
        self.assertIsNone(reset_scheduler.hours_until_reset("nonexistent"))
        self.assertIsNone(reset_scheduler.hours_since_reset("nonexistent"))


if __name__ == "__main__":
    unittest.main()

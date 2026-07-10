import os
import sys
import threading
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import error_outcome_tracker
import retry_policy


class KeyNormalizationTest(unittest.TestCase):
    def setUp(self):
        error_outcome_tracker.reset()

    def test_key_strips_hex_hashes(self):
        k1 = error_outcome_tracker._key("error abc1234def5 connection reset")
        k2 = error_outcome_tracker._key("error 9f82beef1234 connection reset")
        self.assertEqual(k1, k2)

    def test_key_strips_numbers(self):
        k1 = error_outcome_tracker._key("errno 54 connection reset")
        k2 = error_outcome_tracker._key("errno 110 connection reset")
        self.assertEqual(k1, k2)

    def test_key_strips_unix_paths(self):
        k1 = error_outcome_tracker._key("no such file /tmp/foo.py")
        k2 = error_outcome_tracker._key("no such file /var/bar.py")
        self.assertEqual(k1, k2)

    def test_key_is_empty_for_none(self):
        self.assertEqual(error_outcome_tracker._key(None), "")

    def test_key_is_empty_for_empty_string(self):
        self.assertEqual(error_outcome_tracker._key(""), "")

    def test_key_is_lowercase(self):
        k = error_outcome_tracker._key("Connection RESET by Peer")
        self.assertEqual(k, k.lower())

    def test_key_truncates_to_80_chars(self):
        long = "x" * 200
        self.assertLessEqual(len(error_outcome_tracker._key(long)), 80)


class SuggestTest(unittest.TestCase):
    def setUp(self):
        error_outcome_tracker.reset()

    def test_returns_none_with_no_data(self):
        self.assertIsNone(error_outcome_tracker.suggest("connection reset"))

    def test_returns_none_below_min_samples(self):
        note = "connection reset by peer"
        min_s = int(os.environ.get("ORCH_OUTCOME_MIN_SAMPLES", "5"))
        for _ in range(min_s - 1):
            error_outcome_tracker.record(note, True, True)
        self.assertIsNone(error_outcome_tracker.suggest(note))

    def test_returns_transient_when_success_rate_is_high(self):
        note = "novel transient error xyz"
        for _ in range(6):
            error_outcome_tracker.record(note, True, True)
        self.assertEqual(error_outcome_tracker.suggest(note), "transient")

    def test_returns_terminal_when_transient_retries_rarely_succeed(self):
        note = "some misleading transient looking error"
        for _ in range(6):
            error_outcome_tracker.record(note, True, False)  # retries always fail
        self.assertEqual(error_outcome_tracker.suggest(note), "terminal")

    def test_returns_none_when_success_rate_is_ambiguous(self):
        note = "ambiguous error pattern here"
        for _ in range(4):
            error_outcome_tracker.record(note, True, True)
        for _ in range(4):
            error_outcome_tracker.record(note, True, False)
        # 50% success rate — below confidence threshold both ways → None
        self.assertIsNone(error_outcome_tracker.suggest(note))

    def test_returns_none_for_empty_note(self):
        self.assertIsNone(error_outcome_tracker.suggest(""))

    def test_returns_none_for_none_note(self):
        self.assertIsNone(error_outcome_tracker.suggest(None))

    def test_at_exact_min_samples_boundary(self):
        note = "exact boundary test error"
        min_s = int(os.environ.get("ORCH_OUTCOME_MIN_SAMPLES", "5"))
        for _ in range(min_s):
            error_outcome_tracker.record(note, True, True)
        # At exactly MIN_SAMPLES successes, should be confident transient
        self.assertEqual(error_outcome_tracker.suggest(note), "transient")


class RecordTest(unittest.TestCase):
    def setUp(self):
        error_outcome_tracker.reset()

    def test_record_increments_transient_ok(self):
        error_outcome_tracker.record("conn reset", True, True)
        s = error_outcome_tracker.stats()
        k = error_outcome_tracker._key("conn reset")
        self.assertEqual(s[k]["transient_ok"], 1)
        self.assertEqual(s[k]["transient_fail"], 0)

    def test_record_increments_transient_fail(self):
        error_outcome_tracker.record("conn reset", True, False)
        s = error_outcome_tracker.stats()
        k = error_outcome_tracker._key("conn reset")
        self.assertEqual(s[k]["transient_fail"], 1)
        self.assertEqual(s[k]["transient_ok"], 0)

    def test_record_increments_terminal_ok(self):
        error_outcome_tracker.record("agent run failed", False, True)
        s = error_outcome_tracker.stats()
        k = error_outcome_tracker._key("agent run failed")
        self.assertEqual(s[k]["terminal_ok"], 1)
        self.assertEqual(s[k]["terminal_fail"], 0)

    def test_record_is_fail_soft_on_none_note(self):
        # Must not raise
        error_outcome_tracker.record(None, True, True)
        self.assertEqual(error_outcome_tracker.stats(), {})

    def test_record_is_fail_soft_on_empty_note(self):
        error_outcome_tracker.record("", True, True)
        self.assertEqual(error_outcome_tracker.stats(), {})


class StatsAndResetTest(unittest.TestCase):
    def setUp(self):
        error_outcome_tracker.reset()

    def test_stats_returns_copy_not_reference(self):
        error_outcome_tracker.record("err", True, True)
        s = error_outcome_tracker.stats()
        # Mutating the returned dict must not affect internal state
        k = list(s.keys())[0]
        s[k]["transient_ok"] = 9999
        s2 = error_outcome_tracker.stats()
        self.assertNotEqual(s2[k]["transient_ok"], 9999)

    def test_reset_clears_all_stats(self):
        error_outcome_tracker.record("some error", True, True)
        error_outcome_tracker.reset()
        self.assertEqual(error_outcome_tracker.stats(), {})


class ThreadSafetyTest(unittest.TestCase):
    def setUp(self):
        error_outcome_tracker.reset()

    def test_concurrent_records_do_not_corrupt_state(self):
        note = "concurrent test error"
        errors = []

        def worker():
            try:
                for _ in range(20):
                    error_outcome_tracker.record(note, True, True)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        s = error_outcome_tracker.stats()
        k = error_outcome_tracker._key(note)
        self.assertEqual(s[k]["transient_ok"], 200)


class RetryPolicyIntegrationTest(unittest.TestCase):
    def setUp(self):
        error_outcome_tracker.reset()

    def test_classify_defers_to_outcome_tracker_over_regex_default(self):
        note = "totally novel error pattern that regex misses"
        # Teach the tracker this is transient
        for _ in range(6):
            error_outcome_tracker.record(note, True, True)
        result = retry_policy.classify(note)
        self.assertEqual(result, "transient")

    def test_classify_falls_back_to_regex_when_tracker_has_no_data(self):
        # Standard transient pattern — tracker has no data yet
        self.assertEqual(retry_policy.classify("connection reset by peer"), "transient")

    def test_classify_terminal_regex_still_wins_over_tracker(self):
        note = "agent run failed: out of memory"
        # Even if we teach tracker it's transient, terminal regex wins
        for _ in range(10):
            error_outcome_tracker.record(note, True, True)
        # "agent run failed" hits _TERMINAL regex → always terminal
        self.assertEqual(retry_policy.classify(note), "terminal")

    def test_classify_is_fail_soft_when_tracker_import_errors(self):
        broken = types.SimpleNamespace(suggest=None)  # not callable
        with patch.dict(sys.modules, {"error_outcome_tracker": broken}):
            # Should fall back to regex without raising
            result = retry_policy.classify("connection reset by peer")
        self.assertEqual(result, "transient")

    def test_record_outcome_updates_tracker_on_success(self):
        note = "novel provider error 503 retry"
        retry_policy.record_outcome(note, succeeded=True)
        s = error_outcome_tracker.stats()
        k = error_outcome_tracker._key(note)
        # classify("novel provider error 503 retry") hits _TRANSIENT → was_transient=True
        self.assertEqual(s.get(k, {}).get("transient_ok", 0) + s.get(k, {}).get("terminal_ok", 0), 1)

    def test_record_outcome_is_fail_soft_on_import_error(self):
        with patch.dict(sys.modules, {"error_outcome_tracker": None}):
            retry_policy.record_outcome("some note", succeeded=True)  # must not raise


if __name__ == "__main__":
    unittest.main()

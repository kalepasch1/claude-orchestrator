"""Tests for queue_monitor — real-time queue monitoring and alerting."""
import unittest


class TestQueueMonitor(unittest.TestCase):

    def test_detect_low_merge_rate(self):
        from runner.queue_monitor import detect_alerts
        states = {"QUEUED": 100, "RUNNING": 5, "DONE": 90, "MERGED": 1,
                  "BLOCKED": 0, "TESTFAIL": 0, "BUILDFAIL": 0,
                  "SHELVED": 0, "DECOMPOSED": 0, "QUARANTINED": 0}
        alerts = detect_alerts(states)
        categories = [a["category"] for a in alerts]
        self.assertIn("low_merge_rate", categories)

    def test_detect_queue_stalled(self):
        from runner.queue_monitor import detect_alerts
        states = {"QUEUED": 50, "RUNNING": 0, "DONE": 10, "MERGED": 5,
                  "BLOCKED": 0, "TESTFAIL": 0, "BUILDFAIL": 0,
                  "SHELVED": 0, "DECOMPOSED": 0, "QUARANTINED": 0}
        alerts = detect_alerts(states)
        categories = [a["category"] for a in alerts]
        self.assertIn("queue_stalled", categories)

    def test_healthy_queue_no_alerts(self):
        from runner.queue_monitor import detect_alerts
        states = {"QUEUED": 5, "RUNNING": 3, "DONE": 2, "MERGED": 20,
                  "BLOCKED": 0, "TESTFAIL": 0, "BUILDFAIL": 0,
                  "SHELVED": 0, "DECOMPOSED": 0, "QUARANTINED": 0}
        alerts = detect_alerts(states)
        # Only merge-rate and stall checks use states; the DB checks will fail gracefully
        state_alerts = [a for a in alerts if a["category"] in ("low_merge_rate", "queue_stalled")]
        self.assertEqual(len(state_alerts), 0)

    def test_syntax_check(self):
        import py_compile
        py_compile.compile("runner/queue_monitor.py", doraise=True)


if __name__ == "__main__":
    unittest.main()

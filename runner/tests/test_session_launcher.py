"""Tests for session_launcher."""
import unittest


class TestSessionLauncher(unittest.TestCase):
    def test_create_and_list(self):
        from runner.session_launcher import create_session, list_sessions
        s = create_session(session_id="test-1")
        sessions = list_sessions()
        self.assertTrue(any(x["session_id"] == "test-1" for x in sessions))

    def test_session_lifecycle(self):
        from runner.session_launcher import create_session
        s = create_session(session_id="test-2")
        s.start()
        self.assertEqual(s.status, "running")
        s.record_claim(3)
        s.record_done(2)
        s.record_failure("timeout")
        self.assertEqual(s.tasks_claimed, 3)
        self.assertEqual(s.tasks_done, 2)
        self.assertEqual(s.tasks_failed, 1)
        s.stop()
        self.assertEqual(s.status, "stopped")

    def test_to_dict(self):
        from runner.session_launcher import create_session
        s = create_session(session_id="test-3")
        d = s.to_dict()
        self.assertIn("session_id", d)
        self.assertIn("uptime_s", d)

    def test_syntax(self):
        import py_compile
        py_compile.compile("runner/session_launcher.py", doraise=True)


if __name__ == "__main__":
    unittest.main()

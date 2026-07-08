import os
import plistlib
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class LaunchdPlistTest(unittest.TestCase):

    def test_runner_launchd_uses_keepalive_supervisor(self):
        path = os.path.join(ROOT, "runner", "launchd", "com.orchestrator.runner.plist")
        with open(path, "rb") as f:
            data = plistlib.load(f)

        command = " ".join(data["ProgramArguments"])
        self.assertIn("__APP_DIR__/Contents/MacOS/ClaudeRunner", command)
        self.assertNotIn("python3 runner.py", command)
        self.assertEqual(data["EnvironmentVariables"]["ORCH_KEEPALIVE_STAY_RESIDENT"], "true")
        self.assertNotIn("/Users/kpasch", command)
        self.assertNotIn("/Users/kpasch", data["EnvironmentVariables"]["CLAUDE_ORCH_HOME"])

    def test_launcher_template_is_repo_placeholder_driven(self):
        path = os.path.join(ROOT, "scripts", "launchd", "ClaudeRunner-launcher.sh")
        with open(path) as f:
            text = f.read()
        self.assertIn("__REPO_PATH__", text)
        self.assertIn("__APP_DIR__", text)
        self.assertNotIn("REPO=/Users/kpasch", text)


if __name__ == "__main__":
    unittest.main()

"""Tests for CI pipeline — verify GitHub Actions workflow exists and enforces testing."""
import os
import unittest


class TestCIPipeline(unittest.TestCase):
    def _repo_root(self):
        return os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))

    def _ci_path(self):
        return os.path.join(self._repo_root(), ".github", "workflows", "ci.yml")

    def test_ci_yaml_exists(self):
        self.assertTrue(os.path.isfile(self._ci_path()),
                        f"ci.yml not found at {self._ci_path()}")
        with open(self._ci_path()) as f:
            content = f.read()
        self.assertIn("pytest", content)

    def test_ci_runs_on_push_and_pr(self):
        """CI must trigger on both push and pull_request to enforce pre-merge testing."""
        with open(self._ci_path()) as f:
            content = f.read()
        self.assertIn("push:", content, "CI must trigger on push")
        self.assertIn("pull_request:", content, "CI must trigger on pull_request")

    def test_ci_sets_pythonpath(self):
        """PYTHONPATH must include runner/ so imports resolve."""
        with open(self._ci_path()) as f:
            content = f.read()
        self.assertIn("jobs:", content, "ci.yml must define at least one job")
        self.assertIn("PYTHONPATH: runner/", content)

    def test_ci_uses_checkout_and_setup_python(self):
        """Every test job must checkout code and set up Python."""
        with open(self._ci_path()) as f:
            content = f.read()
        self.assertIn("actions/checkout", content)
        self.assertIn("actions/setup-python", content)

    def test_ci_installs_deps_before_test(self):
        """pip install must appear before pytest run."""
        with open(self._ci_path()) as f:
            content = f.read()
        install_pos = content.find("pip install")
        pytest_pos = content.find("pytest")
        self.assertGreater(install_pos, -1, "must install deps")
        self.assertGreater(pytest_pos, install_pos, "pytest must run after install")

    def test_orch_agent_workflow_exists(self):
        """The agentic CI workflow template must exist for lane=ci dispatch."""
        agent_path = os.path.join(self._repo_root(), ".github", "workflows", "orch-agent.yml")
        self.assertTrue(os.path.isfile(agent_path),
                        f"orch-agent.yml not found at {agent_path}")
        with open(agent_path) as f:
            content = f.read()
        self.assertIn("repository_dispatch", content)


if __name__ == "__main__":
    unittest.main()

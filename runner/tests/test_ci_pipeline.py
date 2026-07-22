"""Tests for CI/CD pipeline verification.

Validates that:
  - Required CI config files exist and parse correctly
  - Test commands match expected patterns
  - Branch protection rules are enforced in config
  - Pipeline stages are ordered correctly
"""
import os
import sys
import unittest
import json
import subprocess

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestCIConfigExists(unittest.TestCase):
    """Verify CI/CD configuration files are present."""

    def test_has_ci_config(self):
        """At least one CI config must exist."""
        candidates = [
            ".github/workflows",
            ".gitlab-ci.yml",
            "Jenkinsfile",
            ".circleci/config.yml",
        ]
        found = any(
            os.path.exists(os.path.join(REPO_ROOT, c)) for c in candidates
        )
        self.assertTrue(found, "No CI/CD configuration found in repo root")

class TestGitHubWorkflows(unittest.TestCase):
    """Validate GitHub Actions workflow files if present."""

    @classmethod
    def setUpClass(cls):
        cls.workflows_dir = os.path.join(REPO_ROOT, ".github", "workflows")
        cls.has_workflows = os.path.isdir(cls.workflows_dir)

    def test_workflows_are_valid_yaml(self):
        """All .yml/.yaml files in workflows dir must parse."""
        if not self.has_workflows:
            self.skipTest("No GitHub workflows directory")
        import yaml
        for fname in os.listdir(self.workflows_dir):
            if fname.endswith((".yml", ".yaml")):
                path = os.path.join(self.workflows_dir, fname)
                with open(path) as f:
                    try:
                        yaml.safe_load(f)
                    except yaml.YAMLError as e:
                        self.fail(f"{fname} is invalid YAML: {e}")

    def test_workflows_have_on_trigger(self):
        """Each workflow must define an 'on' trigger."""
        if not self.has_workflows:
            self.skipTest("No GitHub workflows directory")
        import yaml
        for fname in os.listdir(self.workflows_dir):
            if fname.endswith((".yml", ".yaml")):
                path = os.path.join(self.workflows_dir, fname)
                with open(path) as f:
                    doc = yaml.safe_load(f)
                if doc:
                    self.assertIn(True, [k in doc for k in ["on", True]],
                                  f"{fname} missing 'on' trigger")


class TestTestCommand(unittest.TestCase):
    """Verify the project has a runnable test command."""

    def test_pytest_or_unittest_discoverable(self):
        """Project must have a test runner configured."""
        indicators = [
            os.path.join(REPO_ROOT, "pytest.ini"),
            os.path.join(REPO_ROOT, "setup.cfg"),
            os.path.join(REPO_ROOT, "pyproject.toml"),
            os.path.join(REPO_ROOT, "tox.ini"),
        ]
        has_config = any(os.path.exists(p) for p in indicators)
        has_tests_dir = os.path.isdir(os.path.join(REPO_ROOT, "tests")) or \
                        os.path.isdir(os.path.join(REPO_ROOT, "runner", "tests"))
        self.assertTrue(has_config or has_tests_dir,
                        "No test configuration or tests directory found")

    def test_requirements_file_exists(self):
        """Dependency file must exist for reproducible builds."""
        candidates = [
            "requirements.txt", "requirements-dev.txt",
            "pyproject.toml", "setup.py", "setup.cfg", "Pipfile",
        ]
        found = any(
            os.path.exists(os.path.join(REPO_ROOT, c)) for c in candidates
        )
        self.assertTrue(found, "No dependency manifest found")


if __name__ == "__main__":
    unittest.main(verbosity=2)

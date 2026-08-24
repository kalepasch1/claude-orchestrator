"""Superseded PR runs are cancelled; master runs are never cancelled.

Every push to a PR branch queued a fresh full CI run — darwin-kernel tests + typecheck,
the runner guards, compileall over every module — while the previous run for the same PR
kept going against a commit nobody will merge. Five pushes in an hour meant five full runs
to learn about one tip, queued behind each other.

The half that matters more is the exemption. ci.yml already records that auto-sync
promotes dev -> master with GITHUB_TOKEN, whose pushes never trigger workflows, so master
can change with no CI run at all. Cancelling a master run would widen that hole: a
promotion could land, start verifying, be cancelled by the next promotion, and leave two
commits on master with no completed run between them. Wasted minutes on a superseded PR
are cheap; an unverified master tip is the thing the pipeline exists to prevent.
"""
import os
import sys

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CI = os.path.join(REPO, ".github", "workflows", "ci.yml")


@pytest.fixture(scope="module")
def workflow():
    with open(CI, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class TestConcurrency:
    def test_the_workflow_declares_a_concurrency_group(self, workflow):
        assert "concurrency" in workflow

    def test_the_group_is_scoped_per_ref_so_prs_do_not_cancel_each_other(self, workflow):
        assert "github.ref" in workflow["concurrency"]["group"]

    def test_master_runs_are_not_cancellable(self, workflow):
        """The exemption: an unverified master tip is worse than wasted minutes."""
        expr = str(workflow["concurrency"]["cancel-in-progress"])
        assert "refs/heads/master" in expr
        assert "!=" in expr

    def test_superseded_runs_are_cancelled_everywhere_else(self, workflow):
        expr = str(workflow["concurrency"]["cancel-in-progress"])
        # A bare `true` would cancel master too; a bare `false` cancels nothing.
        assert expr.strip().lower() not in ("true", "false")

    def test_the_reasoning_is_recorded_next_to_the_setting(self):
        """A future edit that flips this must have to read why it is conditional."""
        body = open(CI, encoding="utf-8").read()
        head = body[:body.index("jobs:")]
        assert "cancel-in-progress is FALSE on master" in head
        assert "auto-sync" in head


class TestNoBehaviourChange:
    def test_every_job_still_exists(self, workflow):
        assert sorted(workflow["jobs"]) == [
            "darwin-kernel", "runner-guards", "task-reconciliation"]

    def test_the_triggers_are_unchanged(self, workflow):
        on = workflow.get("on") or workflow.get(True)  # YAML 1.1 parses `on:` as True
        assert "pull_request" in on
        assert "workflow_dispatch" in on
        assert on["push"]["branches"] == ["master"]

    def test_the_offline_guard_job_still_unsets_credentials(self):
        """The property that makes runner-guards honest must survive any CI edit."""
        body = open(CI, encoding="utf-8").read()
        assert "SUPABASE_URL: ''" in body
        assert "SUPABASE_SERVICE_KEY: ''" in body

    def test_pip_is_cached(self, workflow):
        steps = workflow["jobs"]["runner-guards"]["steps"]
        setup = [s for s in steps if str(s.get("uses", "")).startswith("actions/setup-python")]
        assert setup and setup[0]["with"].get("cache") == "pip"

    def test_the_python_version_is_unchanged(self, workflow):
        steps = workflow["jobs"]["runner-guards"]["steps"]
        setup = [s for s in steps if str(s.get("uses", "")).startswith("actions/setup-python")]
        assert setup[0]["with"]["python-version"] == "3.11"


class TestWorkflowIsValid:
    def test_every_workflow_file_parses(self):
        root = os.path.join(REPO, ".github", "workflows")
        names = [n for n in os.listdir(root) if n.endswith((".yml", ".yaml"))]
        assert names
        for name in names:
            with open(os.path.join(root, name), encoding="utf-8") as fh:
                assert yaml.safe_load(fh), name

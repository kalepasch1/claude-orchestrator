"""The staging branch is per project: registry, then environment, then default."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import staging_branch  # noqa: E402


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    monkeypatch.delenv(staging_branch.ENV_VAR, raising=False)


def test_the_fleet_default_when_nothing_is_configured():
    assert staging_branch.fleet_staging_branch() == ("orchestrator/dev", staging_branch.SOURCE_DEFAULT)
    branch, source = staging_branch.staging_branch_for(row={})
    assert branch == "orchestrator/dev"
    assert source == staging_branch.SOURCE_DEFAULT


def test_the_environment_beats_the_default(monkeypatch):
    monkeypatch.setenv(staging_branch.ENV_VAR, "  integration  ")
    assert staging_branch.fleet_staging_branch() == ("integration", staging_branch.SOURCE_ENV)


def test_a_project_row_beats_the_environment(monkeypatch):
    # The whole point: a value written against ONE project is more specific than
    # a variable written for the process, so it wins.
    monkeypatch.setenv(staging_branch.ENV_VAR, "orchestrator/dev")
    branch, source = staging_branch.staging_branch_for(row={"staging_branch": "dev"})
    assert (branch, source) == ("dev", staging_branch.SOURCE_REGISTRY)


def test_a_blank_row_value_is_unset_not_a_branch_called_nothing():
    branch, source = staging_branch.staging_branch_for(row={"staging_branch": "   "})
    assert branch == "orchestrator/dev"
    assert source == staging_branch.SOURCE_DEFAULT


def test_a_repo_is_looked_up_by_its_real_path(tmp_path):
    seen = {}

    def select(table, params):
        seen["table"] = table
        seen["params"] = params
        return [{"repo_path": params["repo_path"][3:], "staging_branch": "dev"}]

    branch, source = staging_branch.staging_branch_for(repo=str(tmp_path), select=select)
    assert branch == "dev"
    assert source == staging_branch.SOURCE_REGISTRY
    assert seen["table"] == "projects"
    assert seen["params"]["repo_path"] == f"eq.{os.path.realpath(str(tmp_path))}"


def test_an_unreachable_registry_falls_back_and_says_so(tmp_path):
    def select(table, params):
        raise RuntimeError("set SUPABASE_URL and SUPABASE_SERVICE_KEY")

    branch, source = staging_branch.staging_branch_for(repo=str(tmp_path), select=select)
    assert branch == "orchestrator/dev"
    assert "registry unreachable" in source


def test_a_repo_with_no_row_falls_back_and_says_so(tmp_path):
    branch, source = staging_branch.staging_branch_for(repo=str(tmp_path), select=lambda t, p: [])
    assert branch == "orchestrator/dev"
    assert "no row" in source


def test_describe_reads_as_one_phrase():
    assert staging_branch.describe("dev", staging_branch.SOURCE_REGISTRY) == "dev (project registry)"

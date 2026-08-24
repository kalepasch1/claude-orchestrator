"""Tests for runner/base_branch.py.

MEASURED 2026-08-24: five consecutive beethoven tasks were claimed carrying
`base_branch='main'` while the same rows carried `default_base='master'`. Every one
failed its first worktree command with `fatal: invalid reference: origin/main`. The
literal `or "main"` fallback is wrong for most repos in this fleet, and two of the
call sites compounded it by reading `default_branch` — a key the projects table does
not have — so they could never have read the right value.

These tests build real git repos rather than mocking git, because the whole point of
the module is that the repository is more authoritative than the row.
"""

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import base_branch as BB  # noqa: E402


def _git(a, r):
    return subprocess.run(["git", *a], cwd=r, capture_output=True, text=True, timeout=30)


def _repo(tmp_path, branch="master", name="r"):
    """A repo with `origin` pointing at a real clone, so origin/<branch> exists."""
    upstream = str(tmp_path / f"{name}-upstream")
    os.makedirs(upstream)
    _git(["init", "-q", "-b", branch], upstream)
    _git(["config", "user.email", "t@t"], upstream)
    _git(["config", "user.name", "t"], upstream)
    with open(os.path.join(upstream, "f.txt"), "w") as fh:
        fh.write("x\n")
    _git(["add", "-A"], upstream)
    _git(["commit", "-qm", "c"], upstream)

    clone = str(tmp_path / name)
    subprocess.run(
        ["git", "clone", "-q", upstream, clone], capture_output=True, timeout=60
    )
    return clone


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("ORCH_DEFAULT_BASE_BRANCH", raising=False)
    monkeypatch.delenv("ORCH_BASE_BRANCH_TIMEOUT", raising=False)


# --- from_project ----------------------------------------------------------

def test_default_base_is_preferred():
    assert BB.from_project({"default_base": "master", "default_branch": "main"}) == "master"


def test_falls_through_to_default_branch():
    assert BB.from_project({"default_branch": "dev"}) == "dev"


def test_falls_through_to_prod_branch():
    assert BB.from_project({"prod_branch": "trunk"}) == "trunk"


@pytest.mark.parametrize(
    "given", [{}, None, "master", 7, {"default_base": ""}, {"default_base": "   "},
              {"default_base": None}, {"unrelated": "master"}]
)
def test_from_project_is_fail_soft(given):
    assert BB.from_project(given) == ""


# --- repo interrogation ----------------------------------------------------

def test_remote_head_reads_master(tmp_path):
    assert BB.remote_head(_repo(tmp_path, "master")) == "master"


def test_remote_head_reads_main(tmp_path):
    assert BB.remote_head(_repo(tmp_path, "main")) == "main"


def test_remote_head_on_unusual_name(tmp_path):
    assert BB.remote_head(_repo(tmp_path, "medicalOnly")) == "medicalOnly"


@pytest.mark.parametrize("given", [None, "", "/nonexistent/path/xyz"])
def test_remote_head_fail_soft(given):
    assert BB.remote_head(given) == ""


def test_ref_exists_true_and_false(tmp_path):
    repo = _repo(tmp_path, "master")
    assert BB.ref_exists(repo, "master") is True
    assert BB.ref_exists(repo, "main") is False


@pytest.mark.parametrize("given", [None, "", "   "])
def test_ref_exists_rejects_empty(tmp_path, given):
    assert BB.ref_exists(_repo(tmp_path, "master"), given) is False


def test_ref_exists_bad_repo_is_false():
    assert BB.ref_exists("/nonexistent/path/xyz", "master") is False


def test_from_repo_uses_origin_head(tmp_path):
    assert BB.from_repo(_repo(tmp_path, "master")) == "master"


def test_from_repo_probes_when_origin_head_unset(tmp_path):
    repo = _repo(tmp_path, "master")
    # origin/HEAD is a SYMBOLIC ref; `update-ref -d` does not remove it.
    _git(["symbolic-ref", "-d", "refs/remotes/origin/HEAD"], repo)
    assert BB.remote_head(repo) == ""
    assert BB.from_repo(repo) == "master"


def test_from_repo_bad_path_is_empty():
    assert BB.from_repo("/nonexistent/path/xyz") == ""


# --- resolve ---------------------------------------------------------------

def test_task_value_wins(tmp_path):
    repo = _repo(tmp_path, "master")
    assert BB.resolve({"base_branch": "release"}, {"default_base": "x"}, repo) == "release"


def test_project_used_when_task_is_blank(tmp_path):
    repo = _repo(tmp_path, "master")
    assert BB.resolve({"base_branch": ""}, {"default_base": "dev"}, repo) == "dev"


def test_repo_used_when_task_and_project_are_blank(tmp_path):
    assert BB.resolve({}, {}, _repo(tmp_path, "master")) == "master"


def test_fallback_is_the_last_resort_not_the_first_answer():
    assert BB.resolve({}, {}, None) == "main"


def test_fallback_is_configurable(monkeypatch):
    monkeypatch.setenv("ORCH_DEFAULT_BASE_BRANCH", "master")
    assert BB.resolve({}, {}, None) == "master"


def test_resolve_never_returns_empty():
    assert BB.resolve(None, None, None)


def test_resolve_tolerates_junk_arguments():
    assert BB.resolve("task", 42, 3.14) == "main"


# --- resolve_verified: the 2026-08-24 regression ---------------------------

def test_recorded_main_is_corrected_to_the_branch_that_exists(tmp_path):
    """The exact failure: row says main, repo only has master."""
    repo = _repo(tmp_path, "master")
    task = {"base_branch": "main"}
    assert BB.resolve(task, {}, repo) == "main"          # what shipped
    assert BB.resolve_verified(task, {}, repo) == "master"  # what should have


def test_verified_keeps_a_recorded_branch_that_really_exists(tmp_path):
    repo = _repo(tmp_path, "main")
    assert BB.resolve_verified({"base_branch": "main"}, {}, repo) == "main"


def test_verified_degrades_to_resolve_without_a_repo():
    assert BB.resolve_verified({"base_branch": "main"}, {}, None) == "main"


def test_verified_keeps_candidate_when_repo_yields_nothing(tmp_path):
    empty = str(tmp_path / "empty")
    os.makedirs(empty)
    assert BB.resolve_verified({"base_branch": "main"}, {}, empty) == "main"


# --- mismatch --------------------------------------------------------------

def test_mismatch_reports_the_drift(tmp_path):
    repo = _repo(tmp_path, "master")
    assert BB.mismatch({"base_branch": "main"}, {}, repo) == ("main", "master")


def test_mismatch_is_none_when_they_agree(tmp_path):
    repo = _repo(tmp_path, "master")
    assert BB.mismatch({"base_branch": "master"}, {}, repo) is None


def test_mismatch_is_none_without_a_repo():
    assert BB.mismatch({"base_branch": "main"}, {}, None) is None


def test_mismatch_catches_a_wrong_project_row(tmp_path):
    repo = _repo(tmp_path, "master")
    assert BB.mismatch({}, {"default_base": "main"}, repo) == ("main", "master")


# --- timeout config --------------------------------------------------------

@pytest.mark.parametrize("raw", ["not-a-number", "0", "9999", ""])
def test_bad_timeout_env_falls_back(tmp_path, monkeypatch, raw):
    monkeypatch.setenv("ORCH_BASE_BRANCH_TIMEOUT", raw)
    assert BB.remote_head(_repo(tmp_path, "master")) == "master"


def test_valid_timeout_env_is_honoured(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_BASE_BRANCH_TIMEOUT", "20")
    assert BB.remote_head(_repo(tmp_path, "master")) == "master"

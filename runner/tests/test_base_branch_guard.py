"""A task must not be queued against a branch its project does not have.

About thirty task generators end their base-branch expression with `or "main"`.
For every project whose default_base is `master` that names a branch which does
not exist, so `git worktree add -B agent/<slug> origin/main` fails and each
executor falls through to whatever its own fallback happens to be.

Tasks created in the last 30 days, by project and base_branch:

    beethoven   default_base=master   base=main    5208   <- wrong
    beethoven   default_base=master   base=master  2901   <- right
    apparently  default_base=master   base=main     682   <- wrong
    illuminati  default_base=master   base=main     151   <- wrong

The same queue disagreeing with itself about the same repo. Correcting thirty
generators leaves the thirty-first to be written wrong, so the correction lives
at the insert choke point, next to the deps normalizer and the prompt gate.

What must NOT change: a caller that named a specific branch (darwn's
`medicalOnly`, `orchestrator/dev`, `fix/ci-baseline`, `merge-train-tmp`) knew
something the guard does not.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db


@pytest.fixture(autouse=True)
def clear_cache():
    db._PROJECT_BASE_CACHE.clear()
    yield
    db._PROJECT_BASE_CACHE.clear()


@pytest.fixture
def project_master(monkeypatch):
    """A project configured with default_base=master (beethoven, apparently)."""
    monkeypatch.setitem(db._PROJECT_BASE_CACHE, "p-master", "master")
    return "p-master"


@pytest.fixture
def project_main(monkeypatch):
    """A project configured with default_base=main (tomorrow, pareto-2080)."""
    monkeypatch.setitem(db._PROJECT_BASE_CACHE, "p-main", "main")
    return "p-main"


# --- the bug ---------------------------------------------------------------

def test_a_hardcoded_main_is_corrected_to_the_projects_master(project_master):
    row = {"slug": "some-task", "project_id": project_master, "base_branch": "main"}

    db._guard_task_base_branch(row)

    assert row["base_branch"] == "master"


def test_an_unset_base_is_filled_in_from_the_project(project_master):
    row = {"slug": "some-task", "project_id": project_master}

    db._guard_task_base_branch(row)

    assert row["base_branch"] == "master"


def test_an_empty_base_is_filled_in_from_the_project(project_master):
    row = {"slug": "some-task", "project_id": project_master, "base_branch": "  "}

    db._guard_task_base_branch(row)

    assert row["base_branch"] == "master"


def test_a_hardcoded_master_is_corrected_on_a_main_project(project_main):
    """The mistake runs both ways — branch_repair_bot defaults to 'master'."""
    row = {"slug": "some-task", "project_id": project_main, "base_branch": "master"}

    db._guard_task_base_branch(row)

    assert row["base_branch"] == "main"


# --- what must not change --------------------------------------------------

@pytest.mark.parametrize("deliberate", [
    "medicalOnly",          # darwn
    "orchestrator/dev",     # the fleet's own integration branch
    "fix/ci-baseline",      # tomorrow
    "merge-train-tmp",      # smarter
    "release/2026-08",
])
def test_a_deliberately_named_branch_is_never_rewritten(project_master, deliberate):
    row = {"slug": "some-task", "project_id": project_master, "base_branch": deliberate}

    db._guard_task_base_branch(row)

    assert row["base_branch"] == deliberate


def test_an_already_correct_base_is_left_alone(project_master):
    row = {"slug": "some-task", "project_id": project_master, "base_branch": "master"}

    db._guard_task_base_branch(row)

    assert row["base_branch"] == "master"


def test_a_project_with_no_configured_default_is_left_alone(monkeypatch):
    monkeypatch.setitem(db._PROJECT_BASE_CACHE, "p-blank", "")
    row = {"slug": "some-task", "project_id": "p-blank", "base_branch": "main"}

    db._guard_task_base_branch(row)

    assert row["base_branch"] == "main"


def test_a_row_with_no_project_is_left_alone():
    row = {"slug": "some-task", "base_branch": "main"}

    db._guard_task_base_branch(row)

    assert row["base_branch"] == "main"


# --- fail-soft: the guard must never block an insert -----------------------

def test_a_lookup_failure_leaves_the_row_exactly_as_submitted(monkeypatch):
    def boom(table, params):
        raise RuntimeError("postgrest is down")
    monkeypatch.setattr(db, "select", boom)

    row = {"slug": "some-task", "project_id": "p-unknown", "base_branch": "main"}
    db._guard_task_base_branch(row)

    assert row["base_branch"] == "main"


def test_a_non_dict_row_does_not_raise():
    db._guard_task_base_branch({})          # no keys at all
    db._guard_task_base_branch({"base_branch": None})


def test_the_lookup_is_memoised_per_project(monkeypatch):
    calls = []

    def counting_select(table, params):
        calls.append(params)
        return [{"default_base": "master"}]
    monkeypatch.setattr(db, "select", counting_select)

    for _ in range(5):
        db._project_default_base_cached("p-fresh")

    assert len(calls) == 1, "one query per project per process, like the name cache"

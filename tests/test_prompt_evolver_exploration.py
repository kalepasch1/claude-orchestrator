"""Every prompt-template arm must stay reachable — through the cold-start path.

There are two ways to give a UCB1 bandit exploration, and this module has now
tried both. Seeding every id in TEMPLATE_IDS at n_trials=0 before aggregating
makes each unseen arm score +inf, which is correct for a bandit that owns its
arm set — but here a seeded arm is never written back by select_template, so it
scored +inf forever and the bandit could explore but never exploit. That seeding
was removed on 2026-08-12.

Exploration now happens in the cold-start branch: a kind with no rows at all gets
a round-robin over TEMPLATE_IDS, and arms enter the table through record_outcome.
These tests were still pinning the deleted seeding behaviour and failed on correct
code; they now pin the shipped contract — reachability via round-robin, exploit
once history exists, and NULL tolerance.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from runner import prompt_evolver


@pytest.fixture(autouse=True)
def clean():
    prompt_evolver.invalidate()
    yield
    prompt_evolver.invalidate()


@pytest.fixture()
def rows(monkeypatch):
    """Let each test set the prompt_templates rows select_template will see."""
    box = {"rows": []}
    monkeypatch.setattr(prompt_evolver.db, "select", lambda *a, **k: box["rows"])
    return box


def test_an_arm_with_real_history_beats_an_arm_the_table_has_never_seen(rows):
    """The 2026-08-12 correction: recorded reward must be able to win.

    Under the old seeding this returned a never-tried constant on every call —
    +inf outranks any finite mean, and the seeded arm was never written back, so
    the score could not converge. A bandit that cannot exploit is not a bandit.
    """
    rows["rows"] = [{"kind": "bugfix", "template_id": "base",
                     "total_reward": 50.0, "n_trials": 50}]
    _, chosen = prompt_evolver.select_template("bugfix", "P")
    assert chosen == "base"


def test_every_arm_is_reachable_through_cold_start_round_robin(rows):
    """Reachability is the cold-start branch's job, and it covers every arm."""
    rows["rows"] = []      # no rows for this kind at all
    seen = set()
    for _ in range(len(prompt_evolver.TEMPLATE_IDS) * 3):
        _, chosen = prompt_evolver.select_template("cold-kind", "P")
        seen.add(chosen)
    assert seen == set(prompt_evolver.TEMPLATE_IDS)


def test_an_arm_enters_the_race_as_soon_as_it_has_a_row(rows):
    """record_outcome writes the row; from then on the arm is a candidate."""
    rows["rows"] = [{"kind": "bugfix", "template_id": "base",
                     "total_reward": 1.0, "n_trials": 10}]
    assert prompt_evolver.select_template("bugfix", "P")[1] == "base"
    rows["rows"].append({"kind": "bugfix", "template_id": "edit_first",
                         "total_reward": 9.0, "n_trials": 10})
    assert prompt_evolver.select_template("bugfix", "P")[1] == "edit_first"


def test_best_arm_wins_once_every_arm_has_history(rows):
    """With exploration satisfied, UCB1 still exploits the strongest arm."""
    rows["rows"] = [
        {"kind": "bugfix", "template_id": "base", "total_reward": 5.0, "n_trials": 100},
        {"kind": "bugfix", "template_id": "chain_of_thought",
         "total_reward": 95.0, "n_trials": 100},
        {"kind": "bugfix", "template_id": "edit_first",
         "total_reward": 5.0, "n_trials": 100},
    ]
    _, chosen = prompt_evolver.select_template("bugfix", "P")
    assert chosen == "chain_of_thought"


def test_null_reward_columns_do_not_raise(rows):
    """SQL NULL survives .get()'s default; `or 0` is what actually absorbs it."""
    rows["rows"] = [{"kind": "bugfix", "template_id": "base",
                     "total_reward": None, "n_trials": None}]
    prompt, chosen = prompt_evolver.select_template("bugfix", "P")
    assert chosen in prompt_evolver.TEMPLATE_IDS
    assert "P" in prompt


def test_unknown_template_id_from_db_is_still_aggregated(rows):
    """Seeding known arms must not drop arms the DB knows about."""
    rows["rows"] = [
        {"kind": "bugfix", "template_id": tid, "total_reward": 0.0, "n_trials": 1}
        for tid in prompt_evolver.TEMPLATE_IDS
    ] + [{"kind": "bugfix", "template_id": "experimental",
          "total_reward": 9.0, "n_trials": 1}]
    _, chosen = prompt_evolver.select_template("bugfix", "P")
    assert chosen == "experimental"


def test_non_base_selection_tags_the_prompt(rows):
    """Only a non-base arm is tagged; 'base' is the untagged prompt by definition."""
    rows["rows"] = [{"kind": "bugfix", "template_id": "chain_of_thought",
                     "total_reward": 1.0, "n_trials": 1}]
    prompt, chosen = prompt_evolver.select_template("bugfix", "BODY")
    assert chosen == "chain_of_thought"
    assert prompt == "[template:chain_of_thought]\nBODY"


def test_base_selection_leaves_the_prompt_untouched(rows):
    rows["rows"] = [{"kind": "bugfix", "template_id": "base",
                     "total_reward": 1.0, "n_trials": 1}]
    prompt, chosen = prompt_evolver.select_template("bugfix", "BODY")
    assert (prompt, chosen) == ("BODY", "base")


def test_db_error_falls_back_to_base(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(prompt_evolver.db, "select", boom)
    assert prompt_evolver.select_template("bugfix", "BODY") == ("BODY", "base")

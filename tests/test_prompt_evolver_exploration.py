"""UCB1 over prompt templates must be able to reach every arm.

select_template built its candidate set purely from the rows returned by the
DB. A template that had never been recorded had no row, so it never became a
candidate -- the bandit locked onto whichever arm was written first and never
explored again. These tests pin exploration and NULL tolerance.
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


def test_untried_arm_is_selected_over_a_well_performing_one(rows):
    """An arm with no history scores +inf and must be tried first."""
    rows["rows"] = [{"kind": "bugfix", "template_id": "base",
                     "total_reward": 50.0, "n_trials": 50}]
    _, chosen = prompt_evolver.select_template("bugfix", "P")
    assert chosen != "base"
    assert chosen in prompt_evolver.TEMPLATE_IDS


def test_every_arm_is_reachable_across_successive_selections(rows):
    """The regression: only 'base' had a row, so only 'base' was ever chosen."""
    history = {"base": {"total_reward": 10.0, "n_trials": 10}}
    seen = set()
    for _ in range(len(prompt_evolver.TEMPLATE_IDS) * 3):
        rows["rows"] = [{"kind": "bugfix", "template_id": tid, **agg}
                        for tid, agg in history.items()]
        _, chosen = prompt_evolver.select_template("bugfix", "P")
        seen.add(chosen)
        agg = history.setdefault(chosen, {"total_reward": 0.0, "n_trials": 0})
        agg["n_trials"] += 1
    assert seen == set(prompt_evolver.TEMPLATE_IDS)


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
    rows["rows"] = [{"kind": "bugfix", "template_id": "base",
                     "total_reward": 1.0, "n_trials": 1}]
    prompt, chosen = prompt_evolver.select_template("bugfix", "BODY")
    assert prompt == f"[template:{chosen}]\nBODY"


def test_db_error_falls_back_to_base(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(prompt_evolver.db, "select", boom)
    assert prompt_evolver.select_template("bugfix", "BODY") == ("BODY", "base")

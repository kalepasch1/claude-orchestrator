"""UCB1 over prompt templates must be able to both explore AND exploit.

Two failure modes, and the fix for one was briefly the other:

  * Candidates built purely from DB rows: a template never recorded had no row,
    so the bandit locked onto whichever arm was written first.
  * The fix for that seeded every TEMPLATE_ID at n_trials=0 — which scores +inf,
    is never written back, and so wins forever. Recorded rewards stopped mattering.

Corrected 2026-08-12: exploration lives in the cold-start round-robin (no rows for
the kind), scoring reads only real history. These tests pin BOTH halves plus NULL
tolerance, so neither failure mode can come back silently.
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


def test_exploration_happens_at_cold_start_not_by_seeding_phantom_arms(rows):
    """Where exploration lives after the 2026-08-12 correction.

    These two tests used to assert that an arm with NO row outranks an arm with a
    strong record, because select_template seeded every TEMPLATE_ID at n_trials=0
    before scoring. That seeding was removed on purpose: a seeded arm scores +inf,
    is never written back by select_template (TEMPLATE_IDS are documented as not
    auto-inserted), and therefore wins forever — the recorded rewards could never
    influence anything. A bandit that cannot exploit is not a bandit.

    Exploration now runs through the path built for it: when a kind has NO rows at
    all, successive calls round-robin across every template id. That is what is
    pinned here.
    """
    rows["rows"] = []
    seen = set()
    for _ in range(len(prompt_evolver.TEMPLATE_IDS) * 2):
        _, chosen = prompt_evolver.select_template("cold-start-kind", "P")
        seen.add(chosen)
    assert seen == set(prompt_evolver.TEMPLATE_IDS)


def test_an_arm_with_real_history_is_not_displaced_by_one_without_a_row(rows):
    """The inverse pin: absence of a row is not evidence of promise."""
    rows["rows"] = [{"kind": "bugfix", "template_id": "base",
                     "total_reward": 50.0, "n_trials": 50}]
    _, chosen = prompt_evolver.select_template("bugfix", "P")
    assert chosen == "base"


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
    """A non-base arm must prepend its tag; 'base' must not.

    Driven by giving a non-base arm the winning record. The previous version supplied
    only a 'base' row and expected a tagged prompt, which was only ever true while the
    removed seeding forced a phantom arm to win.
    """
    rows["rows"] = [
        {"kind": "bugfix", "template_id": "base", "total_reward": 0.0, "n_trials": 100},
        {"kind": "bugfix", "template_id": "edit_first",
         "total_reward": 100.0, "n_trials": 100},
    ]
    prompt, chosen = prompt_evolver.select_template("bugfix", "BODY")
    assert chosen == "edit_first"
    assert prompt == "[template:edit_first]\nBODY"


def test_base_selection_leaves_the_prompt_untouched(rows):
    rows["rows"] = [
        {"kind": "bugfix", "template_id": "base", "total_reward": 100.0, "n_trials": 100},
        {"kind": "bugfix", "template_id": "edit_first",
         "total_reward": 0.0, "n_trials": 100},
    ]
    prompt, chosen = prompt_evolver.select_template("bugfix", "BODY")
    assert chosen == "base"
    assert prompt == "BODY"


def test_db_error_falls_back_to_base(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(prompt_evolver.db, "select", boom)
    assert prompt_evolver.select_template("bugfix", "BODY") == ("BODY", "base")

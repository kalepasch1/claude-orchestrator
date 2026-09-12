"""The train must not spend a rebuild budget on work that is not to be landed.

_resolve_task() enumerates the states a card may legitimately be merged in --
("BLOCKED", MERGING_STATE, "DONE", "MERGED", "RUNNING", "QUEUED", "RETRY") -- and then
defeats its own enumeration with `tasks[0] if tasks else None`. When every task row for
a slug is terminal, that fallback hands the train a QUARANTINED or DECOMPOSED task and
the full gate runs on it: rebase, up to MERGE_CONFLICT_REDO_CAP agent rebuilds, tests,
quarantine, retire the card. Next pass a producer files a fresh card for the same slug
and the whole thing repeats.

Measured 2026-09-02 on the live fleet:

    integrate cards created in 7 days                            9,345
    ...whose task is QUEUED (real, waiting work)                    578   (6.2%)
    ...whose task is terminal-and-not-to-be-merged                2,449
    approved integrate cards in the pool                          4,542
    ...whose ONLY task rows are terminal                            823   (18%)
       DECOMPOSED 473 | QUARANTINED 236 | PHANTOM_UNVERIFIED 117
       CLOSED 8 | SUPERSEDED 2 | DEPLOYED_AND_VERIFIED 1

One slug -- dropbox-mission-complete-...-governor-ram-floor, DONE since 2026-08-19,
attempt 272 -- had accumulated 1,101 cards, 294 decided `train:conflict-exhausted`.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import merge_train  # noqa: E402


@pytest.mark.parametrize("state", ["QUARANTINED", "SUPERSEDED", "DECOMPOSED",
                                   "CLOSED", "SHELVED"])
def test_terminal_states_are_not_integratable(state):
    assert merge_train._not_integratable({"state": state}) == state


@pytest.mark.parametrize("state", ["QUEUED", "RUNNING", "DONE", "MERGED", "RETRY",
                                   "BLOCKED", "MERGING", "TESTFAIL", "CONFLICT"])
def test_workable_states_stay_integratable(state):
    assert merge_train._not_integratable({"state": state}) == ""


def test_done_is_never_skipped():
    """DONE -> MERGED is the intended path; skipping it stops the train merging at all."""
    assert "DONE" not in merge_train.NON_INTEGRATABLE_STATES
    assert merge_train._not_integratable({"state": "DONE"}) == ""


def test_merged_is_never_skipped():
    assert "MERGED" not in merge_train.NON_INTEGRATABLE_STATES


def test_phantom_unverified_is_not_skipped():
    """"We think it landed but have not proved it" is a question the train answers."""
    assert merge_train._not_integratable({"state": "PHANTOM_UNVERIFIED"}) == ""


def test_state_matching_is_case_and_space_insensitive():
    assert merge_train._not_integratable({"state": " quarantined "}) == "QUARANTINED"


def test_missing_or_empty_state_is_not_skipped():
    for task in ({}, {"state": None}, {"state": ""}, None):
        assert merge_train._not_integratable(task) == ""


def test_the_skip_set_is_configurable(monkeypatch):
    """Read from the environment so the fleet can widen or narrow it without a deploy."""
    import importlib
    monkeypatch.setenv("ORCH_MERGE_SKIP_TASK_STATES", "SHELVED")
    mod = importlib.reload(merge_train)
    try:
        assert mod.NON_INTEGRATABLE_STATES == frozenset({"SHELVED"})
        assert mod._not_integratable({"state": "QUARANTINED"}) == ""
    finally:
        monkeypatch.delenv("ORCH_MERGE_SKIP_TASK_STATES")
        importlib.reload(merge_train)


def test_default_skip_set_is_exactly_the_five_terminal_states():
    assert merge_train.NON_INTEGRATABLE_STATES == frozenset(
        {"QUARANTINED", "SUPERSEDED", "DECOMPOSED", "CLOSED", "SHELVED"})


def test_resolve_task_still_prefers_a_workable_row_over_a_terminal_one():
    """The preference order already handles the mixed case; this pins that it still does."""
    cards = {"queued-and-quarantined": [
        {"state": "QUARANTINED", "id": "bad"},
        {"state": "QUEUED", "id": "good"},
    ]}

    class _Card(dict):
        pass

    slug, task = merge_train._resolve_task(
        {"slug": "queued-and-quarantined"}, cards)
    assert task["id"] == "good"
    assert merge_train._not_integratable(task) == ""


def test_resolve_task_falls_back_to_a_terminal_row_when_that_is_all_there_is():
    """The fallback still happens -- the caller is what must now refuse it."""
    cards = {"only-decomposed": [{"state": "DECOMPOSED", "id": "parent"}]}
    slug, task = merge_train._resolve_task({"slug": "only-decomposed"}, cards)
    assert task["id"] == "parent"
    assert merge_train._not_integratable(task) == "DECOMPOSED"


def test_the_card_loop_refuses_before_grouping_the_card():
    """Structural: the guard must run before by_project.setdefault, not after."""
    src = open(merge_train.__file__.replace(".pyc", ".py")).read()
    anchor = src.index('_r("skipped", slug, "no-task: no task row for this slug")')
    window = src[anchor:anchor + 900]
    assert "_not_integratable(t)" in window, window
    assert window.index("_not_integratable(t)") < window.index("by_project.setdefault"), window
    assert "_retire_card" in window


def test_the_card_loop_retires_the_card_rather_than_leaving_it_in_the_pool():
    """A card left approved is refiled and re-attempted next pass -- the amplifier."""
    src = open(merge_train.__file__.replace(".pyc", ".py")).read()
    anchor = src.index("_dead = _not_integratable(t)")
    window = src[anchor:anchor + 400]
    assert 'f"task-{_dead.lower()}"' in window, window
    assert "continue" in window

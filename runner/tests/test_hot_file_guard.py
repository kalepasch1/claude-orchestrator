"""Many different cards colliding on one file must not each pay for the same answer.

The per-task guard stops ONE card redoing a conflict it already hit. It cannot see the
larger shape. Measured 2026-09-02 in one merge-train log:

    REDO events                                              283
    distinct (project, conflicting-file-set) signatures        94
    signatures hit by more than one slug                       29
      [beethoven]      28 slugs, all on
                       packages/darwin-kernel/src/passport/passport.ts
      [apparently-law] 16 slugs, all on app/assets/css/sister.css (+2)
      [beethoven]      14 slugs, all on docs/recovery-ledger/README.md
      [tomorrow]       11 slugs, all on pages/index.vue

Twenty-eight separate cards each rebased onto the same base, hit the same file, and each
spent up to MERGE_CONFLICT_REDO_CAP agent rebuilds discovering what the previous
twenty-seven had already established. Every one ended CONFLICT anyway -- "redo cap 4
exhausted" was the outcome of all 1,564 beethoven conflict events in that window -- so
the rebuilds bought a result the fleet already had.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import merge_train as mt  # noqa: E402


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "sigs.json"
    monkeypatch.setattr(mt, "_conflict_ledger_path", lambda: str(path))
    monkeypatch.delenv("ORCH_HOT_FILE_SLUG_THRESHOLD", raising=False)
    monkeypatch.delenv("ORCH_HOT_FILE_GUARD", raising=False)
    mt._hot_file_last_sig.clear()
    return path


PASSPORT = "packages/darwin-kernel/src/passport/passport.ts"


def test_the_signature_is_the_file_set_not_the_slug():
    """Different cards hitting the same files produce the same signature."""
    a = mt._conflict_signature(PASSPORT)
    b = mt._conflict_signature(PASSPORT + ".")
    assert a and a == b


def test_a_signature_starts_with_nobody_on_it():
    assert mt._hot_file_slugs("beethoven", mt._conflict_signature(PASSPORT)) == []


def test_each_failing_card_is_rolled_up():
    sig = mt._conflict_signature(PASSPORT)
    for n in range(3):
        mt._hot_file_record("beethoven", sig, "card-%d" % n)
    assert sorted(mt._hot_file_slugs("beethoven", sig)) == ["card-0", "card-1", "card-2"]


def test_the_same_card_twice_counts_once():
    """The roll counts DISTINCT cards; one card retrying is the other guard's job."""
    sig = mt._conflict_signature(PASSPORT)
    for _ in range(5):
        mt._hot_file_record("beethoven", sig, "card-0")
    assert mt._hot_file_slugs("beethoven", sig) == ["card-0"]


def test_projects_do_not_share_a_roll():
    """The same path in two repos is two different contentions."""
    sig = mt._conflict_signature(PASSPORT)
    mt._hot_file_record("beethoven", sig, "card-0")
    assert mt._hot_file_slugs("tomorrow", sig) == []


def test_different_file_sets_do_not_share_a_roll():
    mt._hot_file_record("beethoven", mt._conflict_signature(PASSPORT), "card-0")
    other = mt._conflict_signature("pages/index.vue")
    assert mt._hot_file_slugs("beethoven", other) == []


def test_a_merge_clears_the_contention():
    """The next card rebases onto a base that carries the change; no grudge."""
    sig = mt._conflict_signature(PASSPORT)
    for n in range(4):
        mt._hot_file_record("beethoven", sig, "card-%d" % n)
    mt._hot_file_clear("beethoven", sig)
    assert mt._hot_file_slugs("beethoven", sig) == []


def test_the_roll_expires():
    sig = mt._conflict_signature(PASSPORT)
    mt._hot_file_record("beethoven", sig, "card-0")
    path = mt._conflict_ledger_path()
    data = json.load(open(path))
    for row in data.values():
        row["at"] = 0          # long ago
    json.dump(data, open(path, "w"))
    assert mt._hot_file_slugs("beethoven", sig) == []


def test_the_roll_is_capped_so_one_hot_file_cannot_grow_forever():
    sig = mt._conflict_signature(PASSPORT)
    for n in range(80):
        mt._hot_file_record("beethoven", sig, "card-%d" % n)
    assert len(mt._hot_file_slugs("beethoven", sig)) <= 50


def test_the_per_task_ledger_still_works_alongside_it():
    """Both live in one file; neither may evict the other."""
    task = {"id": "t1", "slug": "card-0"}
    mt._conflict_ledger_put(task, "abc123abc123")
    sig = mt._conflict_signature(PASSPORT)
    mt._hot_file_record("beethoven", sig, "card-0")
    assert mt._conflict_ledger_get(task) == "abc123abc123"
    assert mt._hot_file_slugs("beethoven", sig) == ["card-0"]
    mt._conflict_ledger_put({"id": "t2", "slug": "card-1"}, "def456def456")
    assert mt._hot_file_slugs("beethoven", sig) == ["card-0"], \
        "a task write evicted the contention roll"


# ── thresholds and switches ──────────────────────────────────────────────────────────

def test_the_default_threshold_lets_the_first_cards_try():
    """Until several have failed there is no evidence the file is contended at all."""
    assert mt._hot_file_threshold() == 3


def test_the_threshold_is_read_at_call_time(monkeypatch):
    monkeypatch.setenv("ORCH_HOT_FILE_SLUG_THRESHOLD", "7")
    assert mt._hot_file_threshold() == 7


@pytest.mark.parametrize("value", ["", "nonsense", "0", "1", "-4"])
def test_the_threshold_never_drops_below_two(monkeypatch, value):
    """A threshold of one would stop the second card ever trying."""
    monkeypatch.setenv("ORCH_HOT_FILE_SLUG_THRESHOLD", value)
    assert mt._hot_file_threshold() >= 2


@pytest.mark.parametrize("value,expected", [
    ("false", False), ("0", False), ("off", False), ("no", False),
    ("true", True), ("1", True), ("", True),
])
def test_the_guard_can_be_turned_off(monkeypatch, value, expected):
    monkeypatch.setenv("ORCH_HOT_FILE_GUARD", value)
    assert mt._hot_file_enabled() is expected


# ── wiring ───────────────────────────────────────────────────────────────────────────

def _conflict_block():
    src = open(mt.__file__.replace(".pyc", ".py")).read()
    start = src.index("CONTENDED FILE: several OTHER cards")
    return src[start:start + 2200]


def test_the_guard_runs_before_the_redo_budget_is_spent():
    block = _conflict_block()
    assert "conflict-contended-file" in block
    assert block.index("_hot_file_slugs") < block.index("_recorded_conflict_signature")


def test_a_card_is_not_counted_against_itself():
    """Its own earlier attempt is the per-task guard's business, not this one's."""
    block = _conflict_block()
    assert "s != slug" in block


def test_the_refusal_names_the_contended_files_and_the_other_cards():
    block = _conflict_block()
    assert "files_hint" in block
    assert "other card(s)" in block


def test_every_path_that_lands_the_work_clears_the_roll():
    """Both of them. The first draft only cleared the fast-forward path, and this test
    caught that `already integrated` -- work that IS in base -- kept the grudge."""
    src = open(mt.__file__.replace(".pyc", ".py")).read()
    landed = [i for i in range(len(src))
              if src.startswith('"state": "MERGED"', i)]
    assert len(landed) >= 2, "expected both the ff-merge and already-integrated paths"
    for at in landed:
        window = src[at:at + 900]
        assert "_hot_file_clear(" in window, window[:400]

"""PROPRIETARY -- Apparently Inc. Trade Secret. Protected under DTSA (18 U.S.C. 1836).

Proof that task_slicer never emits a truncated dependency chain.

Regression cover for QUEUE-DEADLOCK-2026-08-25.md cause 2: the slicer wrote slice-N
without ever writing slice-N-1, leaving slice-N QUEUED with deps pointing at a slug
that does not exist. The dependency predicate only accepts DONE/MERGED, so a
nonexistent blocker is unsatisfiable by construction and the tail of the chain was
unclaimable forever. Eleven live chains were truncated exactly this way.

Pure; no DB, no network. Deterministic.
"""
import pytest

from runner.task_slicer import _insert_chain


def _parts(n, base="p"):
    return [{"slug": "%s-slice-%d" % (base, i), "prompt": "step %d" % i, "deps": []}
            for i in range(1, n + 1)]


def _recorder(fail_slugs=(), fail_once=()):
    """An insert() that records rows and fails for the named slugs.

    `fail_slugs` fail every attempt; `fail_once` fail only their first attempt.
    """
    written, seen = [], {}

    def insert(row):
        slug = row["slug"]
        seen[slug] = seen.get(slug, 0) + 1
        if slug in fail_slugs:
            raise RuntimeError("insert rejected: %s" % slug)
        if slug in fail_once and seen[slug] == 1:
            raise RuntimeError("transient blip: %s" % slug)
        written.append(row)

    return insert, written, seen


def _make_row(part, deps):
    return {"slug": part["slug"], "deps": list(deps)}


def _deps_of(written):
    return {row["slug"]: row["deps"] for row in written}


def _assert_no_dangling(written, landed):
    """Every dep an insert emitted must name a slice that actually landed."""
    known = set(landed)
    for row in written:
        for dep in row["deps"]:
            assert dep in known, "dangling dep %r on %r" % (dep, row["slug"])


def test_clean_run_builds_a_contiguous_chain():
    insert, written, _ = _recorder()
    landed, dropped = _insert_chain(_parts(5), _make_row, lambda s: False, insert)

    assert dropped == []
    assert landed == ["p-slice-%d" % i for i in range(1, 6)]
    deps = _deps_of(written)
    assert deps["p-slice-1"] == []
    for i in range(2, 6):
        assert deps["p-slice-%d" % i] == ["p-slice-%d" % (i - 1)]
    _assert_no_dangling(written, landed)


def test_dropped_middle_slice_never_leaves_a_dangling_dep():
    # THE BUG: slice-3 fails, slices 4 and 5 land pointing at it, and nothing can
    # ever satisfy them. slice-4 must chain off slice-2 instead.
    insert, written, _ = _recorder(fail_slugs={"p-slice-3"})
    landed, dropped = _insert_chain(_parts(5), _make_row, lambda s: False, insert)

    assert dropped == ["p-slice-3"]
    assert landed == ["p-slice-1", "p-slice-2", "p-slice-4", "p-slice-5"]
    deps = _deps_of(written)
    assert deps["p-slice-4"] == ["p-slice-2"]
    assert deps["p-slice-5"] == ["p-slice-4"]
    assert "p-slice-3" not in [d for ds in deps.values() for d in ds]
    _assert_no_dangling(written, landed)


def test_dropped_first_slice_leaves_the_successor_unblocked():
    insert, written, _ = _recorder(fail_slugs={"p-slice-1"})
    landed, dropped = _insert_chain(_parts(3), _make_row, lambda s: False, insert)

    assert dropped == ["p-slice-1"]
    # slice-2 becomes the head of the chain rather than depending on a ghost.
    assert _deps_of(written)["p-slice-2"] == []
    _assert_no_dangling(written, landed)


def test_consecutive_drops_collapse_to_the_last_survivor():
    insert, written, _ = _recorder(fail_slugs={"p-slice-2", "p-slice-3"})
    landed, dropped = _insert_chain(_parts(4), _make_row, lambda s: False, insert)

    assert dropped == ["p-slice-2", "p-slice-3"]
    assert _deps_of(written)["p-slice-4"] == ["p-slice-1"]
    _assert_no_dangling(written, landed)


def test_every_slice_dropped_reports_nothing_landed():
    insert, written, _ = _recorder(fail_slugs={"p-slice-1", "p-slice-2"})
    landed, dropped = _insert_chain(_parts(2), _make_row, lambda s: False, insert)

    assert landed == []
    assert dropped == ["p-slice-1", "p-slice-2"]
    assert written == []


def test_transient_failure_is_retried_and_keeps_the_chain_intact():
    insert, written, seen = _recorder(fail_once={"p-slice-2"})
    landed, dropped = _insert_chain(_parts(3), _make_row, lambda s: False, insert)

    assert dropped == []
    assert seen["p-slice-2"] == 2, "a transient insert failure must be retried once"
    assert _deps_of(written)["p-slice-3"] == ["p-slice-2"]
    _assert_no_dangling(written, landed)


def test_attempts_of_one_disables_the_retry():
    insert, written, seen = _recorder(fail_once={"p-slice-2"})
    landed, dropped = _insert_chain(
        _parts(3), _make_row, lambda s: False, insert, attempts=1)

    assert dropped == ["p-slice-2"]
    assert seen["p-slice-2"] == 1
    assert _deps_of(written)["p-slice-3"] == ["p-slice-1"]
    _assert_no_dangling(written, landed)


def test_existing_slices_are_skipped_and_anchor_the_chain():
    # Idempotent re-entry (2026-07-10 guard): a rerun must not duplicate rows.
    insert, written, _ = _recorder()
    present = {"p-slice-1", "p-slice-2"}
    landed, dropped = _insert_chain(
        _parts(4), _make_row, lambda s: s in present, insert)

    assert dropped == []
    assert landed == ["p-slice-%d" % i for i in range(1, 5)]
    assert [row["slug"] for row in written] == ["p-slice-3", "p-slice-4"]
    assert _deps_of(written)["p-slice-3"] == ["p-slice-2"]
    _assert_no_dangling(written, landed)


def test_rerun_fills_a_hole_left_by_an_earlier_partial_decomposition():
    # The live shape: slices 1, 2, 4, 5 exist and 3 is missing. A rerun must insert
    # only slice-3, chained off its surviving predecessor.
    insert, written, _ = _recorder()
    present = {"p-slice-1", "p-slice-2", "p-slice-4", "p-slice-5"}
    landed, dropped = _insert_chain(
        _parts(5), _make_row, lambda s: s in present, insert)

    assert dropped == []
    assert [row["slug"] for row in written] == ["p-slice-3"]
    assert _deps_of(written)["p-slice-3"] == ["p-slice-2"]
    assert landed == ["p-slice-%d" % i for i in range(1, 6)]


def test_planned_deps_on_the_part_are_ignored_in_favour_of_what_landed():
    # slice_task()/ai_slice_task() precompute deps optimistically; _insert_chain must
    # not trust them, or the truncation bug comes straight back.
    parts = _parts(3)
    parts[2]["deps"] = ["p-slice-2"]
    insert, written, _ = _recorder(fail_slugs={"p-slice-2"})
    landed, dropped = _insert_chain(parts, _make_row, lambda s: False, insert)

    assert dropped == ["p-slice-2"]
    assert _deps_of(written)["p-slice-3"] == ["p-slice-1"]
    _assert_no_dangling(written, landed)


@pytest.mark.parametrize("failing", [
    set(), {"p-slice-1"}, {"p-slice-3"}, {"p-slice-5"},
    {"p-slice-2", "p-slice-4"}, {"p-slice-1", "p-slice-2", "p-slice-3"},
])
def test_no_failure_pattern_can_produce_an_unsatisfiable_edge(failing):
    insert, written, _ = _recorder(fail_slugs=failing)
    landed, dropped = _insert_chain(_parts(5), _make_row, lambda s: False, insert)

    assert set(landed).isdisjoint(failing)
    assert set(dropped) == failing
    _assert_no_dangling(written, landed)

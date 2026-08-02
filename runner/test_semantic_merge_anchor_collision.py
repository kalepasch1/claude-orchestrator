"""Regression tests for semantic_merge._three_way_merge() — the silent-overwrite class.

Root cause B2 (2026-08-02). difflib opcode ranges are half-open, so a pure INSERTION is
zero-width (i1 == i2). The old overlap test `ai1 < bi2 and bi1 < ai2` is False for every
insertion, so two edits anchored at the SAME base offset were declared non-overlapping,
both landed in `edits = {}` keyed by i1, and B's entry silently clobbered A's. One side's
code disappeared with no conflict and no error, reported as a successful auto-merge.

The contract these tests pin down:
    a merge either keeps BOTH sides' code, or it returns None (conflict).
    It must NEVER return a result that is missing one side's contribution.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import semantic_merge  # noqa: E402


def L(text):
    """Text -> the keepends line list _three_way_merge operates on."""
    return text.splitlines(keepends=True)


def merged_text(base, a, b):
    out = semantic_merge._three_way_merge(L(base), L(a), L(b))
    return None if out is None else "".join(out)


# ---------------------------------------------------------------------------
# _ranges_conflict: the zero-width truth table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("a1,a2,b1,b2,expected,why", [
    (5, 5, 5, 5, True,  "two insertions at the same anchor — the clobber bug"),
    (5, 5, 9, 9, False, "two insertions at different anchors are independent"),
    (5, 5, 3, 8, True,  "insertion strictly inside a replaced span"),
    (5, 5, 5, 8, True,  "insertion on the leading edge of a replaced span"),
    (8, 8, 5, 8, True,  "insertion on the trailing edge of a replaced span"),
    (9, 9, 5, 8, False, "insertion clear of the replaced span"),
    (2, 6, 4, 9, True,  "ordinary overlapping replacements"),
    (2, 6, 6, 9, False, "adjacent, non-overlapping replacements"),
])
def test_ranges_conflict_truth_table(a1, a2, b1, b2, expected, why):
    assert semantic_merge._ranges_conflict(a1, a2, b1, b2) is expected, why
    # the predicate must be symmetric — order of the two sides cannot change the verdict
    assert semantic_merge._ranges_conflict(b1, b2, a1, a2) is expected, why + " (symmetric)"


def test_old_overlap_test_would_have_missed_the_collision():
    """Pin the exact expression that was wrong, so nobody reintroduces it."""
    a1 = a2 = b1 = b2 = 5                      # two insertions at the same anchor
    old_test = (a1 < b2 and b1 < a2)           # the pre-fix condition
    assert old_test is False, "the old test really did miss same-anchor insertions"
    assert semantic_merge._ranges_conflict(a1, a2, b1, b2) is True


# ---------------------------------------------------------------------------
# the collision itself
# ---------------------------------------------------------------------------

BASE = "import os\n\ndef run():\n    return compute()\n\ndef compute():\n    return 1\n"


def test_same_anchor_insertions_conflict_instead_of_dropping_one_side():
    a = BASE.replace("def run():\n", "def run():\n    setup_a()\n")
    b = BASE.replace("def run():\n", "def run():\n    setup_b()\n")
    out = merged_text(BASE, a, b)
    if out is not None:
        # A silent overwrite is the bug. If a result is produced at all it must keep BOTH.
        assert "setup_a()" in out and "setup_b()" in out, (
            "one side's insertion was silently discarded:\n" + out)
    assert out is None, "same-anchor insertions are unorderable and must CONFLICT"


def test_improvement_miner_shape_binding_is_never_dropped():
    """The real-world shape: side A restores a binding, side B inserts at the same anchor.

    improvement_miner lost `proposal_only = bool(capacity["limited"])` exactly this way,
    while every `if proposal_only:` reader survived — a module that imports cleanly and
    raises NameError at runtime.
    """
    base = ("def mine(capacity):\n"
            "    rows = fetch()\n"
            "    for row in rows:\n"
            "        row['status'] = 'proposed' if proposal_only else 'for_review'\n"
            "    return rows\n")
    a = base.replace("    rows = fetch()\n",
                     "    rows = fetch()\n    proposal_only = bool(capacity['limited'])\n")
    b = base.replace("    rows = fetch()\n",
                     "    rows = fetch()\n    audit_log('mine')\n")
    out = merged_text(base, a, b)
    assert out is None or "proposal_only =" in out, (
        "the assignment was dropped while its readers survived — the exact NameError "
        "class that wedged the improvement queue for three weeks:\n" + str(out))


def test_no_result_ever_loses_a_side():
    """Property check across every anchor pair — never a partial result."""
    lines = BASE.splitlines(keepends=True)
    for i in range(len(lines) + 1):
        for j in range(len(lines) + 1):
            a = "".join(lines[:i] + ["    MARKER_A = 1\n"] + lines[i:])
            b = "".join(lines[:j] + ["    MARKER_B = 2\n"] + lines[j:])
            out = merged_text(BASE, a, b)
            if out is None:
                continue
            assert "MARKER_A" in out and "MARKER_B" in out, (
                "anchors %d/%d produced a merge missing one side:\n%s" % (i, j, out))


# ---------------------------------------------------------------------------
# end-of-file appends — the other silent drop
# ---------------------------------------------------------------------------

def test_append_at_eof_is_not_dropped():
    """`while i < len(base)` never applied an edit anchored at i == len(base)."""
    a = BASE + "\ndef brand_new():\n    return 'shiny'\n"
    b = BASE.replace("import os\n", "import os\nimport sys\n")
    out = merged_text(BASE, a, b)
    assert out is not None, "an EOF append and a header import do not overlap"
    assert "def brand_new():" in out, "the appended function was silently dropped:\n" + out
    assert "import sys" in out


def test_append_from_both_sides_conflicts():
    a = BASE + "\ndef from_a():\n    return 'a'\n"
    b = BASE + "\ndef from_b():\n    return 'b'\n"
    out = merged_text(BASE, a, b)
    if out is not None:
        assert "from_a" in out and "from_b" in out, "an EOF append was clobbered:\n" + out


# ---------------------------------------------------------------------------
# capability must not regress — genuinely independent edits still merge
# ---------------------------------------------------------------------------

def test_independent_edits_still_merge_cleanly():
    a = BASE.replace("import os\n", "import os\nimport sys\n")
    b = BASE.replace("    return 1\n", "    return 99\n")
    out = merged_text(BASE, a, b)
    assert out is not None, "far-apart edits must still auto-merge"
    assert "import sys" in out and "return 99" in out


def test_identical_edits_on_both_sides_are_not_a_conflict():
    a = b = BASE.replace("import os\n", "import os\nimport sys\n")
    out = merged_text(BASE, a, b)
    assert out is not None and "import sys" in out
    assert out.count("import sys") == 1, "an identical edit must not be applied twice"


def test_unchanged_inputs_round_trip():
    assert merged_text(BASE, BASE, BASE) == BASE

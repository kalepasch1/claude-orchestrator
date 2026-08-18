"""PROPRIETARY -- Apparently Inc. Trade Secret. Protected under DTSA (18 U.S.C. 1836).

Proof for auto_decompose fan-out cap + idempotency guard (swarm backlog rank 6).
Pure; no DB, no network. Deterministic.
"""
from runner.auto_decompose import (
    decompose, should_decompose, is_decomposition_child, _MAX_CHILDREN,
)


def _numbered(n):
    return "\n".join("%d. do task number %d" % (i, i) for i in range(1, n + 1))


def test_is_decomposition_child_detects_slice_item_file():
    assert is_decomposition_child("foo-item-3")
    assert is_decomposition_child("foo-file-0")
    assert is_decomposition_child("foo-slice-12")
    assert not is_decomposition_child("foo")
    assert not is_decomposition_child("recover-missing-branch-foo")
    assert not is_decomposition_child(None)


def test_child_is_never_re_decomposed():
    # A prompt that WOULD decompose (10 items), but the slug is already a child.
    out = decompose("parent-item-2", _numbered(10))
    assert len(out) == 1
    assert out[0]["slug"] == "parent-item-2"
    # should_decompose agrees
    assert should_decompose(_numbered(10), "parent-item-2") is False
    assert should_decompose(_numbered(10), "fresh-parent") is True


def test_fanout_capped_with_remainder_never_dropped():
    out = decompose("bigparent", _numbered(12))
    # _MAX_CHILDREN children + exactly one remainder
    assert len(out) == _MAX_CHILDREN + 1
    assert out[-1]["slug"] == "bigparent-remainder"
    # overflow items 9..12 are preserved in the remainder, not dropped
    rem = out[-1]["prompt"]
    for i in range(_MAX_CHILDREN + 1, 13):
        assert ("number %d" % i) in rem


def test_children_carry_deterministic_dedup_key():
    a = decompose("p", _numbered(5))
    b = decompose("p", _numbered(5))
    assert [t["slug"] for t in a] == [t["slug"] for t in b]           # deterministic
    assert all(t["dedup_key"] == t["slug"] for t in a)                # coalescible
    assert len(a) == 5                                                # under cap: no remainder


def test_no_decomposition_returns_single_with_key():
    out = decompose("solo", "just one small thing, no numbered items")
    assert len(out) == 1
    assert out[0]["slug"] == "solo"
    assert out[0]["dedup_key"] == "solo"

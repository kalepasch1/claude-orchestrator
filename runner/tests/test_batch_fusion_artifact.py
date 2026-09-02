"""A fused batch is N tasks delivered by ONE commit, and nothing recorded which.

distribute_outcome wrote MERGED with no artifact_commit, certified by a boolean.
merge_truth correctly turned that into PHANTOM_UNVERIFIED, so every fused batch
produced phantom rows by construction and the evidence that would clear them was
never written down.

Supplying the sha exposes the second half: merge_truth refuses to let one commit
be the artifact_commit of two tasks. That rule stops task A's commit being pasted
onto task B to fake completion and it is right about that; it cannot tell that
case from a deliberate fusion, which is what JUSTIFIED_MARKER is for.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import batch_fusion
import merge_truth

SHA = "a" * 40


def _batch(n=3):
    return [{"id": f"id{i}", "slug": f"slug-{i}", "prompt": "p" * 10,
             "project_id": "proj"} for i in range(n)]


@pytest.fixture
def captured(monkeypatch):
    seen = []
    monkeypatch.setattr(merge_truth, "guarded_task_update",
                        lambda t, patch, **kw: seen.append((t, dict(patch))))
    monkeypatch.setattr(batch_fusion.db, "update",
                        lambda table, where, patch: seen.append((where, dict(patch))))
    return seen


def test_no_sha_still_writes_no_artifact(captured):
    """The honest old behaviour is preserved for callers that record nothing."""
    batch_fusion.distribute_outcome(_batch(), "out", merged=True)
    assert captured
    assert all("artifact_commit" not in p for _, p in captured)


def test_the_sha_reaches_every_member(captured):
    batch_fusion.distribute_outcome(_batch(3), "out", merged=True, artifact_commit=SHA)
    assert len(captured) == 3
    assert all(p["artifact_commit"] == SHA for _, p in captured)


def test_every_member_carries_the_justification(captured):
    batch_fusion.distribute_outcome(_batch(3), "out", merged=True, artifact_commit=SHA)
    for _, p in captured:
        assert merge_truth.JUSTIFIED_MARKER in p["note"]


def test_the_justification_is_auditable(captured):
    """It must name the batch and the siblings, not just assert an exemption."""
    batch_fusion.distribute_outcome(_batch(3), "out", merged=True, artifact_commit=SHA)
    note = captured[0][1]["note"]
    assert "fusion-" in note, "the batch key must be named"
    assert "3 tasks" in note
    assert SHA[:12] in note
    assert "slug-0" in note and "slug-1" in note


def test_a_single_task_batch_gets_no_override(captured):
    """One task is not a fusion, so the duplicate rule must keep applying."""
    batch_fusion.distribute_outcome(_batch(1), "out", merged=True, artifact_commit=SHA)
    assert captured[0][1]["artifact_commit"] == SHA
    assert merge_truth.JUSTIFIED_MARKER not in captured[0][1]["note"]


def test_a_failed_batch_records_neither(captured):
    batch_fusion.distribute_outcome(_batch(3), "out", merged=False, artifact_commit=SHA)
    for _, p in captured:
        assert p["state"] == "BLOCKED"
        assert "artifact_commit" not in p
        assert merge_truth.JUSTIFIED_MARKER not in p["note"]


def test_a_blank_sha_is_treated_as_no_sha(captured):
    batch_fusion.distribute_outcome(_batch(2), "out", merged=True, artifact_commit="   ")
    assert all("artifact_commit" not in p for _, p in captured)
    assert all(merge_truth.JUSTIFIED_MARKER not in p["note"] for _, p in captured)


def test_the_cost_share_survives_the_new_note(captured):
    batch_fusion.distribute_outcome(_batch(2), "out", merged=True,
                                    cost={"usd": 0.02}, artifact_commit=SHA)
    assert all("cost share=$" in p["note"] for _, p in captured)


def test_merge_truth_accepts_a_justified_shared_commit():
    """The end of the chain: the marker is what makes the shared citation legal."""
    note = f"[batch-fusion] {merge_truth.JUSTIFIED_MARKER} fused delivery"
    assert merge_truth.JUSTIFIED_MARKER in note

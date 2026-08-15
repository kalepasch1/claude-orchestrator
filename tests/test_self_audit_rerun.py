"""PROPRIETARY -- Apparently Inc. Trade Secret. Protected under DTSA (18 U.S.C. 1836)."""
from runner.self_audit_rerun import self_audit

RECS = [{"slug": "a", "sha": "1"}, {"slug": "b", "sha": "2"}, {"slug": "c", "sha": "3"}]


def test_all_reproduce_keeps_everything():
    r = self_audit(RECS, rerun_gate=lambda rec: True)
    assert r.total == 3 and r.reproduced == 3 and r.demoted == 0
    assert all(o.action == "keep" for o in r.outcomes)
    assert r.drift_rate == 0.0


def test_non_reproducible_is_demoted_and_requeued():
    r = self_audit(RECS, rerun_gate=lambda rec: rec["slug"] != "b")
    assert r.demoted == 1
    demoted = [o for o in r.outcomes if o.action == "demote_and_requeue"]
    assert len(demoted) == 1 and demoted[0].slug == "b"
    assert round(r.drift_rate, 3) == round(1 / 3, 3)


def test_gate_that_raises_counts_as_not_reproduced():
    def boom(rec):
        raise RuntimeError("gate could not run")

    r = self_audit([{"slug": "x", "sha": "9"}], rerun_gate=boom)
    assert r.demoted == 1 and r.reproduced == 0


def test_empty_is_safe():
    r = self_audit([], rerun_gate=lambda rec: True)
    assert r.total == 0 and r.drift_rate == 0.0

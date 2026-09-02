"""Twenty-eight cards, one broken symbol, twenty-eight repair runs.

2026-09-02, this host's merge-train log:

    REGRESSFAIL events                                197
    distinct findings behind them                      43
    top 5 findings                          121 events (61%)

    darwn     [fabricated_critical_return] src/utils/zkPrivilegeProof.ts
                                             37 events / 28 distinct cards
    tomorrow  [fabricated_critical_return] server/utils/otc/ecp/reputation...
                                             26 events / 25 distinct cards
    tomorrow  [missing] scripts/reconcile-evidence.mjs::primeCaches
                                             12 events / 12 distinct cards

The guard itself is right and stays fail-closed. Verified by hand before writing a line
of this: `primeCaches` IS exported in tomorrow's `main` and `orchestrator/dev`, and IS
absent from every candidate branch it blocked -- those branches really would delete it.

What was wrong is the accounting. Each of those events costs a rebase, a full regression
scan, and under MERGE_REGRESSION_REDO_CAP an agentic_repair run handed the same directive
about the same symbol -- twenty-eight separate times for one cause. This is the hot-file
rule the operator approved on 2026-09-02, generalised from conflicts to regressions on
their instruction ("the same hot-file rule you already approved, generalised").

The first `threshold` cards keep their full repair budget: one of them may genuinely
restore the symbol, and until several have failed there is no evidence the cause is
shared at all.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import merge_train  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path))
    monkeypatch.setattr(merge_train, "_regression_last_sig", {})
    merge_train._conflict_ledger_load.cache_clear() if hasattr(
        merge_train._conflict_ledger_load, "cache_clear") else None
    yield


# ── signature identity ────────────────────────────────────────────────────────

def test_two_cards_with_the_same_cause_produce_one_signature():
    """The real strings, copied from the log. If these differ, nothing else works."""
    a = ("repair 1/2; [missing] scripts/reconcile-evidence.mjs::primeCaches: exported "
         "`primeCaches` existed in scripts/reconcile-evidence.mjs")
    b = ("repair 2/2; [missing] scripts/reconcile-evidence.mjs::primeCaches: exported "
         "`primeCaches` existed in scripts/reconcile-evidence.mjs at line 99")
    assert merge_train._regression_signature(a) == merge_train._regression_signature(b)
    assert merge_train._regression_signature(a)


def test_the_quarantined_prefix_does_not_split_a_cause():
    """The log carries the same finding both with and without this prefix."""
    a = "SILENT STUB / SHADOWED RE-EXPORT — [fabricated_critical_return] src/utils/zkPrivilegeProof.ts:12: x"
    b = "QUARANTINED; " + a
    assert merge_train._regression_signature(a) == merge_train._regression_signature(b)


def test_a_trailing_and_n_more_does_not_split_a_cause():
    base = "[missing] a/b.mjs::foo: gone"
    assert (merge_train._regression_signature(base)
            == merge_train._regression_signature(base + " ... and 4 more"))


def test_different_symbols_are_different_causes():
    a = "[missing] a/b.mjs::foo: gone"
    b = "[missing] a/b.mjs::bar: gone"
    assert merge_train._regression_signature(a) != merge_train._regression_signature(b)


def test_different_files_are_different_causes():
    a = "[missing] a/b.mjs::foo: gone"
    b = "[missing] c/d.mjs::foo: gone"
    assert merge_train._regression_signature(a) != merge_train._regression_signature(b)


def test_empty_detail_has_no_signature():
    assert merge_train._regression_signature("") == ""
    assert merge_train._regression_signature(None) == ""


# ── the roll ──────────────────────────────────────────────────────────────────

def test_the_roll_counts_distinct_slugs_not_attempts():
    sig = "[missing] a/b.mjs::foo"
    assert merge_train._regression_record("p", sig, "s1") == 1
    assert merge_train._regression_record("p", sig, "s1") == 1     # same card again
    assert merge_train._regression_record("p", sig, "s2") == 2


def test_projects_do_not_share_a_roll():
    sig = "[missing] a/b.mjs::foo"
    merge_train._regression_record("p1", sig, "s1")
    assert merge_train._regression_record("p2", sig, "s2") == 1


def test_a_merge_clears_the_roll():
    sig = "[missing] a/b.mjs::foo"
    merge_train._regression_record("p", sig, "s1")
    merge_train._regression_record("p", sig, "s2")
    merge_train._regression_clear("p", sig)
    assert merge_train._regression_slugs("p", sig) == []


def test_the_roll_does_not_collide_with_the_hot_file_roll():
    """Both live in one ledger file; a shared key would cross-contaminate two guards."""
    sig = "same-string"
    merge_train._regression_record("p", sig, "r1")
    merge_train._hot_file_record("p", sig, "h1")
    assert merge_train._regression_slugs("p", sig) == ["r1"]
    assert merge_train._hot_file_slugs("p", sig) == ["h1"]


# ── the decision ──────────────────────────────────────────────────────────────

def _stub_train(monkeypatch, tmp_path):
    """Neutralise everything _quarantine_regression_failure touches except the decision."""
    calls = {"repair": 0, "patches": [], "coord": [], "logs": [], "retired": []}
    monkeypatch.setattr(merge_train.agentic_repair, "repair_patch",
                        lambda *a, **k: calls.__setitem__("repair", calls["repair"] + 1)
                        or {"state": "QUEUED"})
    monkeypatch.setattr(merge_train, "_task_patch",
                        lambda task, patch: calls["patches"].append(patch))
    monkeypatch.setattr(merge_train, "_retire_card",
                        lambda cid, why: calls["retired"].append(why))
    monkeypatch.setattr(merge_train, "_attribute_train_outcome", lambda *a, **k: None)
    monkeypatch.setattr(merge_train, "_log",
                        lambda *a, **k: calls["logs"].append(a))
    monkeypatch.setattr(merge_train.db, "insert",
                        lambda table, row, **k: calls["coord"].append((table, row)))
    monkeypatch.setattr(merge_train, "_pm", None)
    return calls


DETAIL = ("[missing] scripts/reconcile-evidence.mjs::primeCaches: exported `primeCaches` "
          "existed in scripts/reconcile-evidence.mjs")


def _block(calls, slug):
    return merge_train._quarantine_regression_failure(
        "/repo", {"id": "c-" + slug}, slug,
        {"transient_retries": 0}, "tomorrow", "agent/" + slug, "main", DETAIL)


def test_the_first_cards_keep_their_full_repair_budget(monkeypatch, tmp_path):
    """Until several have failed there is no evidence the cause is shared."""
    calls = _stub_train(monkeypatch, tmp_path)
    monkeypatch.setenv("ORCH_SHARED_REGRESSION_THRESHOLD", "3")
    for slug in ("s1", "s2", "s3"):
        assert _block(calls, slug) == "regressfail"
    assert calls["repair"] == 3, "an early card was denied its repair attempt"
    assert all(p.get("state") != "BLOCKED" for p in calls["patches"])


def test_the_fourth_card_is_parked_without_a_repair(monkeypatch, tmp_path):
    calls = _stub_train(monkeypatch, tmp_path)
    monkeypatch.setenv("ORCH_SHARED_REGRESSION_THRESHOLD", "3")
    for slug in ("s1", "s2", "s3", "s4"):
        _block(calls, slug)
    assert calls["repair"] == 3, "the 4th card spent a repair on a cause already known"
    assert calls["patches"][-1]["state"] == "BLOCKED"


def test_the_parked_card_names_the_cause_and_its_siblings(monkeypatch, tmp_path):
    calls = _stub_train(monkeypatch, tmp_path)
    monkeypatch.setenv("ORCH_SHARED_REGRESSION_THRESHOLD", "3")
    for slug in ("s1", "s2", "s3", "s4"):
        _block(calls, slug)
    note = calls["patches"][-1]["note"]
    assert "SHARED CAUSE" in note
    assert "primeCaches" in note
    assert "s1" in note and "s2" in note, "an operator cannot find the sibling cards"


def test_exactly_one_coordination_task_per_cause(monkeypatch, tmp_path):
    """One per cause, not one per card -- the whole complaint about the old path."""
    calls = _stub_train(monkeypatch, tmp_path)
    monkeypatch.setenv("ORCH_SHARED_REGRESSION_THRESHOLD", "3")
    for slug in ("s1", "s2", "s3", "s4", "s5", "s6"):
        _block(calls, slug)
    shared = [r for _t, r in calls["coord"]
              if r.get("task_type") == "merge_regression_shared_cause"]
    assert len(shared) == 1, "filed %d shared-cause alerts" % len(shared)


def test_a_second_cause_gets_its_own_alert(monkeypatch, tmp_path):
    calls = _stub_train(monkeypatch, tmp_path)
    monkeypatch.setenv("ORCH_SHARED_REGRESSION_THRESHOLD", "2")
    other = "[missing] scripts/other.mjs::somethingElse: gone"
    for slug in ("a1", "a2", "a3"):
        _block(calls, slug)
    for slug in ("b1", "b2", "b3"):
        merge_train._quarantine_regression_failure(
            "/repo", {"id": "c-" + slug}, slug, {"transient_retries": 0},
            "tomorrow", "agent/" + slug, "main", other)
    shared = [r for _t, r in calls["coord"]
              if r.get("task_type") == "merge_regression_shared_cause"]
    assert len(shared) == 2


def test_the_verdict_is_still_regressfail(monkeypatch, tmp_path):
    """Parking is about the COST, not the verdict. Nothing merges here."""
    calls = _stub_train(monkeypatch, tmp_path)
    monkeypatch.setenv("ORCH_SHARED_REGRESSION_THRESHOLD", "2")
    outcomes = [_block(calls, s) for s in ("s1", "s2", "s3")]
    assert outcomes == ["regressfail"] * 3


def test_the_guard_can_be_turned_off(monkeypatch, tmp_path):
    calls = _stub_train(monkeypatch, tmp_path)
    monkeypatch.setenv("ORCH_SHARED_REGRESSION_GUARD", "false")
    monkeypatch.setenv("ORCH_SHARED_REGRESSION_THRESHOLD", "2")
    for slug in ("s1", "s2", "s3", "s4"):
        _block(calls, slug)
    assert calls["repair"] == 4
    assert all(p.get("state") != "BLOCKED" for p in calls["patches"])


def test_a_broken_ledger_never_blocks_a_verdict(monkeypatch, tmp_path):
    """Fail-open. The guard must never be the reason a candidate is not judged."""
    calls = _stub_train(monkeypatch, tmp_path)
    monkeypatch.setenv("ORCH_SHARED_REGRESSION_THRESHOLD", "2")

    def _boom(*a, **k):
        raise OSError("ledger on fire")

    monkeypatch.setattr(merge_train, "_regression_record", _boom)
    assert _block(calls, "s1") == "regressfail"
    assert calls["repair"] == 1, "the card lost its repair to a ledger error"


def test_a_finding_with_no_signature_is_left_alone(monkeypatch, tmp_path):
    calls = _stub_train(monkeypatch, tmp_path)
    monkeypatch.setenv("ORCH_SHARED_REGRESSION_THRESHOLD", "2")
    for slug in ("s1", "s2", "s3"):
        merge_train._quarantine_regression_failure(
            "/repo", {"id": slug}, slug, {"transient_retries": 0},
            "tomorrow", "agent/" + slug, "main", "")
    assert calls["repair"] == 3


def test_threshold_floor_is_two():
    """A threshold of 1 would park the very first card on no evidence at all."""
    import os as _os
    _os.environ["ORCH_SHARED_REGRESSION_THRESHOLD"] = "1"
    try:
        assert merge_train._shared_regression_threshold() == 2
    finally:
        _os.environ.pop("ORCH_SHARED_REGRESSION_THRESHOLD", None)

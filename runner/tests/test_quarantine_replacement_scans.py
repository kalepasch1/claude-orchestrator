"""The quarantine replacement passes must see every QUEUED row.

Both were capped, recency-ordered scans that db's truncated-scan detector had
been reporting in the live logs: repair_misclassified 3502 times,
dedupe_replacements 2619.

A partial window is worse here than an undercount because both functions WRITE.
dedupe_replacements parks duplicates as DECOMPOSED, and a dedupe pass has to see
the whole group to know which member is the newest -- an arbitrary suffix of the
group is not a smaller version of the same job. Both also mutate updated_at,
which is the very column the window was ordered by, so rows churned in and out
of consideration between passes.

Pure: db is stubbed, no network.
"""
import os
import sys

import pytest

_RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNNER not in sys.path:
    sys.path.insert(0, _RUNNER)

import blocker_quarantine as bq  # noqa: E402


def _replacement(n, slug, updated):
    return {"id": f"t{n}", "slug": slug, "state": "QUEUED",
            "note": f"{bq.MARK}: replacement for {slug} category=legal",
            "updated_at": updated, "project_id": "p1",
            "base_branch": "master", "kind": "build"}


@pytest.fixture()
def stub(monkeypatch):
    state = {"rows": [], "calls": [], "updates": []}

    def fake_select_all(table, params=None, **kwargs):
        state["calls"].append((table, dict(params or {}), dict(kwargs)))
        return list(state["rows"])

    def fake_update(table, match, patch):
        state["updates"].append((match.get("id"), patch))
        return True

    monkeypatch.setattr(bq.db, "select_all", fake_select_all)
    monkeypatch.setattr(bq.db, "update", fake_update)
    # repair_misclassified also looks the ORIGINAL quarantined row up by slug via
    # db.select; without this it reaches the real client and dies on the
    # import-time SUPABASE_URL/KEY check instead of exercising the scan.
    monkeypatch.setattr(bq.db, "select", lambda table, params=None: [])
    monkeypatch.setenv("ORCH_QUARANTINE_REPAIR", "true")
    return state


class TestDedupeSeesWholeGroups:
    def test_duplicates_beyond_the_old_cap_are_collapsed(self, stub):
        """One slug with 1500 duplicates; the old limit of 1000 saw a suffix."""
        stub["rows"] = [_replacement(i, "feat-x", f"2026-08-24T00:{i:04d}")
                        for i in range(1500)]
        out = bq.dedupe_replacements()
        assert out["collapsed"] == 1499, "every duplicate but the newest is parked"

    def test_newest_is_kept(self, stub):
        """The order is load-bearing: items[0] is the survivor."""
        stub["rows"] = [_replacement(0, "feat-x", "2026-08-24T03:00:00"),
                        _replacement(1, "feat-x", "2026-08-24T02:00:00"),
                        _replacement(2, "feat-x", "2026-08-24T01:00:00")]
        bq.dedupe_replacements()
        parked = {tid for tid, _p in stub["updates"]}
        assert parked == {"t1", "t2"}

    def test_parked_rows_are_decomposed_not_deleted(self, stub):
        stub["rows"] = [_replacement(0, "feat-x", "2026-08-24T02:00:00"),
                        _replacement(1, "feat-x", "2026-08-24T01:00:00")]
        bq.dedupe_replacements()
        _tid, patch = stub["updates"][0]
        assert patch["state"] == "DECOMPOSED"

    def test_a_single_replacement_is_left_alone(self, stub):
        stub["rows"] = [_replacement(0, "feat-x", "2026-08-24T01:00:00")]
        assert bq.dedupe_replacements()["collapsed"] == 0
        assert stub["updates"] == []

    def test_unrelated_queued_rows_are_ignored(self, stub):
        stub["rows"] = [{"id": "z", "slug": "other", "state": "QUEUED",
                         "note": "ordinary task", "updated_at": "2026-08-24T01:00:00"}]
        assert bq.dedupe_replacements()["collapsed"] == 0


class TestScansArePagedAndOrdered:
    def test_dedupe_uses_the_paging_helper_without_a_limit(self, stub):
        stub["rows"] = [_replacement(0, "feat-x", "2026-08-24T01:00:00")]
        bq.dedupe_replacements()
        _table, params, kwargs = stub["calls"][0]
        assert "limit" not in params
        assert kwargs.get("order") == "updated_at.desc"

    def test_repair_uses_the_paging_helper_without_a_limit(self, stub):
        stub["rows"] = [_replacement(0, "feat-x", "2026-08-24T01:00:00")]
        bq.repair_misclassified()
        _table, params, kwargs = stub["calls"][0]
        assert "limit" not in params
        assert kwargs.get("order") == "updated_at.desc"

    @pytest.mark.parametrize("fn,small", [("dedupe_replacements", 5),
                                          ("repair_misclassified", 5)])
    def test_budget_floor_holds(self, stub, fn, small):
        """A small caller value must not reintroduce a narrow horizon."""
        stub["rows"] = [_replacement(0, "feat-x", "2026-08-24T01:00:00")]
        getattr(bq, fn)(limit=small)
        _table, _params, kwargs = stub["calls"][0]
        assert kwargs.get("max_rows") >= 10000

    def test_state_filter_is_still_server_side(self, stub):
        stub["rows"] = []
        bq.dedupe_replacements()
        _table, params, _kwargs = stub["calls"][0]
        assert params.get("state") == "eq.QUEUED"


class TestFailSoft:
    def test_repair_respects_its_kill_switch(self, stub, monkeypatch):
        monkeypatch.setenv("ORCH_QUARANTINE_REPAIR", "false")
        stub["rows"] = [_replacement(0, "feat-x", "2026-08-24T01:00:00")]
        assert bq.repair_misclassified() == {"checked": 0, "repaired": 0}
        assert stub["calls"] == []

    def test_empty_queue_is_fail_soft(self, stub):
        stub["rows"] = []
        assert bq.dedupe_replacements()["collapsed"] == 0

    def test_a_failing_update_does_not_abort_the_pass(self, stub, monkeypatch):
        stub["rows"] = [_replacement(i, "feat-x", f"2026-08-24T0{i}:00:00")
                        for i in range(3)]

        def boom(table, match, patch):
            raise RuntimeError("write failed")

        monkeypatch.setattr(bq.db, "update", boom)
        assert bq.dedupe_replacements()["collapsed"] == 0

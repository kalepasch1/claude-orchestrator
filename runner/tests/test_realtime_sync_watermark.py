"""A sync layer that drops changes is worse than no sync layer.

realtime_sync polls with a watermark cursor: `updated_at > wm`, under a LIMIT. The sort
order therefore decides WHICH changes come back when more rows changed than the limit
allows — and the configured order was `updated_at.desc`. So a burst of more than 20 task
updates between polls returned the newest 20, advanced the watermark past all of them, and
made every older change in that window unreachable forever: `> wm` can never match it
again. Silent, permanent loss, in the one component whose job is to miss nothing.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import realtime_sync as rs  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_state():
    rs._watermarks.clear()
    yield
    rs._watermarks.clear()


class FakeDB:
    """Rows ordered/limited the way PostgREST would."""

    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def select(self, _table, params=None):
        params = params or {}
        self.queries.append(dict(params))
        rows = list(self.rows)
        gt = (params.get("updated_at") or "")
        if gt.startswith("gt."):
            bound = gt[3:]
            rows = [r for r in rows if r["updated_at"] > bound]
        rows.sort(key=lambda r: r["updated_at"],
                  reverse=str(params.get("order", "")).endswith(".desc"))
        limit = int(params.get("limit") or 0)
        return rows[:limit] if limit else rows


def _rows(n, start=1):
    return [{"id": i, "updated_at": f"2026-08-24T00:00:{i:02d}Z"}
            for i in range(start, start + n)]


PARAMS = {"select": "id,updated_at", "order": "updated_at.desc", "limit": "20"}


class TestCursorDirection:
    def test_the_first_poll_seeds_at_now_and_does_not_replay_history(self, monkeypatch):
        db = FakeDB(_rows(50))
        monkeypatch.setattr(rs, "db", db)
        rs._poll_table("tasks", PARAMS)
        # Seeding keeps the configured descending order.
        assert db.queries[0].get("order") == "updated_at.desc"
        assert rs._watermarks["tasks"] == "2026-08-24T00:00:50Z"

    def test_a_watermarked_poll_reads_oldest_first(self, monkeypatch):
        db = FakeDB(_rows(50))
        monkeypatch.setattr(rs, "db", db)
        rs._watermarks["tasks"] = "2026-08-24T00:00:00Z"
        rows = rs._poll_table("tasks", PARAMS)
        assert db.queries[-1]["order"] == "updated_at.asc"
        assert rows[0]["updated_at"] == "2026-08-24T00:00:01Z"

    def test_no_change_is_skipped_when_a_burst_exceeds_the_page(self, monkeypatch):
        """The bug: 50 changes, page of 20 — all 50 must eventually be seen."""
        db = FakeDB(_rows(50))
        monkeypatch.setattr(rs, "db", db)
        rs._watermarks["tasks"] = "2026-08-24T00:00:00Z"

        seen = []
        for _ in range(5):
            seen.extend(r["id"] for r in rs._poll_table("tasks", PARAMS))

        assert sorted(seen) == list(range(1, 51))
        assert len(seen) == len(set(seen)), "no row may be dispatched twice"

    def test_the_watermark_only_advances_over_returned_rows(self, monkeypatch):
        db = FakeDB(_rows(50))
        monkeypatch.setattr(rs, "db", db)
        rs._watermarks["tasks"] = "2026-08-24T00:00:00Z"
        rs._poll_table("tasks", PARAMS)
        assert rs._watermarks["tasks"] == "2026-08-24T00:00:20Z"


class TestSaturation:
    def test_a_full_page_is_saturated(self):
        assert rs._is_saturated(_rows(20), PARAMS) is True

    def test_a_partial_page_is_not(self):
        assert rs._is_saturated(_rows(3), PARAMS) is False

    def test_an_unusable_limit_is_not_saturated(self):
        for params in ({}, {"limit": ""}, {"limit": "many"}, {"limit": None}):
            assert rs._is_saturated(_rows(20), params) is False


class TestFailSoft:
    def test_a_failing_select_returns_no_rows_and_does_not_move_the_cursor(self, monkeypatch):
        class Boom:
            def select(self, *_a, **_k):
                raise RuntimeError("db down")

        monkeypatch.setattr(rs, "db", Boom())
        rs._watermarks["tasks"] = "2026-08-24T00:00:05Z"
        assert rs._poll_table("tasks", PARAMS) == []
        assert rs._watermarks["tasks"] == "2026-08-24T00:00:05Z"

    def test_an_empty_result_leaves_the_cursor_alone(self, monkeypatch):
        monkeypatch.setattr(rs, "db", FakeDB([]))
        rs._watermarks["tasks"] = "2026-08-24T00:00:05Z"
        assert rs._poll_table("tasks", PARAMS) == []
        assert rs._watermarks["tasks"] == "2026-08-24T00:00:05Z"

    def test_rows_without_updated_at_do_not_clear_the_cursor(self, monkeypatch):
        monkeypatch.setattr(rs, "db", FakeDB([]))
        rs._watermarks["tasks"] = "2026-08-24T00:00:05Z"
        monkeypatch.setattr(rs, "db", type("D", (), {
            "select": staticmethod(lambda *_a, **_k: [{"id": 1}])})())
        rs._poll_table("tasks", PARAMS)
        assert rs._watermarks["tasks"] == "2026-08-24T00:00:05Z"


class TestDispatchUnchanged:
    def test_a_handler_error_is_counted_and_swallowed(self, monkeypatch):
        rs._handlers["tasks"] = [lambda _rows: (_ for _ in ()).throw(RuntimeError("bad"))]
        before = rs._stats["handler_errors"]
        try:
            rs._dispatch("tasks", [{"id": 1}])
        finally:
            rs._handlers["tasks"] = []
        assert rs._stats["handler_errors"] == before + 1

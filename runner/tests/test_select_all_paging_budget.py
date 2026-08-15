#!/usr/bin/env python3
"""select_all() must not fetch rows it is going to discard.

The page size was fixed, so `select_all(max_rows=10)` against a large table still asked
PostgREST for a full 1000-row page and then sliced 990 rows off in the return — a full
page of network transfer and JSON decoding per call, thrown away. The last request is
now clamped to the remaining budget. Also hardens the numeric args, which previously
raised on a non-int instead of falling back.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402


class SelectAllBudgetTest(unittest.TestCase):
    def _fake_table(self, total):
        """Return (select_stub, requests) simulating a table of `total` rows."""
        requests = []
        rows = [{"id": i} for i in range(total)]

        def fake_select(table, params):
            limit = int(params["limit"])
            offset = int(params["offset"])
            requests.append({"limit": limit, "offset": offset})
            return rows[offset:offset + limit]

        return fake_select, requests

    def test_last_page_is_clamped_to_remaining_budget(self):
        fake, reqs = self._fake_table(10_000)
        with patch.object(db, "select", fake):
            out = db.select_all("tasks", max_rows=10, page_size=1000)
        assert len(out) == 10
        assert reqs == [{"limit": 10, "offset": 0}], \
            f"should request exactly 10 rows, not a full page: {reqs}"

    def test_never_requests_more_than_the_cap_in_total(self):
        fake, reqs = self._fake_table(10_000)
        with patch.object(db, "select", fake):
            db.select_all("tasks", max_rows=2500, page_size=1000)
        assert sum(r["limit"] for r in reqs) <= 2500, reqs
        assert reqs[-1]["limit"] == 500, f"final page should be the remainder: {reqs}"

    def test_full_pagination_still_reaches_every_row(self):
        fake, reqs = self._fake_table(2_500)
        with patch.object(db, "select", fake):
            out = db.select_all("tasks", max_rows=10_000, page_size=1000)
        assert len(out) == 2_500
        assert [r["id"] for r in out] == list(range(2_500))

    def test_short_table_makes_one_request(self):
        fake, reqs = self._fake_table(5)
        with patch.object(db, "select", fake):
            out = db.select_all("tasks", page_size=1000)
        assert len(out) == 5
        assert len(reqs) == 1

    def test_offsets_advance_by_the_clamped_size(self):
        """Advancing by the nominal page size instead of the requested one skips rows."""
        fake, reqs = self._fake_table(30)
        with patch.object(db, "select", fake):
            out = db.select_all("tasks", max_rows=30, page_size=10)
        assert [r["id"] for r in out] == list(range(30))
        assert [r["offset"] for r in reqs][:3] == [0, 10, 20], reqs

    def test_zero_or_negative_cap_returns_empty_without_querying(self):
        fake, reqs = self._fake_table(100)
        with patch.object(db, "select", fake):
            assert db.select_all("tasks", max_rows=0) == []
            assert db.select_all("tasks", max_rows=-5) == []
        assert reqs == [], "no query should be issued for an empty budget"

    def test_non_numeric_args_fall_back_instead_of_raising(self):
        fake, _ = self._fake_table(5)
        with patch.object(db, "select", fake):
            assert len(db.select_all("tasks", page_size="nope")) == 5
            assert len(db.select_all("tasks", max_rows="nope")) == 5

    def test_deterministic_order_is_still_applied(self):
        captured = {}

        def fake_select(table, params):
            captured.update(params)
            return []

        with patch.object(db, "select", fake_select):
            db.select_all("tasks")
        assert captured["order"] == "id.asc"


if __name__ == "__main__":
    unittest.main()

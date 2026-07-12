#!/usr/bin/env python3
"""
test_crud.py - Tests for the thin CRUD wrapper (crud.py).

Covers: normal CRUD paths, missing rows, duplicate suppression, concurrent
update handling, fail-soft on errors, upsert with/without match keys,
delete of non-existent rows, and edge cases (None/empty inputs).
"""
import sys, os, types, unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import crud


class TestGet(unittest.TestCase):
    """get() returns a single row or None."""

    @patch("crud.db.select")
    def test_get_existing_row(self, mock_select):
        mock_select.return_value = [{"id": "1", "key": "MAX_PARALLEL", "value": "4"}]
        row = crud.get("fleet_config", {"key": "MAX_PARALLEL"})
        self.assertEqual(row["value"], "4")
        mock_select.assert_called_once()

    @patch("crud.db.select")
    def test_get_missing_row_returns_none(self, mock_select):
        mock_select.return_value = []
        self.assertIsNone(crud.get("fleet_config", {"key": "NONEXISTENT"}))

    @patch("crud.db.select", side_effect=Exception("network error"))
    def test_get_error_returns_none(self, mock_select):
        self.assertIsNone(crud.get("fleet_config", {"key": "X"}))


class TestListRows(unittest.TestCase):
    """list_rows() returns a list, never None."""

    @patch("crud.db.select")
    def test_list_returns_rows(self, mock_select):
        mock_select.return_value = [{"id": "1"}, {"id": "2"}]
        rows = crud.list_rows("tasks")
        self.assertEqual(len(rows), 2)

    @patch("crud.db.select", return_value=None)
    def test_list_none_returns_empty(self, mock_select):
        self.assertEqual(crud.list_rows("tasks"), [])

    @patch("crud.db.select", side_effect=Exception("timeout"))
    def test_list_error_returns_empty(self, mock_select):
        self.assertEqual(crud.list_rows("tasks"), [])


class TestCreate(unittest.TestCase):
    """create() returns (None, new_row) or (None, None)."""

    @patch("crud.db.insert")
    def test_create_success(self, mock_insert):
        new = {"id": "abc", "key": "K", "value": "V"}
        mock_insert.return_value = [new]
        old, result = crud.create("fleet_config", {"key": "K", "value": "V"})
        self.assertIsNone(old)
        self.assertEqual(result["id"], "abc")

    @patch("crud.db.insert", side_effect=Exception("conflict"))
    def test_create_error_returns_none_tuple(self, mock_insert):
        old, new = crud.create("fleet_config", {"key": "K"})
        self.assertIsNone(old)
        self.assertIsNone(new)

    @patch("crud.db.insert", return_value=None)
    def test_create_empty_response(self, mock_insert):
        old, new = crud.create("fleet_config", {"key": "K"})
        self.assertIsNone(old)
        self.assertIsNone(new)


class TestUpdate(unittest.TestCase):
    """update() returns (old_row, new_row) tuple."""

    @patch("crud.db.update")
    @patch("crud.db.select")
    def test_update_success(self, mock_select, mock_update):
        old_row = {"id": "1", "key": "K", "value": "old"}
        new_row = {"id": "1", "key": "K", "value": "new"}
        mock_select.return_value = [old_row]
        mock_update.return_value = [new_row]
        old, new = crud.update("fleet_config", {"id": "1"}, {"value": "new"})
        self.assertEqual(old["value"], "old")
        self.assertEqual(new["value"], "new")

    @patch("crud.db.select", return_value=[])
    def test_update_missing_row(self, mock_select):
        old, new = crud.update("fleet_config", {"id": "999"}, {"value": "X"})
        self.assertIsNone(old)
        self.assertIsNone(new)

    @patch("crud.db.update", return_value=None)
    @patch("crud.db.select")
    def test_update_concurrent_write_refetches(self, mock_select, mock_update):
        """When db.update returns None (concurrent 409 swallowed), re-fetch."""
        row = {"id": "1", "key": "K", "value": "V"}
        mock_select.return_value = [row]
        old, new = crud.update("fleet_config", {"id": "1"}, {"value": "V2"})
        self.assertEqual(old["value"], "V")
        # Re-fetched the same row since update returned None
        self.assertEqual(new["value"], "V")

    @patch("crud.db.select", side_effect=Exception("db down"))
    def test_update_error_failsoft(self, mock_select):
        old, new = crud.update("fleet_config", {"id": "1"}, {"value": "X"})
        self.assertIsNone(old)
        self.assertIsNone(new)


class TestUpsert(unittest.TestCase):
    """upsert() returns (old_or_None, new_row)."""

    @patch("crud.db.insert")
    @patch("crud.db.select")
    def test_upsert_insert_new(self, mock_select, mock_insert):
        mock_select.return_value = []
        mock_insert.return_value = [{"id": "1", "key": "K", "value": "V"}]
        old, new = crud.upsert("fleet_config", {"key": "K", "value": "V"}, match_keys=["key"])
        self.assertIsNone(old)
        self.assertEqual(new["value"], "V")

    @patch("crud.db.insert")
    @patch("crud.db.select")
    def test_upsert_update_existing(self, mock_select, mock_insert):
        existing = {"id": "1", "key": "K", "value": "old"}
        mock_select.return_value = [existing]
        mock_insert.return_value = [{"id": "1", "key": "K", "value": "new"}]
        old, new = crud.upsert("fleet_config", {"key": "K", "value": "new"}, match_keys=["key"])
        self.assertEqual(old["value"], "old")
        self.assertEqual(new["value"], "new")

    @patch("crud.db.insert")
    def test_upsert_without_match_keys(self, mock_insert):
        mock_insert.return_value = [{"id": "1", "key": "K"}]
        old, new = crud.upsert("fleet_config", {"key": "K"})
        self.assertIsNone(old)
        self.assertEqual(new["key"], "K")

    @patch("crud.db.insert", side_effect=Exception("error"))
    def test_upsert_error_failsoft(self, mock_insert):
        old, new = crud.upsert("fleet_config", {"key": "K"})
        self.assertIsNone(old)
        self.assertIsNone(new)


class TestDelete(unittest.TestCase):
    """delete() returns (old_row, None) or (None, None)."""

    @patch("crud.db._req")
    @patch("crud.db.select")
    def test_delete_existing(self, mock_select, mock_req):
        row = {"id": "1", "key": "K", "value": "V"}
        mock_select.return_value = [row]
        old, new = crud.delete("fleet_config", {"id": "1"})
        self.assertEqual(old["key"], "K")
        self.assertIsNone(new)

    @patch("crud.db.select", return_value=[])
    def test_delete_missing_row(self, mock_select):
        old, new = crud.delete("fleet_config", {"id": "999"})
        self.assertIsNone(old)
        self.assertIsNone(new)

    @patch("crud.db.select", side_effect=Exception("err"))
    def test_delete_error_failsoft(self, mock_select):
        old, new = crud.delete("fleet_config", {"id": "1"})
        self.assertIsNone(old)
        self.assertIsNone(new)


class TestHelpers(unittest.TestCase):
    """Edge cases for internal helpers."""

    def test_first_empty_list(self):
        self.assertIsNone(crud._first([]))

    def test_first_none(self):
        self.assertIsNone(crud._first(None))

    def test_first_non_list(self):
        self.assertIsNone(crud._first("string"))

    def test_match_params(self):
        result = crud._match_params({"id": "1", "state": "QUEUED"})
        self.assertEqual(result, {"id": "eq.1", "state": "eq.QUEUED"})


if __name__ == "__main__":
    unittest.main()

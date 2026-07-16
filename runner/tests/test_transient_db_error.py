"""Tests for TransientDBError — HTTP 409 in db._req raises a retryable exception."""
import unittest
from unittest.mock import patch, MagicMock
import urllib.error


class TestTransientDBError(unittest.TestCase):

    def test_409_raises_transient_db_error(self):
        """db._req() must raise TransientDBError (not urllib.error.HTTPError) on HTTP 409."""
        from runner.db import _req, TransientDBError

        mock_resp = MagicMock()
        err = urllib.error.HTTPError(
            url="https://example.supabase.co/rest/v1/tasks",
            code=409,
            msg="Conflict",
            hdrs={},
            fp=None,
        )
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(TransientDBError) as ctx:
                _req("POST", "/rest/v1/tasks", body={"slug": "test"})
            # Original HTTPError is chained
            self.assertIsInstance(ctx.exception.__cause__, urllib.error.HTTPError)
            self.assertEqual(ctx.exception.__cause__.code, 409)

    def test_non_409_still_raises_http_error(self):
        """Non-409 HTTP errors must propagate as-is."""
        from runner.db import _req, TransientDBError

        err = urllib.error.HTTPError(
            url="https://example.supabase.co/rest/v1/tasks",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=None,
        )
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(urllib.error.HTTPError):
                _req("POST", "/rest/v1/tasks", body={"slug": "test"})

    def test_insert_swallows_transient_db_error(self):
        """insert() must catch TransientDBError and return None (idempotent upsert)."""
        from runner.db import insert, TransientDBError

        err = urllib.error.HTTPError(
            url="https://example.supabase.co/rest/v1/outcomes",
            code=409,
            msg="Conflict",
            hdrs={},
            fp=None,
        )
        with patch("urllib.request.urlopen", side_effect=err):
            result = insert("outcomes", {"task_id": "abc", "model": "test"}, upsert=True)
            self.assertIsNone(result)

    def test_update_swallows_transient_db_error(self):
        """update() must catch TransientDBError on concurrent-write 409."""
        from runner.db import update, TransientDBError

        err = urllib.error.HTTPError(
            url="https://example.supabase.co/rest/v1/tasks",
            code=409,
            msg="Conflict",
            hdrs={},
            fp=None,
        )
        with patch("urllib.request.urlopen", side_effect=err):
            result = update("tasks", {"state": "DONE"}, id="abc-123")
            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

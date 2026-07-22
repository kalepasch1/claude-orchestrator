import io
import socket
import urllib.error
from unittest.mock import patch

import db


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b'[]'


def test_get_retries_transient_dns_failure(monkeypatch):
    monkeypatch.setattr(db, "URL", "https://example.supabase.co")
    monkeypatch.setattr(db, "KEY", "test-key")
    monkeypatch.setattr(db, "HTTP_RETRIES", 2)
    attempts = [urllib.error.URLError(socket.gaierror(8, "temporary DNS failure")), _Response()]

    with patch.object(db.urllib.request, "urlopen", side_effect=attempts) as open_mock, \
         patch.object(db.time, "sleep") as sleep_mock:
        assert db._req("GET", "/rest/v1/projects", params={"select": "id"}) == []

    assert open_mock.call_count == 2
    sleep_mock.assert_called_once()

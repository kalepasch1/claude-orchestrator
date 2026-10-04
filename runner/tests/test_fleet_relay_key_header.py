"""The fleet relays (*/api/_fleet-relay) fail closed since 2026-10-01: every request without
a matching x-fleet-relay-key is a 401. The runner's PostgREST client must therefore send the
key, from FLEET_RELAY_KEY, on every request -- and send nothing when it is unset (a direct
*.supabase.co endpoint has no use for it)."""
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402


class _Resp(io.BytesIO):
    status = 200
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def getheader(self, *_a, **_k):
        return None


@pytest.fixture
def captured(monkeypatch):
    seen = []

    def fake_urlopen(req, timeout=None):
        seen.append({k.lower(): v for k, v in req.header_items()})
        return _Resp(json.dumps([]).encode())

    monkeypatch.setattr(db, "URL", "https://www.madeus.cc/api/_fleet-relay")
    monkeypatch.setattr(db, "KEY", "service-key")
    monkeypatch.setenv("ORCH_SUPABASE_FALLBACK_URLS", "")
    monkeypatch.setattr(db.urllib.request, "urlopen", fake_urlopen)
    return seen


def test_sends_the_relay_key_when_configured(monkeypatch, captured):
    monkeypatch.setenv("FLEET_RELAY_KEY", "relay-secret")
    db._req("GET", "/rest/v1/tasks")
    assert captured and captured[-1].get("x-fleet-relay-key") == "relay-secret"


def test_sends_no_relay_header_when_unset(monkeypatch, captured):
    monkeypatch.delenv("FLEET_RELAY_KEY", raising=False)
    db._req("GET", "/rest/v1/tasks")
    assert captured and "x-fleet-relay-key" not in captured[-1]

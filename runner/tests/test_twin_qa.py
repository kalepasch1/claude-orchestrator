#!/usr/bin/env python3
"""Tests for twin_qa.py - gate wiring, red-blocks-promotion, artifact linking."""
import json
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_mock_db_data = {}
_mock_db_inserts = []

class MockDB:
    @staticmethod
    def select(table, query=None):
        return _mock_db_data.get(table, [])
    @staticmethod
    def insert(table, data):
        _mock_db_inserts.append({"table": table, "data": data})
        return data
    @staticmethod
    def update(table, data, where=None):
        return data

sys.modules["db"] = MockDB()

# Mock log
class MockLog:
    @staticmethod
    def get(name):
        return MockLog()
    def info(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def error(self, *a, **kw): pass
sys.modules["log"] = MockLog()

import twin_qa


def test_disabled():
    """When disabled, returns skipped."""
    twin_qa.ENABLED = False
    r = twin_qa.run("test-project", "https://staging.example.com")
    assert r.get("skipped") is True
    twin_qa.ENABLED = True


def test_no_staging_url():
    """No staging URL returns error."""
    _mock_db_data.clear()
    r = twin_qa.run("test-project")
    assert r["ok"] is False
    assert "no staging URL" in r["error"]


def test_no_journeys():
    """No journeys defined passes by default."""
    with tempfile.TemporaryDirectory() as td:
        twin_qa.PERSONAS_DIR = td  # empty dir
        r = twin_qa.run("test-project", "https://staging.example.com")
        assert r["ok"] is True
        assert r["blocks_promotion"] is False
        assert r["passed"] == 0


def test_journey_discovery():
    """Discovers journey specs from personas dir."""
    with tempfile.TemporaryDirectory() as td:
        twin_qa.PERSONAS_DIR = td
        spec = {"name": "test-journey", "project": "myproj", "steps": [{"action": "navigate", "url": "/"}]}
        with open(os.path.join(td, "test.json"), "w") as f:
            json.dump(spec, f)
        journeys = twin_qa._discover_journeys("myproj")
        assert len(journeys) == 1
        assert journeys[0]["name"] == "test-journey"


def test_journey_discovery_filters_project():
    """Only returns journeys matching the requested project."""
    with tempfile.TemporaryDirectory() as td:
        twin_qa.PERSONAS_DIR = td
        for proj in ["a", "b"]:
            with open(os.path.join(td, f"{proj}.json"), "w") as f:
                json.dump({"name": f"{proj}-journey", "project": proj, "steps": []}, f)
        journeys = twin_qa._discover_journeys("a")
        assert len(journeys) == 1
        assert journeys[0]["project"] == "a"


def test_red_journey_blocks_promotion():
    """A failed journey blocks promotion and files a qafix task."""
    _mock_db_inserts.clear()
    _mock_db_data.clear()

    with tempfile.TemporaryDirectory() as td:
        twin_qa.PERSONAS_DIR = td
        twin_qa.ARTIFACTS_DIR = os.path.join(td, "artifacts")
        twin_qa.DRY_RUN = False

        spec = {"name": "failing-journey", "project": "testproj",
                "steps": [{"action": "navigate", "url": "/fail"}]}
        with open(os.path.join(td, "fail.json"), "w") as f:
            json.dump(spec, f)

        with mock.patch.object(twin_qa, "_run_journey") as mock_run:
            mock_run.return_value = {
                "name": "failing-journey", "passed": False, "duration_s": 1.5,
                "error": "element not found", "trace_path": "/tmp/trace.zip",
                "screenshot_path": "/tmp/fail.png",
            }
            r = twin_qa.run("testproj", "https://staging.example.com")

        assert r["ok"] is True
        assert r["blocks_promotion"] is True
        assert r["failed"] == 1
        # Should have filed a qafix task
        qafix_inserts = [i for i in _mock_db_inserts if i["table"] == "tasks" and "qafix" in i["data"].get("slug", "")]
        assert len(qafix_inserts) >= 1
        assert "trace" in qafix_inserts[0]["data"]["prompt"].lower()

    twin_qa.DRY_RUN = True


def test_green_journey_allows_promotion():
    """All green journeys allow promotion."""
    _mock_db_inserts.clear()
    with tempfile.TemporaryDirectory() as td:
        twin_qa.PERSONAS_DIR = td
        twin_qa.DRY_RUN = False

        spec = {"name": "happy-journey", "project": "testproj",
                "steps": [{"action": "navigate", "url": "/ok"}]}
        with open(os.path.join(td, "ok.json"), "w") as f:
            json.dump(spec, f)

        with mock.patch.object(twin_qa, "_run_journey") as mock_run:
            mock_run.return_value = {
                "name": "happy-journey", "passed": True, "duration_s": 0.5,
                "error": None, "trace_path": None, "screenshot_path": None,
            }
            r = twin_qa.run("testproj", "https://staging.example.com")

        assert r["blocks_promotion"] is False
        assert r["passed"] == 1

    twin_qa.DRY_RUN = True


def test_dry_run_passes():
    """Dry run mode passes all journeys."""
    with tempfile.TemporaryDirectory() as td:
        twin_qa.PERSONAS_DIR = td
        twin_qa.DRY_RUN = True

        spec = {"name": "dr-journey", "project": "testproj", "steps": [{"action": "navigate", "url": "/"}]}
        with open(os.path.join(td, "dr.json"), "w") as f:
            json.dump(spec, f)

        r = twin_qa.run("testproj", "https://staging.example.com")
        assert r["blocks_promotion"] is False
        assert r["passed"] == 1


def test_staging_url_resolution():
    """Resolves staging URL from deploy_health."""
    _mock_db_data["deploy_health"] = [{"vercel_project": "my-app-staging"}]
    url = twin_qa._resolve_staging_url("my-app")
    assert url == "https://my-app-staging.vercel.app"
    _mock_db_data.clear()


def test_generate_playwright_script():
    """Generated script has correct structure."""
    steps = [
        {"action": "navigate", "url": "/test"},
        {"action": "click", "selector": "#btn"},
        {"action": "assert_visible", "selector": ".result"},
    ]
    script = twin_qa._generate_playwright_script("test", "https://example.com", steps, {}, "/trace.zip", "/fail.png")
    assert "test('test'" in script
    assert "page.goto" in script
    assert "page.click" in script
    assert "toBeVisible" in script


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print("All twin_qa tests passed")

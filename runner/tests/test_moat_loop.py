#!/usr/bin/env python3
"""Tests for moat_loop, moat_activate, and ingest_fulltext."""
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Stub db before importing modules under test
# ---------------------------------------------------------------------------
import types as _types
_fake_db = _types.ModuleType("db")
_fake_db.select = lambda *a, **kw: []
_fake_db.insert = lambda *a, **kw: None
_fake_db.update = lambda *a, **kw: None
_fake_db.upsert = lambda *a, **kw: None
sys.modules["db"] = _fake_db

import moat_loop
import moat_activate
import ingest_fulltext


# ── moat_loop tests ──────────────────────────────────────────────────────────

class TestMoatCycle:
    def setup_method(self):
        moat_loop.reset_stats()

    def test_cycle_with_mocked_sources_produces_summary(self):
        """Moat cycle with mocked sources produces summary with win-rate."""
        source_data = [
            {"id": "rec-1", "title": "Test Record A", "stage": "proposed_rule"},
            {"id": "rec-2", "title": "Test Record B", "stage": "final_rule"},
            {"id": "rec-3", "title": "Test Record C", "stage": "annual_filing"},
        ]

        def mock_cade(record):
            return {"decision": "approve", "confidence": 0.9}

        summary = moat_loop.run_moat_cycle([source_data], mock_cade)

        assert summary["status"] == "ok"
        assert summary["records"] == 3
        assert summary["wins"] == 3
        assert summary["total"] == 3
        assert summary["win_rate"] == 1.0
        assert "calibration_delta" in summary
        assert summary["reindexed"] == 3

    def test_cycle_with_partial_failures(self):
        """Cycle handles partial cade failures gracefully."""
        source_data = [
            {"id": "rec-1", "title": "Good"},
            {"id": "rec-2", "title": "Bad"},
        ]

        call_count = [0]
        def flaky_cade(record):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("simulated failure")
            return {"ok": True}

        summary = moat_loop.run_moat_cycle([source_data], flaky_cade)
        assert summary["status"] == "ok"
        assert summary["wins"] == 1
        assert summary["total"] == 2
        assert 0 < summary["win_rate"] < 1.0

    def test_disabled_returns_status(self):
        """Disabled moat returns disabled status."""
        old = moat_loop.ENABLED
        moat_loop.ENABLED = False
        try:
            summary = moat_loop.run_moat_cycle([], lambda r: None)
            assert summary["status"] == "disabled"
        finally:
            moat_loop.ENABLED = old


# ── moat_activate tests ─────────────────────────────────────────────────────

class TestMoatActivate:
    def setup_method(self):
        moat_activate.reset_stats()

    def test_activation_from_seed_file(self):
        """Activation from seed file produces records."""
        seed_path = os.path.join(os.path.dirname(__file__), "..",
                                 "seeds", "golden_engagements_seed.json")
        records = moat_activate.trigger_once(seed_path=seed_path, live=False)
        assert len(records) == 3
        assert records[0]["source"] in ("federal_register", "edgar")
        assert all("id" in r for r in records)

    def test_activation_missing_seed_returns_empty(self):
        """Missing seed file returns empty list gracefully."""
        records = moat_activate.trigger_once(
            seed_path="/tmp/nonexistent_seed_xyz.json", live=False)
        assert records == []

    def test_activation_stats_increment(self):
        """Stats track activations."""
        seed_path = os.path.join(os.path.dirname(__file__), "..",
                                 "seeds", "golden_engagements_seed.json")
        moat_activate.trigger_once(seed_path=seed_path, live=False)
        s = moat_activate.stats()
        assert s["activations"] >= 1
        assert s["seed_records"] >= 3


# ── ingest_fulltext tests ────────────────────────────────────────────────────

class TestIngestFulltext:
    def setup_method(self):
        ingest_fulltext.reset_stats()

    def test_fulltext_ingestion_with_mocked_network(self):
        """Fulltext ingestion with mocked network fetches, chunks, embeds."""
        html_content = ("<html><body><h1>Title</h1>"
                        "<p>Section one content here.</p>"
                        "\n\n"
                        "<p>Section two content here.</p></body></html>")

        def mock_fetch(url):
            return html_content

        embedded = []
        class MockStore:
            def add(self, chunk_id, vector, metadata):
                embedded.append({"id": chunk_id, "vec": vector, "meta": metadata})

        def mock_embedder(text):
            return [0.1] * 8  # fake 8-dim vector

        record = {"id": "test-001",
                  "full_text_url": "https://example.com/doc.htm"}

        with tempfile.TemporaryDirectory() as tmpdir:
            result = ingest_fulltext.ingest_fulltext(
                record, MockStore(), mock_embedder,
                fetcher=mock_fetch, corpus_dir=tmpdir)

        assert result["status"] == "ingested"
        assert result["chunks"] >= 1
        assert record["full_text_status"] == "ingested"
        assert len(embedded) >= 1

    def test_no_url_skips(self):
        """Record without full_text_url is skipped."""
        record = {"id": "no-url"}
        result = ingest_fulltext.ingest_fulltext(
            record, None, None, fetcher=lambda u: "")
        assert result["status"] == "skipped"

    def test_fetch_failure_returns_error(self):
        """Network failure returns error status."""
        def bad_fetch(url):
            raise ConnectionError("simulated network failure")

        record = {"id": "fail-001",
                  "full_text_url": "https://example.com/fail.htm"}
        result = ingest_fulltext.ingest_fulltext(
            record, None, None, fetcher=bad_fetch)
        assert result["status"] == "error"
        assert "fetch_failed" in result["reason"]

    def test_blob_saved_to_disk(self):
        """Raw blob is saved to corpus/blobs/<hash>.txt."""
        def mock_fetch(url):
            return "<p>Test blob content</p>"

        class MockStore:
            def add(self, *a, **kw): pass

        record = {"id": "blob-001",
                  "full_text_url": "https://example.com/blob.htm"}
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ingest_fulltext.ingest_fulltext(
                record, MockStore(), lambda t: [0.0],
                fetcher=mock_fetch, corpus_dir=tmpdir)
            assert result["status"] == "ingested"
            blobs = os.listdir(tmpdir)
            assert len(blobs) == 1
            assert blobs[0].endswith(".txt")


# ── stats tests ──────────────────────────────────────────────────────────────

class TestStats:
    def test_moat_loop_stats(self):
        moat_loop.reset_stats()
        s = moat_loop.stats()
        assert isinstance(s, dict)
        assert "cycles" in s
        assert "records_ingested" in s

    def test_moat_activate_stats(self):
        moat_activate.reset_stats()
        s = moat_activate.stats()
        assert isinstance(s, dict)
        assert "activations" in s
        assert "seed_records" in s

    def test_ingest_fulltext_stats(self):
        ingest_fulltext.reset_stats()
        s = ingest_fulltext.stats()
        assert isinstance(s, dict)
        assert "fetched" in s
        assert "ingested" in s

#!/usr/bin/env python3
"""Tests for knowledge_bus — the cross-app bus had no test file at all.

Two defects these pin:

* `json.dumps(body)[:MAX_BODY_LEN]` sliced encoded JSON at a fixed length, so any
  oversized event was stored as a broken fragment. subscribe() then failed json.loads
  and — via a bare except — handed consumers the raw truncated string instead of a
  dict. The bus corrupted precisely its largest payloads, silently.
* The topic filter interpolated values straight into `in.(...)`, so a topic containing
  a comma split into two topics and one containing a quote/paren malformed the filter.
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import knowledge_bus as kb  # noqa: E402


class EncodeBodyTest(unittest.TestCase):
    def test_small_body_round_trips_unchanged(self):
        body = {"slug": "abc", "outcome": "ok"}
        assert json.loads(kb._encode_body(body)) == body

    def test_oversized_body_stays_valid_json(self):
        body = {"notes": "x" * (kb.MAX_BODY_LEN * 3), "slug": "big"}
        encoded = kb._encode_body(body)
        assert len(encoded) <= kb.MAX_BODY_LEN
        decoded = json.loads(encoded)  # must not raise
        assert decoded["_truncated"] is True
        assert decoded["_original_chars"] > kb.MAX_BODY_LEN
        assert "notes" in decoded["keys"]

    def test_oversized_with_many_keys_still_fits(self):
        body = {f"key_{i}": "y" * 200 for i in range(500)}
        encoded = kb._encode_body(body)
        assert len(encoded) <= kb.MAX_BODY_LEN
        assert json.loads(encoded)["_truncated"] is True

    def test_non_serialisable_values_do_not_raise(self):
        class Weird:
            def __repr__(self):
                return "<weird>"

        assert json.loads(kb._encode_body({"o": Weird()}))["o"] == "<weird>"


class InFilterTest(unittest.TestCase):
    def test_simple_topics_are_quoted(self):
        assert kb._in_filter(["a", "b"]) == 'in.("a","b")'

    def test_topic_with_comma_is_not_split(self):
        """The whole comma-bearing value must stay one filter element."""
        assert kb._in_filter(["fix,pattern"]) == 'in.("fix,pattern")'

    def test_quotes_are_escaped(self):
        assert kb._in_filter(['say"hi']) == 'in.("say\\"hi")'

    def test_backslashes_are_escaped(self):
        assert kb._in_filter(["a\\b"]) == 'in.("a\\\\b")'


class SubscribeTest(unittest.TestCase):
    def test_empty_topics_short_circuits(self):
        assert kb.subscribe([]) == []

    def test_uses_quoted_filter_and_decodes_body(self):
        captured = {}

        def fake_select(table, params):
            captured.update(params)
            return [{"topic": "t", "body": json.dumps({"k": "v"}), "project": "p",
                     "source": "s", "created_at": "now"}]

        with patch.object(kb.db, "select", fake_select):
            rows = kb.subscribe(["task_outcome", "fix,pattern"])
        assert captured["topic"] == 'in.("task_outcome","fix,pattern")'
        assert rows[0]["body"] == {"k": "v"}

    def test_db_error_is_fail_soft(self):
        def boom(table, params):
            raise RuntimeError("db down")

        with patch.object(kb.db, "select", boom):
            assert kb.subscribe(["t"]) == []


class PublishTest(unittest.TestCase):
    def test_rejects_empty_topic_or_body(self):
        assert kb.publish("", {"a": 1}) is False
        assert kb.publish("t", {}) is False

    def test_publishes_valid_json_for_oversized_body(self):
        inserted = {}

        with patch.object(kb.db, "select", lambda t, p: []), \
             patch.object(kb.db, "insert", lambda t, row: inserted.update(row)):
            assert kb.publish("t", {"notes": "z" * (kb.MAX_BODY_LEN * 2)}) is True
        assert json.loads(inserted["body"])["_truncated"] is True

    def test_duplicate_within_window_is_skipped(self):
        with patch.object(kb.db, "select", lambda t, p: [{"id": 1}]):
            assert kb.publish("t", {"a": 1}) is False

    def test_db_error_is_fail_soft(self):
        def boom(*a, **k):
            raise RuntimeError("db down")

        with patch.object(kb.db, "select", boom):
            assert kb.publish("t", {"a": 1}) is False


if __name__ == "__main__":
    unittest.main()

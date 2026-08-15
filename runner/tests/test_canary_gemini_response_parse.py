#!/usr/bin/env python3
"""canary.py --request-only: print the model's text, and fail loudly with exit 3.

Acceptance for canary-gemini-25-request-parse-response-text:
  * a well-formed Gemini generateContent response prints the extracted text and exits 0;
  * an unexpected structure prints an error and exits non-zero (3, specifically).

The live API call is deliberately out of scope — see canary.request_only.__doc__. The
response body comes from a path or stdin, so these tests need no key and no network and
cover the parsing the original slice never reached.
"""
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import canary


def _response(text="canary"):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


class TestParseGeminiText:
    def test_extracts_the_first_parts_text(self):
        assert canary.parse_gemini_text(_response("canary")) == "canary"

    def test_accepts_a_raw_json_string(self):
        assert canary.parse_gemini_text(json.dumps(_response("hello"))) == "hello"

    def test_accepts_bytes(self):
        assert canary.parse_gemini_text(json.dumps(_response("hi")).encode()) == "hi"

    def test_takes_the_first_candidate_and_first_part(self):
        payload = {"candidates": [
            {"content": {"parts": [{"text": "first"}, {"text": "second"}]}},
            {"content": {"parts": [{"text": "other candidate"}]}},
        ]}
        assert canary.parse_gemini_text(payload) == "first"

    def test_empty_text_is_a_valid_extraction_not_an_error(self):
        assert canary.parse_gemini_text(_response("")) == ""

    def test_unicode_survives_the_round_trip(self):
        assert canary.parse_gemini_text(_response("canário 🐤")) == "canário 🐤"

    @pytest.mark.parametrize("payload", [
        None, 42, [], "not json at all", b"\xff\xfe",
        {}, {"candidates": []}, {"candidates": "nope"},
        {"candidates": [{}]},
        {"candidates": [{"content": None}]},
        {"candidates": [{"content": {}}]},
        {"candidates": [{"content": {"parts": []}}]},
        {"candidates": [{"content": {"parts": [{}]}}]},
        {"candidates": [{"content": {"parts": [{"text": 5}]}}]},
        {"candidates": [{"content": {"parts": "nope"}}]},
    ])
    def test_every_malformed_shape_raises_one_error_type(self, payload):
        with pytest.raises(canary.GeminiResponseError):
            canary.parse_gemini_text(payload)

    def test_a_safety_block_is_diagnosed_as_such(self):
        with pytest.raises(canary.GeminiResponseError, match="blocked"):
            canary.parse_gemini_text({"promptFeedback": {"blockReason": "SAFETY"}})


class TestRequestOnlyFlow:
    def test_a_valid_response_prints_the_text_and_exits_zero(self, tmp_path, capsys):
        path = tmp_path / "resp.json"
        path.write_text(json.dumps(_response("canary")), encoding="utf-8")
        assert canary.request_only(str(path)) == 0
        assert capsys.readouterr().out.strip() == "canary"

    def test_the_raw_json_envelope_is_not_printed(self, tmp_path, capsys):
        path = tmp_path / "resp.json"
        path.write_text(json.dumps(_response("canary")), encoding="utf-8")
        canary.request_only(str(path))
        out = capsys.readouterr().out
        assert "candidates" not in out and "parts" not in out

    def test_an_unexpected_structure_exits_three_with_an_error(self, tmp_path, capsys):
        path = tmp_path / "resp.json"
        path.write_text(json.dumps({"nope": True}), encoding="utf-8")
        assert canary.request_only(str(path)) == 3
        captured = capsys.readouterr()
        assert captured.out.strip() == ""
        assert "could not parse" in captured.err

    def test_invalid_json_exits_three(self, tmp_path):
        path = tmp_path / "resp.json"
        path.write_text("{not json", encoding="utf-8")
        assert canary.request_only(str(path)) == 3

    def test_an_unreadable_body_exits_two_not_three(self, tmp_path, capsys):
        assert canary.request_only(str(tmp_path / "missing.json")) == 2
        assert "could not read" in capsys.readouterr().err

    def test_stdin_is_the_default_source(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_response("piped"))))
        assert canary.request_only() == 0
        assert capsys.readouterr().out.strip() == "piped"


class TestCliWiring:
    def test_main_routes_the_request_only_flag(self, tmp_path, capsys):
        path = tmp_path / "resp.json"
        path.write_text(json.dumps(_response("canary")), encoding="utf-8")
        assert canary.main(["--request-only", str(path)]) == 0
        assert capsys.readouterr().out.strip() == "canary"

    def test_main_returns_three_on_a_bad_response(self, tmp_path):
        path = tmp_path / "resp.json"
        path.write_text("[]", encoding="utf-8")
        assert canary.main(["--request-only", str(path)]) == 3

    def test_the_existing_validation_contract_is_untouched(self):
        assert canary.main(["a canary lives here"]) == 0
        assert canary.main(["nothing here"]) == 1
        assert canary.validate_canary("CANARY") is True
        assert canary.validate_canary(None) is False

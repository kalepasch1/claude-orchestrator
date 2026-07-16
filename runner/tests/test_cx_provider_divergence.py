#!/usr/bin/env python3
"""Canary test for cx_provider_divergence — offline, no network."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cx_provider_divergence import _extract_verdict


def test_extract_verdict_valid_json():
    result = _extract_verdict('{"verdict":"support","score":8,"reasoning":"clear"}')
    assert result["verdict"] == "support"
    assert result["score"] == 8


def test_extract_verdict_embedded_json():
    result = _extract_verdict('Here is my answer: {"verdict":"oppose","score":3,"reasoning":"weak"} end')
    assert result["verdict"] == "oppose"


def test_extract_verdict_empty():
    assert _extract_verdict("") == {}
    assert _extract_verdict(None) == {}


def test_extract_verdict_no_json():
    assert _extract_verdict("just plain text with no json") == {}

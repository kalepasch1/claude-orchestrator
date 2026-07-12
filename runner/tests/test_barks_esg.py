"""Tests for barks_esg – 20+ cases covering contracts and ESG engine."""

from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from barks_contracts import Claim, OutreachDraft, Result
from barks_esg import EsgTargetingEngine


engine = EsgTargetingEngine()


# ── empty / None inputs ──────────────────────────────────────────────

def test_empty_string_returns_ok_empty_draft():
    r = engine.generate_draft("")
    assert r.ok is True
    assert r.data.claims == []
    assert r.data.body == ""


def test_none_input_returns_ok_empty_draft():
    r = engine.generate_draft(None)
    assert r.ok is True
    assert r.data.claims == []
    assert r.data.body == ""


def test_extract_claims_empty():
    assert engine.extract_claims("") == []


def test_extract_claims_none():
    assert engine.extract_claims(None) == []


# ── single claim patterns ────────────────────────────────────────────

def test_single_commit_to():
    text = "We commit to reducing emissions by 50%."
    claims = engine.extract_claims(text)
    assert len(claims) == 1
    assert "commit to" in claims[0].text.lower()


def test_single_we_pledge():
    text = "We pledge to plant one million trees."
    claims = engine.extract_claims(text)
    assert len(claims) == 1
    assert "pledge" in claims[0].text.lower()


def test_single_our_goal_is():
    text = "Our goal is carbon neutrality by 2030."
    claims = engine.extract_claims(text)
    assert len(claims) == 1


def test_single_we_aim_to():
    text = "We aim to achieve zero waste by 2025."
    claims = engine.extract_claims(text)
    assert len(claims) == 1


def test_single_we_will():
    text = "We will invest $10M in renewable energy."
    claims = engine.extract_claims(text)
    assert len(claims) == 1


def test_single_committed_to():
    text = "The company is committed to ethical sourcing."
    claims = engine.extract_claims(text)
    assert len(claims) == 1


def test_single_dedicated_to():
    text = "Our team is dedicated to community well-being."
    claims = engine.extract_claims(text)
    assert len(claims) == 1


# ── multiple claims ──────────────────────────────────────────────────

def test_multiple_claims():
    text = (
        "We commit to net-zero by 2040. "
        "We pledge to use only recycled materials. "
        "We aim to reduce water usage by 30%."
    )
    claims = engine.extract_claims(text)
    assert len(claims) == 3


def test_multiple_claims_sorted_by_position():
    text = "We pledge X. We commit to Y. We aim to Z."
    claims = engine.extract_claims(text)
    positions = [c.source_span[0] for c in claims]
    assert positions == sorted(positions)


# ── source span verification ─────────────────────────────────────────

def test_source_span_matches_text_single():
    text = "Hello world. We commit to transparency."
    claims = engine.extract_claims(text)
    assert len(claims) == 1
    c = claims[0]
    assert text[c.source_span[0] : c.source_span[1]] == c.text


def test_source_span_matches_text_all_claims():
    text = (
        "Introduction. We pledge to improve diversity. "
        "Some filler text here. Our goal is full inclusion."
    )
    claims = engine.extract_claims(text)
    for c in claims:
        actual = text[c.source_span[0] : c.source_span[1]]
        assert actual == c.text, f"span mismatch: {actual!r} != {c.text!r}"


def test_no_claim_has_invalid_span_in_draft():
    """TRUTH GATE: every claim in the draft must have a valid span."""
    text = "We commit to A. We pledge B. Random noise. We will do C."
    r = engine.generate_draft(text)
    assert r.ok
    for c in r.data.claims:
        start, end = c.source_span
        assert 0 <= start < end <= len(text)
        assert text[start:end] == c.text


# ── no claims in random text ─────────────────────────────────────────

def test_no_claims_plain_text():
    text = "The weather is nice today. Stocks went up."
    claims = engine.extract_claims(text)
    assert claims == []


def test_no_claims_returns_empty_draft():
    r = engine.generate_draft("Just some ordinary text without commitments.")
    assert r.ok is True
    assert r.data.claims == []
    assert r.data.body == ""


# ── garbage / edge-case input ────────────────────────────────────────

def test_garbage_binary_like():
    r = engine.generate_draft("\x00\x01\x02 random bytes \xff\xfe")
    assert r.ok is True  # fail-soft


def test_whitespace_only():
    r = engine.generate_draft("   \n\t  ")
    assert r.ok is True
    assert r.data.claims == []


def test_very_long_input():
    text = "We commit to excellence. " * 1000
    r = engine.generate_draft(text)
    assert r.ok is True
    assert len(r.data.claims) >= 1


def test_case_insensitive():
    text = "WE COMMIT TO SUSTAINABILITY."
    claims = engine.extract_claims(text)
    assert len(claims) == 1


# ── draft body contains claims ───────────────────────────────────────

def test_draft_body_contains_claim_text():
    text = "We pledge to support local communities."
    r = engine.generate_draft(text)
    assert r.ok
    assert "pledge" in r.data.body.lower()


def test_draft_returns_result_type():
    r = engine.generate_draft("We commit to openness.")
    assert isinstance(r, Result)
    assert isinstance(r.data, OutreachDraft)


# ── deduplication ─────────────────────────────────────────────────────

def test_duplicate_sentence_not_repeated():
    text = "We commit to X. We commit to X."
    claims = engine.extract_claims(text)
    # Each occurrence is a separate sentence at a different offset, so we
    # get two claims, but never a duplicate span.
    spans = [c.source_span for c in claims]
    assert len(spans) == len(set(spans))

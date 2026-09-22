"""disputes: fact interpolation, an unconditional review gate, a
non-strippable draft header, and no legal assertion or send path.
"""
import os
import sys

import pytest

_DELEGATION = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DELEGATION)
sys.path.insert(0, os.path.join(os.path.dirname(_DELEGATION), "contracts"))

import disputes  # noqa: E402
from disputes import (  # noqa: E402
    DRAFT_FOOTER,
    DRAFT_HEADER,
    GROUNDS,
    DisputeDraft,
    draft,
    render,
)
from intake import parse_inbound  # noqa: E402


FIXTURE = (
    "From: Meridian Card Services\n"
    "Account Number: 4410-9987\n"
    "Amount due: $312.00\n"
    "Due date: 2026-09-30\n"
    "Please pay by the due date.\n"
)


def item():
    return parse_inbound(FIXTURE, source="mail")


# ── (1) the draft interpolates issuer, amount and account reference ─────────

def test_draft_interpolates_issuer_amount_and_account_reference():
    d = draft(item(), "amount_wrong", holder="Dana Okonkwo")
    assert "Meridian Card Services" in d.body
    assert "312.00" in d.body
    assert "4410-9987" in d.body


def test_draft_records_the_parsed_facts_on_the_dataclass():
    d = draft(item(), "amount_wrong", holder="Dana Okonkwo")
    assert d.issuer == "Meridian Card Services"
    assert d.amount_usd == pytest.approx(312.00)
    assert d.account_ref == "4410-9987"


def test_subject_carries_the_account_and_amount():
    d = draft(item(), "duplicate")
    assert "4410-9987" in d.subject and "312.00" in d.subject


def test_holder_name_appears_and_falls_back_to_a_placeholder():
    assert "Dana Okonkwo" in draft(item(), "duplicate", holder="Dana Okonkwo").body
    assert "[holder name]" in draft(item(), "duplicate").body


def test_grounds_sentence_is_the_one_for_the_code():
    d = draft(item(), "already_paid")
    assert GROUNDS["already_paid"] in d.body


def test_enclosures_list_the_original_notice():
    d = draft(item(), "duplicate")
    assert any("original notice" in e for e in d.enclosures)


# ── (2) review_required is True on EVERY path ──────────────────────────────

@pytest.mark.parametrize("grounds", list(GROUNDS) + ["", "nonsense", None, 0, object()])
def test_review_required_is_true_on_every_path(grounds):
    assert draft(item(), grounds, holder="Dana").review_required is True


@pytest.mark.parametrize("bad_item", [None, "", 0, object(), [], {}])
def test_review_required_is_true_even_for_garbage_input(bad_item):
    assert draft(bad_item, "duplicate").review_required is True


def test_review_required_cannot_be_constructed_away():
    # Even a caller who explicitly asks for False gets True.
    assert DisputeDraft(review_required=False).review_required is True


def test_happy_path_still_requires_review():
    d = draft(item(), "amount_wrong", holder="Dana Okonkwo")
    assert d.grounds_recognised is True
    assert d.review_required is True


# ── (3) the header is present and survives a render round-trip ─────────────

def test_header_and_footer_are_present_in_the_rendered_body():
    d = draft(item(), "duplicate")
    assert DRAFT_HEADER in d.body
    assert DRAFT_FOOTER in d.body


def test_header_survives_a_round_trip_through_the_renderer():
    d = draft(item(), "duplicate")
    once = render(d)
    twice = render(once)
    assert DRAFT_HEADER in twice and DRAFT_FOOTER in twice


def test_round_trip_does_not_duplicate_the_markers():
    d = draft(item(), "duplicate")
    rendered = render(render(render(d)))
    assert rendered.count(DRAFT_HEADER) == 1
    assert rendered.count(DRAFT_FOOTER) == 1


def test_header_is_reapplied_after_a_caller_strips_it():
    d = draft(item(), "duplicate")
    d.body = d.body.replace(DRAFT_HEADER, "").replace(DRAFT_FOOTER, "")
    assert DRAFT_HEADER not in d.body
    assert DRAFT_HEADER in render(d)          # non-strippable


@pytest.mark.parametrize("bad", [None, 0, object(), [], {}])
def test_render_never_raises_and_always_marks_the_draft(bad):
    out = render(bad)
    assert DRAFT_HEADER in out and DRAFT_FOOTER in out


# ── (4) an unknown grounds code raises nothing and still needs review ──────

@pytest.mark.parametrize("grounds", ["", "  ", "not_a_code", "DROP TABLE", None, 42, object()])
def test_unknown_grounds_raises_no_exception_and_still_requires_review(grounds):
    d = draft(item(), grounds, holder="Dana")
    assert isinstance(d, DisputeDraft)
    assert d.review_required is True
    assert d.grounds_recognised is False
    assert d.body.strip()


def test_unknown_grounds_flags_a_note_for_the_reviewer():
    d = draft(item(), "not_a_code")
    assert any("unrecognised grounds" in n for n in d.notes)


def test_known_grounds_are_marked_recognised():
    for code in GROUNDS:
        assert draft(item(), code).grounds_recognised is True


# ── no legal assertion, no advice, no promised remedy ─────────────────────

_FORBIDDEN_LANGUAGE = (
    "u.s.c.", "usc ", "pursuant to", "under section", "violates",
    "in violation of", "you are legally", "required by law", "we demand",
    "entitled to", "will be refunded", "must refund", "statute",
    "fair credit billing act", "fcra", "fdcpa", "regulation z",
    "i will sue", "legal action will", "attorney", "damages",
)


@pytest.mark.parametrize("grounds", list(GROUNDS) + ["unknown_code"])
def test_draft_asserts_no_legal_position(grounds):
    body = draft(item(), grounds, holder="Dana").body.lower()
    for phrase in _FORBIDDEN_LANGUAGE:
        assert phrase not in body, f"draft cites/asserts {phrase!r}"


def test_grounds_table_itself_contains_no_legal_assertion():
    for sentence in GROUNDS.values():
        low = sentence.lower()
        for phrase in _FORBIDDEN_LANGUAGE:
            assert phrase not in low


def test_draft_promises_no_remedy():
    body = draft(item(), "already_paid").body.lower()
    for phrase in ("you must", "will be credited", "i expect a refund", "guarantee"):
        assert phrase not in body


def test_owner_gate_seam_is_recorded_on_the_draft():
    d = draft(item(), "duplicate")
    assert any("owner-only legal gate" in n for n in d.notes)


# ── no send path ──────────────────────────────────────────────────────────

_FORBIDDEN_MODULES = (
    "smtplib", "requests", "httpx", "urllib", "urllib3", "http",
    "socket", "ssl", "ftplib", "poplib", "imaplib", "telnetlib",
    "aiohttp", "websocket", "websockets", "paramiko", "twilio",
    "boto3", "sendgrid", "subprocess",
)


def test_module_namespace_contains_no_network_primitive():
    leaked = [name for name in vars(disputes) if name.lower() in _FORBIDDEN_MODULES]
    assert leaked == [], f"disputes.py exposes transmission primitives: {leaked}"


def test_module_source_imports_no_network_library():
    with open(disputes.__file__, "r") as handle:
        source = handle.read()
    for mod in _FORBIDDEN_MODULES:
        assert f"import {mod}" not in source
        assert f"from {mod}" not in source


def test_module_exposes_no_send_function():
    for name in dir(disputes):
        assert not name.lower().startswith(("send", "submit", "file_", "transmit", "post_"))


def test_drafting_invokes_no_socket(monkeypatch):
    import socket

    def _tripwire(*args, **kwargs):
        raise AssertionError("disputes attempted to open a socket")

    monkeypatch.setattr(socket, "socket", _tripwire)
    monkeypatch.setattr(socket, "create_connection", _tripwire)
    assert draft(item(), "duplicate").review_required is True

"""negotiate: baseline-driven proposals, budget gating, creep detection, and a
standing assertion that this module transmits nothing.
"""
import os
import sys

import pytest

_DELEGATION = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DELEGATION)
sys.path.insert(0, os.path.join(os.path.dirname(_DELEGATION), "contracts"))

import negotiate  # noqa: E402
from negotiate import (  # noqa: E402
    CREEP_MIN_PERIODS,
    PeriodObservation,
    detect_subscription_creep,
    propose,
    settle,
)
from autonomy import AuthorityBudget, AuthorityTier, NegotiationOutcome  # noqa: E402
from intake import parse_inbound  # noqa: E402


def bill(amount, issuer="Northwind Cable", due="2026-09-15"):
    return parse_inbound(
        f"From: {issuer}\nAccount: AC-9910\nAmount due: ${amount}\nDue date: {due}\n"
    )


def history(*amounts, issuer="Northwind Cable"):
    return [PeriodObservation(issuer=issuer, amount_usd=a, period=f"p{i}")
            for i, a in enumerate(amounts)]


def capped(cap=500.0):
    return AuthorityBudget(tier=AuthorityTier.CAPPED, cap_usd=cap, holder_id="h1")


# ── a bill above baseline produces a proposal with a justification ──────────

def test_above_baseline_bill_produces_proposal_with_justification():
    p = propose(bill(180.00), capped(500.0), history(100.00, 100.00, 100.00))
    assert p.should_negotiate is True
    assert p.justification.strip()
    assert p.target_reduction_usd > 0
    assert p.draft_message.strip()


def test_proposal_records_baseline_and_current_amount():
    p = propose(bill(180.00), capped(500.0), history(100.00, 100.00, 100.00))
    assert p.current_amount_usd == pytest.approx(180.00)
    assert p.baseline_usd == pytest.approx(100.00)


def test_bill_at_or_below_baseline_is_not_negotiated():
    p = propose(bill(100.00), capped(500.0), history(100.00, 100.00, 100.00))
    assert p.should_negotiate is False
    assert p.justification == ""


def test_trivial_overage_is_below_the_attention_floor():
    p = propose(bill(102.00), capped(500.0), history(100.00, 100.00, 100.00))
    assert p.should_negotiate is False


def test_no_history_means_no_baseline_and_no_proposal():
    p = propose(bill(180.00), capped(500.0), [])
    assert p.should_negotiate is False


def test_solicitation_is_never_negotiated():
    item = parse_inbound(
        "From: Apex Lending\nYou are pre-approved! Apply now.\nAmount due: $180.00\n"
        "Due date: 2026-09-15\n"
    )
    p = propose(item, capped(500.0), history(100.00, 100.00, 100.00))
    assert p.should_negotiate is False


# ── a proposal exceeding the budget: requires_approval, never accepted ──────

def test_proposal_exceeding_budget_requires_approval_and_is_not_accepted():
    p = propose(bill(900.00), capped(500.0), history(400.00, 400.00, 400.00))
    assert p.should_negotiate is True
    assert p.requires_approval is True
    assert p.accepted is False


def test_proposal_within_budget_does_not_require_approval():
    p = propose(bill(180.00), capped(500.0), history(100.00, 100.00, 100.00))
    assert p.requires_approval is False


def test_approval_only_budget_always_requires_approval():
    b = AuthorityBudget(tier=AuthorityTier.APPROVAL_ONLY, holder_id="h1")
    p = propose(bill(180.00), b, history(100.00, 100.00, 100.00))
    assert p.requires_approval is True
    assert p.accepted is False


def test_no_proposal_is_ever_auto_accepted():
    for amount in (120.00, 180.00, 900.00, 5000.00):
        p = propose(bill(amount), capped(500.0), history(100.00, 100.00, 100.00))
        assert p.accepted is False


def test_settle_refuses_to_record_acceptance_while_approval_is_pending():
    p = propose(bill(900.00), capped(500.0), history(400.00, 400.00, 400.00))
    assert p.requires_approval is True
    outcome = settle(p, accepted=True, counterparty_id="Northwind")
    assert isinstance(outcome, NegotiationOutcome)
    assert outcome.accepted is False


def test_settle_records_an_approved_outcome_using_the_contract_type():
    p = propose(bill(180.00), capped(500.0), history(100.00, 100.00, 100.00))
    outcome = settle(p, accepted=True, final_amount_usd=40.00)
    assert isinstance(outcome, NegotiationOutcome)
    assert outcome.accepted is True
    assert outcome.amount == pytest.approx(40.00)


# ── subscription creep: rising series yes, flat series no ──────────────────

def test_creep_detected_across_three_rising_periods():
    assert detect_subscription_creep(history(60.00, 72.00, 89.00)) is True


def test_creep_not_flagged_on_a_flat_series():
    assert detect_subscription_creep(history(60.00, 60.00, 60.00)) is False


def test_creep_not_flagged_on_a_falling_series():
    assert detect_subscription_creep(history(89.00, 72.00, 60.00)) is False


def test_creep_not_flagged_on_a_single_jump_in_an_otherwise_flat_series():
    assert detect_subscription_creep(history(60.00, 60.00, 95.00)) is False


def test_creep_needs_at_least_the_minimum_number_of_periods():
    assert detect_subscription_creep(history(60.00, 72.00)) is False
    assert len(history(60.00, 72.00)) < CREEP_MIN_PERIODS


def test_creep_surfaces_on_the_proposal_and_in_the_justification():
    p = propose(bill(89.00), capped(500.0), history(60.00, 72.00, 89.00))
    assert p.creep_detected is True
    assert "creep" in p.justification.lower()


@pytest.mark.parametrize("bad", [None, "history", 123, object(), [None, "x", {}]])
def test_creep_detection_never_raises_on_garbage(bad):
    assert detect_subscription_creep(bad) in (True, False)


@pytest.mark.parametrize("bad_item", [None, "bill", 0, object(), []])
def test_propose_never_raises_on_garbage_and_fails_closed(bad_item):
    p = propose(bad_item, capped(500.0), history(100.00, 100.00, 100.00))
    assert p.should_negotiate is False
    assert p.accepted is False
    assert p.requires_approval is True


# ── NO TRANSMISSION: prove no network primitive is reachable ───────────────

_FORBIDDEN_MODULES = (
    "smtplib", "requests", "httpx", "urllib", "urllib3", "http",
    "socket", "ssl", "ftplib", "poplib", "imaplib", "telnetlib",
    "aiohttp", "websocket", "websockets", "paramiko", "twilio",
    "boto3", "sendgrid", "subprocess",
)


def test_module_namespace_contains_no_network_primitive():
    leaked = [name for name in vars(negotiate) if name.lower() in _FORBIDDEN_MODULES]
    assert leaked == [], f"negotiate.py exposes transmission primitives: {leaked}"


def test_module_source_imports_no_network_library():
    with open(negotiate.__file__, "r") as handle:
        source = handle.read()
    for mod in _FORBIDDEN_MODULES:
        assert f"import {mod}" not in source, f"negotiate.py imports {mod}"
        assert f"from {mod}" not in source, f"negotiate.py imports from {mod}"


def test_propose_invokes_no_socket_even_when_one_is_available(monkeypatch):
    """Spy on the real socket primitive; a proposal must never touch it."""
    import socket

    calls = []

    def _tripwire(*args, **kwargs):
        calls.append(args)
        raise AssertionError("negotiate attempted to open a socket")

    monkeypatch.setattr(socket, "socket", _tripwire)
    monkeypatch.setattr(socket, "create_connection", _tripwire)

    p = propose(bill(180.00), capped(500.0), history(100.00, 100.00, 100.00))
    assert p.should_negotiate is True
    assert calls == []


def test_draft_message_is_returned_not_sent():
    p = propose(bill(180.00), capped(500.0), history(100.00, 100.00, 100.00))
    # The only egress is the returned string — the operator's reviewed seam.
    assert isinstance(p.draft_message, str)
    assert "DRAFT" in p.draft_message


def test_draft_message_asserts_no_legal_position():
    p = propose(bill(180.00), capped(500.0), history(100.00, 100.00, 100.00))
    low = p.draft_message.lower()
    for phrase in ("you are required by law", "pursuant to", "violation of",
                   "we demand", "legal action", "u.s.c."):
        assert phrase not in low

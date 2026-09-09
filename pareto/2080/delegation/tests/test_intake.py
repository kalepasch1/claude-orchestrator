"""intake: fixture bill parses, solicitations do not become bills, malformed
input degrades to `unknown`, and the package alias wiring resolves.
"""
import os
import sys

import pytest

# '2080' is not a valid Python identifier — same sys.path convention as
# pareto/2080/household_legal/tests/test_household_legal.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import intake  # noqa: E402
from intake import InboundItem, classify, parse_inbound  # noqa: E402


FIXTURE_BILL = """\
From: Pacific Gas & Electric
Account Number: 8891-2210-4
Statement period: 2026-07-01 to 2026-07-31

Amount due: $184.27
Due date: 2026-08-15

Please pay by the due date to avoid a late fee.
"""

FIXTURE_SOLICITATION = """\
From: Apex Lending Group
You are PRE-APPROVED for a personal loan of up to $25,000!

Consolidate your debt and lower your rate today. Apply now — limited time offer.
No obligation. To stop receiving these, unsubscribe here.
"""

FIXTURE_DISPUTE_RESPONSE = """\
From: Meridian Card Services
Account: 4410-9987

We have completed our investigation in response to your dispute of the
charge dated 2026-06-14. The disputed amount of $312.00 has been credited.
"""

FIXTURE_NOTICE = """\
From: City of Oakland Water
Account: WTR-55120
FINAL NOTICE — your account is past due. Amount due: $96.40.
Service is subject to disconnection.
"""

FIXTURE_STATEMENT = """\
From: Vanguard Brokerage
Account: Z-778120
Monthly statement. Statement period: 2026-07-01 to 2026-07-31.
Previous balance: $12,400.00. This is not a bill.
"""


# ── (1) a fixture bill parses to the right issuer, amount and due date ───────

def test_fixture_bill_parses_issuer_amount_and_due_date():
    item = parse_inbound(FIXTURE_BILL, source="mail")
    assert item.issuer == "Pacific Gas & Electric"
    assert item.amount_usd == pytest.approx(184.27)
    assert item.due_date == "2026-08-15"
    assert item.account_ref == "8891-2210-4"


def test_fixture_bill_classifies_as_bill():
    assert classify(parse_inbound(FIXTURE_BILL)) == intake.BILL


def test_parse_retains_raw_text_verbatim():
    item = parse_inbound(FIXTURE_BILL, source="mail")
    assert item.raw_text == FIXTURE_BILL


def test_amount_is_never_silently_rounded():
    item = parse_inbound("Amount due: $1,234.56\nDue date: 2026-09-01")
    assert item.amount_usd == pytest.approx(1234.56)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Due date: 2026-08-15", "2026-08-15"),
        ("Due date: 8/15/2026", "2026-08-15"),
        ("Payment due: August 15, 2026", "2026-08-15"),
    ],
)
def test_due_date_formats_normalize_to_iso(raw, expected):
    assert parse_inbound(raw).due_date == expected


# ── (2) a solicitation classifies as solicitation, NOT bill ─────────────────

def test_solicitation_is_not_a_bill():
    item = parse_inbound(FIXTURE_SOLICITATION, source="mail")
    assert classify(item) == intake.SOLICITATION
    assert classify(item) != intake.BILL


def test_solicitation_with_a_bill_shaped_amount_still_classifies_as_solicitation():
    # The dangerous case: junk mail carrying an amount and a deadline. If this
    # ever returns `bill`, the firewall can autonomously pay a stranger.
    raw = (
        "From: Apex Lending Group\n"
        "Amount due: $49.00\n"
        "Due date: 2026-09-30\n"
        "You may qualify! Apply now — no obligation.\n"
    )
    assert classify(parse_inbound(raw)) == intake.SOLICITATION


# ── (3) malformed input returns `unknown` and does NOT raise ────────────────

@pytest.mark.parametrize(
    "bad",
    [None, "", "   \n\t  ", 12345, [], {}, object(), b"\x00\x01\x02"],
)
def test_malformed_input_parses_without_raising(bad):
    item = parse_inbound(bad)
    assert isinstance(item, InboundItem)
    assert item.amount_usd is None
    assert item.due_date is None


@pytest.mark.parametrize("bad", [None, "", "   ", 12345, [], {}, object()])
def test_malformed_input_classifies_unknown_without_raising(bad):
    assert classify(bad) == intake.UNKNOWN


def test_unclassifiable_text_is_unknown_not_a_guess():
    assert classify(parse_inbound("Hi, lunch on Thursday?")) == intake.UNKNOWN


def test_amount_alone_is_not_enough_to_be_a_bill():
    # An amount with no due date and no bill language stays unknown.
    assert classify(parse_inbound("Your refund of $20.00 was processed.")) == intake.UNKNOWN


def test_classify_only_ever_returns_a_member_of_CLASSES():
    for fixture in (
        FIXTURE_BILL, FIXTURE_SOLICITATION, FIXTURE_DISPUTE_RESPONSE,
        FIXTURE_NOTICE, FIXTURE_STATEMENT, "", "nonsense",
    ):
        assert classify(parse_inbound(fixture)) in intake.CLASSES


# ── remaining classes ───────────────────────────────────────────────────────

def test_dispute_response_classifies():
    assert classify(parse_inbound(FIXTURE_DISPUTE_RESPONSE)) == intake.DISPUTE_RESPONSE


def test_notice_classifies():
    assert classify(parse_inbound(FIXTURE_NOTICE)) == intake.NOTICE


def test_statement_self_declaration_beats_bill_markers():
    assert classify(parse_inbound(FIXTURE_STATEMENT)) == intake.STATEMENT


# ── (4) package wiring: `from pareto.delegation import classify` resolves ────

def test_package_alias_import_resolves():
    repo_root = os.path.dirname(  # <repo>/
        os.path.dirname(          # <repo>/pareto/
            os.path.dirname(      # <repo>/pareto/2080/
                os.path.dirname(  # <repo>/pareto/2080/delegation/
                    os.path.dirname(os.path.abspath(__file__))
                )
            )
        )
    )
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from pareto.delegation import classify as aliased_classify
    from pareto.delegation import InboundItem as AliasedInboundItem

    assert aliased_classify(parse_inbound(FIXTURE_BILL)) == intake.BILL
    assert AliasedInboundItem is InboundItem


def test_classification_is_deterministic():
    item = parse_inbound(FIXTURE_BILL)
    assert len({classify(item) for _ in range(25)}) == 1

"""P2v2 Delegation firewall tests.

The two acceptance assertions the task names are `AuthorityFailClosedTests` (an
over-budget or unapproved action is BLOCKED) and
`FixtureBillNegotiationTests.test_fixture_bill_produces_a_signed_receipt`.

The rest hold the two failure directions apart, which is the design's only real
subtlety: `intake` must fail SOFT (a bad document costs one item) while `authority`
must fail CLOSED (anything unproven is denied). A test suite that only checked the
happy path would let those two drift into each other.
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import digest as digest_mod  # noqa: E402
import disputes  # noqa: E402
import intake  # noqa: E402
import negotiate  # noqa: E402
from _contracts import TIER_APPROVAL_ONLY, TIER_CAPPED, TIER_UNLIMITED, tier_of  # noqa: E402
from authority import (  # noqa: E402
    DENY_BAD_AMOUNT,
    DENY_NO_BUDGET,
    DENY_OVER_CAP,
    DENY_UNAPPROVED,
    DENY_UNKNOWN_TIER,
    TrustRatchet,
    approval_only_budget,
    authorize,
    capped_budget,
    unlimited_budget,
)

FIXTURE_BILL = """From: Northwind Energy
Subject: Your monthly statement

Amount due: $248.50
Payment due by March 14, 2027

Thank you for being a customer.
"""

FIXTURE_FEE = "From: Harbor Bank\nA late fee of $35.00 was applied to your account."

FIXTURE_RATE = ("From: Cascade Internet\n"
                "Notice of rate increase: your monthly price is going up to $89.99 "
                "effective next cycle.")


class ContractsWiringTests(unittest.TestCase):
    """The firewall must be using the real contracts, not silently shimming."""

    def test_contracts_module_is_importable(self):
        import _contracts

        self.assertIsNotNone(
            _contracts.contracts,
            "contracts/autonomy.py must import; a silent shim would mean these tests "
            "never exercise the real AuthorityBudget/Receipt types")

    def test_budgets_carry_the_contract_tiers(self):
        self.assertEqual(tier_of(approval_only_budget()), TIER_APPROVAL_ONLY)
        self.assertEqual(tier_of(capped_budget()), TIER_CAPPED)
        self.assertEqual(tier_of(unlimited_budget()), TIER_UNLIMITED)

    def test_capped_budget_defaults_to_the_spec_cap(self):
        self.assertEqual(capped_budget().cap_usd, 500.0)


class AuthorityFailClosedTests(unittest.TestCase):
    """ACCEPTANCE (a): an over-budget or unapproved action is BLOCKED."""

    def test_zero_tier_blocks_an_unapproved_action(self):
        decision = authorize(approval_only_budget(holder_id="h1"), amount_usd=1.00)
        self.assertFalse(decision.permitted)
        self.assertEqual(decision.reason, DENY_UNAPPROVED)
        self.assertTrue(decision.requires_approval)

    def test_zero_tier_allows_the_same_action_once_approved(self):
        decision = authorize(approval_only_budget(holder_id="h1"), amount_usd=1.00,
                             approved=True)
        self.assertTrue(decision.permitted)
        self.assertTrue(decision.requires_receipt)

    def test_capped_tier_blocks_over_cap(self):
        decision = authorize(capped_budget(cap_usd=500.0), amount_usd=500.01)
        self.assertFalse(decision.permitted)
        self.assertEqual(decision.reason, DENY_OVER_CAP)

    def test_capped_tier_allows_exactly_at_cap(self):
        self.assertTrue(authorize(capped_budget(cap_usd=500.0), amount_usd=500.0))

    def test_approval_cannot_lift_a_cap(self):
        """A ceiling liftable by the same click that satisfies it is not a ceiling."""
        decision = authorize(capped_budget(cap_usd=100.0), amount_usd=250.0,
                             approved=True)
        self.assertFalse(decision.permitted)
        self.assertEqual(decision.reason, DENY_OVER_CAP)

    def test_unlimited_tier_allows_but_demands_a_receipt(self):
        decision = authorize(unlimited_budget(), amount_usd=10_000.0)
        self.assertTrue(decision.permitted)
        self.assertTrue(decision.requires_receipt)

    def test_missing_budget_is_denied(self):
        decision = authorize(None, amount_usd=1.0)
        self.assertFalse(decision.permitted)
        self.assertEqual(decision.reason, DENY_NO_BUDGET)

    def test_unrecognised_tier_is_denied_not_assumed_safe(self):
        class Rogue:
            tier = "superuser"
            cap_usd = 0.0

        decision = authorize(Rogue(), amount_usd=1.0)
        self.assertFalse(decision.permitted)
        self.assertEqual(decision.reason, DENY_UNKNOWN_TIER)

    def test_unparseable_amount_is_denied(self):
        for bad in ("not a number", None, float("nan"), float("inf"), -5.0):
            with self.subTest(bad=bad):
                self.assertFalse(authorize(capped_budget(), amount_usd=bad).permitted)

    def test_boolean_amount_is_not_read_as_one_dollar(self):
        """isinstance(True, int) is True in Python; a bool must not slip through."""
        decision = authorize(capped_budget(), amount_usd=True)
        self.assertFalse(decision.permitted)
        self.assertEqual(decision.reason, DENY_BAD_AMOUNT)

    def test_decision_is_falsy_when_denied(self):
        self.assertFalse(bool(authorize(approval_only_budget(), amount_usd=1.0)))


class TrustRatchetTests(unittest.TestCase):
    def test_advance_is_one_step_and_never_skips_capped(self):
        ratchet = TrustRatchet()
        capped = ratchet.advance(approval_only_budget(holder_id="h1"))
        self.assertEqual(tier_of(capped), TIER_CAPPED)
        self.assertEqual(tier_of(ratchet.advance(capped)), TIER_UNLIMITED)

    def test_advance_preserves_the_holder(self):
        self.assertEqual(
            TrustRatchet().advance(approval_only_budget(holder_id="h9")).holder_id, "h9")

    def test_reverse_drops_straight_to_approval_only(self):
        """Trust is withdrawn because something went wrong; one notch is not enough."""
        self.assertEqual(
            tier_of(TrustRatchet().reverse(unlimited_budget(holder_id="h1"))),
            TIER_APPROVAL_ONLY)

    def test_reversed_budget_actually_blocks(self):
        reversed_budget = TrustRatchet().reverse(unlimited_budget(holder_id="h1"))
        self.assertFalse(authorize(reversed_budget, amount_usd=1.0).permitted)


class IntakeFailSoftTests(unittest.TestCase):
    """`intake` fails SOFT — the opposite of `authority`, on purpose."""

    def test_classifies_a_bill(self):
        self.assertEqual(intake.parse(FIXTURE_BILL).kind, intake.KIND_BILL)

    def test_classifies_a_fee(self):
        self.assertEqual(intake.parse(FIXTURE_FEE).kind, intake.KIND_FEE)

    def test_classifies_a_rate_change(self):
        self.assertEqual(intake.parse(FIXTURE_RATE).kind, intake.KIND_RATE_CHANGE)

    def test_extracts_a_comma_grouped_amount_in_full(self):
        """'$1,234.56' must not be truncated to 1."""
        self.assertEqual(intake.extract_amount("Total: $1,234.56"), 1234.56)

    def test_extracts_amount_and_vendor_and_due_date(self):
        item = intake.parse(FIXTURE_BILL)
        self.assertEqual(item.amount_usd, 248.50)
        self.assertEqual(item.vendor, "Northwind Energy")
        self.assertIn("March 14", item.due_date)

    def test_garbage_does_not_raise(self):
        for bad in (None, "", "   ", b"\xff\xfe\x00", 12345, object()):
            with self.subTest(bad=bad):
                item = intake.parse(bad)
                self.assertIsInstance(item, intake.InboundItem)

    def test_empty_document_is_marked_unparsed(self):
        self.assertFalse(intake.parse("").parsed)

    def test_one_bad_document_does_not_cost_the_batch(self):
        items = intake.parse_batch([FIXTURE_BILL, None, FIXTURE_FEE])
        self.assertEqual(len(items), 3)
        self.assertEqual(sum(1 for i in items if i.parsed), 2)

    def test_unrecognised_text_is_unknown_and_not_negotiable(self):
        item = intake.parse("Happy birthday from your dentist!")
        self.assertEqual(item.kind, intake.KIND_UNKNOWN)
        self.assertFalse(item.negotiable)


class FixtureBillNegotiationTests(unittest.TestCase):
    """ACCEPTANCE (b): a fixture bill negotiated in simulation yields a signed Receipt."""

    def test_fixture_bill_produces_a_signed_receipt(self):
        item = intake.parse(FIXTURE_BILL)
        result = negotiate.simulate(item, capped_budget(holder_id="h1", cap_usd=500.0))

        self.assertTrue(result.attempted, result.notes)
        self.assertIsNotNone(result.receipt)
        self.assertTrue(result.receipt.signature, "the receipt must be signed")
        self.assertTrue(negotiate.verify_receipt(result.receipt),
                        "the receipt's signature must verify against its contents")
        self.assertGreater(result.amount_saved, 0.0)
        self.assertAlmostEqual(result.proposed_usd + result.amount_saved,
                               result.original_usd, places=2)

    def test_tampering_with_a_receipt_invalidates_it(self):
        result = negotiate.simulate(intake.parse(FIXTURE_BILL), capped_budget())
        result.receipt.amount_saved = 9_999.0
        self.assertFalse(negotiate.verify_receipt(result.receipt))

    def test_unsigned_receipt_does_not_verify(self):
        result = negotiate.simulate(intake.parse(FIXTURE_BILL), capped_budget())
        result.receipt.signature = ""
        self.assertFalse(negotiate.verify_receipt(result.receipt))

    def test_negotiation_is_blocked_when_authority_denies(self):
        """The gate runs BEFORE the work, and a denial is not 'nothing to save'."""
        result = negotiate.simulate(intake.parse(FIXTURE_BILL), approval_only_budget())
        self.assertFalse(result.attempted)
        self.assertIsNone(result.receipt)
        self.assertFalse(result.decision.permitted)
        self.assertEqual(result.decision.reason, DENY_UNAPPROVED)

    def test_over_cap_bill_is_blocked(self):
        result = negotiate.simulate(intake.parse(FIXTURE_BILL),
                                    capped_budget(cap_usd=100.0))
        self.assertFalse(result.attempted)
        self.assertEqual(result.decision.reason, DENY_OVER_CAP)

    def test_non_negotiable_item_is_skipped_without_a_receipt(self):
        item = intake.parse("Happy birthday from your dentist!")
        result = negotiate.simulate(item, unlimited_budget())
        self.assertFalse(result.attempted)
        self.assertIsNone(result.receipt)

    def test_fee_recovers_more_than_a_bill(self):
        budget = unlimited_budget()
        fee = negotiate.simulate(intake.parse(FIXTURE_FEE), budget)
        bill = negotiate.simulate(intake.parse(FIXTURE_BILL), budget)
        self.assertGreater(fee.amount_saved / fee.original_usd,
                           bill.amount_saved / bill.original_usd)

    def test_batch_survives_a_bad_item(self):
        items = intake.parse_batch([FIXTURE_BILL, None, FIXTURE_FEE])
        results = negotiate.simulate_batch(items, unlimited_budget())
        self.assertEqual(len(results), 3)
        self.assertEqual(sum(1 for r in results if r.attempted), 2)


class DisputeTests(unittest.TestCase):
    def test_draft_is_blocked_without_authority(self):
        letter = disputes.draft(intake.parse(FIXTURE_FEE), approval_only_budget(),
                                reason=disputes.REASON_UNAUTHORIZED)
        self.assertFalse(letter.drafted)
        self.assertEqual(letter.body, "",
                         "a denied budget must not leave a ready-to-send letter behind")

    def test_draft_produces_a_signed_receipt(self):
        letter = disputes.draft(intake.parse(FIXTURE_FEE), unlimited_budget(),
                                reason=disputes.REASON_UNAUTHORIZED,
                                holder_name="A. Holder")
        self.assertTrue(letter.drafted, letter.notes)
        self.assertIn("$35.00", letter.body)
        self.assertIn("A. Holder", letter.body)
        self.assertTrue(negotiate.verify_receipt(letter.receipt))

    def test_a_draft_claims_no_saving(self):
        """Nothing has moved yet; claiming a saving would inflate the digest."""
        letter = disputes.draft(intake.parse(FIXTURE_FEE), unlimited_budget())
        self.assertEqual(letter.receipt.amount_saved, 0.0)

    def test_unknown_reason_falls_back_rather_than_raising(self):
        letter = disputes.draft(intake.parse(FIXTURE_FEE), unlimited_budget(),
                                reason="not-a-reason")
        self.assertEqual(letter.reason, disputes.REASON_OTHER)
        self.assertTrue(letter.drafted)


class DigestTests(unittest.TestCase):
    def _month(self, budget):
        items = intake.parse_batch([FIXTURE_BILL, FIXTURE_FEE, FIXTURE_RATE, None])
        negotiations = negotiate.simulate_batch(items, budget)
        drafts = [disputes.draft(items[1], budget,
                                 reason=disputes.REASON_UNAUTHORIZED)]
        return digest_mod.build(items=items, negotiations=negotiations,
                                disputes=drafts, period="March 2027")

    def test_digest_totals_the_savings_and_verifies(self):
        card = self._month(unlimited_budget())
        self.assertEqual(card.items_seen, 4)
        self.assertEqual(card.items_parsed, 3)
        self.assertEqual(card.negotiations_attempted, 3)
        self.assertGreater(card.total_saved, 0.0)
        self.assertTrue(digest_mod.verify_all(card))

    def test_blocked_items_are_reported_not_hidden(self):
        """An under-provisioned budget must not read as a quiet month."""
        card = self._month(approval_only_budget())
        self.assertEqual(card.negotiations_attempted, 0)
        self.assertTrue(card.blocked)
        self.assertGreater(card.awaiting_approval, 0)
        self.assertIn("waiting for your approval", card.render())

    def test_render_is_plain_text_with_the_period(self):
        self.assertIn("March 2027", self._month(unlimited_budget()).render())

    def test_empty_month_does_not_raise(self):
        card = digest_mod.build()
        self.assertEqual(card.items_seen, 0)
        self.assertIn("$0.00", card.render())

    def test_a_tampered_receipt_fails_the_month(self):
        card = self._month(unlimited_budget())
        card.receipts[0].amount_saved = 1_000_000.0
        self.assertFalse(digest_mod.verify_all(card))


if __name__ == "__main__":
    unittest.main()

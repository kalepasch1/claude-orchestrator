"""P3v2 Daily micro-sweeps tests.

The two acceptance assertions the task names are
`SweepEngineTests.test_a_run_generates_signed_receipts` (a sweep-engine test that
generates receipts) and `MeterTests.test_paid_for_itself_multiple_from_fixture_receipts`
(a meter test deriving "paid for itself ×N" from a fixture set of receipts).

The rest hold the two properties that make the meter trustworthy: sweeps FAIL SOFT
(a broken sweep costs one sweep, not the day), and the meter counts only receipts
whose signature verifies (so the product cannot self-certify its own worth).
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import engine  # noqa: E402
import meter  # noqa: E402
from _contracts import make_receipt  # noqa: E402

HOUSEHOLD = {
    "account": {"transactions": [{"amount": 4.30}, {"amount": 12.75}, {"amount": 0.50}]},
    "benefits": [
        {"name": "Energy credit", "value_usd": 120.0, "days_remaining": 12},
        {"name": "Expired credit", "value_usd": 90.0, "days_remaining": 400},
        {"name": "Already taken", "value_usd": 60.0, "days_remaining": 5, "claimed": True},
    ],
    "policies": [
        {"name": "Auto", "renewal_usd": 1400.0, "best_quote_usd": 1150.0},
        {"name": "Home", "renewal_usd": 900.0, "best_quote_usd": 950.0},
    ],
    "accounts": [
        {"name": "Checking", "balance_usd": 12000.0, "apy": 0.001, "best_apy": 0.045},
    ],
}


class ContractsWiringTests(unittest.TestCase):
    def test_contracts_module_is_importable(self):
        import _contracts

        self.assertIsNotNone(
            _contracts.contracts,
            "contracts/autonomy.py must import; a silent shim would mean these tests "
            "never exercise the real Receipt type")


class SweepEngineTests(unittest.TestCase):
    """ACCEPTANCE: the engine generates receipts."""

    def test_a_run_generates_signed_receipts(self):
        run = engine.run_all(HOUSEHOLD)

        self.assertEqual(run.failed, [], "no sweep should fail on a well-formed household")
        self.assertGreater(len(run.receipts), 0, "a productive run must emit receipts")
        self.assertGreater(run.total_saved, 0.0)
        for receipt in run.receipts:
            self.assertTrue(receipt.signature, "every savings receipt must be signed")
            self.assertTrue(engine.verify_receipt(receipt),
                            "every savings receipt must verify against its contents")
        self.assertAlmostEqual(
            run.total_saved,
            round(sum(r.amount_saved for r in run.receipts), 2), places=2)

    def test_harvest_rounds_transactions_up(self):
        result = engine.harvest(HOUSEHOLD["account"])
        self.assertAlmostEqual(result.saved_usd, 0.70 + 0.25 + 0.50, places=2)

    def test_benefit_window_ignores_expired_and_claimed(self):
        result = engine.benefit_window(HOUSEHOLD["benefits"])
        self.assertEqual(result.saved_usd, 120.0)

    def test_insurance_reshop_ignores_policies_already_below_market(self):
        result = engine.insurance_reshop(HOUSEHOLD["policies"])
        self.assertEqual(result.saved_usd, 250.0)

    def test_idle_cash_uses_the_yield_gap(self):
        result = engine.idle_cash(HOUSEHOLD["accounts"])
        self.assertAlmostEqual(result.saved_usd, 12000.0 * 0.044, places=2)

    def test_a_sweep_that_finds_nothing_emits_no_receipt(self):
        """A zero-value receipt would dilute the meter with events that paid nothing."""
        result = engine.benefit_window([])
        self.assertEqual(result.saved_usd, 0.0)
        self.assertIsNone(result.receipt)

    def test_immaterial_savings_emit_no_receipt(self):
        result = engine.harvest({"transactions": [{"amount": 10.99}]})
        self.assertLess(result.saved_usd, engine.MIN_MATERIAL_USD)
        self.assertIsNone(result.receipt)

    def test_empty_household_is_not_an_error(self):
        run = engine.run_all({})
        self.assertEqual(run.failed, [])
        self.assertEqual(run.total_saved, 0.0)

    def test_garbage_household_does_not_raise(self):
        for bad in (None, "not a dict", 42, []):
            with self.subTest(bad=bad):
                self.assertEqual(engine.run_all(bad).failed, [])

    def test_malformed_entries_are_skipped_not_fatal(self):
        run = engine.run_all({
            "benefits": [{"name": "ok", "value_usd": 50.0, "days_remaining": 3},
                         "not-a-dict", {"value_usd": "abc", "days_remaining": 1}],
            "policies": ["junk"],
            "accounts": [None],
            "account": {"transactions": ["junk", {"amount": None}]},
        })
        self.assertEqual(run.failed, [])
        self.assertEqual(run.total_saved, 50.0)


class FailSoftTests(unittest.TestCase):
    """One broken sweep must cost one sweep, not the day."""

    def test_a_raising_sweep_is_skipped_and_the_others_still_run(self):
        def boom(_household, _key):
            raise RuntimeError("upstream API is down")

        battery = dict(engine.DEFAULT_SWEEPS)
        battery["exploding"] = boom
        run = engine.run_all(HOUSEHOLD, sweeps=battery)

        self.assertIn("exploding", run.failed)
        self.assertGreater(run.total_saved, 0.0,
                           "the healthy sweeps must still have produced savings")
        failed = [r for r in run.results if r.name == "exploding"][0]
        self.assertFalse(failed.ok)
        self.assertIn("upstream API is down", failed.error)

    def test_a_sweep_returning_junk_is_contained(self):
        battery = {"rogue": lambda _h, _k: "not a SweepResult"}
        run = engine.run_all(HOUSEHOLD, sweeps=battery)
        self.assertIn("rogue", run.failed)
        self.assertEqual(run.receipts, [])

    def test_a_failed_sweep_contributes_no_savings(self):
        battery = {"exploding": lambda _h, _k: (_ for _ in ()).throw(ValueError("x"))}
        self.assertEqual(engine.run_all(HOUSEHOLD, sweeps=battery).total_saved, 0.0)


class MeterTests(unittest.TestCase):
    """ACCEPTANCE: 'paid for itself xN' derived from a fixture set of receipts."""

    def _fixture_receipts(self, amounts):
        out = []
        for i, amount in enumerate(amounts):
            receipt = make_receipt(explanation=f"fixture {i}", amount_saved=amount,
                                   action="sweep:fixture", timestamp=1_700_000_000.0 + i)
            receipt.signature = engine.sign_receipt(receipt)
            out.append(receipt)
        return out

    def test_paid_for_itself_multiple_from_fixture_receipts(self):
        receipts = self._fixture_receipts([120.0, 250.0, 30.0])   # 400.00 saved
        reading = meter.compute(receipts, subscription_cost=100.0, period="2027")

        self.assertEqual(reading.receipts_counted, 3)
        self.assertEqual(reading.receipts_rejected, 0)
        self.assertEqual(reading.total_saved, 400.0)
        self.assertEqual(reading.multiple, 4.0)
        self.assertTrue(reading.paid_for_itself)
        self.assertIn("Paid for itself ×4.0", reading.render())

    def test_multiple_is_purely_savings_over_cost(self):
        reading = meter.compute(self._fixture_receipts([50.0]), subscription_cost=200.0)
        self.assertEqual(reading.multiple, 0.25)
        self.assertFalse(reading.paid_for_itself)

    def test_unsigned_receipts_are_rejected(self):
        """A meter that counted forged receipts would be self-certifying."""
        receipts = self._fixture_receipts([100.0])
        receipts[0].signature = ""
        reading = meter.compute(receipts, subscription_cost=10.0)
        self.assertEqual(reading.receipts_counted, 0)
        self.assertEqual(reading.receipts_rejected, 1)
        self.assertEqual(reading.total_saved, 0.0)

    def test_tampered_receipts_are_rejected(self):
        receipts = self._fixture_receipts([100.0])
        receipts[0].amount_saved = 999_999.0
        reading = meter.compute(receipts, subscription_cost=10.0)
        self.assertEqual(reading.receipts_counted, 0)
        self.assertIn("missing or invalid signature", reading.rejected_reasons)

    def test_signature_check_can_be_disabled_explicitly(self):
        receipts = self._fixture_receipts([100.0])
        receipts[0].signature = ""
        reading = meter.compute(receipts, subscription_cost=10.0,
                                require_signature=False)
        self.assertEqual(reading.receipts_counted, 1)

    def test_zero_subscription_cost_is_undefined_not_infinite(self):
        reading = meter.compute(self._fixture_receipts([100.0]), subscription_cost=0.0)
        self.assertIsNone(reading.multiple)
        self.assertFalse(reading.paid_for_itself)
        self.assertIn("no multiple", reading.render())

    def test_meter_reads_a_sweep_run_directly(self):
        run = engine.run_all(HOUSEHOLD)
        reading = meter.compute(run, subscription_cost=50.0)
        self.assertEqual(reading.receipts_counted, len(run.receipts))
        self.assertEqual(reading.total_saved, run.total_saved)

    def test_meter_reads_a_receipt_store_protocol(self):
        class Store:
            def __init__(self, receipts):
                self._receipts = receipts

            def list_all(self, holder_id):
                return self._receipts

        reading = meter.compute(Store(self._fixture_receipts([10.0, 20.0])),
                                subscription_cost=6.0, holder_id="h1")
        self.assertEqual(reading.total_saved, 30.0)
        self.assertEqual(reading.multiple, 5.0)

    def test_empty_and_garbage_inputs_do_not_raise(self):
        for bad in (None, [], "junk", 42):
            with self.subTest(bad=bad):
                reading = meter.compute(bad, subscription_cost=10.0)
                self.assertEqual(reading.total_saved, 0.0)

    def test_unusable_amounts_are_rejected_not_counted_as_zero(self):
        receipts = self._fixture_receipts([10.0])
        receipts[0].amount_saved = "not a number"
        reading = meter.compute(receipts, subscription_cost=5.0)
        self.assertEqual(reading.receipts_rejected, 1)
        self.assertIn("unusable amount_saved", reading.rejected_reasons)

    def test_negative_subscription_cost_is_treated_as_unpaid(self):
        reading = meter.compute(self._fixture_receipts([10.0]), subscription_cost=-5.0)
        self.assertEqual(reading.subscription_cost, 0.0)
        self.assertIsNone(reading.multiple)


if __name__ == "__main__":
    unittest.main()

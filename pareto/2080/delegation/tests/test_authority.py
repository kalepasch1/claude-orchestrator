"""authority: tier boundaries, receipt emission, fail-closed paths, and the
guardian ratchet reverse.
"""
import math
import os
import sys

import pytest

# '2080' is not a valid Python identifier — same sys.path convention as
# pareto/2080/household_legal/tests/test_household_legal.py.
_DELEGATION = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DELEGATION)
sys.path.insert(0, os.path.join(os.path.dirname(_DELEGATION), "contracts"))

import authority  # noqa: E402
from authority import DEFAULT_CAP_USD, authorize  # noqa: E402
from autonomy import AuthorityBudget, AuthorityTier, Receipt  # noqa: E402


class StubStore:
    """Minimal ReceiptStore stand-in."""

    def __init__(self, raises=False):
        self.receipts = []
        self._raises = raises

    def store(self, receipt):
        if self._raises:
            raise RuntimeError("store unavailable")
        self.receipts.append(receipt)
        return f"r{len(self.receipts)}"

    def retrieve(self, receipt_id):
        return None

    def list_all(self, holder_id):
        return list(self.receipts)


class GuardianRatchet:
    """ReverseTrustRatchet stand-in: takeover demotes to APPROVAL_ONLY."""

    def takeover(self, budget, guardian_id):
        return AuthorityBudget(
            tier=AuthorityTier.APPROVAL_ONLY,
            cap_usd=0.0,
            holder_id=budget.holder_id,
            description=f"guardian takeover by {guardian_id}",
        )

    def release(self, budget):
        return budget


def capped(cap=DEFAULT_CAP_USD):
    return AuthorityBudget(tier=AuthorityTier.CAPPED, cap_usd=cap, holder_id="h1")


# ── APPROVAL_ONLY: never auto-allows, at any amount ─────────────────────────

@pytest.mark.parametrize("amount", [0, 0.01, 1, 499.99, 500, 500.01, 10_000, 1e9])
def test_approval_only_never_allows(amount):
    d = authorize(AuthorityBudget(tier=AuthorityTier.APPROVAL_ONLY, holder_id="h1"),
                  amount, "pay water bill")
    assert d.allowed is False
    assert d.requires_approval is True


# ── CAPPED: at, just under, just over ───────────────────────────────────────

def test_capped_just_under_is_allowed():
    d = authorize(capped(500.0), 499.99, "pay water bill")
    assert d.allowed is True and d.requires_approval is False


def test_capped_exactly_at_cap_is_allowed_inclusive():
    d = authorize(capped(500.0), 500.0, "pay water bill")
    assert d.allowed is True and d.requires_approval is False


def test_capped_just_over_requires_approval():
    d = authorize(capped(500.0), 500.01, "pay water bill")
    assert d.allowed is False and d.requires_approval is True


def test_capped_over_cap_is_never_silently_truncated():
    # The decision must not come back as "allowed, for the cap amount".
    d = authorize(capped(500.0), 1200.00, "pay tuition")
    assert d.allowed is False
    assert "truncat" in d.reason.lower()


def test_capped_budget_left_at_dataclass_default_uses_documented_default_cap():
    d = authorize(AuthorityBudget(tier=AuthorityTier.CAPPED, holder_id="h1"),
                  DEFAULT_CAP_USD, "pay water bill")
    assert d.allowed is True


@pytest.mark.parametrize("bad_cap", [float("nan"), float("inf"), -1.0, "500", None])
def test_capped_with_unusable_cap_fails_closed(bad_cap):
    b = AuthorityBudget(tier=AuthorityTier.CAPPED, holder_id="h1")
    b.cap_usd = bad_cap
    d = authorize(b, 10.0, "pay water bill")
    if bad_cap is None:
        assert d.allowed is True          # documented fallback to $500
    else:
        assert d.allowed is False and d.requires_approval is True


# ── UNLIMITED_WITH_RECEIPTS: allows, and writes exactly one receipt ─────────

def test_unlimited_allows_and_writes_exactly_one_receipt():
    store = StubStore()
    b = AuthorityBudget(tier=AuthorityTier.UNLIMITED_WITH_RECEIPTS, holder_id="h1")
    d = authorize(b, 25_000.00, "settle roof repair", store=store)
    assert d.allowed is True and d.requires_approval is False
    assert len(store.receipts) == 1
    assert isinstance(store.receipts[0], Receipt)
    assert d.receipt is store.receipts[0]


def test_unlimited_writes_one_receipt_per_call_not_more():
    store = StubStore()
    b = AuthorityBudget(tier=AuthorityTier.UNLIMITED_WITH_RECEIPTS, holder_id="h1")
    for _ in range(4):
        authorize(b, 10.0, "pay", store=store)
    assert len(store.receipts) == 4


def test_unlimited_without_store_fails_closed():
    b = AuthorityBudget(tier=AuthorityTier.UNLIMITED_WITH_RECEIPTS, holder_id="h1")
    d = authorize(b, 10.0, "pay", store=None)
    assert d.allowed is False and d.requires_approval is True


def test_unlimited_with_broken_store_fails_closed_and_records_nothing():
    store = StubStore(raises=True)
    b = AuthorityBudget(tier=AuthorityTier.UNLIMITED_WITH_RECEIPTS, holder_id="h1")
    d = authorize(b, 10.0, "pay", store=store)
    assert d.allowed is False and d.requires_approval is True
    assert store.receipts == []


def test_unlimited_with_store_missing_store_method_fails_closed():
    d = authorize(AuthorityBudget(tier=AuthorityTier.UNLIMITED_WITH_RECEIPTS, holder_id="h1"),
                  10.0, "pay", store=object())
    assert d.allowed is False and d.requires_approval is True


# ── fail-closed: unknown tier / bad amount / no budget ──────────────────────

@pytest.mark.parametrize("tier", ["capped", None, 0, 1, object(), "UNLIMITED_WITH_RECEIPTS"])
def test_unknown_tier_fails_closed(tier):
    b = AuthorityBudget(holder_id="h1")
    b.tier = tier
    d = authorize(b, 10.0, "pay", store=StubStore())
    assert d.allowed is False and d.requires_approval is True


@pytest.mark.parametrize(
    "amount",
    [-0.01, -1, -1e9, float("nan"), float("inf"), float("-inf"),
     None, "100", [], {}, True, False],
)
def test_bad_amount_fails_closed(amount):
    d = authorize(capped(500.0), amount, "pay", store=StubStore())
    assert d.allowed is False and d.requires_approval is True


def test_absent_budget_fails_closed():
    d = authorize(None, 10.0, "pay", store=StubStore())
    assert d.allowed is False and d.requires_approval is True


def test_authorize_never_raises_on_garbage():
    for bad in [object(), 0, "budget", [], {}]:
        d = authorize(bad, 10.0, "pay", store=StubStore())
        assert d.allowed is False and d.requires_approval is True


def test_allowed_and_requires_approval_are_never_both_true():
    cases = [
        (AuthorityBudget(tier=AuthorityTier.APPROVAL_ONLY, holder_id="h"), 10.0, None),
        (capped(500.0), 10.0, None),
        (capped(500.0), 10_000.0, None),
        (AuthorityBudget(tier=AuthorityTier.UNLIMITED_WITH_RECEIPTS, holder_id="h"),
         10.0, StubStore()),
    ]
    for budget, amount, store in cases:
        d = authorize(budget, amount, "pay", store=store)
        assert not (d.allowed and d.requires_approval)


# ── guardian takeover: ratchet reverse demotes, next call re-evaluates ──────

def test_ratchet_reverse_demotes_and_next_call_is_re_evaluated_lower():
    budget = AuthorityBudget(tier=AuthorityTier.CAPPED, cap_usd=500.0, holder_id="parent")

    before = authorize(budget, 250.0, "pay pharmacy")
    assert before.allowed is True

    demoted = GuardianRatchet().takeover(budget, guardian_id="adult-child")
    assert demoted.tier is AuthorityTier.APPROVAL_ONLY

    after = authorize(demoted, 250.0, "pay pharmacy")
    assert after.allowed is False and after.requires_approval is True


def test_takeover_then_release_round_trip_is_re_evaluated_each_time():
    ratchet = GuardianRatchet()
    budget = capped(500.0)
    demoted = ratchet.takeover(budget, "guardian-1")
    assert authorize(demoted, 100.0, "pay").allowed is False
    # The original budget object is untouched by the takeover.
    assert authorize(budget, 100.0, "pay").allowed is True


def test_decision_carries_a_human_readable_reason():
    for d in (authorize(capped(500.0), 10.0, "pay"),
              authorize(capped(500.0), 10_000.0, "pay")):
        assert isinstance(d.reason, str) and d.reason.strip()

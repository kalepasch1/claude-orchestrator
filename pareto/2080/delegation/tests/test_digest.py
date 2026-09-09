"""digest: correct totals, separated counts, an empty period that still
renders, and a hard assertion that the contract AuditBundle is reused.
"""
import os
import sys
import time

import pytest

_DELEGATION = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DELEGATION)
sys.path.insert(0, os.path.join(os.path.dirname(_DELEGATION), "contracts"))

import digest as digest_mod  # noqa: E402
from digest import Digest, build_digest, render_card  # noqa: E402
from autonomy import AuditBundle, Receipt  # noqa: E402


import datetime

#: A moment INSIDE the 2026-08-01..2026-08-31 window every fixture uses.
#: Not time.time(): a receipt stamped "now" falls outside an August period and
#: is correctly filtered out, which would make these fixtures test nothing.
NOW = datetime.datetime(2026, 8, 15, 12, 0, 0).timestamp()


class StubStore:
    """ReceiptStore stand-in. The ONLY way digest may reach receipts."""

    def __init__(self, receipts=None, raises=False):
        self._receipts = list(receipts or [])
        self.raises = raises
        self.list_all_calls = []

    def store(self, receipt):
        self._receipts.append(receipt)
        return "r1"

    def retrieve(self, receipt_id):
        return None

    def list_all(self, holder_id):
        self.list_all_calls.append(holder_id)
        if self.raises:
            raise RuntimeError("store unavailable")
        return list(self._receipts)


def receipt(saved, action="negotiated cable bill", ts=None):
    return Receipt(
        explanation=f"I {action} and saved ${saved:,.2f}.",
        amount_saved=saved,
        action=action,
        timestamp=NOW if ts is None else ts,
    )


def build(store=None, **kw):
    return build_digest("2026-08-01", "2026-08-31", store, "h1", **kw)


# ── (1) mixed receipts total amount_saved correctly ───────────────────────

def test_mixed_receipts_total_correctly():
    store = StubStore([receipt(40.00), receipt(12.50), receipt(7.25)])
    d = build(store)
    assert d.total_saved_usd == pytest.approx(59.75)
    assert d.actions_taken == 3


def test_negative_and_zero_amounts_are_included_in_the_total():
    store = StubStore([receipt(40.00), receipt(-15.00), receipt(0.0)])
    d = build(store)
    assert d.total_saved_usd == pytest.approx(25.00)
    assert d.actions_taken == 3


def test_unusable_amounts_count_as_zero_not_as_an_error():
    r = receipt(10.00)
    r.amount_saved = "not a number"
    d = build(StubStore([r, receipt(5.00)]))
    assert d.total_saved_usd == pytest.approx(5.00)
    assert d.actions_taken == 2


def test_total_is_rounded_to_cents():
    d = build(StubStore([receipt(0.1), receipt(0.2)]))
    assert d.total_saved_usd == pytest.approx(0.30)


# ── (2) awaiting-approval and pending drafts are counted SEPARATELY ───────

def test_awaiting_and_drafts_are_not_folded_into_actions_taken():
    d = build(
        StubStore([receipt(40.00), receipt(10.00)]),
        pending_approvals=["a", "b", "c"],
        pending_drafts=["d1", "d2"],
    )
    assert d.actions_taken == 2            # receipts only
    assert d.awaiting_approval == 3
    assert d.drafts_pending_review == 2


def test_pending_items_do_not_contribute_to_total_saved():
    d = build(
        StubStore([receipt(40.00)]),
        pending_approvals=["a", "b"],
        pending_drafts=["d1"],
    )
    assert d.total_saved_usd == pytest.approx(40.00)


def test_pending_only_period_reports_zero_actions_taken():
    d = build(StubStore([]), pending_approvals=["a"], pending_drafts=["d"])
    assert d.actions_taken == 0
    assert d.awaiting_approval == 1 and d.drafts_pending_review == 1


def test_card_states_pending_items_separately_from_things_done():
    card = build(
        StubStore([receipt(40.00)]),
        pending_approvals=["a"], pending_drafts=["d"],
    ).render()
    assert "need your OK" in card
    assert "waiting for you to read" in card


# ── (3) an empty period yields a valid card with zeros, no exception ──────

def test_empty_period_yields_zeros_and_no_exception():
    d = build(StubStore([]))
    assert d.total_saved_usd == 0.0
    assert d.actions_taken == 0
    assert d.awaiting_approval == 0
    assert d.drafts_pending_review == 0
    assert d.is_empty is True


def test_empty_period_still_renders_a_readable_card():
    card = build(StubStore([])).render()
    assert card.strip()
    assert "Nothing needed your attention" in card


def test_absent_store_yields_a_valid_empty_card():
    d = build(None)
    assert d.actions_taken == 0
    assert d.render().strip()


def test_broken_store_degrades_instead_of_raising():
    d = build(StubStore(raises=True))
    assert d.actions_taken == 0
    assert d.render().strip()


@pytest.mark.parametrize("bad_store", [object(), 0, "store", [], {}])
def test_store_without_the_protocol_method_degrades(bad_store):
    d = build(bad_store)
    assert d.actions_taken == 0


@pytest.mark.parametrize("bad", [object(), 0, "d1", b"d1"])
def test_uncountable_pending_collections_report_zero_and_note_it(bad):
    d = build(StubStore([]), pending_approvals=bad, pending_drafts=bad)
    assert d.awaiting_approval == 0 and d.drafts_pending_review == 0


def test_a_bare_string_is_not_counted_as_its_characters():
    # list("d1") is 2 — a caller who passed one id as a string must not see
    # "2 drafts waiting" on an audit card.
    d = build(StubStore([]), pending_drafts="d1")
    assert d.drafts_pending_review == 0
    assert any("not a collection" in n for n in d.notes)


def test_none_means_zero_without_a_warning():
    d = build(StubStore([]), pending_approvals=None, pending_drafts=None)
    assert d.awaiting_approval == 0 and d.drafts_pending_review == 0
    assert d.notes == []


def test_receipts_outside_the_period_are_excluded():
    inside = receipt(40.00, ts=NOW)
    before = receipt(99.00, ts=datetime.datetime(2026, 7, 4).timestamp())
    after = receipt(99.00, ts=datetime.datetime(2026, 9, 9).timestamp())
    d = build(StubStore([before, inside, after]))
    assert d.actions_taken == 1
    assert d.total_saved_usd == pytest.approx(40.00)


def test_an_iso_end_date_includes_the_whole_last_day():
    late = receipt(40.00, ts=datetime.datetime(2026, 8, 31, 23, 30).timestamp())
    assert build(StubStore([late])).actions_taken == 1


def test_a_receipt_with_no_usable_timestamp_is_kept_not_dropped():
    # Under-reporting an autonomous agent's spending is the worse failure.
    r = receipt(40.00)
    r.timestamp = None
    assert build(StubStore([r])).actions_taken == 1


def test_build_digest_never_raises_on_garbage_periods():
    for start, end in [(None, None), (0, 0), (object(), object()), ("x", "y")]:
        assert isinstance(build_digest(start, end, StubStore([]), "h1"), Digest)


# ── (4) the contract AuditBundle is REUSED, not forked ───────────────────

def test_digest_bundle_is_the_contract_audit_bundle():
    d = build(StubStore([receipt(40.00)]))
    assert isinstance(d.bundle, AuditBundle)
    assert type(d.bundle) is AuditBundle


def test_the_module_imports_the_contract_type_rather_than_defining_one():
    # A future refactor that defines a local AuditBundle fails here.
    assert digest_mod.AuditBundle is AuditBundle


def test_bundle_carries_the_period_and_the_receipts():
    receipts = [receipt(40.00), receipt(10.00)]
    d = build(StubStore(receipts))
    assert d.bundle.period_start == "2026-08-01"
    assert d.bundle.period_end == "2026-08-31"
    assert len(d.bundle.receipts) == 2
    assert all(isinstance(r, Receipt) for r in d.bundle.receipts)


def test_empty_period_still_produces_a_contract_bundle():
    assert isinstance(build(StubStore([])).bundle, AuditBundle)


# ── receipts come only through the ReceiptStore protocol ────────────────

def test_receipts_are_sourced_through_list_all_only():
    store = StubStore([receipt(40.00)])
    build(store)
    assert store.list_all_calls == ["h1"]


def test_digest_does_not_touch_the_filesystem(monkeypatch):
    def _tripwire(*args, **kwargs):
        raise AssertionError("digest touched the filesystem")

    monkeypatch.setattr("builtins.open", _tripwire)
    d = build(StubStore([receipt(40.00)]))
    assert d.actions_taken == 1


# ── plain language ──────────────────────────────────────────────────────

def test_card_uses_plain_language_and_no_jargon():
    card = build(
        StubStore([receipt(40.00)]),
        pending_approvals=["a"], pending_drafts=["d"],
    ).render().lower()
    for jargon in ("authoritytier", "receiptstore", "auditbundle", "requires_approval",
                   "inbounditem", "amount_saved", "protocol", "dataclass", "null"):
        assert jargon not in card


def test_card_leads_with_the_money():
    assert "saved you $59.75" in build(
        StubStore([receipt(40.00), receipt(19.75)])
    ).render()


def test_long_period_is_capped_so_the_card_stays_a_card():
    d = build(StubStore([receipt(1.00) for _ in range(40)]))
    assert d.actions_taken == 40
    assert "and 35 more" in d.render()
    assert len(d.render().splitlines()) < 15


def test_render_card_never_raises():
    assert render_card(Digest()).strip()
    for bad in (None, 0, object()):
        assert isinstance(render_card(bad), str)

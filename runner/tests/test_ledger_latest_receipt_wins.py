"""A release is certified by its CURRENT journey verdict, not its best-ever one.

Found while running the first real end-to-end journey trace: two receipts landed for
one release sha (a FAIL, then a PASS after the probe bug was fixed). The selection was
`[r for r in candidates if r["ok"] is True][-1]` — any passing row, newest ignored.
Reverse the order and a release whose journey now fails still projects as verified.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import canonical_proof_ledger as ledger

SHA = "1056c81d73bccf34227101f7355b54a102bd5131"


def _row(ok, recorded_at, journey="http", url="https://apparently.cc"):
    return {"release_sha": SHA, "journey": journey, "ok": ok,
            "url": url, "recorded_at": recorded_at}


def test_latest_pass_certifies():
    journeys = {SHA: [_row(False, "2026-08-23T17:51:49Z"), _row(True, "2026-08-23T17:53:58Z")]}
    rec, why = ledger._journey_receipt(SHA, journeys)
    assert rec is not None, why
    assert "17:53:58" in rec["detail"]


def test_later_failure_supersedes_an_earlier_pass():
    journeys = {SHA: [_row(True, "2026-08-23T10:00:00Z"), _row(False, "2026-08-23T11:00:00Z")]}
    rec, why = ledger._journey_receipt(SHA, journeys)
    assert rec is None, "a stale pass must not certify a release that now fails"
    assert "most recent" in why
    assert "superseded" in why


def test_selection_does_not_depend_on_caller_ordering():
    """Same rows, reversed. The verdict must not change."""
    rows = [_row(True, "2026-08-23T10:00:00Z"), _row(False, "2026-08-23T11:00:00Z")]
    a, _ = ledger._journey_receipt(SHA, {SHA: rows})
    b, _ = ledger._journey_receipt(SHA, {SHA: list(reversed(rows))})
    assert a is None and b is None


def test_required_journey_still_filters_before_recency():
    """A newer receipt for a DIFFERENT journey must not shadow the required one."""
    journeys = {SHA: [_row(True, "2026-08-23T10:00:00Z", journey="checkout"),
                      _row(False, "2026-08-23T11:00:00Z", journey="smoke")]}
    rec, why = ledger._journey_receipt(SHA, journeys, required_journey="checkout")
    assert rec is not None, why
    assert "journey=checkout" in rec["detail"]


def test_no_receipt_at_all_is_distinct_from_a_failing_one():
    rec, why = ledger._journey_receipt(SHA, {})
    assert rec is None
    assert why == "no production journey receipt for this release sha"


def test_missing_recorded_at_does_not_raise():
    journeys = {SHA: [_row(True, None), _row(True, "2026-08-23T11:00:00Z")]}
    rec, why = ledger._journey_receipt(SHA, journeys)
    assert rec is not None, why

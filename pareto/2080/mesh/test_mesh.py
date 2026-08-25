"""P5v2 intergenerational mesh: authority fails CLOSED, parsing fails SOFT.

The load-bearing assertions here are the negative ones. A guardian edge is
what separates "my daughter manages my accounts" from "a stranger does", so
every transition is tested for refusal without that edge, and the refusal must
leave state byte-identical to what went in.
"""
import os
import sys

import pytest

# '2080' is not a valid Python identifier — same sys.path convention as
# pareto/2080/contracts/test_contracts_smoke.py and household_legal.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts"))

import autonomy  # noqa: E402
import child_lanes as cl  # noqa: E402
import estate as es  # noqa: E402
import passport as pp  # noqa: E402
import takeover as tk  # noqa: E402


GRANDPARENT, PARENT, CHILD, STRANGER = "gp", "parent", "child", "stranger"


@pytest.fixture()
def household():
    """gp -guardian_of-> parent -guardian_of-> child; stranger is unrelated."""
    return [
        pp.make_passport("h1", GRANDPARENT, [PARENT], pp.AUTHORITY_GUARDIAN),
        pp.make_passport("h1", PARENT, [CHILD], pp.AUTHORITY_GUARDIAN),
        pp.make_passport("h1", CHILD, [], pp.AUTHORITY_DEPENDENT),
        pp.make_passport("h2", STRANGER, [], pp.AUTHORITY_MEMBER),
    ]


def _budget(holder, tier=autonomy.AuthorityTier.UNLIMITED_WITH_RECEIPTS, cap=10_000.0):
    return autonomy.AuthorityBudget(tier=tier, cap_usd=cap, holder_id=holder)


# --- passport: the guardian_of edge --------------------------------------

def test_uses_the_contracts_household_passport(household):
    assert isinstance(household[0], autonomy.HouseholdPassport)


def test_direct_guardian_has_authority(household):
    assert pp.has_authority_over(household, PARENT, CHILD) is True


def test_authority_is_transitive_across_generations(household):
    assert pp.has_authority_over(household, GRANDPARENT, CHILD) is True


def test_authority_is_not_symmetric(household):
    assert pp.has_authority_over(household, CHILD, PARENT) is False


def test_stranger_has_no_authority(household):
    assert pp.has_authority_over(household, STRANGER, CHILD) is False


def test_unknown_member_has_no_authority(household):
    assert pp.has_authority_over(household, "ghost", CHILD) is False


def test_self_authority_is_refused(household):
    assert pp.has_authority_over(household, PARENT, PARENT) is False


def test_blank_ids_are_refused(household):
    assert pp.has_authority_over(household, "", CHILD) is False
    assert pp.has_authority_over(household, PARENT, "") is False
    assert pp.has_authority_over(household, None, CHILD) is False


def test_guardians_and_wards_resolve(household):
    assert pp.guardians_of(household, CHILD) == [PARENT]
    assert pp.wards_of(household, GRANDPARENT) == [PARENT]


# --- passport: malformed graphs fail SOFT ---------------------------------

def test_malformed_passports_are_skipped_not_raised():
    mesh = pp.build_mesh([None, "not-a-passport", 42])
    assert mesh == {}


def test_a_malformed_entry_does_not_poison_valid_ones(household):
    mesh = pp.build_mesh(household + [None, object()])
    assert mesh[PARENT] == [CHILD]


def test_non_iterable_passports_returns_empty():
    assert pp.build_mesh(42) == {}


def test_a_cycle_does_not_hang_and_denies():
    cyclic = [
        pp.make_passport("h1", "a", ["b"]),
        pp.make_passport("h1", "b", ["a"]),
    ]
    assert pp.has_authority_over(cyclic, "a", "unrelated") is False
    assert pp.has_authority_over(cyclic, "a", "b") is True


# --- takeover: reverse trust-ratchet, fails CLOSED ------------------------

def test_ratchet_satisfies_the_reverse_trust_ratchet_protocol(household):
    assert isinstance(tk.HouseholdReverseRatchet(household), autonomy.ReverseTrustRatchet)


def test_guardian_takeover_ratchets_down_exactly_one_tier(household):
    ratchet = tk.HouseholdReverseRatchet(household)
    out = ratchet.takeover(_budget(PARENT), GRANDPARENT)
    assert out.tier is autonomy.AuthorityTier.CAPPED
    assert out.cap_usd == tk.DEFAULT_CAPPED_USD


def test_takeover_by_a_stranger_is_refused_and_changes_nothing(household):
    before = _budget(PARENT)
    after, reason = tk.HouseholdReverseRatchet(household).takeover_with_reason(before, STRANGER)
    assert after == before
    assert reason.startswith("denied")


def test_takeover_by_a_ward_of_the_holder_is_refused(household):
    """A child cannot ratchet down their own parent."""
    before = _budget(PARENT)
    after, reason = tk.HouseholdReverseRatchet(household).takeover_with_reason(before, CHILD)
    assert after == before
    assert reason.startswith("denied")


def test_holder_cannot_take_over_from_themselves(household):
    before = _budget(PARENT)
    after, reason = tk.HouseholdReverseRatchet(household).takeover_with_reason(before, PARENT)
    assert after == before
    assert "themselves" in reason


def test_takeover_with_no_holder_is_refused(household):
    before = _budget("")
    after, reason = tk.HouseholdReverseRatchet(household).takeover_with_reason(before, GRANDPARENT)
    assert after == before
    assert reason.startswith("denied")


def test_takeover_bottoms_out_at_approval_only(household):
    budget = _budget(PARENT, autonomy.AuthorityTier.APPROVAL_ONLY, 0.0)
    after, reason = tk.HouseholdReverseRatchet(household).takeover_with_reason(budget, GRANDPARENT)
    assert after == budget
    assert reason.startswith("no-op")


def test_graduated_takeover_walks_down_then_stops(household):
    out = tk.graduated_takeover(household, _budget(PARENT), GRANDPARENT, steps=5)
    assert out.tier is autonomy.AuthorityTier.APPROVAL_ONLY
    assert out.cap_usd == 0.0


def test_graduated_takeover_by_a_stranger_never_moves(household):
    before = _budget(PARENT)
    assert tk.graduated_takeover(household, before, STRANGER, steps=5) == before


def test_release_restores_one_tier(household):
    ratchet = tk.HouseholdReverseRatchet(household)
    lowered = ratchet.takeover(_budget(PARENT), GRANDPARENT)
    assert ratchet.release(lowered).tier is autonomy.AuthorityTier.UNLIMITED_WITH_RECEIPTS


# --- child lanes: graduation fails CLOSED ---------------------------------

def test_guardian_graduates_a_lane_one_stage(household):
    lane = cl.ChildLane(child_id=CHILD, household_id="h1", stage=cl.STAGE_SUPERVISED, age=14)
    out, reason = cl.graduate(household, lane, PARENT)
    assert out.stage == cl.STAGE_ASSISTED
    assert reason.startswith("granted")


def test_stranger_cannot_graduate_a_lane(household):
    lane = cl.ChildLane(child_id=CHILD, household_id="h1", stage=cl.STAGE_SUPERVISED, age=14)
    out, reason = cl.graduate(household, lane, STRANGER)
    assert out == lane
    assert reason.startswith("denied")


def test_a_child_cannot_graduate_their_own_lane(household):
    lane = cl.ChildLane(child_id=CHILD, household_id="h1", stage=cl.STAGE_SUPERVISED, age=14)
    out, reason = cl.graduate(household, lane, CHILD)
    assert out == lane
    assert reason.startswith("denied")


def test_graduation_below_the_age_floor_is_refused(household):
    lane = cl.ChildLane(child_id=CHILD, household_id="h1", stage=cl.STAGE_SUPERVISED, age=9)
    out, reason = cl.graduate(household, lane, PARENT)
    assert out == lane
    assert "requires age 13" in reason


def test_independence_requires_the_adult_age_floor(household):
    lane = cl.ChildLane(child_id=CHILD, household_id="h1", stage=cl.STAGE_ASSISTED, age=15)
    out, reason = cl.graduate(household, lane, PARENT)
    assert out == lane
    assert "requires age 18" in reason


def test_malformed_lane_is_refused_not_raised(household):
    out, reason = cl.graduate(household, None, PARENT)
    assert out is None
    assert reason.startswith("denied")


def test_unknown_stage_is_refused(household):
    lane = cl.ChildLane(child_id=CHILD, stage="wizard", age=30)
    out, reason = cl.graduate(household, lane, PARENT)
    assert out == lane
    assert reason.startswith("denied")


def test_own_account_requires_independence(household):
    lane = cl.ChildLane(child_id=CHILD, household_id="h1", stage=cl.STAGE_ASSISTED, age=19)
    out, reason = cl.open_own_account(household, lane, PARENT, "acct-1")
    assert out == lane
    assert "must reach independent" in reason


def test_independent_lane_opens_its_own_account(household):
    lane = cl.ChildLane(child_id=CHILD, household_id="h1", stage=cl.STAGE_INDEPENDENT, age=19)
    out, reason = cl.open_own_account(household, lane, PARENT, "acct-1")
    assert out.has_own_account is True
    assert reason.startswith("granted")


def test_stranger_cannot_open_an_account(household):
    lane = cl.ChildLane(child_id=CHILD, household_id="h1", stage=cl.STAGE_INDEPENDENT, age=19)
    out, reason = cl.open_own_account(household, lane, STRANGER, "acct-1")
    assert out == lane
    assert reason.startswith("denied")


def test_ready_to_graduate_is_advisory_only():
    lanes = [
        cl.ChildLane(child_id="a", stage=cl.STAGE_SUPERVISED, age=14),
        cl.ChildLane(child_id="b", stage=cl.STAGE_SUPERVISED, age=8),
        None,
    ]
    assert [l.child_id for l in cl.lanes_ready_to_graduate(lanes)] == ["a"]


# --- estate continuity ----------------------------------------------------

DAY = 86400.0


def _will(owner=PARENT, beneficiaries=None, age_days=0.0):
    import time
    return es.EstateDocument(
        doc_id="will-1", owner_id=owner, kind="will",
        beneficiaries=list(beneficiaries or [CHILD]),
        updated_at=time.time() - age_days * DAY,
    )


def test_a_fresh_document_is_not_stale():
    assert es.stale_documents([_will(age_days=10)]) == []


def test_a_document_past_its_review_window_is_stale():
    assert len(es.stale_documents([_will(age_days=400)])) == 1


def test_an_unreadable_date_is_treated_as_stale():
    doc = _will()
    doc.updated_at = "not-a-date"
    assert len(es.stale_documents([doc])) == 1


def test_malformed_documents_are_skipped_not_raised():
    assert es.stale_documents([None, "nope", 7]) == []


def test_a_beneficiary_who_left_the_household_is_flagged():
    doc = _will(beneficiaries=[CHILD, "ex-spouse"])
    assert es.orphaned_beneficiaries([doc], [PARENT, CHILD]) == {"will-1": ["ex-spouse"]}


def test_no_orphans_when_every_beneficiary_is_a_member():
    assert es.orphaned_beneficiaries([_will()], [PARENT, CHILD]) == {}


def test_guardian_may_sync_beneficiaries(household):
    doc, reason = es.sync_beneficiaries(household, _will(), GRANDPARENT, ["new-heir"])
    assert doc.beneficiaries == ["new-heir"]
    assert reason.startswith("granted")


def test_owner_may_sync_their_own_estate(household):
    doc, reason = es.sync_beneficiaries(household, _will(), PARENT, ["new-heir"])
    assert doc.beneficiaries == ["new-heir"]
    assert reason.startswith("granted")


def test_stranger_may_not_sync_beneficiaries(household):
    before = _will()
    doc, reason = es.sync_beneficiaries(household, before, STRANGER, ["thief"])
    assert doc.beneficiaries == [CHILD]
    assert reason.startswith("denied")


def test_sync_dedupes_and_drops_blanks(household):
    doc, _ = es.sync_beneficiaries(household, _will(), PARENT, ["a", "a", "", "  ", "b"])
    assert doc.beneficiaries == ["a", "b"]


def test_continuity_report_is_clean_for_a_current_estate():
    report = es.continuity_report([_will(age_days=5)], [PARENT, CHILD])
    assert report["current"] is True


def test_continuity_report_surfaces_drift():
    report = es.continuity_report(
        [_will(age_days=400, beneficiaries=["ex-spouse"])], [PARENT, CHILD]
    )
    assert report["current"] is False
    assert report["stale"] == ["will-1"]
    assert report["orphaned_beneficiaries"] == {"will-1": ["ex-spouse"]}

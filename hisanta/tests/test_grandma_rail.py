"""Tests for hisanta.grandma.rail module (20+ tests)."""

import pytest
from hisanta.contracts.family import (
    GiftLane,
    GrandmaStorySlot,
    MilestoneReaction,
    PII_FREE_FIELDS,
)
from hisanta.grandma.rail import GrandmaRail


@pytest.fixture
def rail():
    return GrandmaRail()


# --- record_story ---

def test_record_story_marks_recorded(rail):
    slot = GrandmaStorySlot(story_id="s1")
    result = rail.record_story(slot)
    assert result.recorded is True

def test_record_story_stored(rail):
    rail.record_story(GrandmaStorySlot(story_id="s1"))
    assert len(rail.stories) == 1

def test_record_story_preserves_id(rail):
    result = rail.record_story(GrandmaStorySlot(story_id="abc"))
    assert result.story_id == "abc"

def test_record_multiple_stories(rail):
    rail.record_story(GrandmaStorySlot(story_id="s1"))
    rail.record_story(GrandmaStorySlot(story_id="s2"))
    assert len(rail.stories) == 2

def test_record_story_custom_duration(rail):
    slot = GrandmaStorySlot(story_id="s1", duration_seconds=300)
    result = rail.record_story(slot)
    assert result.duration_seconds == 300


# --- add_milestone_reaction ---

def test_add_reaction_stored(rail):
    r = MilestoneReaction(milestone_id="m1", reaction_text="Wow!")
    rail.add_milestone_reaction(r)
    assert len(rail.reactions) == 1

def test_add_reaction_returns_reaction(rail):
    r = MilestoneReaction(milestone_id="m1", reaction_text="Wow!")
    result = rail.add_milestone_reaction(r)
    assert result.milestone_id == "m1"


# --- serialize_reaction (PII-free) ---

def test_serialize_contains_only_pii_free_fields(rail):
    r = MilestoneReaction(
        milestone_id="m1", reaction_text="Great!", child_name="Alice", approved=True
    )
    d = rail.serialize_reaction(r)
    assert set(d.keys()) == PII_FREE_FIELDS

def test_serialize_no_child_name(rail):
    r = MilestoneReaction(
        milestone_id="m1", reaction_text="Great!", child_name="Alice"
    )
    d = rail.serialize_reaction(r)
    assert "child_name" not in d

def test_serialize_values_correct(rail):
    r = MilestoneReaction(
        milestone_id="m1", reaction_text="Bravo!", child_name="Bob", approved=True
    )
    d = rail.serialize_reaction(r)
    assert d["milestone_id"] == "m1"
    assert d["reaction_text"] == "Bravo!"
    assert d["approved"] is True

def test_serialize_unapproved(rail):
    r = MilestoneReaction(milestone_id="m2", reaction_text="Nice")
    d = rail.serialize_reaction(r)
    assert d["approved"] is False


# --- get_visible_reactions ---

def test_visible_only_approved(rail):
    rail.add_milestone_reaction(
        MilestoneReaction(milestone_id="m1", reaction_text="A", approved=True)
    )
    rail.add_milestone_reaction(
        MilestoneReaction(milestone_id="m2", reaction_text="B", approved=False)
    )
    visible = rail.get_visible_reactions()
    assert len(visible) == 1
    assert visible[0]["milestone_id"] == "m1"

def test_visible_empty_when_none_approved(rail):
    rail.add_milestone_reaction(
        MilestoneReaction(milestone_id="m1", reaction_text="A", approved=False)
    )
    assert rail.get_visible_reactions() == []

def test_visible_empty_initially(rail):
    assert rail.get_visible_reactions() == []

def test_visible_pii_free(rail):
    rail.add_milestone_reaction(
        MilestoneReaction(
            milestone_id="m1", reaction_text="Yay", child_name="Eve", approved=True
        )
    )
    visible = rail.get_visible_reactions()
    assert "child_name" not in visible[0]

def test_visible_multiple_approved(rail):
    for i in range(5):
        rail.add_milestone_reaction(
            MilestoneReaction(milestone_id=f"m{i}", reaction_text=f"R{i}", approved=True)
        )
    assert len(rail.get_visible_reactions()) == 5


# --- fund_gift ---

def test_fund_gift_queued(rail):
    result = rail.fund_gift(10.0)
    assert result["queued"] is True

def test_fund_gift_not_direct_purchase(rail):
    result = rail.fund_gift(10.0)
    assert result["direct_purchase"] is False

def test_fund_gift_amount(rail):
    result = rail.fund_gift(25.50)
    assert result["amount"] == 25.50

def test_fund_gift_default_lane(rail):
    result = rail.fund_gift(5.0)
    assert result["lane"] == "AD_HOC"

def test_fund_gift_advent_lane(rail):
    result = rail.fund_gift(5.0, lane=GiftLane.ADVENT)
    assert result["lane"] == "ADVENT"

def test_fund_gift_earned_reward_lane(rail):
    result = rail.fund_gift(5.0, lane=GiftLane.EARNED_REWARD)
    assert result["lane"] == "EARNED_REWARD"

def test_fund_gift_adds_to_queue(rail):
    rail.fund_gift(10.0)
    rail.fund_gift(20.0)
    assert len(rail.gift_queue) == 2

def test_fund_gift_zero_amount(rail):
    result = rail.fund_gift(0.0)
    assert result["queued"] is True
    assert result["amount"] == 0.0

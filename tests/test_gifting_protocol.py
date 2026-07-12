"""Tests for H4 family gifting protocol."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from hisanta.contracts.family import ParentApproval, ApprovalStatus, constitution_check, ConstitutionAction
from hisanta.hisanta.gifting.protocol import (
    execute_gift, GiftRequest, GiftLane, GiftResult, MatchJar
)


def test_ad_hoc_fails_without_approval():
    req = GiftRequest(lane=GiftLane.AD_HOC, child_id="c1", item_description="toy")
    result = execute_gift(req, approval=None)
    assert not result.success
    assert "fail-closed" in result.message


def test_advent_fails_without_approval():
    req = GiftRequest(lane=GiftLane.ADVENT, child_id="c1", item_description="calendar gift")
    result = execute_gift(req)
    assert not result.success


def test_earned_reward_fails_without_approval():
    req = GiftRequest(lane=GiftLane.EARNED_REWARD, child_id="c1", item_description="badge")
    result = execute_gift(req)
    assert not result.success


def test_all_lanes_succeed_with_approval():
    approval = ParentApproval(parent_id="p1", child_id="c1", action_id="a1")
    for lane in GiftLane:
        req = GiftRequest(lane=lane, child_id="c1", item_description="item")
        result = execute_gift(req, approval)
        assert result.success, f"{lane} should succeed with approval"


def test_gift_actions_escalate_via_constitution():
    for action_type in ["gift", "advent_gift", "earned_reward", "match_jar"]:
        check = constitution_check(action_type)
        assert check == ConstitutionAction.ESCALATE, f"{action_type} should ESCALATE"


def test_all_lanes_mark_escalated():
    approval = ParentApproval(parent_id="p1", child_id="c1", action_id="a1")
    for lane in GiftLane:
        req = GiftRequest(lane=lane, child_id="c1", item_description="item")
        result = execute_gift(req, approval)
        assert result.escalated, f"{lane} should be escalated"


def test_denied_approval_fails():
    approval = ParentApproval(
        parent_id="p1", child_id="c1", action_id="a1",
        status=ApprovalStatus.DENIED
    )
    req = GiftRequest(lane=GiftLane.AD_HOC, child_id="c1", item_description="toy")
    result = execute_gift(req, approval)
    assert not result.success


def test_grandma_match_jar_with_approval():
    approval = ParentApproval(parent_id="p1", child_id="c1", action_id="match1")
    jar = MatchJar(funder_id="grandma1", funder_name="Grandma",
                   child_id="c1", match_ratio=1.0, max_match=50.0)
    matched = jar.match(20.0, approval)
    assert matched == 20.0
    assert jar.balance == 20.0


def test_grandma_match_jar_without_approval():
    jar = MatchJar(funder_id="grandma1", funder_name="Grandma",
                   child_id="c1", match_ratio=1.0)
    matched = jar.match(20.0, approval=None)
    assert matched == 0.0


def test_match_jar_respects_max():
    approval = ParentApproval(parent_id="p1", child_id="c1", action_id="m1")
    jar = MatchJar(funder_id="g1", funder_name="Grandma",
                   child_id="c1", match_ratio=1.0, max_match=30.0)
    matched = jar.match(50.0, approval)
    assert matched == 30.0


def test_bad_input_failsoft():
    result = execute_gift(None)
    assert not result.success
    result2 = execute_gift("garbage", "junk")
    assert not result2.success

"""Tests for H3 kindness mint — parent-verified kindness quests."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from hisanta.contracts.family import ParentVerificationReceipt, RewardCoins
from hisanta.hisanta.kindness.mint import mint_reward, mint_from_ai_verdict


def test_valid_receipt_mints_coins():
    receipt = ParentVerificationReceipt(
        parent_id="parent1", child_id="child1",
        quest_id="q1", description="helped neighbor"
    )
    coins = mint_reward(receipt)
    assert coins is not None
    assert isinstance(coins, RewardCoins)
    assert coins.amount == 10
    assert coins.child_id == "child1"
    assert coins.quest_id == "q1"


def test_no_receipt_returns_none():
    assert mint_reward(None) is None
    assert mint_reward() is None


def test_ai_verdict_rejected():
    assert mint_from_ai_verdict(child_id="c1", verdict="kind") is None


def test_non_receipt_object_rejected():
    """Non-ParentVerificationReceipt objects must not mint."""
    assert mint_reward("not a receipt") is None
    assert mint_reward({"parent_id": "p1"}) is None
    assert mint_reward(42) is None


def test_unverified_receipt_rejected():
    receipt = ParentVerificationReceipt(
        parent_id="p1", child_id="c1",
        quest_id="q1", description="act", verified=False
    )
    assert mint_reward(receipt) is None


def test_missing_fields_rejected():
    receipt = ParentVerificationReceipt(
        parent_id="", child_id="c1",
        quest_id="q1", description="act"
    )
    assert mint_reward(receipt) is None

    receipt2 = ParentVerificationReceipt(
        parent_id="p1", child_id="",
        quest_id="q1", description="act"
    )
    assert mint_reward(receipt2) is None


def test_custom_coin_amount():
    receipt = ParentVerificationReceipt(
        parent_id="p1", child_id="c1",
        quest_id="q1", description="act"
    )
    coins = mint_reward(receipt, coins_per_quest=25)
    assert coins.amount == 25

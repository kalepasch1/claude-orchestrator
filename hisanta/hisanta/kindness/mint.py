"""H3 Parent-verified kindness quests mint.

Real-world kindness acts are verified by a PARENT acting as oracle.
Only a valid ParentVerificationReceipt mints RewardCoins.
NO AI judgment of child behavior — reject any attempt to mint without
a parent receipt (fail-closed). Fail-soft on malformed input.
"""
from typing import Optional
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
from hisanta.contracts.family import ParentVerificationReceipt, RewardCoins


_DEFAULT_COINS_PER_QUEST = 10


def mint_reward(receipt: Optional[ParentVerificationReceipt] = None,
                coins_per_quest: int = _DEFAULT_COINS_PER_QUEST) -> Optional[RewardCoins]:
    """Mint RewardCoins for a verified kindness quest.

    Fail-closed: returns None (zero coins) if receipt is missing,
    invalid, or not a genuine ParentVerificationReceipt.
    Fail-soft: never raises on malformed input.
    """
    try:
        # Fail-closed: no receipt -> no coins
        if receipt is None:
            return None

        # Must be an actual ParentVerificationReceipt, not an AI verdict
        if not isinstance(receipt, ParentVerificationReceipt):
            return None

        # Must be verified by parent
        if not getattr(receipt, 'verified', False):
            return None

        # Must have required fields
        if not receipt.parent_id or not receipt.child_id or not receipt.quest_id:
            return None

        return RewardCoins(
            amount=coins_per_quest,
            child_id=receipt.child_id,
            quest_id=receipt.quest_id,
            source="kindness_mint",
        )
    except Exception:
        # Fail-soft: never raise
        return None


def mint_from_ai_verdict(**kwargs) -> Optional[RewardCoins]:
    """Explicitly rejected: AI-generated verdicts cannot mint coins."""
    return None

"""Grandma rail: story recording, milestone reactions, and gift funding."""

from __future__ import annotations

from hisanta.contracts.family import (
    GiftLane,
    GrandmaStorySlot,
    MilestoneReaction,
    PII_FREE_FIELDS,
)


class GrandmaRail:
    """Rail for grandma interactions with PII-safe serialization."""

    def __init__(self) -> None:
        self.stories: list[GrandmaStorySlot] = []
        self.reactions: list[MilestoneReaction] = []
        self.gift_queue: list[dict] = []

    def record_story(self, slot: GrandmaStorySlot) -> GrandmaStorySlot:
        """Mark a story slot as recorded and store it."""
        try:
            slot.recorded = True
            self.stories.append(slot)
            return slot
        except Exception:
            return slot

    def add_milestone_reaction(
        self, reaction: MilestoneReaction
    ) -> MilestoneReaction:
        """Store a milestone reaction."""
        try:
            self.reactions.append(reaction)
            return reaction
        except Exception:
            return reaction

    def get_visible_reactions(self) -> list[dict]:
        """Return only approved reactions, serialized with PII_FREE_FIELDS only."""
        try:
            return [
                self.serialize_reaction(r)
                for r in self.reactions
                if r.approved
            ]
        except Exception:
            return []

    def serialize_reaction(self, reaction: MilestoneReaction) -> dict:
        """Return dict with only PII_FREE_FIELDS keys (no child_name or other PII)."""
        try:
            return {
                k: getattr(reaction, k)
                for k in PII_FREE_FIELDS
                if hasattr(reaction, k)
            }
        except Exception:
            return {}

    def fund_gift(
        self, amount: float, lane: GiftLane = GiftLane.AD_HOC
    ) -> dict:
        """Add gift to parent queue (not a direct purchase)."""
        try:
            entry = {
                "queued": True,
                "amount": amount,
                "lane": lane.name,
                "direct_purchase": False,
            }
            self.gift_queue.append(entry)
            return entry
        except Exception:
            return {
                "queued": False,
                "amount": 0.0,
                "lane": GiftLane.AD_HOC.name,
                "direct_purchase": False,
            }

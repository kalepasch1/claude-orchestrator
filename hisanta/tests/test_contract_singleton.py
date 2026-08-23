"""The family contracts must exist exactly ONCE.

There used to be two files both spelling the module `hisanta.contracts.family`
with different definitions of ParentApproval, ParentVerificationReceipt,
CoppaConsent and constitution_check. Which one a caller got depended on which
directory happened to be on sys.path, so an isinstance check or an enum
comparison could fail across the seam, and hisanta/tests/* could not even be
collected. These tests fail the moment the duplicate starts growing back.
"""

import importlib

import pytest

import hisanta.contracts.family as family


def test_the_shim_points_at_the_canonical_file():
    """hisanta/contracts/family.py must re-export, never re-declare."""
    assert family.CANONICAL_PATH.replace("\\", "/").endswith(
        "hisanta/hisanta/contracts/family.py"
    )
    assert family.CANONICAL_MODULE is not None


def test_every_public_name_is_the_canonical_object():
    canonical = family.CANONICAL_MODULE
    assert family.__all__, "the shim must export something"
    for name in family.__all__:
        assert getattr(family, name) is getattr(canonical, name), (
            f"{name} is a SECOND definition, not the canonical one"
        )


def test_both_enums_for_a_constitution_verdict_are_the_same_object():
    """ConstitutionAction was a separate enum with the same member names —
    the classic way two halves of a codebase disagree about a verdict."""
    assert family.ConstitutionAction is family.ConstitutionVerdict
    assert family.ConstitutionAction.ESCALATE is family.ConstitutionVerdict.ESCALATE


def test_the_gifting_and_mastery_stacks_share_one_ParentApproval():
    protocol = importlib.import_module("hisanta.gifting.protocol")
    mint = importlib.import_module("hisanta.kindness.mint")
    assert protocol.ParentApproval is family.ParentApproval
    assert mint.ParentVerificationReceipt is family.ParentVerificationReceipt
    assert mint.RewardCoins is family.RewardCoins


def test_a_receipt_built_here_satisfies_the_mint_isinstance_check():
    """The concrete failure the duplicate caused: a receipt from one copy is
    not an instance of the other copy's class, so the mint silently returns
    None and the child never gets the coins they earned."""
    mint = importlib.import_module("hisanta.kindness.mint")
    receipt = family.ParentVerificationReceipt(
        parent_id="p1", child_id="c1", quest_id="q1", description="helped"
    )
    coins = mint.mint_reward(receipt)
    assert coins is not None
    assert isinstance(coins, family.RewardCoins)


def test_the_nested_subpackages_resolve_to_the_same_file():
    """hisanta.mastery.engine and hisanta.hisanta.mastery.engine must be the
    same source file, so it does not matter which rootdir a runner picks."""
    short = importlib.import_module("hisanta.mastery.engine")
    long = importlib.import_module("hisanta.hisanta.mastery.engine")
    assert short.__file__ == long.__file__


def test_both_spellings_of_the_engine_share_one_set_of_contracts():
    """Python gives the same file loaded under two module names two sets of
    CLASSES. That is harmless for the engine's own types, but it must never
    happen to the contracts — so every module in the stack imports them by the
    single absolute path `hisanta.contracts.family`, and both spellings of the
    engine therefore hold the identical RewardSchedule."""
    short = importlib.import_module("hisanta.mastery.engine")
    long = importlib.import_module("hisanta.hisanta.mastery.engine")
    assert short.RewardSchedule is family.RewardSchedule
    assert long.RewardSchedule is family.RewardSchedule
    assert short.MasteryEfficacyMetric is long.MasteryEfficacyMetric


@pytest.mark.parametrize(
    "action,expected",
    [
        ("charge_child", "DENY"),
        ("open_ended_child_chat", "DENY"),
        ("gift", "ESCALATE"),
        ("purchase", "ESCALATE"),
        ("advent_gift", "ESCALATE"),
        ("earned_reward", "ESCALATE"),
        ("match_jar", "ESCALATE"),
        ("loot", "ESCALATE"),
        ("ai_message", "ESCALATE"),
        ("view_story", "ALLOW"),
        ("", "ALLOW"),
    ],
)
def test_one_constitution_table_covers_both_callers(action, expected):
    """The two former copies disagreed: one escalated purchase/advent_gift/
    earned_reward/match_jar, the other loot/gift/ai_message. The merged table
    must cover every action either caller relied on."""
    assert family.constitution_check(action).name == expected

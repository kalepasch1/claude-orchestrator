"""The family contracts must exist exactly ONCE.

There used to be two files both spelling the module `hisanta.contracts.family`
with different definitions of ParentApproval, ParentVerificationReceipt,
CoppaConsent and constitution_check. Which one a caller got depended on which
directory happened to be on sys.path, so an isinstance check or an enum
comparison could fail across the seam, and hisanta/tests/* could not even be
collected. These tests fail the moment the duplicate starts growing back.

DIRECTION (settled 2026-08-24). This file used to assert that
`hisanta/contracts/family.py` was the SHIM and the nested file was canonical, while
`test_family_contract_single_source.py` asserted the exact opposite. Both were
committed; they cannot both pass, and the merge that left four files full of conflict
markers was the symptom, not the cause. The direction below is the one the rest of the
tree already states: `hisanta/__init__.py` appends the nested path and says in so many
words that it is "never prepended: hisanta/contracts stays the canonical
hisanta.contracts". So the top-level file holds the definitions and the NESTED file is
the shim. What these tests actually guard — one definition, same objects by either
spelling — is unchanged and still enforced.
"""

import importlib

import pytest

import hisanta.contracts.family as family
import hisanta.hisanta.contracts.family as nested


def test_the_shim_points_at_the_canonical_file():
    """hisanta/hisanta/contracts/family.py must re-export, never re-declare."""
    assert nested.CANONICAL_PATH.replace("\\", "/").endswith(
        "hisanta/contracts/family.py"
    )
    assert nested.CANONICAL_MODULE is family


def test_every_public_name_is_the_canonical_object():
    assert family.__all__, "the canonical module must export something"
    for name in family.__all__:
        assert getattr(nested, name) is getattr(family, name), (
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

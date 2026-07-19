"""Tests for hisanta.mastery.engine module (20+ tests)."""

import pytest
from hisanta.contracts.family import Quest, QuestKind, RewardSchedule
from hisanta.mastery.engine import MasteryEngine


@pytest.fixture
def engine():
    return MasteryEngine()


# --- schedule_review ---

def test_schedule_review_success_doubles(engine):
    result = engine.schedule_review(Quest(kind=QuestKind.READING), last_interval=2, success=True)
    assert result == 5  # 2 * 2.5 = 5

def test_schedule_review_success_from_1(engine):
    result = engine.schedule_review(Quest(kind=QuestKind.MATH), last_interval=1, success=True)
    assert result == 2  # 1 * 2.5 = 2.5 -> int(2.5) = 2

def test_schedule_review_success_large_interval(engine):
    result = engine.schedule_review(Quest(kind=QuestKind.READING), last_interval=10, success=True)
    assert result == 25  # 10 * 2.5

def test_schedule_review_fail_resets(engine):
    result = engine.schedule_review(Quest(kind=QuestKind.MATH), last_interval=10, success=False)
    assert result == 1

def test_schedule_review_fail_from_1(engine):
    result = engine.schedule_review(Quest(kind=QuestKind.KINDNESS), last_interval=1, success=False)
    assert result == 1

def test_schedule_review_min_interval_1(engine):
    result = engine.schedule_review(Quest(kind=QuestKind.READING), last_interval=0, success=True)
    assert result >= 1

def test_schedule_review_negative_interval(engine):
    result = engine.schedule_review(Quest(kind=QuestKind.READING), last_interval=-5, success=True)
    assert result >= 1


# --- adaptive_difficulty ---

def test_adaptive_increase(engine):
    result = engine.adaptive_difficulty(5, [0.9, 0.85, 0.95])
    assert result == 6

def test_adaptive_decrease(engine):
    result = engine.adaptive_difficulty(5, [0.1, 0.2, 0.3])
    assert result == 4

def test_adaptive_stay(engine):
    result = engine.adaptive_difficulty(5, [0.5, 0.6, 0.7])
    assert result == 5

def test_adaptive_clamp_max(engine):
    result = engine.adaptive_difficulty(10, [1.0, 1.0, 1.0])
    assert result == 10

def test_adaptive_clamp_min(engine):
    result = engine.adaptive_difficulty(1, [0.0, 0.0, 0.0])
    assert result == 1

def test_adaptive_empty_scores(engine):
    result = engine.adaptive_difficulty(5, [])
    assert result == 5

def test_adaptive_boundary_high(engine):
    # avg exactly 0.8 should NOT increase (> 0.8 required)
    result = engine.adaptive_difficulty(5, [0.8])
    assert result == 5

def test_adaptive_boundary_low(engine):
    # avg exactly 0.4 should NOT decrease (< 0.4 required)
    result = engine.adaptive_difficulty(5, [0.4])
    assert result == 5


# --- complete_weekly_quests ---

def test_weekly_all_complete(engine):
    quests = [
        Quest(kind=QuestKind.READING, completed=True),
        Quest(kind=QuestKind.MATH, completed=True),
    ]
    result = engine.complete_weekly_quests(quests)
    assert result["advent_door_opened"] is True
    assert result["doors_opened"] == 1

def test_weekly_not_all_complete(engine):
    quests = [
        Quest(kind=QuestKind.READING, completed=True),
        Quest(kind=QuestKind.MATH, completed=False),
    ]
    result = engine.complete_weekly_quests(quests)
    assert result["advent_door_opened"] is False
    assert result["doors_opened"] == 0

def test_weekly_empty_quests(engine):
    result = engine.complete_weekly_quests([])
    assert result["advent_door_opened"] is False

def test_weekly_opens_exactly_one_door(engine):
    quests = [Quest(kind=QuestKind.READING, completed=True) for _ in range(10)]
    result = engine.complete_weekly_quests(quests)
    assert result["doors_opened"] == 1


# --- create_reward_schedule ---

def test_reward_schedule_fixed(engine):
    rs = engine.create_reward_schedule("fixed", coupled_to_purchase=False)
    assert isinstance(rs, RewardSchedule)
    assert rs.schedule_type == "fixed"

def test_reward_schedule_variable_ratio_not_coupled(engine):
    rs = engine.create_reward_schedule("variable_ratio", coupled_to_purchase=False)
    assert rs is not None
    assert rs.variable_ratio_coupled_to_purchase is False

def test_reward_schedule_rejects_coupled_variable_ratio(engine):
    rs = engine.create_reward_schedule("variable_ratio", coupled_to_purchase=True)
    assert rs is None

def test_reward_schedule_coupled_but_fixed_ok(engine):
    rs = engine.create_reward_schedule("fixed", coupled_to_purchase=True)
    assert rs is not None


# --- get_efficacy_metrics ---

def test_efficacy_basic(engine):
    m = engine.get_efficacy_metrics("math", [0.8, 0.9, 1.0])
    assert m.subject == "math"
    assert m.attempts == 3
    assert abs(m.score - 0.9) < 0.01

def test_efficacy_empty_scores(engine):
    m = engine.get_efficacy_metrics("reading", [])
    assert m.subject == "reading"
    assert m.score == 0.0
    assert m.attempts == 0

def test_efficacy_single_score(engine):
    m = engine.get_efficacy_metrics("science", [0.75])
    assert m.attempts == 1
    assert abs(m.score - 0.75) < 0.01

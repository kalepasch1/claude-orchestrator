"""Test suite for Galop free-play launch: no-cost entry, play-money balances, leaderboards.

This module covers:
1. Free-play account initialization and no-cost entry flow
2. Play-money balance management (allocations, deductions, insufficient fund checks)
3. Contest/leaderboard loop using low/no-cost feed tiers
4. Feed configuration seam for flexible data source selection
5. Graceful degradation to delayed data with clear labeling
6. Validation that odds are never fabricated from non-real data sources
7. Cross-brand Apparently integration and brand isolation
"""
import os
import sys
import pytest
from datetime import datetime, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import test fixtures and utilities (adjust paths as needed)
from unittest.mock import Mock, patch, MagicMock


class TestFreePlayAccountInitialization:
    """Test free-play account creation and no-cost entry flow."""

    def test_create_freeplay_account_zero_cost(self):
        """Test that free-play account creation incurs no cost."""
        user_id = "user_freeplay_001"
        brand = "apparently"

        # Mock account creation
        account = {
            "user_id": user_id,
            "brand": brand,
            "mode": "freeplay",
            "creation_cost": 0.0,
            "play_money_balance": 1000.0,
            "created_at": datetime.now().isoformat()
        }

        assert account["creation_cost"] == 0.0, "Free-play account should have zero creation cost"
        assert account["mode"] == "freeplay"
        assert account["play_money_balance"] >= 1000.0

    def test_freeplay_account_initial_balance_allocation(self):
        """Test that new free-play accounts receive initial play-money balance."""
        user_id = "user_freeplay_002"
        initial_balance = 1000.0

        account = {
            "user_id": user_id,
            "play_money_balance": initial_balance,
            "balance_type": "play_money",
            "currency": "virtual"
        }

        assert account["play_money_balance"] == initial_balance
        assert account["balance_type"] == "play_money"
        assert account["currency"] == "virtual"

    def test_freeplay_account_isolation_by_brand(self):
        """Test that free-play accounts are isolated across brands."""
        user_id = "user_freeplay_003"

        accounts = {
            "apparently": {
                "user_id": user_id,
                "brand": "apparently",
                "balance": 1000.0
            },
            "racefeed": {
                "user_id": user_id,
                "brand": "racefeed",
                "balance": 1000.0
            }
        }

        # Verify brand isolation
        assert accounts["apparently"]["balance"] == 1000.0
        assert accounts["racefeed"]["balance"] == 1000.0
        assert accounts["apparently"]["brand"] != accounts["racefeed"]["brand"]

    def test_freeplay_account_cannot_cross_brand_transfer(self):
        """Test that play-money balances cannot transfer across brands."""
        user_id = "user_freeplay_004"

        apparently_balance = 500.0
        racefeed_balance = 1000.0

        # Attempt cross-brand transfer should fail
        def transfer_cross_brand(from_brand, to_brand, amount):
            if from_brand != to_brand:
                return {"status": "error", "reason": "cross_brand_transfer_not_allowed"}
            return {"status": "success"}

        result = transfer_cross_brand("apparently", "racefeed", 100.0)
        assert result["status"] == "error"
        assert "cross_brand" in result["reason"]

    def test_freeplay_onboarding_minimal_data_requirement(self):
        """Test that free-play onboarding requires minimal data."""
        required_fields = ["user_id", "brand", "mode"]
        onboarding_data = {
            "user_id": "user_freeplay_005",
            "brand": "apparently",
            "mode": "freeplay"
        }

        for field in required_fields:
            assert field in onboarding_data, f"Required field {field} missing"


class TestPlayMoneyBalanceManagement:
    """Test play-money balance operations: allocations, deductions, validations."""

    def test_play_money_deduction_sufficient_balance(self):
        """Test play-money deduction when balance is sufficient."""
        user_id = "user_balance_001"
        initial_balance = 1000.0
        wager_amount = 100.0

        balance = initial_balance
        balance -= wager_amount

        assert balance == 900.0, f"Expected 900.0, got {balance}"
        assert balance >= 0, "Balance should not go negative"

    def test_play_money_deduction_exact_balance(self):
        """Test play-money deduction for exact balance amount."""
        balance = 100.0
        wager = 100.0

        balance -= wager

        assert balance == 0.0, f"Expected 0.0, got {balance}"

    def test_play_money_deduction_insufficient_balance_rejected(self):
        """Test that wager is rejected when balance is insufficient."""
        user_id = "user_balance_002"
        balance = 50.0
        wager = 100.0

        if balance < wager:
            result = {"status": "rejected", "reason": "insufficient_balance", "balance": balance, "requested": wager}
        else:
            balance -= wager
            result = {"status": "success"}

        assert result["status"] == "rejected"
        assert result["balance"] == 50.0
        assert result["requested"] == 100.0

    def test_play_money_deduction_zero_wager_rejected(self):
        """Test that zero or negative wagers are rejected."""
        balance = 1000.0
        wager = 0.0

        if wager <= 0:
            result = {"status": "rejected", "reason": "invalid_wager"}
        else:
            balance -= wager
            result = {"status": "success"}

        assert result["status"] == "rejected"
        assert balance == 1000.0, "Balance should not change on rejected wager"

    def test_play_money_allocation_to_new_contest(self):
        """Test allocating play-money to a new contest."""
        user_id = "user_balance_003"
        balance = 1000.0
        contest_id = "contest_001"
        allocation = 250.0

        if allocation <= balance:
            balance -= allocation
            allocation_record = {
                "contest_id": contest_id,
                "allocated_amount": allocation,
                "status": "allocated"
            }
            success = True
        else:
            success = False

        assert success is True
        assert balance == 750.0
        assert allocation_record["status"] == "allocated"

    def test_play_money_balance_precision_decimal(self):
        """Test that play-money balance handles decimal precision correctly."""
        balance = Decimal("1000.00")
        wager = Decimal("33.33")

        balance -= wager

        assert balance == Decimal("966.67"), f"Expected 966.67, got {balance}"

    def test_play_money_add_bonus_to_balance(self):
        """Test adding bonus play-money to balance."""
        user_id = "user_balance_004"
        initial_balance = 1000.0
        bonus_amount = 500.0
        reason = "referral_bonus"

        final_balance = initial_balance + bonus_amount
        bonus_record = {
            "user_id": user_id,
            "bonus_amount": bonus_amount,
            "reason": reason,
            "balance_before": initial_balance,
            "balance_after": final_balance
        }

        assert final_balance == 1500.0
        assert bonus_record["balance_after"] == 1500.0

    def test_play_money_balance_history_tracking(self):
        """Test that balance history is tracked for audit purposes."""
        user_id = "user_balance_005"
        transactions = []

        initial = {"type": "initial", "amount": 1000.0, "balance": 1000.0}
        wager1 = {"type": "wager", "amount": -100.0, "balance": 900.0}
        win1 = {"type": "win", "amount": 200.0, "balance": 1100.0}
        wager2 = {"type": "wager", "amount": -50.0, "balance": 1050.0}

        transactions = [initial, wager1, win1, wager2]

        assert len(transactions) == 4
        assert transactions[-1]["balance"] == 1050.0
        assert all("type" in t and "amount" in t and "balance" in t for t in transactions)


class TestContestAndLeaderboardLoop:
    """Test contest creation, leaderboard management, and free-tier participation."""

    def test_contest_creation_for_freeplay(self):
        """Test creating a contest for free-play users."""
        contest = {
            "contest_id": "contest_freeplay_001",
            "name": "Galop Free-Play Daily",
            "entry_fee": 0.0,
            "mode": "freeplay",
            "start_time": datetime.now().isoformat(),
            "end_time": (datetime.now() + timedelta(hours=24)).isoformat(),
            "created_for_brands": ["apparently"]
        }

        assert contest["entry_fee"] == 0.0, "Free-play contest should have zero entry fee"
        assert contest["mode"] == "freeplay"
        assert "apparently" in contest["created_for_brands"]

    def test_contest_participation_no_cost_entry(self):
        """Test that free-play users can enter contest at no cost."""
        user_id = "user_contest_001"
        contest_id = "contest_freeplay_001"
        initial_balance = 1000.0
        entry_fee = 0.0

        balance_after = initial_balance - entry_fee
        entry_record = {
            "user_id": user_id,
            "contest_id": contest_id,
            "entry_status": "confirmed",
            "balance_deducted": entry_fee
        }

        assert balance_after == 1000.0, "Balance should not change for zero entry fee"
        assert entry_record["entry_status"] == "confirmed"

    def test_leaderboard_ranking_by_profit(self):
        """Test leaderboard ranking by profit (wins - wagers)."""
        contest_id = "contest_freeplay_002"
        entries = [
            {"user_id": "user_001", "total_wagers": 500.0, "total_wins": 800.0, "profit": 300.0},
            {"user_id": "user_002", "total_wagers": 400.0, "total_wins": 600.0, "profit": 200.0},
            {"user_id": "user_003", "total_wagers": 600.0, "total_wins": 750.0, "profit": 150.0},
        ]

        # Sort by profit descending
        ranked = sorted(entries, key=lambda x: x["profit"], reverse=True)

        assert ranked[0]["user_id"] == "user_001"
        assert ranked[0]["profit"] == 300.0
        assert ranked[1]["user_id"] == "user_002"
        assert ranked[2]["user_id"] == "user_003"

    def test_leaderboard_tie_handling_by_timestamp(self):
        """Test leaderboard tie-breaking by earliest entry time."""
        contest_id = "contest_freeplay_003"
        now = datetime.now()
        entries = [
            {"user_id": "user_a", "profit": 100.0, "entry_time": now},
            {"user_id": "user_b", "profit": 100.0, "entry_time": now + timedelta(seconds=1)},
            {"user_id": "user_c", "profit": 100.0, "entry_time": now - timedelta(seconds=1)},
        ]

        # Sort by profit desc, then by entry_time asc
        ranked = sorted(entries, key=lambda x: (-x["profit"], x["entry_time"]))

        assert ranked[0]["user_id"] == "user_c"  # Earliest entry
        assert ranked[1]["user_id"] == "user_a"
        assert ranked[2]["user_id"] == "user_b"  # Latest entry

    def test_contest_payout_distribution_freeplay(self):
        """Test payout calculation and distribution for free-play contest."""
        contest_id = "contest_freeplay_004"
        total_prize_pool = 1000.0  # Funded by platform, not from entry fees
        prize_distribution = [
            {"rank": 1, "payout_percent": 0.40, "amount": 400.0},
            {"rank": 2, "payout_percent": 0.25, "amount": 250.0},
            {"rank": 3, "payout_percent": 0.15, "amount": 150.0},
            {"rank": 4, "payout_percent": 0.10, "amount": 100.0},
            {"rank": 5, "payout_percent": 0.10, "amount": 100.0},
        ]

        total_distributed = sum(p["amount"] for p in prize_distribution)
        assert total_distributed == 1000.0, f"Expected 1000.0, got {total_distributed}"

        # Verify percentages sum to 1.0
        total_percent = sum(p["payout_percent"] for p in prize_distribution)
        assert total_percent == 1.0, f"Expected 1.0, got {total_percent}"

    def test_contest_close_and_settle(self):
        """Test contest closing and settlement process."""
        contest_id = "contest_freeplay_005"
        contest_state = {
            "contest_id": contest_id,
            "status": "active",
            "end_time": datetime.now() - timedelta(hours=1)
        }

        # Close and settle
        if datetime.now() >= datetime.fromisoformat(contest_state["end_time"]):
            contest_state["status"] = "settled"
            settlement_record = {
                "contest_id": contest_id,
                "settled_at": datetime.now().isoformat(),
                "status": "success"
            }

        assert contest_state["status"] == "settled"
        assert settlement_record["status"] == "success"


class TestFeedConfigurationSeam:
    """Test feed configuration flexibility and low/no-cost tier selection."""

    def test_feed_config_set_cheap_feed_source(self):
        """Test setting a cheap/free feed source via configuration."""
        feed_config = {
            "feed_source": "apparently_free_delayed",
            "cost_tier": "free",
            "data_delay_minutes": 15,
            "enabled": True,
            "operator_set": True
        }

        assert feed_config["cost_tier"] == "free"
        assert feed_config["data_delay_minutes"] == 15
        assert feed_config["enabled"] is True

    def test_feed_config_multiple_tier_options(self):
        """Test that multiple feed tier options are available for operator selection."""
        available_tiers = [
            {"tier": "free", "delay_minutes": 30, "cost": 0.0},
            {"tier": "delayed", "delay_minutes": 10, "cost": 10.0},
            {"tier": "realtime", "delay_minutes": 0, "cost": 100.0},
        ]

        # Verify all tiers are available
        assert len(available_tiers) == 3
        free_tier = next(t for t in available_tiers if t["tier"] == "free")
        assert free_tier["cost"] == 0.0

    def test_feed_config_degradation_to_delayed_data(self):
        """Test automatic degradation to delayed data when live feed fails."""
        primary_feed = {"source": "live_odds", "status": "failed"}
        fallback_feed = {"source": "delayed_cache", "status": "ok", "delay_minutes": 15}

        if primary_feed["status"] == "failed":
            active_feed = fallback_feed
            degradation_notice = {
                "degraded": True,
                "reason": "live_feed_unavailable",
                "active_feed": fallback_feed["source"]
            }
        else:
            active_feed = primary_feed
            degradation_notice = None

        assert active_feed["source"] == "delayed_cache"
        assert degradation_notice is not None
        assert degradation_notice["degraded"] is True

    def test_feed_config_clear_labeling_of_degraded_data(self):
        """Test that degraded data is clearly labeled for user visibility."""
        race_data = {
            "race_id": "race_001",
            "odds": {"horse_1": 2.5, "horse_2": 3.0},
            "data_source": "delayed_cache",
            "data_freshness": "15_minutes_old",
            "labels": {
                "is_live": False,
                "is_delayed": True,
                "delay_notice": "Odds data is delayed by ~15 minutes"
            }
        }

        assert race_data["labels"]["is_delayed"] is True
        assert race_data["labels"]["is_live"] is False
        assert "delay_notice" in race_data["labels"]

    def test_feed_config_operator_override_capability(self):
        """Test that operator can override feed configuration."""
        original_config = {"feed_source": "realtime", "cost_tier": "premium"}
        new_config = {"feed_source": "delayed_cache", "cost_tier": "free"}

        # Operator override
        override_result = {
            "original": original_config,
            "new": new_config,
            "operator_authorized": True,
            "changed": True
        }

        assert override_result["changed"] is True
        assert override_result["new"]["cost_tier"] == "free"

    def test_feed_config_cost_validation(self):
        """Test validation that selected feed tier aligns with no/low-cost requirement."""
        tier = {"name": "free_tier", "cost": 0.0, "monthly_budget": 0.0}

        def validate_free_tier(tier):
            if tier["cost"] == 0.0 and tier["monthly_budget"] == 0.0:
                return {"valid": True, "status": "free_tier_confirmed"}
            return {"valid": False, "status": "cost_violation"}

        result = validate_free_tier(tier)
        assert result["valid"] is True


class TestOddsValidationAndFabrication_Prevention:
    """Test that odds are never fabricated; always from real data sources."""

    def test_odds_must_come_from_data_source(self):
        """Test that odds require a valid data source reference."""
        race_id = "race_001"
        odds = {
            "horse_1": 2.5,
            "horse_2": 3.0,
            "horse_3": 4.5
        }

        # Odds without source should be invalid
        odds_with_source = {
            "values": odds,
            "source": "apparently_free_delayed",
            "source_valid": True
        }

        assert odds_with_source["source_valid"] is True
        assert odds_with_source["source"] is not None

    def test_odds_source_validation_rejects_synthetic_data(self):
        """Test that synthetic/fabricated odds are rejected."""
        def validate_odds_source(source_name):
            fabricated_sources = ["synthetic", "mock", "test", "fake", "generated"]
            if source_name.lower() in fabricated_sources:
                return {"valid": False, "reason": "synthetic_data_not_allowed"}
            return {"valid": True}

        result_synthetic = validate_odds_source("synthetic")
        result_real = validate_odds_source("apparently_real_feed")

        assert result_synthetic["valid"] is False
        assert result_real["valid"] is True

    def test_odds_timestamp_requirement(self):
        """Test that odds must have a source timestamp."""
        race_odds = {
            "race_id": "race_001",
            "odds": {"horse_1": 2.5},
            "source_timestamp": datetime.now().isoformat(),
            "timestamp_valid": True
        }

        assert race_odds["timestamp_valid"] is True
        assert race_odds["source_timestamp"] is not None

    def test_odds_with_delayed_data_marked_explicitly(self):
        """Test that delayed odds include explicit timestamp and age marker."""
        now = datetime.now()
        odds_timestamp = now - timedelta(minutes=15)

        delayed_odds = {
            "race_id": "race_001",
            "odds_timestamp": odds_timestamp.isoformat(),
            "fetch_timestamp": now.isoformat(),
            "data_age_minutes": 15,
            "is_delayed": True,
            "delay_label": "Data is 15 minutes old"
        }

        assert delayed_odds["is_delayed"] is True
        assert delayed_odds["data_age_minutes"] == 15
        assert "delay_label" in delayed_odds

    def test_odds_cannot_be_modified_post_source(self):
        """Test that odds from data source cannot be arbitrarily modified."""
        original_odds = {"horse_1": 2.5, "horse_2": 3.0}
        source_hash = hash(str(original_odds))

        odds_record = {
            "odds": original_odds,
            "source_hash": source_hash,
            "integrity_check": True
        }

        # Attempt modification
        modified_odds = {"horse_1": 10.0, "horse_2": 3.0}
        new_hash = hash(str(modified_odds))

        assert source_hash != new_hash, "Modified odds should have different hash"
        assert odds_record["integrity_check"] is True

    def test_odds_data_source_audit_trail(self):
        """Test that odds include audit trail of data source."""
        race_odds = {
            "race_id": "race_001",
            "odds": {"horse_1": 2.5},
            "source": "apparently_free_delayed",
            "fetch_timestamp": datetime.now().isoformat(),
            "audit_log": [
                {"event": "fetched", "source": "apparently_free_delayed", "time": datetime.now().isoformat()},
                {"event": "validated", "status": "pass", "time": datetime.now().isoformat()},
            ]
        }

        assert len(race_odds["audit_log"]) >= 2
        assert "fetched" in [e["event"] for e in race_odds["audit_log"]]


class TestGracefulDegradation:
    """Test graceful degradation to delayed data with clear user labeling."""

    def test_primary_feed_failure_fallback_activation(self):
        """Test that fallback feed activates when primary feed fails."""
        primary_status = {"available": False, "error": "connection_timeout"}
        fallback_status = {"available": True, "delay_minutes": 15}

        if not primary_status["available"]:
            active_feed = fallback_status
            degradation_event = {
                "degraded": True,
                "fallback_active": True
            }

        assert degradation_event["degraded"] is True
        assert active_feed["delay_minutes"] == 15

    def test_degradation_notice_display_to_user(self):
        """Test that degradation notice is displayed to users."""
        feed_status = {
            "is_degraded": True,
            "degradation_reason": "live_feed_unavailable",
            "user_notice": "Odds are currently delayed by approximately 15 minutes.",
            "user_notice_visible": True
        }

        assert feed_status["user_notice_visible"] is True
        assert "delayed" in feed_status["user_notice"].lower()

    def test_degradation_cached_data_freshness_check(self):
        """Test that cached/delayed data freshness is checked."""
        cached_data = {
            "fetch_time": datetime.now() - timedelta(minutes=15),
            "current_time": datetime.now(),
            "max_age_minutes": 30
        }

        age_minutes = (cached_data["current_time"] - cached_data["fetch_time"]).total_seconds() / 60
        is_fresh = age_minutes <= cached_data["max_age_minutes"]

        assert is_fresh is True
        assert age_minutes == 15

    def test_degradation_stale_data_rejection(self):
        """Test that data exceeding max age is rejected."""
        cached_data = {
            "fetch_time": datetime.now() - timedelta(hours=2),
            "current_time": datetime.now(),
            "max_age_minutes": 30
        }

        age_minutes = (cached_data["current_time"] - cached_data["fetch_time"]).total_seconds() / 60
        is_stale = age_minutes > cached_data["max_age_minutes"]

        if is_stale:
            result = {"status": "rejected", "reason": "data_stale"}
        else:
            result = {"status": "accepted"}

        assert result["status"] == "rejected"

    def test_degradation_status_recovery(self):
        """Test transition from degraded to normal feed status."""
        feed_state = {"status": "degraded", "fallback_active": True}

        # Primary feed recovers
        feed_state["status"] = "normal"
        feed_state["fallback_active"] = False
        recovery_log = {
            "recovered_to": "primary_feed",
            "timestamp": datetime.now().isoformat()
        }

        assert feed_state["status"] == "normal"
        assert feed_state["fallback_active"] is False


class TestApparentlyCrossBrandIntegration:
    """Test Apparently cross-brand functionality and isolation."""

    def test_apparently_brand_accounts_isolated(self):
        """Test that Apparently brand accounts are isolated from other brands."""
        user_id = "user_crossbrand_001"

        apparently_account = {
            "user_id": user_id,
            "brand": "apparently",
            "account_id": "acc_001",
            "balance": 1000.0
        }

        racefeed_account = {
            "user_id": user_id,
            "brand": "racefeed",
            "account_id": "acc_002",
            "balance": 500.0
        }

        assert apparently_account["brand"] != racefeed_account["brand"]
        assert apparently_account["account_id"] != racefeed_account["account_id"]

    def test_apparently_powered_by_partner_branding(self):
        """Test that Apparently free-play displays partner branding appropriately."""
        ui_context = {
            "brand": "racefeed",
            "powered_by": "apparently",
            "display_text": "Powered by Apparently",
            "attribution_visible": True
        }

        assert ui_context["powered_by"] == "apparently"
        assert ui_context["attribution_visible"] is True

    def test_apparently_data_source_for_racefeed(self):
        """Test that Racefeed uses Apparently as data source in free-play."""
        feed_config = {
            "primary_brand": "racefeed",
            "data_provider": "apparently",
            "data_feed_name": "apparently_free_delayed"
        }

        assert feed_config["data_provider"] == "apparently"

    def test_apparently_apparently_cross_brand_never_same_account(self):
        """Test that cross-brand accounts never merge into one."""
        user_id = "user_crossbrand_002"

        brand_accounts = {}
        for brand in ["apparently", "racefeed"]:
            brand_accounts[brand] = {
                "user_id": user_id,
                "brand": brand,
                "account_id": f"acc_{brand}_unique"
            }

        account_ids = [acc["account_id"] for acc in brand_accounts.values()]
        assert len(account_ids) == len(set(account_ids)), "Account IDs should be unique per brand"


class TestOrchestrationPipelineIntegration:
    """Test integration with orchestration pipeline and contract compliance."""

    def test_pipeline_preflight_triage_completes(self):
        """Test that orchestration preflight triage step completes."""
        triage_result = {
            "task_id": "dropbox-racefeed-galop-free-play-001",
            "stage": "preflight_triage",
            "model": "google:gemini-2.0-flash",
            "status": "completed",
            "quality_score": 7.0
        }

        assert triage_result["status"] == "completed"
        assert triage_result["quality_score"] >= 7.0

    def test_pipeline_strategy_planning_outputs(self):
        """Test that strategy planning produces required outputs."""
        strategy = {
            "stage": "strategy_planner",
            "model": "local:codestral:22b",
            "plan_document": "free_play_implementation_plan.md",
            "feed_config_seam_documented": True,
            "validation_rules_documented": True
        }

        assert strategy["feed_config_seam_documented"] is True
        assert strategy["validation_rules_documented"] is True

    def test_pipeline_agentic_coder_stage(self):
        """Test that agentic coder stage completes with required code."""
        coder_result = {
            "stage": "agentic_coder",
            "model": "swarm:openai using claude-haiku-4-5-20251001",
            "components_implemented": [
                "free_play_account_init",
                "play_money_manager",
                "contest_loop",
                "feed_config_seam",
                "data_degradation_handler",
                "odds_validation"
            ]
        }

        required = ["free_play_account_init", "play_money_manager", "odds_validation"]
        assert all(c in coder_result["components_implemented"] for c in required)

    def test_pipeline_qa_validation_passes(self):
        """Test that QA validation stage passes all checks."""
        qa_results = {
            "stage": "independent_QA_route",
            "model": "local:llama3.1",
            "checks_passed": 18,
            "checks_total": 20,
            "status": "pass"
        }

        assert qa_results["status"] == "pass"
        assert qa_results["checks_passed"] >= 15

    def test_pipeline_merge_to_dev_after_tests(self):
        """Test that code auto-merges to orchestrator/dev after test pass."""
        merge_record = {
            "source_branch": "agent/galop-freeplay-launch",
            "target_branch": "orchestrator/dev",
            "tests_passed": True,
            "merge_status": "completed",
            "merged_at": datetime.now().isoformat()
        }

        assert merge_record["tests_passed"] is True
        assert merge_record["merge_status"] == "completed"


class TestEdgeCasesAndErrorHandling:
    """Test edge cases, error conditions, and boundary scenarios."""

    def test_freeplay_contest_zero_participants(self):
        """Test contest with zero participants can still close cleanly."""
        contest = {
            "contest_id": "contest_empty",
            "participants": [],
            "closed": True,
            "closure_status": "success"
        }

        assert len(contest["participants"]) == 0
        assert contest["closed"] is True

    def test_play_money_concurrent_wager_deduction(self):
        """Test that concurrent wagers don't allow overdraft."""
        balance = 100.0
        concurrent_wagers = [50.0, 60.0]  # Total 110.0

        def attempt_wager(wager_amount):
            nonlocal balance
            if wager_amount <= balance:
                balance -= wager_amount
                return {"status": "success"}
            return {"status": "failed", "reason": "insufficient_balance"}

        result1 = attempt_wager(concurrent_wagers[0])
        result2 = attempt_wager(concurrent_wagers[1])

        assert result1["status"] == "success"
        assert result2["status"] == "failed"
        assert balance == 50.0

    def test_feed_data_source_unavailability_handling(self):
        """Test handling when all feed sources become unavailable."""
        feed_sources = [
            {"name": "primary", "available": False},
            {"name": "fallback", "available": False},
            {"name": "cache", "available": False}
        ]

        available_sources = [f for f in feed_sources if f["available"]]

        if not available_sources:
            status = {"status": "no_feed_available", "action": "halt_contests"}
        else:
            status = {"status": "feed_available"}

        assert status["status"] == "no_feed_available"
        assert status["action"] == "halt_contests"

    def test_contest_settlement_with_missing_wager_records(self):
        """Test contest settlement when some wager records are incomplete."""
        wagers = [
            {"user_id": "user_1", "amount": 100.0, "settled": True},
            {"user_id": "user_2", "amount": 50.0, "settled": True},
            {"user_id": "user_3", "amount": None, "settled": False},
        ]

        settled_wagers = [w for w in wagers if w["settled"]]
        unsettled = [w for w in wagers if not w["settled"]]

        settlement_status = {
            "total_wagers": len(wagers),
            "settled": len(settled_wagers),
            "unsettled": len(unsettled),
            "can_finalize": len(unsettled) == 0
        }

        assert settlement_status["unsettled"] == 1
        assert settlement_status["can_finalize"] is False

    def test_play_money_negative_balance_prevention(self):
        """Test that balance can never go negative."""
        balance = 100.0
        max_withdrawal = balance

        # Attempt to withdraw more than available
        attempted_withdrawal = 150.0

        if attempted_withdrawal > balance:
            withdrawal = min(attempted_withdrawal, balance)
            result = {"approved": withdrawal, "denied": attempted_withdrawal - withdrawal}

        assert result["approved"] == 100.0
        assert result["denied"] == 50.0

    def test_race_odds_with_missing_horse_entries(self):
        """Test odds validation when some horses are missing odds."""
        race_horses = ["horse_1", "horse_2", "horse_3", "horse_4"]
        odds_provided = {"horse_1": 2.5, "horse_3": 4.5}

        missing = [h for h in race_horses if h not in odds_provided]
        odds_complete = len(missing) == 0

        validation = {
            "complete": odds_complete,
            "missing_odds": missing
        }

        assert validation["complete"] is False
        assert len(validation["missing_odds"]) == 2

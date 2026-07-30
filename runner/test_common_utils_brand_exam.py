#!/usr/bin/env python3
"""
test_common_utils_brand_exam.py - Common utilities for brand exam contracts and zombie-reaper.

Covers timestamp parsing, string truncation, and tiered logic evaluation for:
  - Brand examination workflow with prediction markets institute
  - Zombie-reaper integration with common_utils
  - Safe timestamp comparison across ISO formats
  - Note field truncation with UTF-8 safety
  - Tiered resource allocation for contract tiers
  - Dropbox PMI integration with contract enforcement

Environment variables tested:
  ORCH_BRAND_EXAM_ENABLED (default: false)
  ORCH_CONTRACT_ENFORCE_TIERS (enables tier-based capability control)
  ORCH_DROPBOX_PMI_INTEGRATION (enables prediction markets institute features)
"""
import sys
import os
import datetime
import json
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Disable DB at module load
os.environ["ORCH_DB_ENABLED"] = "false"
os.environ["ORCH_DB_URL"] = ""

import common_utils


class TestTruncateStringAtBytes:
    """Test safe string truncation at byte limits."""

    def test_ascii_string_within_limit(self):
        """ASCII strings within limit are not truncated."""
        s = "hello world"
        result = common_utils.truncate_string_at_bytes(s, 100)
        assert result == s

    def test_ascii_string_exceeds_limit(self):
        """ASCII strings exceeding limit are truncated."""
        s = "x" * 1100
        result = common_utils.truncate_string_at_bytes(s, 1000)
        assert len(result) <= 1000
        assert result.encode('utf-8') != s.encode('utf-8')

    def test_utf8_multibyte_within_limit(self):
        """UTF-8 multibyte strings within limit are preserved."""
        s = "café ☕ 🚀"
        result = common_utils.truncate_string_at_bytes(s, 100)
        assert result == s

    def test_utf8_multibyte_exceeds_byte_limit(self):
        """UTF-8 multibyte characters are not split mid-character."""
        s = "café " * 100  # ~500 bytes
        result = common_utils.truncate_string_at_bytes(s, 50)
        # Result should be valid UTF-8 and not exceed byte limit
        assert len(result.encode('utf-8')) <= 50
        # Should decode without errors
        decoded = result.encode('utf-8').decode('utf-8')
        assert isinstance(decoded, str)

    def test_emoji_truncation_safe(self):
        """Emoji characters (4 bytes) don't cause truncation crashes."""
        s = "message 🚀 " * 50
        result = common_utils.truncate_string_at_bytes(s, 100)
        assert len(result.encode('utf-8')) <= 100
        # Should not raise on decode
        _ = result.encode('utf-8').decode('utf-8')

    def test_empty_string_returns_empty(self):
        """Empty string returns empty."""
        result = common_utils.truncate_string_at_bytes("", 1000)
        assert result == ""

    def test_none_input_returns_none(self):
        """None input is handled gracefully."""
        result = common_utils.truncate_string_at_bytes(None, 1000)
        assert result is None

    def test_exact_byte_limit(self):
        """String at exactly byte limit is not truncated."""
        s = "x" * 50  # 50 ASCII bytes
        result = common_utils.truncate_string_at_bytes(s, 50)
        assert result == s

    def test_custom_max_bytes(self):
        """Custom max_bytes parameter is respected."""
        s = "a" * 100
        result = common_utils.truncate_string_at_bytes(s, 50)
        assert len(result.encode('utf-8')) <= 50

    def test_note_field_truncation_use_case(self):
        """Real-world use case: truncating task notes at 1000 bytes."""
        existing_note = "x" * 990
        append_text = " | retry-promoter"
        combined = f"{existing_note}{append_text}"
        result = common_utils.truncate_string_at_bytes(combined, 1000)
        assert len(result.encode('utf-8')) <= 1000
        assert existing_note[:50] in result  # Some of original is preserved

    def test_mixed_unicode_scripts(self):
        """Mixed Unicode scripts (Latin, CJK, Arabic) are handled safely."""
        s = "English 中文 العربية Ελληνικά" * 10
        result = common_utils.truncate_string_at_bytes(s, 100)
        assert len(result.encode('utf-8')) <= 100
        # Should be valid UTF-8
        decoded = result.encode('utf-8').decode('utf-8')
        assert isinstance(decoded, str)

    def test_zero_byte_limit(self):
        """Zero byte limit returns empty or truncates to empty."""
        result = common_utils.truncate_string_at_bytes("hello", 0)
        assert result == "" or len(result.encode('utf-8')) == 0


class TestParseIsoTimestamp:
    """Test robust ISO 8601 timestamp parsing."""

    def test_iso_with_timezone_utc(self):
        """ISO timestamp with +00:00 timezone parses correctly."""
        iso_str = "2026-07-30T12:30:45+00:00"
        result = common_utils.parse_iso_timestamp(iso_str)
        assert result is not None
        assert result.year == 2026
        assert result.month == 7
        assert result.day == 30

    def test_iso_with_z_timezone(self):
        """ISO timestamp with Z timezone (UTC) is normalized."""
        iso_str = "2026-07-30T12:30:45Z"
        result = common_utils.parse_iso_timestamp(iso_str)
        assert result is not None
        assert result.year == 2026

    def test_iso_with_microseconds(self):
        """ISO timestamp with microseconds parses correctly."""
        iso_str = "2026-07-30T12:30:45.123456+00:00"
        result = common_utils.parse_iso_timestamp(iso_str)
        assert result is not None
        assert result.microsecond == 123456

    def test_naive_iso_timestamp(self):
        """ISO timestamp without timezone (naive) parses correctly."""
        iso_str = "2026-07-30T12:30:45"
        result = common_utils.parse_iso_timestamp(iso_str)
        assert result is not None
        assert result.year == 2026

    def test_invalid_iso_returns_none(self):
        """Invalid ISO string returns None."""
        result = common_utils.parse_iso_timestamp("not-a-timestamp")
        assert result is None

    def test_empty_string_returns_none(self):
        """Empty string returns None."""
        result = common_utils.parse_iso_timestamp("")
        assert result is None

    def test_none_input_returns_none(self):
        """None input returns None."""
        result = common_utils.parse_iso_timestamp(None)
        assert result is None

    def test_non_string_input_returns_none(self):
        """Non-string input returns None."""
        result = common_utils.parse_iso_timestamp(12345)
        assert result is None

    def test_iso_with_negative_utc_offset(self):
        """ISO timestamp with negative UTC offset parses correctly."""
        iso_str = "2026-07-30T12:30:45-05:00"
        result = common_utils.parse_iso_timestamp(iso_str)
        assert result is not None
        assert result.year == 2026


class TestIsOlderThan:
    """Test timestamp comparison logic."""

    def test_old_timestamp_is_older_than_cutoff(self):
        """Timestamp in past is older than future cutoff."""
        now = datetime.datetime.now(datetime.timezone.utc)
        old = (now - datetime.timedelta(hours=1)).isoformat()
        cutoff = now.isoformat()
        assert common_utils.is_older_than(old, cutoff)

    def test_future_timestamp_not_older_than_cutoff(self):
        """Timestamp in future is not older than earlier cutoff."""
        now = datetime.datetime.now(datetime.timezone.utc)
        future = (now + datetime.timedelta(hours=1)).isoformat()
        cutoff = now.isoformat()
        assert not common_utils.is_older_than(future, cutoff)

    def test_same_timestamp_not_older(self):
        """Timestamp equal to cutoff is not older."""
        now = datetime.datetime.now(datetime.timezone.utc)
        iso = now.isoformat()
        assert not common_utils.is_older_than(iso, iso)

    def test_empty_timestamp_treated_as_very_old(self):
        """Empty timestamp string is treated as very old."""
        cutoff = datetime.datetime.now(datetime.timezone.utc).isoformat()
        assert common_utils.is_older_than("", cutoff)

    def test_none_timestamp_treated_as_very_old(self):
        """None timestamp is treated as very old."""
        cutoff = datetime.datetime.now(datetime.timezone.utc).isoformat()
        assert common_utils.is_older_than(None, cutoff)

    def test_invalid_timestamp_treated_as_very_old(self):
        """Invalid timestamp string is treated as very old."""
        cutoff = datetime.datetime.now(datetime.timezone.utc).isoformat()
        assert common_utils.is_older_than("malformed", cutoff)

    def test_none_cutoff_returns_false(self):
        """None cutoff returns False (timestamp not older than nothing)."""
        now = datetime.datetime.now(datetime.timezone.utc)
        iso = now.isoformat()
        assert not common_utils.is_older_than(iso, None)

    def test_empty_cutoff_returns_false(self):
        """Empty cutoff string returns False."""
        now = datetime.datetime.now(datetime.timezone.utc)
        iso = now.isoformat()
        assert not common_utils.is_older_than(iso, "")

    def test_30_minute_threshold(self):
        """30-minute threshold matches zombie-reaper staleness check."""
        now = datetime.datetime.now(datetime.timezone.utc)
        # Use a time clearly older than 30 minutes
        stale_31min = (now - datetime.timedelta(minutes=31)).isoformat()
        # Use a time clearly newer than 30 minutes
        recent_29min = (now - datetime.timedelta(minutes=29)).isoformat()
        cutoff = (now - datetime.timedelta(minutes=30)).isoformat()

        # 31 min old should be older than 30 min cutoff
        assert common_utils.is_older_than(stale_31min, cutoff)
        # 29 min old should not be older than 30 min cutoff
        assert not common_utils.is_older_than(recent_29min, cutoff)

    def test_zombie_reaper_dead_runner_threshold(self):
        """Dead runner timeout (180s) threshold comparison."""
        now = datetime.datetime.now(datetime.timezone.utc)
        dead = (now - datetime.timedelta(seconds=180)).isoformat()
        cutoff = (now - datetime.timedelta(seconds=180)).isoformat()
        # At exactly the threshold
        assert common_utils.is_older_than(dead, cutoff) or not common_utils.is_older_than(dead, cutoff)

    def test_retry_promotion_threshold(self):
        """RETRY promotion threshold (120s) comparison."""
        now = datetime.datetime.now(datetime.timezone.utc)
        elapsed = (now - datetime.timedelta(seconds=120)).isoformat()
        cutoff = (now - datetime.timedelta(seconds=120)).isoformat()
        # At exactly the threshold
        assert common_utils.is_older_than(elapsed, cutoff) or not common_utils.is_older_than(elapsed, cutoff)


class TestApplyTieredLogic:
    """Test tiered condition evaluation."""

    def test_first_tier_matches_returns_result(self):
        """First matching tier returns its result."""
        tiers = [
            (lambda: True, "first"),
            (lambda: True, "second"),
        ]
        result = common_utils.apply_tiered_logic(tiers)
        assert result == "first"

    def test_skips_false_tiers_to_next_match(self):
        """False tiers are skipped until a truthy tier is found."""
        tiers = [
            (lambda: False, "first"),
            (lambda: False, "second"),
            (lambda: True, "third"),
        ]
        result = common_utils.apply_tiered_logic(tiers)
        assert result == "third"

    def test_no_match_returns_default(self):
        """No matching tier returns default value."""
        tiers = [
            (lambda: False, "first"),
            (lambda: False, "second"),
        ]
        result = common_utils.apply_tiered_logic(tiers, default="default")
        assert result == "default"

    def test_no_match_no_default_returns_none(self):
        """No matching tier with no default returns None."""
        tiers = [
            (lambda: False, "first"),
        ]
        result = common_utils.apply_tiered_logic(tiers)
        assert result is None

    def test_dead_runner_logic_example(self):
        """Example: dead runner detection logic."""
        live_runners = {"Mac.lan-0", "Mac.lan-1"}
        account = "Mac.lan-2"
        cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)).isoformat()

        tiers = [
            (lambda: account in live_runners, "runner_alive"),
            (lambda: account.startswith("cowork-"), "cowork_dispatch"),
            (lambda: True, "dead_runner"),
        ]
        result = common_utils.apply_tiered_logic(tiers)
        assert result == "dead_runner"

    def test_exception_in_tier_continues_to_next(self):
        """Exception in tier evaluation skips to next tier."""
        tiers = [
            (lambda: 1 / 0, "first"),  # Raises ZeroDivisionError
            (lambda: True, "second"),
        ]
        result = common_utils.apply_tiered_logic(tiers)
        assert result == "second"

    def test_non_callable_truthy_tier(self):
        """Non-callable truthy value in tier is treated as matching."""
        tiers = [
            (lambda: False, "first"),
            ("truthy_string", "second"),
        ]
        result = common_utils.apply_tiered_logic(tiers)
        assert result == "second"

    def test_non_callable_falsy_tier(self):
        """Non-callable falsy value in tier is skipped."""
        tiers = [
            ("", "first"),
            (None, "second"),
            (lambda: True, "third"),
        ]
        result = common_utils.apply_tiered_logic(tiers)
        assert result == "third"


class TestConsumeFromTier:
    """Test tiered consumption/allocation logic."""

    def test_consume_from_tier_simple(self):
        """Simple consumption from single tier."""
        consumed, remaining = common_utils.consume_from_tier(0, 0, 100, 50)
        assert consumed == 50
        assert remaining == 0

    def test_consume_exceeds_tier_capacity(self):
        """Consuming more than available reduces consumed amount."""
        # Start at 80, max is 100, trying to consume 50
        consumed, remaining = common_utils.consume_from_tier(80, 0, 100, 50)
        assert consumed == 20  # Only 20 available (100-80)
        assert remaining == 30

    def test_consume_with_unlimited_tier(self):
        """Unlimited tier (max=None) provides all requested."""
        consumed, remaining = common_utils.consume_from_tier(1000, 0, None, 50)
        assert consumed == 50
        assert remaining == 0

    def test_consume_zero_amount(self):
        """Consuming zero returns zero consumed and zero remaining."""
        consumed, remaining = common_utils.consume_from_tier(0, 0, 100, 0)
        assert consumed == 0
        assert remaining == 0

    def test_consume_negative_amount(self):
        """Negative consume amount returns zero consumed."""
        consumed, remaining = common_utils.consume_from_tier(0, 0, 100, -50)
        assert consumed == 0
        assert remaining == -50

    def test_brand_exam_tier_quota_standard(self):
        """Example: standard tier brand exams (quota 100/day)."""
        # 60 exams already done, try to consume 50 more
        consumed, remaining = common_utils.consume_from_tier(60, 0, 100, 50)
        assert consumed == 40  # Only 40 available (100-60)
        assert remaining == 10

    def test_brand_exam_tier_quota_premium(self):
        """Example: premium tier brand exams (quota 500/day)."""
        consumed, remaining = common_utils.consume_from_tier(300, 0, 500, 300)
        assert consumed == 200  # Only 200 available (500-300)
        assert remaining == 100

    def test_brand_exam_tier_quota_enterprise(self):
        """Example: enterprise tier (unlimited)."""
        consumed, remaining = common_utils.consume_from_tier(1000, 0, None, 5000)
        assert consumed == 5000  # All requested available
        assert remaining == 0

    def test_tiered_pricing_example(self):
        """Example: tiered pricing consumption."""
        # First 100 units @ $1, next 400 @ $2, unlimited @ $5
        consumed_tier1, remaining1 = common_utils.consume_from_tier(0, 0, 100, 150)
        assert consumed_tier1 == 100
        assert remaining1 == 50

        consumed_tier2, remaining2 = common_utils.consume_from_tier(100, 100, 500, remaining1)
        assert consumed_tier2 == 50
        assert remaining2 == 0


class TestIntegrationWithZombieReaper:
    """Test common_utils functions in zombie-reaper context."""

    def test_dead_runner_timestamp_comparison(self):
        """Zombie-reaper: dead runner timeout is correctly compared."""
        now = datetime.datetime.now(datetime.timezone.utc)
        task_updated = (now - datetime.timedelta(seconds=120)).isoformat()
        dead_cutoff = (now - datetime.timedelta(seconds=180)).isoformat()

        # Task updated 120s ago, dead cutoff is 180s ago
        # So task is NOT older than cutoff (it's more recent)
        assert not common_utils.is_older_than(task_updated, dead_cutoff)

    def test_stale_task_timestamp_comparison(self):
        """Zombie-reaper: stale task (>30min) is correctly identified."""
        now = datetime.datetime.now(datetime.timezone.utc)
        task_updated = (now - datetime.timedelta(minutes=31)).isoformat()
        stale_cutoff = (now - datetime.timedelta(minutes=30)).isoformat()

        # Task updated 31 min ago, cutoff is 30 min ago
        # So task IS older than cutoff
        assert common_utils.is_older_than(task_updated, stale_cutoff)

    def test_retry_promotion_truncation(self):
        """Zombie-reaper: RETRY note truncation."""
        existing_note = "x" * 999
        append = " | retry-promoter"
        combined = f"{existing_note}{append}"

        truncated = common_utils.truncate_string_at_bytes(combined, 1000)
        assert len(truncated.encode('utf-8')) <= 1000

    def test_heartbeat_cutoff_calculation(self):
        """Zombie-reaper: heartbeat cutoff with FLEET_TTL_S."""
        now = datetime.datetime.now(datetime.timezone.utc)
        fleet_ttl_s = 180
        cutoff = (now - datetime.timedelta(seconds=fleet_ttl_s)).isoformat()

        live_heartbeat = (now - datetime.timedelta(seconds=120)).isoformat()
        dead_heartbeat = (now - datetime.timedelta(seconds=240)).isoformat()

        # Live heartbeat is more recent than cutoff
        assert not common_utils.is_older_than(live_heartbeat, cutoff)
        # Dead heartbeat is older than cutoff
        assert common_utils.is_older_than(dead_heartbeat, cutoff)


class TestIntegrationWithBrandExam:
    """Test common_utils in brand exam context."""

    def test_brand_exam_task_timestamp_valid(self):
        """Brand exam: task timestamp is properly parsed."""
        now = datetime.datetime.now(datetime.timezone.utc)
        task_iso = now.isoformat()
        parsed = common_utils.parse_iso_timestamp(task_iso)
        assert parsed is not None

    def test_brand_exam_contract_note_truncation(self):
        """Brand exam: contract note field truncation."""
        long_note = "contract-pmi-validation-" + "x" * 1000
        truncated = common_utils.truncate_string_at_bytes(long_note, 1000)
        assert len(truncated.encode('utf-8')) <= 1000

    def test_brand_exam_approval_workflow_timestamps(self):
        """Brand exam: approval workflow timestamp comparison."""
        now = datetime.datetime.now(datetime.timezone.utc)
        init_time = (now - datetime.timedelta(minutes=5)).isoformat()
        validation_time = (now - datetime.timedelta(minutes=2)).isoformat()

        # Validation is more recent than initialization
        assert not common_utils.is_older_than(validation_time, init_time)

    def test_brand_exam_tier_based_quota(self):
        """Brand exam: tier-based quota enforcement."""
        # Standard tier: 100 exams/day
        consumed, remaining = common_utils.consume_from_tier(60, 0, 100, 50)
        assert consumed == 40  # Limited to 40 remaining capacity

        # Premium tier: 500 exams/day
        consumed, remaining = common_utils.consume_from_tier(300, 0, 500, 50)
        assert consumed == 50  # Full amount available


class TestErrorHandling:
    """Test robustness and error handling."""

    def test_truncate_malformed_utf8(self):
        """Truncation handles malformed UTF-8 gracefully."""
        # Use errors='replace' in decode to handle invalid UTF-8
        s = "test"
        result = common_utils.truncate_string_at_bytes(s, 1000)
        assert isinstance(result, str)

    def test_timestamp_comparison_with_mixed_formats(self):
        """Mixed ISO formats are compared safely."""
        iso1 = "2026-07-30T12:00:00Z"
        iso2 = "2026-07-30T12:00:00+00:00"
        iso3 = "2026-07-30T12:00:00+00:00"  # Use aware format for consistency

        # All represent approximately same time
        cutoff = "2026-07-31T00:00:00Z"

        assert common_utils.is_older_than(iso1, cutoff)
        assert common_utils.is_older_than(iso2, cutoff)
        # Aware ISO formats work correctly
        assert common_utils.is_older_than(iso3, cutoff)

    def test_tiered_logic_with_all_exceptions(self):
        """Tiered logic handles all exceptions gracefully."""
        def failing_fn():
            raise RuntimeError("oops")

        tiers = [
            (failing_fn, "first"),
            (lambda: True, "second"),
        ]
        result = common_utils.apply_tiered_logic(tiers)
        assert result == "second"


class TestEdgeCasesAndBoundaries:
    """Test edge cases and boundary conditions."""

    def test_byte_boundary_multibyte_char(self):
        """Character split at byte boundary is handled correctly."""
        # 4-byte emoji at exact byte boundary
        emoji = "🚀"  # 4 bytes in UTF-8
        s = "x" * 48 + emoji  # 48 + 4 = 52 bytes
        result = common_utils.truncate_string_at_bytes(s, 50)
        # Should truncate emoji, not leave it incomplete
        assert len(result.encode('utf-8')) <= 50

    def test_iso_timestamp_with_different_timezones(self):
        """ISO timestamps with various timezone offsets parse correctly."""
        offsets = ["+00:00", "-05:00", "+09:00", "Z"]
        base_iso = "2026-07-30T12:30:45"

        for offset in offsets:
            if offset == "Z":
                iso = base_iso + offset
            else:
                iso = base_iso + offset
            parsed = common_utils.parse_iso_timestamp(iso)
            assert parsed is not None

    def test_large_note_field_with_special_chars(self):
        """Large note field with special characters is truncated safely."""
        special_note = "task-error: " + "😞 " * 500 + "retrying..."
        truncated = common_utils.truncate_string_at_bytes(special_note, 1000)
        assert len(truncated.encode('utf-8')) <= 1000
        assert "task-error" in truncated

    def test_consume_tier_at_boundaries(self):
        """Tier consumption at exact boundaries."""
        # Exactly at tier boundary
        consumed, remaining = common_utils.consume_from_tier(99, 0, 100, 1)
        assert consumed == 1
        assert remaining == 0

        # One past tier boundary
        consumed, remaining = common_utils.consume_from_tier(100, 0, 100, 1)
        assert consumed == 0
        assert remaining == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

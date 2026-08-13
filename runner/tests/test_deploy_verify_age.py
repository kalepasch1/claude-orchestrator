#!/usr/bin/env python3
"""Regression: _age_minutes must not report an unknown age as "brand new".

The stuck-deploy branch is `state is None and age_min > stuck_min`. _age_minutes
returned 0 on ANY failure to parse `created_at`, so a release with a NULL or malformed
timestamp was pinned at zero minutes old and could never cross the threshold — a
genuinely wedged deploy went undetected for the life of the row, silently. Unknown is
now None, and the caller reports it instead of treating it as healthy.
"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deploy_verify  # noqa: E402


def _iso(minutes_ago, tz=True):
    dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes_ago)
    return dt.isoformat() if tz else dt.replace(tzinfo=None).isoformat()


class AgeMinutesTest(unittest.TestCase):
    def test_recent_timestamp_is_small(self):
        age = deploy_verify._age_minutes({"created_at": _iso(5)})
        assert age is not None and 4 <= age <= 6, age

    def test_old_timestamp_exceeds_threshold(self):
        age = deploy_verify._age_minutes({"created_at": _iso(240)})
        assert age is not None and age > 200, age

    def test_zulu_suffix_is_parsed(self):
        raw = (datetime.datetime.now(datetime.timezone.utc)
               - datetime.timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        age = deploy_verify._age_minutes({"created_at": raw})
        assert age is not None and 29 <= age <= 31, age

    def test_naive_timestamp_is_treated_as_utc(self):
        """A naive created_at used to raise (offset-naive vs -aware) and become 0."""
        age = deploy_verify._age_minutes({"created_at": _iso(45, tz=False)})
        assert age is not None and 44 <= age <= 46, age

    def test_missing_created_at_is_unknown_not_zero(self):
        assert deploy_verify._age_minutes({}) is None
        assert deploy_verify._age_minutes({"created_at": None}) is None
        assert deploy_verify._age_minutes({"created_at": ""}) is None

    def test_malformed_created_at_is_unknown_not_zero(self):
        for bad in ("not-a-date", "2026-13-45T99:99:99", 12345, [], {}):
            assert deploy_verify._age_minutes({"created_at": bad}) is None, bad

    def test_unknown_age_never_looks_newer_than_the_threshold(self):
        """The whole point: unknown must not silently satisfy `age <= stuck_min`."""
        age = deploy_verify._age_minutes({"created_at": None})
        assert age is not None or age is None  # explicit: it is None
        assert age is None, "unknown age must be None so the caller cannot compare it to 0"


if __name__ == "__main__":
    unittest.main()

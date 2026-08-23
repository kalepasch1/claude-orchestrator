#!/usr/bin/env python3
"""The merge train's scan interlock: MERGE_TRAIN_SCAN_LIMIT cannot starve this host.

MERGE_TRAIN_SCAN_LIMIT=0 in fleet_config is the fleet-wide lever for hosts too old to
honour integration_owner — starving _pick_cards is the only thing that build responds to.
It was pinned away on this host, the pin silently did not take because the running runner
had inherited the pre-edit pins list, and one train pass returned an all-zero summary
before anyone noticed. The comment in merge_train.py draws the conclusion: a safety
interlock that depends on a restart landing in the right order is not a safety interlock.

So current code declines the switch. That rule was covered only by a script in
test_20260806_session_fixes.py which calls the real _pick_cards() against a live database
— pytest reports that file as skipped, so under the suite the rule was verified nowhere.
These tests are pure: they exercise the sanitiser directly.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merge_train


class ScanLimitInterlockTest(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("MERGE_TRAIN_SCAN_LIMIT")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("MERGE_TRAIN_SCAN_LIMIT", None)
        else:
            os.environ["MERGE_TRAIN_SCAN_LIMIT"] = self._saved

    def _limit(self, value=None):
        if value is None:
            os.environ.pop("MERGE_TRAIN_SCAN_LIMIT", None)
        else:
            os.environ["MERGE_TRAIN_SCAN_LIMIT"] = value
        return merge_train._scan_limit()

    def test_unset_uses_the_default(self):
        self.assertEqual(self._limit(None), merge_train.DEFAULT_SCAN_LIMIT)

    def test_zero_is_declined_rather_than_honoured(self):
        # The exact value the fleet-wide switch sets. Honouring it here is the all-zero
        # train pass this interlock exists to prevent.
        self.assertEqual(self._limit("0"), merge_train.DEFAULT_SCAN_LIMIT)

    def test_negative_is_declined(self):
        self.assertEqual(self._limit("-1"), merge_train.DEFAULT_SCAN_LIMIT)

    def test_quoted_and_padded_zero_is_still_declined(self):
        # fleet_config values arrive as strings and have arrived quoted before; a switch
        # that is escapable by a stray quote is not a switch, and one that is honoured
        # because of a stray quote is worse.
        for raw in ['"0"', ' 0 ', '\t"0"\n', '"-5"']:
            self.assertEqual(self._limit(raw), merge_train.DEFAULT_SCAN_LIMIT, repr(raw))

    def test_unparseable_values_fall_back_rather_than_reaching_postgrest(self):
        # This string goes straight into a PostgREST limit param. A junk value must not
        # be forwarded and turned into a query error that reads like an outage.
        for raw in ["", "abc", "3000; DROP", "1e5", "null"]:
            self.assertEqual(self._limit(raw), merge_train.DEFAULT_SCAN_LIMIT, repr(raw))

    def test_a_positive_override_is_honoured_exactly(self):
        # A genuine local override still works — the interlock declines starvation, not
        # configuration.
        self.assertEqual(self._limit("50"), "50")
        self.assertEqual(self._limit("9000"), "9000")

    def test_the_returned_limit_is_always_a_string(self):
        # It is passed as a PostgREST query param; an int would serialise differently
        # depending on the client.
        for raw in [None, "0", "50", "abc"]:
            self.assertIsInstance(self._limit(raw), str)

    def test_the_default_is_a_positive_number(self):
        self.assertGreater(int(merge_train.DEFAULT_SCAN_LIMIT), 0)


if __name__ == "__main__":
    unittest.main()

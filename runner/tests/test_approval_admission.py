"""Tests for runner/approval_admission.py — the approvals flood gate."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import approval_admission as aa  # noqa: E402


class ApprovalAdmissionTest(unittest.TestCase):

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in (
            "ORCH_APPROVAL_ADMISSION", "ORCH_APPROVAL_GATED_KINDS",
            "ORCH_APPROVAL_DAILY_CAP", "ORCH_APPROVAL_DEDUPE_TTL_SEC")}
        for k in self._saved:
            os.environ.pop(k, None)
        aa.reset()

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        aa.reset()

    # --- defaults -----------------------------------------------------

    def test_enabled_by_default(self):
        self.assertTrue(aa.enabled())

    def test_self_is_gated_by_default(self):
        self.assertIn("self", aa.gated_kinds())

    def test_default_cap_is_under_the_500_per_day_acceptance_bound(self):
        self.assertLess(aa.daily_cap(), 500)

    # --- dedupe -------------------------------------------------------

    def test_first_self_card_is_admitted(self):
        ok, why = aa.admit({"project": "ORCHESTRATOR", "kind": "self", "title": "t"})
        self.assertTrue(ok)
        self.assertEqual(why, "")

    def test_identical_self_card_is_refused(self):
        row = {"project": "ORCHESTRATOR", "kind": "self", "title": "t"}
        self.assertTrue(aa.admit(dict(row))[0])
        ok, why = aa.admit(dict(row))
        self.assertFalse(ok)
        self.assertIn("duplicate", why)

    def test_title_whitespace_and_case_do_not_defeat_dedupe(self):
        self.assertTrue(aa.admit({"kind": "self", "title": "Disk  pressure"})[0])
        self.assertFalse(aa.admit({"kind": "self", "title": "disk pressure"})[0])

    def test_different_title_is_admitted(self):
        self.assertTrue(aa.admit({"kind": "self", "title": "a"})[0])
        self.assertTrue(aa.admit({"kind": "self", "title": "b"})[0])

    def test_different_project_is_admitted(self):
        self.assertTrue(aa.admit({"project": "x", "kind": "self", "title": "t"})[0])
        self.assertTrue(aa.admit({"project": "y", "kind": "self", "title": "t"})[0])

    def test_zero_ttl_disables_dedupe_but_not_the_cap(self):
        os.environ["ORCH_APPROVAL_DEDUPE_TTL_SEC"] = "0"
        row = {"kind": "self", "title": "t"}
        self.assertTrue(aa.admit(dict(row))[0])
        self.assertTrue(aa.admit(dict(row))[0])

    # --- rate cap -----------------------------------------------------

    def test_cap_refuses_beyond_the_ceiling(self):
        os.environ["ORCH_APPROVAL_DAILY_CAP"] = "3"
        for i in range(3):
            self.assertTrue(aa.admit({"kind": "self", "title": f"t{i}"})[0])
        ok, why = aa.admit({"kind": "self", "title": "t99"})
        self.assertFalse(ok)
        self.assertIn("rate cap", why)

    def test_cap_of_zero_refuses_everything_gated(self):
        os.environ["ORCH_APPROVAL_DAILY_CAP"] = "0"
        self.assertFalse(aa.admit({"kind": "self", "title": "t"})[0])

    def test_refused_rows_do_not_consume_cap(self):
        os.environ["ORCH_APPROVAL_DAILY_CAP"] = "2"
        self.assertTrue(aa.admit({"kind": "self", "title": "t"})[0])
        self.assertFalse(aa.admit({"kind": "self", "title": "t"})[0])   # dupe
        self.assertTrue(aa.admit({"kind": "self", "title": "u"})[0])
        self.assertFalse(aa.admit({"kind": "self", "title": "v"})[0])   # cap

    # --- ungated kinds ------------------------------------------------

    def test_material_is_never_gated(self):
        row = {"project": "PORTFOLIO", "kind": "material", "title": "t"}
        for _ in range(50):
            self.assertTrue(aa.admit(dict(row))[0])

    def test_ops_and_config_are_not_gated_by_default(self):
        for kind in ("ops", "config", "integrate", "proposal"):
            row = {"kind": kind, "title": "t"}
            self.assertTrue(aa.admit(dict(row))[0])
            self.assertTrue(aa.admit(dict(row))[0])

    def test_gated_kinds_are_configurable(self):
        os.environ["ORCH_APPROVAL_GATED_KINDS"] = "self,config"
        self.assertTrue(aa.admit({"kind": "config", "title": "t"})[0])
        self.assertFalse(aa.admit({"kind": "config", "title": "t"})[0])

    # --- kill switch --------------------------------------------------

    def test_disabled_gate_admits_everything(self):
        os.environ["ORCH_APPROVAL_ADMISSION"] = "0"
        row = {"kind": "self", "title": "t"}
        for _ in range(10):
            self.assertTrue(aa.admit(dict(row))[0])

    # --- fail-soft on bad input ---------------------------------------

    def test_none_row_is_admitted_not_raised(self):
        self.assertTrue(aa.admit(None)[0])

    def test_non_dict_row_is_admitted_not_raised(self):
        self.assertTrue(aa.admit("nonsense")[0])

    def test_missing_kind_is_admitted(self):
        self.assertTrue(aa.admit({"title": "t"})[0])

    def test_missing_title_still_dedupes_within_kind_and_project(self):
        self.assertTrue(aa.admit({"project": "p", "kind": "self"})[0])
        self.assertFalse(aa.admit({"project": "p", "kind": "self"})[0])

    def test_unparseable_env_falls_back_to_defaults(self):
        os.environ["ORCH_APPROVAL_DAILY_CAP"] = "not-a-number"
        self.assertEqual(aa.daily_cap(), 200)

    def test_fingerprint_is_empty_for_unusable_rows(self):
        self.assertEqual(aa.fingerprint(None), "")
        self.assertEqual(aa.fingerprint({}), "")

    # --- observability ------------------------------------------------

    def test_stats_reports_admissions(self):
        aa.admit({"kind": "self", "title": "t"})
        s = aa.stats()
        self.assertTrue(s["enabled"])
        self.assertEqual(s["admitted_last_24h"].get("self"), 1)
        self.assertGreaterEqual(s["tracked_fingerprints"], 1)

    def test_reset_clears_state(self):
        aa.admit({"kind": "self", "title": "t"})
        aa.reset()
        self.assertTrue(aa.admit({"kind": "self", "title": "t"})[0])

    def test_module_functions_delegate_to_the_singleton(self):
        aa.admit({"kind": "self", "title": "t"})
        self.assertEqual(aa._gate.stats()["admitted_last_24h"].get("self"), 1)


if __name__ == "__main__":
    unittest.main()

"""Tests for the capability.py half of the shared world model.

version() already files a verify card per consumer when a contract change is breaking, but
that happens at publish time — after the change exists. consumers()/contract_blast_radius()
expose the same set BEFORE the build, which is the whole point of a world model.
"""
import os
import sys
import types
import unittest
from unittest import mock

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

# capability imports db/privacy/provenance at module scope; stub whatever is unavailable so
# the test file is importable in a bare checkout.
for _name in ("db", "privacy", "provenance"):
    try:
        __import__(_name)
    except Exception:  # pragma: no cover - environment dependent
        sys.modules[_name] = types.ModuleType(_name)

import capability  # noqa: E402


class ConsumersTest(unittest.TestCase):
    def test_active_only_and_deduped_and_sorted(self):
        rows = [{"project": "beta", "status": "active"},
                {"project": "alpha", "status": "active"},
                {"project": "beta", "status": "active"},
                {"project": "gamma", "status": "removed"},
                {"project": None, "status": "active"}]
        with mock.patch.object(capability, "usage", return_value=rows):
            self.assertEqual(capability.consumers("kyc"), ["alpha", "beta"])

    def test_no_instances(self):
        with mock.patch.object(capability, "usage", return_value=[]):
            self.assertEqual(capability.consumers("kyc"), [])

    def test_failure_is_soft(self):
        with mock.patch.object(capability, "usage", side_effect=RuntimeError("db down")):
            self.assertEqual(capability.consumers("kyc"), [])


class ContractBlastRadiusTest(unittest.TestCase):
    OLD = {"inputs": [{"name": "email", "required": True}],
           "outputs": [{"name": "score", "required": True}]}

    def test_backward_compatible_change_lists_no_consumers(self):
        new = {"inputs": [{"name": "email", "required": True},
                          {"name": "phone", "required": False}],
               "outputs": [{"name": "score", "required": True}]}
        with mock.patch.object(capability, "get",
                               return_value={"slug": "kyc", "contract": self.OLD}), \
             mock.patch.object(capability, "consumers", return_value=["beta"]):
            out = capability.contract_blast_radius("kyc", new)
        self.assertEqual(out["breaking"], [])
        self.assertEqual(out["consumers"], [])

    def test_removed_required_input_is_breaking_and_names_consumers(self):
        new = {"inputs": [], "outputs": [{"name": "score", "required": True}]}
        with mock.patch.object(capability, "get",
                               return_value={"slug": "kyc", "contract": self.OLD}), \
             mock.patch.object(capability, "consumers", return_value=["beta", "gamma"]):
            out = capability.contract_blast_radius("kyc", new)
        self.assertTrue(out["breaking"])
        self.assertEqual(out["consumers"], ["beta", "gamma"])

    def test_added_required_input_is_breaking(self):
        new = {"inputs": [{"name": "email", "required": True},
                          {"name": "ssn", "required": True}],
               "outputs": [{"name": "score", "required": True}]}
        with mock.patch.object(capability, "get",
                               return_value={"slug": "kyc", "contract": self.OLD}), \
             mock.patch.object(capability, "consumers", return_value=["beta"]):
            self.assertTrue(capability.contract_blast_radius("kyc", new)["breaking"])

    def test_unknown_capability_is_empty_not_an_error(self):
        with mock.patch.object(capability, "get", return_value=None):
            out = capability.contract_blast_radius("nope", {})
        self.assertEqual(out["breaking"], [])
        self.assertEqual(out["consumers"], [])

    def test_never_raises(self):
        with mock.patch.object(capability, "get", side_effect=RuntimeError("boom")):
            self.assertEqual(capability.contract_blast_radius("kyc", {})["breaking"], [])

    def test_does_not_publish_anything(self):
        """The whole value is that this is a dry run — it must not write."""
        with mock.patch.object(capability, "get",
                               return_value={"slug": "kyc", "contract": self.OLD}), \
             mock.patch.object(capability, "consumers", return_value=[]), \
             mock.patch.object(capability.db, "insert", create=True) as ins:
            capability.contract_blast_radius("kyc", {"inputs": [], "outputs": []})
        ins.assert_not_called()


class ContractNoteTest(unittest.TestCase):
    def _select(self, instances, caps):
        def _s(table, params=None, *a, **k):
            return instances if table == "capability_instances" else caps
        return _s

    def test_lists_instantiated_contracts(self):
        with mock.patch.object(capability.db, "select", create=True,
                               side_effect=self._select(
                                   [{"capability_id": 1, "version": "2.1.0",
                                     "status": "active"}],
                                   [{"id": 1, "slug": "kyc", "name": "KYC"}])):
            note = capability.contract_note("beta")
        self.assertIn("kyc v2.1.0", note)

    def test_deduplicates_repeat_instances(self):
        with mock.patch.object(capability.db, "select", create=True,
                               side_effect=self._select(
                                   [{"capability_id": 1, "version": "1.0.0",
                                     "status": "active"},
                                    {"capability_id": 1, "version": "1.0.0",
                                     "status": "active"}],
                                   [{"id": 1, "slug": "kyc", "name": "KYC"}])):
            note = capability.contract_note("beta")
        self.assertEqual(note.count("- kyc"), 1)

    def test_empty_when_project_instantiates_nothing(self):
        with mock.patch.object(capability.db, "select", create=True,
                               side_effect=self._select([], [])):
            self.assertEqual(capability.contract_note("beta"), "")

    def test_unknown_capability_id_produces_no_note(self):
        with mock.patch.object(capability.db, "select", create=True,
                               side_effect=self._select(
                                   [{"capability_id": 99, "status": "active"}],
                                   [{"id": 1, "slug": "kyc", "name": "KYC"}])):
            self.assertEqual(capability.contract_note("beta"), "")

    def test_never_raises(self):
        with mock.patch.object(capability.db, "select", create=True,
                               side_effect=RuntimeError("db down")):
            self.assertEqual(capability.contract_note("beta"), "")


if __name__ == "__main__":
    unittest.main()

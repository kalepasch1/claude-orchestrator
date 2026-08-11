"""Wave-C shared contracts: the narrowest checks that prove the contract holds.

These guard the properties siblings depend on: fail-soft Result, structural
Protocol conformance, defaults that are safe when a shard supplies nothing, and
the ORCH_ config surface.
"""
from __future__ import annotations

import os
import re
import unittest

from runner import wave_c_contracts as wc


class TestResultFailSoft(unittest.TestCase):
    def test_ok_and_err(self):
        good = wc.ok({"a": 1})
        self.assertTrue(good.ok)
        self.assertEqual(good.value, {"a": 1})
        self.assertEqual(good.error, "")

        bad = wc.err("boom")
        self.assertFalse(bad.ok)
        self.assertIsNone(bad.value)
        self.assertEqual(bad.error, "boom")

    def test_err_never_raises_on_bad_input(self):
        for bad_input in (None, 0, object(), [1, 2]):
            r = wc.err(bad_input)
            self.assertFalse(r.ok)
            self.assertIsInstance(r.error, str)

    def test_data_alias_round_trips(self):
        r = wc.Result(ok=True, data="legacy")
        self.assertEqual(r.value, "legacy")
        self.assertEqual(r.data, "legacy")
        r.data = "updated"
        self.assertEqual(r.value, "updated")


class TestConfigSurface(unittest.TestCase):
    def test_orch_prefixed_and_secret_free(self):
        names = [n for n in dir(wc) if n.startswith("ORCH_")]
        self.assertTrue(names, "wave-c must expose ORCH_-prefixed config")
        for name in names:
            self.assertNotRegex(name, r"PASSWORD|TOKEN|SECRET|KEY")

    def test_transplant_floor_is_the_raised_similarity(self):
        # Part 4 raised the transplant floor to 0.55.
        self.assertAlmostEqual(wc.ORCH_WAVEC_TRANSPLANT_MIN_SIMILARITY, 0.55)

    def test_merge_unit_defaults_to_initiative(self):
        self.assertEqual(wc.ORCH_WAVEC_MERGE_UNIT, "initiative")


class TestDefaultsAreSafe(unittest.TestCase):
    def test_every_dataclass_constructs_with_no_arguments(self):
        for cls in (
            wc.TransplantCandidate,
            wc.DispositionLedgerEntry,
            wc.ContractFirstSpec,
            wc.GoldenPathTemplate,
            wc.StrategyContext,
            wc.CodeGenRequest,
            wc.CodeGenResult,
            wc.MatterRecord,
            wc.ExposureRecord,
            wc.HedgeFlywheelMetric,
            wc.RenewalScheduleEntry,
            wc.Initiative,
            wc.InitiativeMergeCard,
            wc.DispositionMemoryEntry,
        ):
            with self.subTest(cls=cls.__name__):
                cls()  # must not raise — siblings rely on zero-arg defaults

    def test_fail_closed_defaults(self):
        self.assertEqual(wc.DispositionLedgerEntry().disposition, wc.Disposition.PENDING)
        self.assertFalse(wc.TransplantCandidate().eligible)
        self.assertFalse(wc.ExposureRecord().hedgeable)
        self.assertFalse(wc.RenewalScheduleEntry().monitor_armed)
        self.assertFalse(wc.Initiative().complete)
        self.assertFalse(wc.CodeGenResult().verify_passed)

    def test_mutable_defaults_are_not_shared(self):
        a, b = wc.MatterRecord(), wc.MatterRecord()
        a.linked_artifacts["inbox"] = ["x"]
        self.assertEqual(b.linked_artifacts, {})


class TestProtocolConformance(unittest.TestCase):
    def test_a_minimal_implementation_satisfies_each_protocol(self):
        class Spine:
            def upsert(self, matter):
                return wc.ok(matter)

            def view(self, matter_id, view):
                return wc.ok({})

            def link(self, matter_id, surface, artifact_id):
                return wc.ok(True)

        class Memory:
            def remember(self, entry):
                return wc.ok(True)

            def should_suppress(self, dedupe_key):
                return wc.ok(False)

        self.assertIsInstance(Spine(), wc.MatterSpine)
        self.assertIsInstance(Memory(), wc.DispositionMemory)

    def test_incomplete_implementation_is_rejected(self):
        class Partial:
            def remember(self, entry):
                return wc.ok(True)

        self.assertNotIsInstance(Partial(), wc.DispositionMemory)


class TestContractsAreBodyFree(unittest.TestCase):
    """The contracts module must stay declarations only — no engine behaviour."""

    def test_no_engine_imports(self):
        path = os.path.join(os.path.dirname(__file__), "wave_c_contracts.py")
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
        for banned in ("import requests", "import psycopg", "from supabase", "import httpx"):
            self.assertNotIn(banned, source)

    def test_enum_values_match_the_migration_checks(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "supabase",
            "migrations",
            "20260805000000_wave_c_platform_spine.sql",
        )
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            sql = fh.read()
        for member in wc.Disposition:
            self.assertIn(f"'{member.value}'", sql)
        for member in wc.MatterStage:
            self.assertIn(f"'{member.value}'", sql)
        for member in wc.InitiativeState:
            self.assertIn(f"'{member.value}'", sql)

    def test_migration_tables_are_idempotent(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "supabase",
            "migrations",
            "20260805000000_wave_c_platform_spine.sql",
        )
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            sql = fh.read()
        creates = re.findall(r"create table\s+(if not exists\s+)?", sql, flags=re.I)
        self.assertTrue(creates)
        self.assertTrue(all(c.strip() for c in creates), "every create table must be idempotent")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

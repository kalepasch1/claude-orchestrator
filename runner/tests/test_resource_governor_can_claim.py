#!/usr/bin/env python3
"""
test_resource_governor_can_claim.py — unit tests for can_claim gate logic.

Validates the RAM-floor and disk-hard thresholds that protect the Mac from
over-commitment.  All tests mock the underlying system calls so they run
on any platform without psutil or vm_stat.
"""
import os, sys, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import resource_governor as rg


class TestCanClaim(unittest.TestCase):
    """Ensure can_claim correctly gates on RAM headroom and disk usage."""

    def setUp(self):
        # runner/.env sets ORCH_DISABLE_MEM_GATE=1 (deliberate, 2026-07-22: workloads
        # deploy to repo/cloud, so the RAM gate was blocking the whole queue), and db.py
        # auto-loads that .env on import. These tests exercise the threshold logic itself,
        # so neutralize the bypass here -- otherwise can_claim() short-circuits to
        # "ok (mem-gate disabled)" and every assertion below is silently vacuous.
        # Same problem with DISK_HARD_PCT: the code default is 90 but .env deploys 99.8,
        # so the 95%-disk case below asserted against a threshold the suite never used.
        # Pin it to the code default so the test checks the rule (used >= hard blocks)
        # rather than one machine's tuning.
        patcher = patch.dict(os.environ, {"ORCH_DISABLE_MEM_GATE": "", "DISK_HARD_PCT": "90"})
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch.object(rg, "mem_pressure_ok", return_value=True)
    @patch.object(rg, "disk_pct", return_value=(50.0, 200.0))
    @patch.object(rg, "ram_free_gb", return_value=8.0)
    def test_healthy_system_allows_claim(self, _ram, _disk, _pres):
        ok, reason = rg.can_claim(n_active=2)
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    @patch.object(rg, "mem_pressure_ok", return_value=True)
    @patch.object(rg, "disk_pct", return_value=(50.0, 200.0))
    @patch.object(rg, "ram_free_gb", return_value=1.5)
    def test_low_ram_blocks_claim(self, _ram, _disk, _pres):
        ok, reason = rg.can_claim(n_active=0)
        self.assertFalse(ok)
        self.assertIn("low RAM", reason)

    @patch.object(rg, "mem_pressure_ok", return_value=True)
    @patch.object(rg, "disk_pct", return_value=(95.0, 5.0))
    @patch.object(rg, "ram_free_gb", return_value=16.0)
    def test_high_disk_blocks_claim(self, _ram, _disk, _pres):
        ok, reason = rg.can_claim(n_active=0)
        self.assertFalse(ok)
        self.assertIn("disk", reason)

    @patch.object(rg, "mem_pressure_ok", return_value=False)
    @patch.object(rg, "disk_pct", return_value=(50.0, 200.0))
    @patch.object(rg, "ram_free_gb", return_value=16.0)
    def test_kernel_pressure_alone_does_not_block_with_ample_ram(self, _ram, _disk, _pres):
        """pressure_should_block requires BOTH kernel pressure AND low headroom."""
        ok, reason = rg.can_claim(n_active=0)
        self.assertTrue(ok)

    @patch.object(rg, "mem_pressure_ok", return_value=False)
    @patch.object(rg, "disk_pct", return_value=(50.0, 200.0))
    @patch.object(rg, "ram_free_gb", return_value=2.0)
    def test_kernel_pressure_plus_low_ram_blocks(self, _ram, _disk, _pres):
        ok, reason = rg.can_claim(n_active=0)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()

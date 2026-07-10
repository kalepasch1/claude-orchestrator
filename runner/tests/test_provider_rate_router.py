#!/usr/bin/env python3
import os
import sys
import time
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import provider_rate_router as prr


def _make_account(name, cooldown_until=0):
    return {"name": name, "type": "login"}


def _make_pool(accounts_data):
    """Return a mock AccountPool with specified accounts and state."""
    pool = MagicMock()
    pool.accts = [d["acct"] for d in accounts_data]
    pool.state = {d["acct"]["name"]: {"cooldown_until": d["cooldown_until"]} for d in accounts_data}
    return pool


class TestProviderRateRouter(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig_home = os.environ.get("CLAUDE_ORCH_HOME")
        os.environ["CLAUDE_ORCH_HOME"] = self.tmp
        # Reset module-level state
        prr.HOME = self.tmp
        prr._STATE_DIR = os.path.join(self.tmp, "module_state")
        prr._ROUTING_LOG = os.path.join(prr._STATE_DIR, "provider_routing_log.jsonl")
        os.makedirs(prr._STATE_DIR, exist_ok=True)

    def tearDown(self):
        if self._orig_home is None:
            os.environ.pop("CLAUDE_ORCH_HOME", None)
        else:
            os.environ["CLAUDE_ORCH_HOME"] = self._orig_home

    def _patch_accounts(self, accounts_data):
        """Patch _all_accounts to return specified data."""
        return patch.object(prr, "_all_accounts", return_value=accounts_data)

    def _healthy(self, name, remaining=40_000_000):
        return (_make_account(name), True, 0, remaining)

    def _cooling(self, name, cd_until=None, remaining=40_000_000):
        if cd_until is None:
            cd_until = time.time() + 3600
        return (_make_account(name), False, cd_until, remaining)

    # ── basic routing ─────────────────────────────────────────────────────────

    def test_picks_single_healthy_account(self):
        with self._patch_accounts([self._healthy("account-a")]):
            acct, log_e = prr.pick("task-1")
        self.assertEqual(acct["name"], "account-a")
        self.assertEqual(log_e["reason"], "healthy_max_capacity")

    def test_prefers_healthy_over_cooling(self):
        data = [self._cooling("account-a"), self._healthy("account-b")]
        with self._patch_accounts(data):
            acct, _ = prr.pick("task-2")
        self.assertEqual(acct["name"], "account-b")

    def test_prefers_more_capacity_among_healthy(self):
        data = [self._healthy("low-cap", remaining=1_000_000),
                self._healthy("high-cap", remaining=30_000_000)]
        with self._patch_accounts(data):
            acct, _ = prr.pick("task-3")
        self.assertEqual(acct["name"], "high-cap")

    def test_all_cooling_picks_soonest_reset(self):
        now = time.time()
        data = [self._cooling("account-a", cd_until=now + 7200),
                self._cooling("account-b", cd_until=now + 1800)]
        with self._patch_accounts(data):
            acct, log_e = prr.pick("task-4")
        self.assertEqual(acct["name"], "account-b")
        self.assertIn("all_cooling_soonest_reset", log_e["reason"])

    def test_no_accounts_returns_none(self):
        with self._patch_accounts([]):
            acct, log_e = prr.pick("task-5")
        self.assertIsNone(acct)
        self.assertEqual(log_e["reason"], "no_accounts")

    # ── operator force override ───────────────────────────────────────────────

    def test_force_account_overrides_routing(self):
        import account_pool as ap_mod
        mock_pool = _make_pool([
            {"acct": _make_account("personal-max"), "cooldown_until": 0},
            {"acct": _make_account("team-api"), "cooldown_until": 0},
        ])
        with patch.dict(os.environ, {"ORCH_FORCE_ACCOUNT": "team-api"}):
            with patch.object(ap_mod, "AccountPool", return_value=mock_pool):
                with patch.object(prr, "FORCE_ACCOUNT", "team-api"):
                    with patch.object(prr, "_account_remaining", return_value=40_000_000):
                        acct, log_e = prr.pick("force-task")
        self.assertEqual(acct["name"], "team-api")
        self.assertEqual(log_e["reason"], "forced")

    # ── audit log ─────────────────────────────────────────────────────────────

    def test_routing_log_written(self):
        with self._patch_accounts([self._healthy("account-a")]):
            prr.pick("audit-task")
        log_path = prr._ROUTING_LOG
        self.assertTrue(os.path.exists(log_path))
        lines = open(log_path).readlines()
        self.assertTrue(len(lines) >= 1)
        entry = json.loads(lines[-1])
        self.assertEqual(entry["task"], "audit-task")
        self.assertEqual(entry["account"], "account-a")

    def test_log_entry_contains_capacity_estimate(self):
        with self._patch_accounts([self._healthy("account-a", remaining=5_000_000)]):
            _, log_e = prr.pick("cap-task")
        self.assertEqual(log_e["est_remaining_tokens"], 5_000_000)
        self.assertGreater(log_e["est_tasks_remaining"], 0)

    # ── capacity estimation ───────────────────────────────────────────────────

    def test_account_remaining_missing_state_returns_full_budget(self):
        # No capacity_pacer.json -> assume full budget
        result = prr._account_remaining("new-account")
        self.assertEqual(result, prr._WEEKLY_BUDGET)

    def test_account_remaining_reads_pacer_state(self):
        pacer_data = {
            "spend:tracked-account": {
                "total_tokens": 5_000_000,
                "period_start": time.time(),
            }
        }
        pacer_path = os.path.join(prr._STATE_DIR, "capacity_pacer.json")
        json.dump(pacer_data, open(pacer_path, "w"))
        result = prr._account_remaining("tracked-account")
        self.assertEqual(result, prr._WEEKLY_BUDGET - 5_000_000)

    def test_account_remaining_resets_after_period(self):
        old_start = time.time() - (200 * 3600)  # 200h ago > 168h period
        pacer_data = {
            "spend:old-account": {
                "total_tokens": 40_000_000,
                "period_start": old_start,
            }
        }
        pacer_path = os.path.join(prr._STATE_DIR, "capacity_pacer.json")
        json.dump(pacer_data, open(pacer_path, "w"))
        result = prr._account_remaining("old-account")
        self.assertEqual(result, prr._WEEKLY_BUDGET)

    # ── log_entry shape ───────────────────────────────────────────────────────

    def test_log_entry_has_all_fields(self):
        acct = _make_account("test-acct")
        entry = prr._log_entry(acct, "healthy_max_capacity", "my-task", 10_000_000)
        for field in ("ts", "task", "account", "reason", "est_remaining_tokens", "est_tasks_remaining"):
            self.assertIn(field, entry)
        self.assertEqual(entry["account"], "test-acct")
        self.assertEqual(entry["task"], "my-task")

    def test_log_entry_none_account(self):
        entry = prr._log_entry(None, "no_accounts", "t", 0)
        self.assertIsNone(entry["account"])


if __name__ == "__main__":
    unittest.main()

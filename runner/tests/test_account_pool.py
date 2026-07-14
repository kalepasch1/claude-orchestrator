import os
import sys
import time


RUNNER = os.path.dirname(os.path.dirname(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import account_pool


def _pool():
    pool = account_pool.AccountPool.__new__(account_pool.AccountPool)
    pool.accts = [
        {"name": "max-1", "type": "subscription"},
        {"name": "max-2", "type": "subscription"},
        {"name": "max-3", "type": "subscription"},
        {"name": "anthropic-api", "type": "api"},
    ]
    future = time.time() + 3600
    pool.state = {
        "max-1": {"cooldown_until": future},
        "max-2": {"cooldown_until": future},
        "max-3": {"cooldown_until": future},
    }
    pool._cfg_ts = time.time()
    pool._state_ts = time.time()
    return pool


def test_disabled_api_row_does_not_mask_exhausted_subscriptions(monkeypatch):
    pool = _pool()
    monkeypatch.setattr(account_pool, "_api_billing_allowed", lambda: False)

    assert pool.all_exhausted() is True
    assert pool.current()["name"] in {"max-1", "max-2", "max-3"}


def test_explicitly_enabled_api_capacity_remains_usable(monkeypatch):
    pool = _pool()
    monkeypatch.setattr(account_pool, "_api_billing_allowed", lambda: True)

    assert pool.all_exhausted() is False
    assert pool.current()["name"] == "anthropic-api"

import os
import sys
import time


RUNNER = os.path.dirname(os.path.dirname(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import exhaustion_signal


def test_disabled_api_account_is_excluded_from_dashboard_capacity(monkeypatch, tmp_path):
    future = time.time() + 3600
    rows = [
        {"name": "max-1", "type": "subscription", "cooldown_until": future},
        {"name": "max-2", "type": "subscription", "cooldown_until": future},
        {"name": "max-3", "type": "subscription", "cooldown_until": future},
    ]
    monkeypatch.setattr(exhaustion_signal, "_usable_account_rows", lambda: rows)
    monkeypatch.setattr(exhaustion_signal, "_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(exhaustion_signal, "_read_local_state", lambda: {
        "all_exhausted": True,
        "exhausted_until": future,
        "accounts_cooling": [
            {"name": "max-1", "until": future, "remaining_min": 60},
            {"name": "max-2", "until": future, "remaining_min": 60},
            {"name": "max-3", "until": future, "remaining_min": 60},
            {"name": "anthropic-api", "until": future, "remaining_min": 60},
        ],
        "total_cooling": 4,
    })

    signal = exhaustion_signal.update()

    assert signal["all_exhausted"] is True
    assert signal["accounts_cooling"] == 3
    assert signal["total_accounts"] == 3
    assert {d["name"] for d in signal["details"]} == {"max-1", "max-2", "max-3"}

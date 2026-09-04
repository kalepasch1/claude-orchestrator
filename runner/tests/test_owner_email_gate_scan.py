"""The owner-email chokepoint must see every pending notification.

gate_owner_emails is described in its own docstring as "the single chokepoint
that enforces it no matter which composer produced the row". It was reading a
capped `select(..., order=id.desc, limit=400)`, and db's truncated-scan detector
was reporting it 8391 times in the live logs -- more than any other call site in
the fleet.

Descending order meant the cap always fell on the OLDEST unsent rows. Once more
than `limit` notifications were pending, everything past the cap was never
inspected and therefore never demoted: it stayed channel='email' and remained
eligible to reach the owner's inbox. The guard failed silently, and it failed
preferentially for the rows that had been waiting longest.

Pure: db is stubbed, no network.
"""
import os
import sys

import pytest

_RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNNER not in sys.path:
    sys.path.insert(0, _RUNNER)

import approval_policy as ap  # noqa: E402


def _notif(n):
    return {"id": f"n{n}", "approval_id": f"a{n}", "channel": "email"}


@pytest.fixture()
def gate(monkeypatch):
    """Stub db; record what was demoted and how the tables were read."""
    state = {"pending": [], "cards": {}, "demoted": [],
             "select_all": [], "card_queries": []}

    def fake_select_all(table, params=None, **kwargs):
        state["select_all"].append((table, dict(params or {}), dict(kwargs)))
        return list(state["pending"])

    def fake_select(table, params=None):
        params = dict(params or {})
        if table == "approvals":
            raw = params.get("id", "")
            ids = raw[len("in.("):-1].split(",") if raw.startswith("in.(") else []
            state["card_queries"].append(ids)
            return [state["cards"][i] for i in ids if i in state["cards"]]
        return []

    def fake_update(table, match, patch):
        if table == "notifications" and patch.get("channel") == "cockpit":
            state["demoted"].append(match["id"])
        return True

    monkeypatch.setattr(ap.db, "select_all", fake_select_all)
    monkeypatch.setattr(ap.db, "select", fake_select)
    monkeypatch.setattr(ap.db, "update", fake_update)
    return state


class TestSeesTheWholeBacklog:
    def test_notifications_beyond_the_old_cap_are_demoted(self, gate):
        """1200 pending with the old limit of 400 left 800 emailable."""
        gate["pending"] = [_notif(i) for i in range(1200)]
        assert ap.gate_owner_emails() == 1200
        assert len(gate["demoted"]) == 1200

    def test_read_through_the_paging_helper(self, gate):
        gate["pending"] = [_notif(0)]
        ap.gate_owner_emails()
        assert [t for t, _p, _k in gate["select_all"]] == ["notifications"]

    def test_no_silent_limit_is_sent(self, gate):
        gate["pending"] = [_notif(0)]
        ap.gate_owner_emails()
        _t, params, _k = gate["select_all"][0]
        assert "limit" not in params

    def test_paging_budget_has_a_floor(self, gate):
        """A small caller value must not reintroduce a narrow horizon."""
        gate["pending"] = [_notif(0)]
        ap.gate_owner_emails(limit=10)
        _t, _p, kwargs = gate["select_all"][0]
        assert kwargs.get("max_rows") >= 5000

    def test_filter_still_targets_unsent_owner_channels(self, gate):
        gate["pending"] = [_notif(0)]
        ap.gate_owner_emails()
        _t, params, _k = gate["select_all"][0]
        assert params.get("sent") == "eq.false"
        assert params.get("channel") == "in.(email,digest)"


class TestCardLookupIsChunked:
    def test_large_id_list_is_split(self, gate):
        """One in.(...) of thousands of ids is a URL the server rejects with 400."""
        gate["pending"] = [_notif(i) for i in range(500)]
        ap.gate_owner_emails()
        assert len(gate["card_queries"]) == 10
        assert all(len(q) <= ap._CARD_LOOKUP_CHUNK for q in gate["card_queries"])

    def test_every_id_is_still_looked_up(self, gate):
        gate["pending"] = [_notif(i) for i in range(120)]
        ap.gate_owner_emails()
        looked_up = {i for q in gate["card_queries"] for i in q}
        assert looked_up == {f"a{i}" for i in range(120)}

    def test_a_failing_chunk_demotes_rather_than_emails(self, gate, monkeypatch):
        """Unknown card => not legal-gated => demoted. Fail safe, not fail open."""
        gate["pending"] = [_notif(i) for i in range(60)]

        def boom(table, params=None):
            raise RuntimeError("URL too long")

        monkeypatch.setattr(ap.db, "select", boom)
        assert ap.gate_owner_emails() == 60


class TestLegalCardsStillEmail:
    def test_legal_gated_card_is_not_demoted(self, gate, monkeypatch):
        gate["pending"] = [_notif(0), _notif(1)]
        gate["cards"] = {"a0": {"id": "a0"}, "a1": {"id": "a1"}}
        monkeypatch.setattr(ap, "is_legal_gated", lambda card: card["id"] == "a0")
        ap.gate_owner_emails()
        assert gate["demoted"] == ["n1"]

    def test_system_alerts_without_a_card_are_left_alone(self, gate):
        gate["pending"] = [{"id": "n9", "approval_id": None, "channel": "email"}]
        assert ap.gate_owner_emails() == 0
        assert gate["demoted"] == []

    def test_unreadable_notifications_table_is_fail_soft(self, gate, monkeypatch):
        monkeypatch.setattr(ap.db, "select_all",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
        assert ap.gate_owner_emails() == 0

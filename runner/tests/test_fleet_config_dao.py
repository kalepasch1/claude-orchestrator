"""fleet_config_dao must not pay for round trips it does not need.

Slice 3 of the high-performance-database work. The DAO is the owner module for
fleet configuration: every writer in the fleet reaches the table through it, so
a redundant request here is a redundant request everywhere.

Two costs are pinned by this suite:

  * set_value() used to issue get -> upsert -> get. db.insert already sends
    `Prefer: return=representation`, so the trailing read re-fetched a row the
    write had just handed back. It is now only issued when the write response
    is unusable.
  * get_many()/set_many() collapse N reads into one `key=in.(...)` request.

The behavioural contract is unchanged and is asserted alongside the counts:
same (old, new) return shape, same fail-soft None, same change-hook firing.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fleet_config_dao as dao


class FakeDB:
    """Records every call so tests can assert on the round-trip count."""

    def __init__(self, rows=None, upsert_returns="representation"):
        self.rows = dict(rows or {})
        self.selects = []
        self.upserts = []
        self.upsert_returns = upsert_returns

    def select(self, table, params):
        assert table == "fleet_config"
        self.selects.append(params)
        key = params.get("key", "")
        if key.startswith("eq."):
            row = self.rows.get(key[3:])
            return [row] if row else []
        if key.startswith("in.("):
            wanted = [k.strip('"') for k in key[4:-1].split(",") if k]
            return [self.rows[k] for k in wanted if k in self.rows]
        return list(self.rows.values())

    def upsert(self, table, row):
        assert table == "fleet_config"
        self.upserts.append(row)
        self.rows[row["key"]] = dict(row)
        if self.upsert_returns == "representation":
            return [dict(row)]
        if self.upsert_returns == "dict":
            return dict(row)
        return None      # the 409-dedup path


@pytest.fixture
def fake_db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(dao, "db", fake)
    monkeypatch.setattr(dao, "_change_hook", None)
    return fake


# --- write path: one read, one write, no trailing read ---------------------

def test_set_value_does_not_re_read_after_a_write_that_returned_the_row(fake_db):
    old, new = dao.set_value("ORCH_X", "1")

    assert len(fake_db.upserts) == 1
    assert len(fake_db.selects) == 1, "the trailing read is the redundant one"
    assert old is None
    assert new["key"] == "ORCH_X" and new["value"] == "1"


def test_set_value_falls_back_to_a_read_when_the_write_returns_nothing(fake_db):
    fake_db.upsert_returns = None

    old, new = dao.set_value("ORCH_X", "1")

    assert len(fake_db.selects) == 2, "unusable response must be re-read, not invented"
    assert new["value"] == "1"


def test_set_value_accepts_a_bare_dict_response(fake_db):
    fake_db.upsert_returns = "dict"

    _, new = dao.set_value("ORCH_X", "1")

    assert len(fake_db.selects) == 1
    assert new["value"] == "1"


def test_set_value_still_reports_the_previous_row_as_old(fake_db):
    fake_db.rows["ORCH_X"] = {"key": "ORCH_X", "value": "before"}

    old, new = dao.set_value("ORCH_X", "after")

    assert old["value"] == "before"
    assert new["value"] == "after"


def test_set_value_returns_none_for_new_when_the_write_raises(fake_db, monkeypatch):
    def boom(table, row):
        raise RuntimeError("postgrest is down")
    monkeypatch.setattr(fake_db, "upsert", boom)
    fake_db.rows["ORCH_X"] = {"key": "ORCH_X", "value": "before"}

    old, new = dao.set_value("ORCH_X", "after")

    assert old["value"] == "before"
    assert new is None


def test_values_are_stringified_as_before(fake_db):
    _, new = dao.set_value("ORCH_X", 42)
    assert new["value"] == "42"


# --- change hook -----------------------------------------------------------

def test_change_hook_fires_with_created_then_updated(fake_db, monkeypatch):
    seen = []
    monkeypatch.setattr(dao, "_change_hook",
                        lambda old, new, change_type: seen.append(change_type))

    dao.set_value("ORCH_X", "1")
    dao.set_value("ORCH_X", "2")

    assert seen == ["created", "updated"]


def test_a_raising_hook_never_breaks_the_write(fake_db, monkeypatch):
    def boom(old, new, change_type):
        raise RuntimeError("subscriber exploded")
    monkeypatch.setattr(dao, "_change_hook", boom)

    _, new = dao.set_value("ORCH_X", "1")

    assert new["value"] == "1"


# --- batched reads ---------------------------------------------------------

def test_get_many_fetches_every_key_in_one_request(fake_db):
    fake_db.rows = {
        "A": {"key": "A", "value": "1"},
        "B": {"key": "B", "value": "2"},
    }

    got = dao.get_many(["A", "B", "MISSING"])

    assert len(fake_db.selects) == 1
    assert got["A"]["value"] == "1" and got["B"]["value"] == "2"
    assert "MISSING" not in got, "absent keys stay absent, as get() returns None"


def test_get_many_on_no_keys_makes_no_request(fake_db):
    assert dao.get_many([]) == {}
    assert dao.get_many(None) == {}
    assert fake_db.selects == []


def test_get_many_quotes_keys_so_a_comma_cannot_split_the_filter(fake_db):
    dao.get_many(["A,B"])

    assert fake_db.selects[0]["key"] == 'in.("A,B")'


def test_get_many_is_fail_soft(fake_db, monkeypatch):
    def boom(table, params):
        raise RuntimeError("postgrest is down")
    monkeypatch.setattr(fake_db, "select", boom)

    assert dao.get_many(["A"]) == {}


# --- batched writes --------------------------------------------------------

def test_set_many_reads_all_previous_rows_in_one_request(fake_db):
    fake_db.rows = {"A": {"key": "A", "value": "old-a"}}

    results = dao.set_many([
        {"key": "A", "value": "new-a"},
        {"key": "B", "value": "new-b"},
    ])

    assert len(fake_db.selects) == 1, "one read for the whole batch"
    assert len(fake_db.upserts) == 2
    assert results[0][0]["value"] == "old-a"
    assert results[0][1]["value"] == "new-a"
    assert results[1][0] is None
    assert results[1][1]["value"] == "new-b"


def test_set_many_matches_repeated_set_value_calls(fake_db):
    batched = dao.set_many([{"key": "A", "value": "1"}, {"key": "B", "value": "2"}])

    fake_db.rows.clear()
    one_at_a_time = [dao.set_value("A", "1"), dao.set_value("B", "2")]

    strip = lambda pairs: [(o, {k: v for k, v in n.items() if k != "updated_at"})
                           for o, n in pairs]
    assert strip(batched) == strip(one_at_a_time)


def test_set_many_carries_note_and_updated_by(fake_db):
    dao.set_many([{"key": "A", "value": "1", "note": "why", "updated_by": "me"}])

    assert fake_db.upserts[0]["note"] == "why"
    assert fake_db.upserts[0]["updated_by"] == "me"


def test_set_many_refuses_an_item_with_no_key_before_writing_anything(fake_db):
    with pytest.raises(ValueError):
        dao.set_many([{"key": "A", "value": "1"}, {"value": "no key"}])

    assert fake_db.upserts == [], "a bad item must not leave a partial batch behind"


def test_set_many_on_an_empty_batch_touches_nothing(fake_db):
    assert dao.set_many([]) == []
    assert fake_db.selects == [] and fake_db.upserts == []

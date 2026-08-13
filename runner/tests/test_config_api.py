"""Offline tests for the fleet-configuration REST layer.

No database and no socket: the store is injected, which is the whole point of routing
through the `ConfigStore` seam. The assertions that matter are the negative ones — a
credential must not cross the response boundary in either direction.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_api  # noqa: E402


class FakeStore:
    """Minimal ConfigStore stand-in that records what it was asked to write."""

    def __init__(self, rows=None):
        self.rows = dict(rows or {})
        self.writes = []

    def get_config(self, key):
        return self.rows.get(key)

    def get_all(self):
        return list(self.rows.values())

    def update_config(self, key, value, note=None, updated_by=None):
        old = self.rows.get(key)
        new = {"key": key, "value": value, "note": note, "updated_by": updated_by}
        self.rows[key] = new
        self.writes.append(new)
        return old, new


class TestReads(unittest.TestCase):
    def test_get_returns_the_row(self):
        store = FakeStore({"ORCH_MAX_PARALLEL": {"key": "ORCH_MAX_PARALLEL", "value": "8"}})
        status, body = config_api.get_config("ORCH_MAX_PARALLEL", store=store)
        self.assertEqual(status, 200)
        self.assertEqual(body["config"]["value"], "8")

    def test_missing_key_is_404(self):
        self.assertEqual(config_api.get_config("NOPE", store=FakeStore())[0], 404)

    def test_empty_key_is_400(self):
        self.assertEqual(config_api.get_config("  ", store=FakeStore())[0], 400)

    def test_legacy_credential_row_is_redacted_but_still_listed(self):
        # The 2026-08-02 residue. Serving it over HTTP would re-open the incident;
        # hiding the key entirely would send an operator hunting for a phantom.
        store = FakeStore({"GITHUB_PAT": {"key": "GITHUB_PAT", "value": "ghp_" + "a" * 30}})
        status, body = config_api.get_config("GITHUB_PAT", store=store)
        self.assertEqual(status, 200)
        self.assertTrue(body["config"]["redacted"])
        self.assertEqual(body["config"]["value"], config_api.REDACTED)
        self.assertNotIn("ghp_", str(body))

    def test_redaction_reason_never_leaks_the_material(self):
        store = FakeStore({"innocuous": {"key": "innocuous", "value": "AIza" + "b" * 35}})
        _status, body = config_api.get_config("innocuous", store=store)
        self.assertTrue(body["config"]["redacted"])
        self.assertNotIn("b" * 10, body["config"]["redaction_reason"])

    def test_redaction_does_not_mutate_the_stored_row(self):
        # The row handed back is frequently the DAO's cached object; redacting in
        # place would corrupt config for every in-process consumer.
        original = {"key": "GITHUB_PAT", "value": "ghp_" + "c" * 30}
        store = FakeStore({"GITHUB_PAT": original})
        config_api.get_config("GITHUB_PAT", store=store)
        self.assertEqual(original["value"], "ghp_" + "c" * 30)

    def test_list_counts_redactions(self):
        store = FakeStore({
            "ORCH_MAX_PARALLEL": {"key": "ORCH_MAX_PARALLEL", "value": "8"},
            "VERCEL_TOKEN": {"key": "VERCEL_TOKEN", "value": "vcp_" + "d" * 25},
        })
        status, body = config_api.list_config(store=store)
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 2)
        self.assertEqual(body["redacted_count"], 1)
        self.assertNotIn("vcp_", str(body))


class TestWrites(unittest.TestCase):
    def test_create_is_201_and_update_is_200(self):
        store = FakeStore()
        self.assertEqual(config_api.put_config("ORCH_X", {"value": "1"}, store=store)[0], 201)
        self.assertEqual(config_api.put_config("ORCH_X", {"value": "2"}, store=store)[0], 200)

    def test_missing_value_is_400(self):
        self.assertEqual(config_api.put_config("ORCH_X", {}, store=FakeStore())[0], 400)
        self.assertEqual(config_api.put_config("ORCH_X", None, store=FakeStore())[0], 400)

    def test_credential_is_refused_422_and_never_reaches_the_store(self):
        store = FakeStore()
        status, body = config_api.put_config("GITHUB_PAT", {"value": "ghp_" + "e" * 30},
                                             store=store)
        self.assertEqual(status, 422)
        self.assertEqual(store.writes, [])
        self.assertNotIn("ghp_", str(body))

    def test_credential_by_value_shape_is_refused_under_an_innocuous_key(self):
        # The observed table held a row literally keyed `key`; an innocuous name is
        # no evidence of innocuous content.
        store = FakeStore()
        self.assertEqual(
            config_api.put_config("notes", {"value": "sk-" + "f" * 30}, store=store)[0], 422)
        self.assertEqual(store.writes, [])

    def test_store_level_refusal_surfaces_as_422_not_500(self):
        class RefusingStore(FakeStore):
            def update_config(self, *_a, **_k):
                raise ValueError("[fleet-config-guard] refusing to store a credential")

        self.assertEqual(
            config_api.put_config("ORCH_X", {"value": "1"}, store=RefusingStore())[0], 422)


class TestDispatch(unittest.TestCase):
    def test_routes_list_and_item(self):
        store = FakeStore({"ORCH_X": {"key": "ORCH_X", "value": "1"}})
        self.assertEqual(config_api.dispatch("GET", "/config", store=store)[0], 200)
        self.assertEqual(config_api.dispatch("GET", "/config/ORCH_X", store=store)[0], 200)
        self.assertEqual(
            config_api.dispatch("PUT", "/config/ORCH_Y", {"value": "2"}, store=store)[0], 201)

    def test_trailing_slash_and_lowercase_verb_are_tolerated(self):
        store = FakeStore({"ORCH_X": {"key": "ORCH_X", "value": "1"}})
        self.assertEqual(config_api.dispatch("get", "/config/", store=store)[0], 200)

    def test_unknown_path_is_404_and_wrong_verb_is_405(self):
        # Collapsing these makes a typo'd verb read as a missing endpoint.
        self.assertEqual(config_api.dispatch("GET", "/nope", store=FakeStore())[0], 404)
        status, body = config_api.dispatch("DELETE", "/config/ORCH_X", store=FakeStore())
        self.assertEqual(status, 405)
        self.assertEqual(body["allowed"], ["GET", "PUT"])

    def test_put_on_the_collection_is_405(self):
        self.assertEqual(
            config_api.dispatch("PUT", "/config", {"value": "1"}, store=FakeStore())[0], 405)


if __name__ == "__main__":
    unittest.main(verbosity=2)

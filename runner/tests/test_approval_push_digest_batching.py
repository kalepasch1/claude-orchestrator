#!/usr/bin/env python3
"""Approval digest batching + the security posture that unblocked it.

The original task was quarantined as a secret/security risk. These tests pin BOTH halves
of the rework: the useful behaviour (one batched digest instead of a ping per card) and
the closed hole (an empty HMAC key can no longer sign a one-click approval link).
"""
import importlib
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

import approval_push as ap  # noqa: E402

GOOD_KEY = "k" * 40
SERVICE_KEY = "s" * 40


def _reload(env):
    """Reload the module under a given environment (module-level AUDIENCE/TTL)."""
    with patch.dict(os.environ, env, clear=False):
        return importlib.reload(ap)


class SigningKeyTest(unittest.TestCase):

    def tearDown(self):
        importlib.reload(ap)

    def test_dedicated_key_is_used(self):
        with patch.dict(os.environ, {"APPROVAL_LINK_SIGNING_KEY": GOOD_KEY}):
            self.assertEqual(ap._signing_key(), GOOD_KEY)

    def test_empty_key_refuses_to_sign(self):
        """THE HOLE: an empty-key HMAC is publicly computable — anyone could forge approve."""
        env = {k: v for k, v in os.environ.items()
               if k not in ("APPROVAL_LINK_SIGNING_KEY", "SUPABASE_SERVICE_KEY",
                            "SUPABASE_SERVICE_ROLE_KEY", "APPROVAL_LINK_ALLOW_SERVICE_KEY")}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ap.SigningKeyUnavailable):
                ap._signing_key()
            with self.assertRaises(ap.SigningKeyUnavailable):
                ap._sign("approval-1", "approve")

    def test_short_key_refuses_to_sign(self):
        with patch.dict(os.environ, {"APPROVAL_LINK_SIGNING_KEY": "short"}):
            with self.assertRaises(ap.SigningKeyUnavailable):
                ap._signing_key()

    def test_service_role_key_is_not_used_without_an_explicit_opt_in(self):
        env = dict(os.environ)
        env.pop("APPROVAL_LINK_SIGNING_KEY", None)
        env.pop("APPROVAL_LINK_ALLOW_SERVICE_KEY", None)
        env["SUPABASE_SERVICE_KEY"] = SERVICE_KEY
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ap.SigningKeyUnavailable):
                ap._signing_key()

    def test_service_role_key_only_under_explicit_opt_in(self):
        env = dict(os.environ)
        env.pop("APPROVAL_LINK_SIGNING_KEY", None)
        env["SUPABASE_SERVICE_KEY"] = SERVICE_KEY
        env["APPROVAL_LINK_ALLOW_SERVICE_KEY"] = "1"
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(ap._signing_key(), SERVICE_KEY)

    def test_ttl_is_clamped(self):
        self.assertEqual(_reload({"APPROVAL_LINK_TTL_S": "999999999"}).LINK_TTL_S, 7 * 24 * 3600)
        self.assertEqual(_reload({"APPROVAL_LINK_TTL_S": "1"}).LINK_TTL_S, 300)
        self.assertEqual(_reload({"APPROVAL_LINK_TTL_S": "not-a-number"}).LINK_TTL_S, 7 * 24 * 3600)

    def test_links_block_degrades_to_an_unsigned_pointer(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("APPROVAL_LINK_SIGNING_KEY", "SUPABASE_SERVICE_KEY",
                            "SUPABASE_SERVICE_ROLE_KEY", "APPROVAL_LINK_ALLOW_SERVICE_KEY")}
        with patch.dict(os.environ, env, clear=True):
            block = ap._links_block({"id": "a1", "alternatives": []})
        self.assertIn("One-click links are disabled", block)
        self.assertNotIn("sig=", block)

    def test_signed_link_contains_the_expected_query_shape(self):
        with patch.dict(os.environ, {"APPROVAL_LINK_SIGNING_KEY": GOOD_KEY,
                                     "SUPABASE_URL": "https://db.example.com"}):
            link = ap._sign("a1", "approve")
        self.assertIn("/functions/v1/approvals-api?", link)
        for part in ("id=a1", "action=approve", "exp=", "sig="):
            self.assertIn(part, link)


class ScrubTest(unittest.TestCase):

    def test_signature_is_scrubbed(self):
        dirty = "https://db.example.com/f?id=a1&action=approve&exp=1&sig=deadbeefcafe"
        clean = ap.scrub(dirty)
        self.assertNotIn("deadbeefcafe", clean)
        self.assertIn("id=a1", clean)
        self.assertIn("action=approve", clean)

    def test_tokens_and_keys_are_scrubbed(self):
        clean = ap.scrub("?token=abc123def&apikey=zzzzzzzz&x=1")
        self.assertNotIn("abc123def", clean)
        self.assertNotIn("zzzzzzzz", clean)
        self.assertIn("x=1", clean)


class DigestTest(unittest.TestCase):

    CARDS = [
        {"id": "a1", "kind": "legal", "project": "tomorrow", "title": "Money transmission?"},
        {"id": "a2", "kind": "operator", "project": "apparently", "title": "Rotate a key"},
        {"id": "a3", "kind": "material", "project": "smarter", "title": "Pricing change"},
    ]

    def test_digest_lists_every_card_once(self):
        title, body = ap.build_digest(self.CARDS)
        self.assertIn("3 decisions need you", title)
        for card in self.CARDS:
            self.assertEqual(body.count(card["title"]), 1)

    def test_digest_singular_for_one_card(self):
        title, _ = ap.build_digest(self.CARDS[:1])
        self.assertIn("1 decision need", title)
        self.assertNotIn("decisions", title)

    def test_digest_never_carries_a_signed_link(self):
        with patch.dict(os.environ, {"APPROVAL_LINK_SIGNING_KEY": GOOD_KEY}):
            _, body = ap.build_digest(self.CARDS)
        self.assertNotIn("sig=", body)
        self.assertNotIn("approvals-api", body)


class RunBatchingTest(unittest.TestCase):
    """One outbound ping per run, not one per card."""

    CARDS = [
        {"id": "a1", "kind": "legal", "project": "p", "title": "One", "alternatives": []},
        {"id": "a2", "kind": "legal", "project": "p", "title": "Two", "alternatives": []},
        {"id": "a3", "kind": "legal", "project": "p", "title": "Three", "alternatives": []},
    ]

    def _run(self, *, digest="1", audience="owner@example.com", already=()):
        inserts, pings = [], []

        def fake_select(table, params=None):
            if table == "notifications":
                return [{"approval_id": x} for x in already]
            return list(self.CARDS)

        policy = type("P", (), {"is_legal_gated": staticmethod(lambda a: True)})()
        notify = type("N", (), {"send": staticmethod(lambda m: pings.append(m))})()
        env = dict(os.environ)
        env["APPROVAL_DIGEST_BATCHING"] = digest
        env["APPROVAL_PUSH_EMAIL"] = audience
        env["APPROVAL_LINK_SIGNING_KEY"] = GOOD_KEY
        with patch.dict(os.environ, env, clear=True):
            mod = importlib.reload(ap)
            with patch.object(mod.db, "select", side_effect=fake_select), \
                 patch.object(mod.db, "insert", side_effect=lambda t, r: inserts.append(r)), \
                 patch.dict(sys.modules, {"approval_policy": policy, "notify": notify}):
                pushed = mod.run()
        importlib.reload(ap)
        return pushed, inserts, pings

    def test_three_cards_produce_one_ping(self):
        pushed, inserts, pings = self._run()
        self.assertEqual(pushed, 3)
        self.assertEqual(len(pings), 1)
        self.assertIn("3 decisions", pings[0])

    def test_one_digest_row_is_written(self):
        _, inserts, _ = self._run()
        digests = [r for r in inserts if r.get("channel") == "digest"]
        self.assertEqual(len(digests), 1)
        self.assertEqual(digests[0]["kind"], "digest")

    def test_per_card_ledger_rows_are_preserved_for_dedup(self):
        _, inserts, _ = self._run()
        emailed = [r for r in inserts if r.get("channel") == "email"]
        smarter = [r for r in inserts if r.get("channel") == "smarter"]
        self.assertEqual({r["approval_id"] for r in emailed}, {"a1", "a2", "a3"})
        self.assertEqual({r["approval_id"] for r in smarter}, {"a1", "a2", "a3"})

    def test_already_pushed_cards_are_skipped(self):
        pushed, inserts, pings = self._run(already=("a1", "a2"))
        self.assertEqual(pushed, 1)
        self.assertEqual(len(pings), 1)
        self.assertIn("1 decision", pings[0])

    def test_nothing_new_means_no_ping_and_no_digest_row(self):
        pushed, inserts, pings = self._run(already=("a1", "a2", "a3"))
        self.assertEqual(pushed, 0)
        self.assertEqual(pings, [])
        self.assertEqual([r for r in inserts if r.get("channel") == "digest"], [])

    def test_batching_off_restores_per_card_pings(self):
        pushed, _, pings = self._run(digest="0")
        self.assertEqual(pushed, 3)
        self.assertEqual(len(pings), 3)

    def test_no_audience_writes_no_email_row_but_still_records_smarter(self):
        _, inserts, _ = self._run(audience="")
        self.assertEqual([r for r in inserts if r.get("channel") == "email"], [])
        self.assertEqual(len([r for r in inserts if r.get("channel") == "smarter"]), 3)

    def test_no_ping_ever_carries_a_signature(self):
        _, _, pings = self._run()
        for ping in pings:
            self.assertNotIn("sig=", ping)


class NoHardcodedOwnerAddressTest(unittest.TestCase):

    def test_source_contains_no_hardcoded_personal_email(self):
        with open(ap.__file__.replace(".pyc", ".py"), encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("kalepasch@gmail.com", source)

    def test_audience_is_empty_when_unconfigured(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("APPROVAL_PUSH_EMAIL", "ORCH_OWNER_EMAIL")}
        with patch.dict(os.environ, env, clear=True):
            mod = importlib.reload(ap)
            self.assertEqual(mod.AUDIENCE, "")
        importlib.reload(ap)


if __name__ == "__main__":
    unittest.main()

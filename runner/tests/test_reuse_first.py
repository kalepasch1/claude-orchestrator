#!/usr/bin/env python3
"""Tests for reuse_first.py - search before build."""
import os, sys, unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import reuse_first as rf

PROMPT = "implement stripe webhook signature verification handler endpoint"


def task(**kw):
    base = {"id": "t1", "slug": "stripe-hook", "prompt": PROMPT, "project_id": "p1"}
    base.update(kw)
    return base


KNOWLEDGE_ROW = {"project": "tomorrow", "title": "Stripe webhook verification",
                 "body": "implement stripe webhook signature verification handler endpoint",
                 "keywords": ["stripe", "webhook"], "tags": ["payments"]}

CAP_ROW = {"slug": "stripe-webhook-verify", "name": "Stripe webhook verify",
           "domain": "payments", "status": "experimental",
           "summary": "implement stripe webhook signature verification handler endpoint"}


def _select_returning(knowledge=None, capabilities=None):
    def sel(table, params=None):
        if table == "knowledge":
            return knowledge or []
        if table == "capabilities":
            return capabilities or []
        return []
    return sel


class TestFindReusableKeyword(unittest.TestCase):
    """No embed provider -> keyword Jaccard path."""

    def test_knowledge_row_matches(self):
        with patch.object(rf, "knowledge_embed", None), patch.object(rf, "db") as mdb:
            mdb.select.side_effect = _select_returning(knowledge=[KNOWLEDGE_ROW])
            hit = rf.find_reusable(task())
        self.assertIsNotNone(hit)
        self.assertEqual(hit["project"], "tomorrow")
        self.assertEqual(hit["source_slug"], "stripe-webhook-verification")  # slugified title
        self.assertGreaterEqual(hit["similarity"], rf.KEYWORD_THRESHOLD)
        self.assertIn("stripe", hit["summary"])

    def test_capability_row_matches_with_real_slug(self):
        with patch.object(rf, "knowledge_embed", None), patch.object(rf, "db") as mdb:
            mdb.select.side_effect = _select_returning(capabilities=[CAP_ROW])
            hit = rf.find_reusable(task())
        self.assertEqual(hit["source_slug"], "stripe-webhook-verify")
        self.assertEqual(hit["project"], "payments")        # domain fallback

    def test_retired_capability_skipped(self):
        with patch.object(rf, "knowledge_embed", None), patch.object(rf, "db") as mdb:
            mdb.select.side_effect = _select_returning(
                capabilities=[{**CAP_ROW, "status": "retired"}])
            self.assertIsNone(rf.find_reusable(task()))

    def test_no_overlap_returns_none(self):
        with patch.object(rf, "knowledge_embed", None), patch.object(rf, "db") as mdb:
            mdb.select.side_effect = _select_returning(
                knowledge=[{"project": "x", "title": "Weather widget",
                            "body": "daily forecast rendering component"}])
            self.assertIsNone(rf.find_reusable(task()))

    def test_empty_prompt_returns_none(self):
        with patch.object(rf, "knowledge_embed", None), patch.object(rf, "db") as mdb:
            self.assertIsNone(rf.find_reusable(task(prompt="")))
            mdb.select.assert_not_called()


class TestFindReusableVector(unittest.TestCase):
    def test_vector_hit_above_threshold(self):
        ke = MagicMock()
        ke.embed.return_value = [0.1, 0.2, 0.3]
        with patch.object(rf, "knowledge_embed", ke), patch.object(rf, "db") as mdb:
            mdb.rpc.return_value = [{"project": "tomorrow", "title": "Stripe webhook",
                                     "body": "verify signatures", "similarity": 0.91}]
            hit = rf.find_reusable(task())
        self.assertEqual(hit["similarity"], 0.91)
        self.assertEqual(hit["project"], "tomorrow")
        mdb.rpc.assert_called_once()
        mdb.select.assert_not_called()                      # vector hit short-circuits

    def test_vector_below_threshold_falls_back_to_keyword(self):
        ke = MagicMock()
        ke.embed.return_value = [0.1]
        with patch.object(rf, "knowledge_embed", ke), patch.object(rf, "db") as mdb:
            mdb.rpc.return_value = [{"title": "x", "similarity": 0.5}]
            mdb.select.side_effect = _select_returning(knowledge=[KNOWLEDGE_ROW])
            hit = rf.find_reusable(task())
        self.assertEqual(hit["source_slug"], "stripe-webhook-verification")

    def test_embed_absent_degrades_to_keyword(self):
        ke = MagicMock()
        ke.embed.return_value = None                        # no provider/key configured
        with patch.object(rf, "knowledge_embed", ke), patch.object(rf, "db") as mdb:
            mdb.select.side_effect = _select_returning(knowledge=[KNOWLEDGE_ROW])
            hit = rf.find_reusable(task())
        self.assertIsNotNone(hit)
        mdb.rpc.assert_not_called()


class TestRewritePrompt(unittest.TestCase):
    def test_prepends_directive_source_summary(self):
        hit = {"source_slug": "s", "project": "p", "similarity": 0.9, "summary": "sum"}
        out = rf.rewrite_prompt(task(), hit)
        self.assertTrue(out.startswith(
            "REUSE FIRST: a solved implementation exists — adapt it instead of rebuilding.\n"))
        self.assertIn("SOURCE: p/s\n", out)
        self.assertIn("SUMMARY: sum\n\n", out)
        self.assertTrue(out.endswith(PROMPT))


class TestPreClaimHook(unittest.TestCase):
    def test_hit_rewrites_db_and_returns_updated_task(self):
        with patch.object(rf, "knowledge_embed", None), patch.object(rf, "db") as mdb:
            mdb.select.side_effect = _select_returning(knowledge=[KNOWLEDGE_ROW])
            out = rf.pre_claim_hook(task())
        table, match, patch_ = mdb.update.call_args.args
        self.assertEqual((table, match), ("tasks", {"id": "t1"}))
        self.assertIn("REUSE FIRST", patch_["prompt"])
        self.assertIn("[reuse-first: matched stripe-webhook-verification]", patch_["prompt"])
        self.assertEqual(out["prompt"], patch_["prompt"])
        note = mdb.insert.call_args.args
        self.assertEqual(note[0], "notifications")
        self.assertEqual(note[1]["channel"], "digest")

    def test_no_hit_passes_through(self):
        t = task()
        with patch.object(rf, "knowledge_embed", None), patch.object(rf, "db") as mdb:
            mdb.select.side_effect = _select_returning()
            out = rf.pre_claim_hook(t)
        self.assertEqual(out, t)
        mdb.update.assert_not_called()

    def test_idempotent_when_already_marked(self):
        t = task(prompt=PROMPT + "\n\n[reuse-first: matched foo]")
        with patch.object(rf, "knowledge_embed", None), patch.object(rf, "db") as mdb:
            out = rf.pre_claim_hook(t)
        self.assertEqual(out, t)
        mdb.select.assert_not_called()

    def test_never_raises_on_db_update_failure(self):
        with patch.object(rf, "knowledge_embed", None), patch.object(rf, "db") as mdb:
            mdb.select.side_effect = _select_returning(knowledge=[KNOWLEDGE_ROW])
            mdb.update.side_effect = RuntimeError("db down")
            t = task()
            out = rf.pre_claim_hook(t)
        self.assertEqual(out, t)                            # unchanged on error

    def test_never_raises_on_select_failure(self):
        with patch.object(rf, "knowledge_embed", None), patch.object(rf, "db") as mdb:
            mdb.select.side_effect = RuntimeError("boom")
            t = task()
            self.assertEqual(rf.pre_claim_hook(t), t)

    def test_non_dict_task_passes_through(self):
        self.assertIsNone(rf.pre_claim_hook(None))


if __name__ == "__main__":
    unittest.main()

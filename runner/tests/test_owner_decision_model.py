#!/usr/bin/env python3
"""Tests for owner_decision_model.py - precedent-based owner decisions."""
import os, sys, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import owner_decision_model as odm


def card(**kw):
    base = {"id": "c1", "kind": "legal", "title": "Legal question", "why": "",
            "detail": "", "prebrief": "", "status": "pending", "project": "x",
            "radar_tag": None, "legal_risk_level": None, "decision_text": None,
            "decision_type": None, "brief_json": None}
    base.update(kw)
    return base


def decided(cat_text, decision_text, decision_type="approve", status="approved"):
    return card(status=status, why=cat_text, decision_text=decision_text,
                decision_type=decision_type)


class TestClassify(unittest.TestCase):
    def test_categories(self):
        self.assertEqual(odm.classify(card(why="third parties rely on signed attestation")),
                         "attestation-reliance")
        self.assertEqual(odm.classify(card(why="page may be general solicitation")),
                         "solicitation")
        self.assertEqual(odm.classify(card(why="giving investment advice on securities")),
                         "financial-advice")
        self.assertEqual(odm.classify(card(why="cross-app data use needs consent")),
                         "data-use-crossapp")
        self.assertEqual(odm.classify(card(why="raise the pricing tier fees")),
                         "pricing")
        self.assertEqual(odm.classify(card(why="marketing testimonial on landing page")),
                         "marketing-claims")
        self.assertEqual(odm.classify(card(why="rename an internal module")), "other")

    def test_decision_text_counts_toward_classification(self):
        c = card(title="q", why="", decision_text="CHOSEN: defer the solicitation fraction")
        self.assertEqual(odm.classify(c), "solicitation")


class TestPattern(unittest.TestCase):
    def test_chosen_prefix_wins(self):
        r = card(decision_text="CHOSEN: Proceed with guardrails and flags",
                 decision_type="deny")
        self.assertEqual(odm._pattern(r), "Proceed with")  # first 12 chars

    def test_falls_back_to_decision_type(self):
        r = card(decision_text="ok fine", decision_type="approve")
        self.assertEqual(odm._pattern(r), "approve")


class TestHistory(unittest.TestCase):
    def test_history_filters_by_category(self):
        rows = [decided("general solicitation risk", "CHOSEN: guardrails"),
                decided("pricing change", "CHOSEN: approve pricing"),
                decided("solicit investors page", "CHOSEN: guardrails")]
        with patch.object(odm, "db") as mdb:
            mdb.select.return_value = rows
            hist = odm.history("solicitation")
        self.assertEqual(len(hist), 2)
        # PostgREST filters requested: decided-only, non-null decision_text
        params = mdb.select.call_args.args[1]
        self.assertEqual(params["status"], "in.(approved,denied)")
        self.assertEqual(params["decision_text"], "not.is.null")


class TestDraft(unittest.TestCase):
    def _hist(self, n_same, n_other=0):
        rows = [decided("general solicitation", "CHOSEN: Proceed with guardrails")
                for _ in range(n_same)]
        rows += [decided("general solicitation", "CHOSEN: Defer the fraction",
                         decision_type="deny", status="denied")
                 for _ in range(n_other)]
        return rows

    def test_auto_apply_on_consistent_precedent(self):
        with patch.object(odm, "db") as mdb:
            mdb.select.return_value = self._hist(5)
            d = odm.draft(card(why="new general solicitation question"))
        self.assertTrue(d["auto_apply"])
        self.assertEqual(d["decision_type"], "approve")
        self.assertIn("auto-applied from owner precedent (5 consistent prior decisions)",
                      d["decision_text"])
        self.assertEqual(d["confidence"], 1.0)

    def test_no_auto_below_consistency(self):
        with patch.object(odm, "db") as mdb:
            mdb.select.return_value = self._hist(3, 2)      # 60% < 80%
            d = odm.draft(card(why="new general solicitation question"))
        self.assertFalse(d["auto_apply"])
        self.assertIn("5 precedents", d["rationale"])

    def test_no_auto_below_min_precedents(self):
        with patch.object(odm, "db") as mdb:
            mdb.select.return_value = self._hist(4)         # 4 < 5
            d = odm.draft(card(why="new general solicitation question"))
        self.assertFalse(d["auto_apply"])

    def test_suggested_option_index_by_label_overlap(self):
        bj = {"options": [{"label": "Proceed fully after counsel"},
                          {"label": "Proceed with guardrails"},
                          {"label": "Defer everything"}],
              "recommended_index": 0}
        with patch.object(odm, "db") as mdb:
            mdb.select.return_value = self._hist(3, 2)
            d = odm.draft(card(why="new general solicitation question", brief_json=bj))
        self.assertEqual(d["suggested_option_index"], 1)


class TestApply(unittest.TestCase):
    def test_auto_path_updates_and_notifies(self):
        hist = [decided("general solicitation", "CHOSEN: Proceed with guardrails")
                for _ in range(6)]
        with patch.object(odm, "db") as mdb:
            mdb.select.return_value = hist
            odm.apply(card(id="z9", why="general solicitation question"))
        table, match, patch_ = mdb.update.call_args.args
        self.assertEqual((table, match), ("approvals", {"id": "z9"}))
        self.assertEqual(patch_["status"], "approved")
        self.assertEqual(patch_["decided_by"], odm.MODEL_MARK)
        note = mdb.insert.call_args.args[1]
        self.assertEqual(mdb.insert.call_args.args[0], "notifications")
        self.assertEqual(note["channel"], "digest")
        self.assertEqual(note["approval_id"], "z9")

    def test_suggest_path_merges_brief_json_leaves_pending(self):
        bj = {"question": "q", "options": [{"label": "a"}, {"label": "b"}],
              "recommended_index": 0}
        with patch.object(odm, "db") as mdb:
            mdb.select.return_value = []                    # no history at all
            odm.apply(card(id="z1", why="general solicitation question", brief_json=bj))
        table, match, patch_ = mdb.update.call_args.args
        self.assertEqual((table, match), ("approvals", {"id": "z1"}))
        self.assertNotIn("status", patch_)                  # stays pending
        merged = patch_["brief_json"]
        self.assertEqual(merged["question"], "q")           # read-modify-write kept keys
        self.assertIn("suggested_option_index", merged)
        self.assertIn("model_rationale", merged)
        self.assertEqual(merged["recommended_index"], merged["suggested_option_index"])
        mdb.insert.assert_not_called()


class TestSweep(unittest.TestCase):
    def test_sweep_only_touches_legal_gated(self):
        pending = [card(id="p1", kind="material", why="routine build"),   # not gated
                   card(id="p2", radar_tag="regulatory",
                        why="general solicitation for securities offering forces registration")]  # gated
        hist = [decided("general solicitation", "CHOSEN: Proceed with guardrails")
                for _ in range(6)]

        def sel(table, params=None):
            if (params or {}).get("status") == "eq.pending":
                return pending
            return hist

        with patch.object(odm, "db") as mdb:
            mdb.select.side_effect = sel
            auto, suggested = odm.sweep()
        self.assertEqual((auto, suggested), (1, 0))
        self.assertEqual(mdb.update.call_count, 1)
        self.assertEqual(mdb.update.call_args.args[1], {"id": "p2"})

    def test_sweep_survives_row_errors(self):
        pending = [card(id="p2", radar_tag="regulatory", why="solicitation")]

        def sel(table, params=None):
            if (params or {}).get("status") == "eq.pending":
                return pending
            raise RuntimeError("db down")

        with patch.object(odm, "db") as mdb:
            mdb.select.side_effect = sel
            self.assertEqual(odm.sweep(), (0, 0))           # skipped, not raised


if __name__ == "__main__":
    unittest.main()

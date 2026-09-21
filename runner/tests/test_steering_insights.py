"""steering_insights: verdict cards distilled into steering, gated on relevance."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import steering_insights as S  # noqa: E402

CARD = {
    "id": "c1111111-0000", "docket_id": "d1", "vertical": "gaming", "confidence": 0.8, "unsettled": True,
    "question": "Must a lottery courier treat automated payout holds under 9 NYCRR 5014.14 as regulated payment actions?",
    "verdict": "REVISED TO ABSORB THE ATTACK. Holding 1 stands under Art. 13(2)(f): a courier holding payouts acts "
               "under 7 U.S.C. § 6 as a regulated payer. A sandbox waiver is permitted for pilots.",
    "conditions": "Decision rule: act on the stricter reading. Concretely — (a) never represent compliance with §9005 "
                  "and log the written request; (b) within five business days obtain and file the official text of "
                  "5014.9; (c) no primary text was opened in this record at all whatsoever.",
    "flips_if": "(1) Official text of 5014.14 does not place validation on the courier. (2) A NYGC advisory opinion "
                "says otherwise about payout holds.",
    "assumptions": '["A1. SCHUFA applies to payout scoring. Not opened; confidence 0.45.", '
                   '"A2. The statute is current. Opened; confidence 0.9."]',
}


class SentenceTest(unittest.TestCase):
    def test_legal_abbreviations_do_not_end_sentences(self):
        s = S._sentences("Attack absorbed on Art. 13(2)(f) and Art. 35; verdict re-framed. Duties arise under 7 U.S.C. § 6 "
                         "and 31 C.F.R. 1010. Next point.")
        self.assertEqual(len(s), 3)
        self.assertTrue(s[1].endswith("31 C.F.R. 1010."))


class DistillTest(unittest.TestCase):
    def setUp(self):
        self.rows = S.distill(CARD, {"lens": "innovation_pathway", "risk_band": "high", "origin": "matrix"})
        self.by_kind = {}
        for r in self.rows:
            self.by_kind.setdefault(r["kind"], []).append(r)

    def test_actions_are_imperatives_only(self):
        actions = [r["insight"] for r in self.by_kind["action"]]
        self.assertEqual(len(actions), 2)
        self.assertTrue(any(a.startswith("Never represent compliance") for a in actions))
        self.assertFalse(any("no primary text" in a.lower() for a in actions), "a limit of the record is not an action")

    def test_tripwires_gap_assumption_and_pathway(self):
        self.assertEqual(len(self.by_kind["tripwire"]), 2)
        self.assertTrue(all(r["insight"].startswith("Watch for:") for r in self.by_kind["tripwire"]))
        self.assertEqual(len(self.by_kind["assumption"]), 1, "only low-confidence assumptions surface")
        gap = self.by_kind["gap"][0]["insight"]
        self.assertTrue(gap.startswith("Unsettled law — Holding 1 stands under Art. 13(2)(f)"), gap)
        self.assertNotIn("REVISED", gap, "procedure is not substance")
        self.assertIn("sandbox waiver", self.by_kind["innovation"][0]["insight"])

    def test_rows_carry_coordinates_terms_signature_and_stay_internal(self):
        for r in self.rows:
            self.assertEqual((r["lens"], r["risk_band"], r["vertical"]), ("innovation_pathway", "high", "gaming"))
            self.assertEqual(r["publication_state"], "internal")
            self.assertTrue(r["signature"] and r["terms"])
        self.assertEqual(len({r["signature"] for r in self.rows}), len(self.rows))

    def test_legacy_guess_needs_upside_language_to_become_an_opportunity(self):
        risky = dict(CARD, verdict="The activity is prohibited and exposes the operator to penalties under the act.")
        rows = S.distill(risky, {"lens": "opportunity", "risk_band": "upside", "origin": "legacy"})
        self.assertFalse([r for r in rows if r["kind"] in ("opportunity", "innovation")])

    def test_empty_card_yields_nothing(self):
        self.assertEqual(S.distill({}), [])
        self.assertEqual(S.distill(None), [])


class BriefTest(unittest.TestCase):
    def setUp(self):
        S.reset_cache()
        self.rows = [dict(r, id="i%d" % i, created_at="2026-09-21T00:00:00+00:00") for i, r in
                     enumerate(S.distill(CARD, {"lens": "innovation_pathway", "risk_band": "high", "origin": "matrix"}))]

    def test_relevant_task_gets_insights_unrelated_task_gets_nothing(self):
        with patch.object(S.db, "select", lambda t, p: list(self.rows)):
            text = S.brief("any", "Add an automated payout hold to the lottery courier withdrawal flow")
            S.reset_cache()
            none = S.brief("any", "Fix the CSS padding on the marketing footer")
        self.assertTrue(text.startswith(S.HEADER))
        self.assertIn("not legal advice", text)
        self.assertIn("(card c1111111)", text)
        self.assertLessEqual(len(text), S.BRIEF_MAX_CHARS + 2)
        self.assertLessEqual(text.count("\n- "), S.BRIEF_MAX_LINES)
        self.assertEqual(none, "")

    def test_at_most_two_lines_per_card_and_kill_switch(self):
        with patch.object(S.db, "select", lambda t, p: list(self.rows)):
            rows = S.relevant("lottery courier payout holds regulated payment actions under 5014")
        self.assertLessEqual(len(rows), 2)
        with patch.object(S, "ENABLED", False):
            self.assertEqual(S.brief("p", "lottery courier payout"), "")

    def test_failures_are_silent(self):
        def boom(t, p):
            raise RuntimeError("down")
        with patch.object(S.db, "select", boom):
            self.assertEqual(S.brief("p", "lottery courier payout hold"), "")
            self.assertEqual(S.authority_lines("row level security"), [])
            self.assertEqual(S.owner_lines(), [])

    def test_owner_lines_lead_with_innovation(self):
        import time
        from datetime import datetime, timezone
        now = datetime.fromtimestamp(time.time(), timezone.utc).isoformat()
        rows = [dict(r, created_at=now) for r in self.rows]
        with patch.object(S.db, "select", lambda t, p: rows):
            lines = S.owner_lines()
        self.assertTrue(lines[0].startswith("Expert insights (7d):"))
        self.assertTrue(any(l.startswith("Regulatory gaps by risk:") for l in lines))
        self.assertTrue(any(l.startswith("Innovation pathway [gaming]:") for l in lines))


class SyncTest(unittest.TestCase):
    def test_only_undistilled_cards_are_written_once(self):
        posted = []

        def select_all(table, params=None, order=None, **k):
            return [{"card_id": "old"}]

        def select(table, params):
            if table == "verdict_cards":
                return [dict(CARD, id="old"), dict(CARD, id="new")]
            return [{"id": "d1", "lens": "red_team", "risk_band": "high", "origin": "matrix"}]

        def req(method, path, body=None, headers=None, params=None):
            posted.extend(body)
            return []
        with patch.object(S.db, "select_all", select_all), patch.object(S.db, "select", select), \
                patch.object(S.db, "_req", req):
            out = S.sync()
        self.assertEqual(out["cards_distilled"], 1)
        self.assertTrue(posted and all(r["card_id"] == "new" for r in posted))
        self.assertEqual(out["insights"], len(posted))


if __name__ == "__main__":
    unittest.main()

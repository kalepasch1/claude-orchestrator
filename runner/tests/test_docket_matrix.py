"""docket_matrix: the docket as lens x risk band x vertical."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import docket_matrix as M  # noqa: E402

GOOD = ("Does the FinCEN money transmitter definition under 31 CFR 1010.100(ff) reach a gaming wallet that "
        "holds customer fiat balances between wagers and pays winnings to a third-party bank account?")


def row(i, vertical, q, status="pending", priority="high", created="2026-09-01T00:00:00+00:00", **kw):
    return dict({"id": "d%d" % i, "vertical": vertical, "question": q, "status": status, "priority": priority,
                 "created_at": created}, **kw)


class ClassifyTest(unittest.TestCase):
    def test_lens_and_band_from_keywords(self):
        self.assertEqual(M.classify("Could a regulatory sandbox or no-action letter let us pilot this?"),
                         ("innovation_pathway", "upside"))
        self.assertEqual(M.classify("Which aviation safety management system control could we borrow?")[0],
                         "cross_industry_analog")
        self.assertEqual(M.classify("Is this unlicensed money transmission a felony with license revocation?")[1],
                         "existential")
        self.assertEqual(M.classify("plain question about nothing in particular"), ("regulatory_gap", "medium"))

    def test_licensing_word_alone_is_not_an_opportunity(self):
        self.assertNotEqual(M.classify("What licensing disclosure must the operator file?")[0], "opportunity")

    def test_stored_tags_win_over_classification(self):
        self.assertEqual(M.coords({"question": "felony?", "lens": "red_team", "risk_band": "low"}), ("red_team", "low"))
        self.assertEqual(M.coords({"question": "sandbox pilot", "lens": "bogus", "risk_band": None})[0], "innovation_pathway")


class AdmissionTest(unittest.TestCase):
    def test_good_question_is_admitted(self):
        self.assertEqual(M.grade_question(GOOD, []), (True, ""))

    def test_rejections(self):
        cases = {
            "What about gambling?": "too short",
            GOOD.rstrip("?") + ".": "not a question",
            "Does the [Company Name] wallet fall under the FinCEN money transmitter definition in 31 CFR 1010.100 when it pays winnings to customers?": "placeholder",
            "Here are 5 questions about whether the FinCEN rule in 31 CFR 1010 reaches a gaming wallet holding customer balances?": "boilerplate",
            "Would a wallet holding customer balances between wagers and paying winnings onward to third parties need anything special done?": "no authority",
        }
        for q, why in cases.items():
            ok, reason = M.grade_question(q, [])
            self.assertFalse(ok, q)
            self.assertIn(why.split()[0], reason)

    def test_near_duplicate_is_refused(self):
        ok, reason = M.grade_question(GOOD, [M.content_words(GOOD.replace("third-party", "external"))])
        self.assertFalse(ok)
        self.assertIn("duplicate", reason)


class CoverageAndCellsTest(unittest.TestCase):
    def test_emptiest_cells_with_guaranteed_innovation_share(self):
        rows = [row(i, "gaming", "What enforcement penalty applies under the state gaming act?") for i in range(50)]
        with patch.object(M, "verticals", lambda: ["gaming", "data"]):
            cells = M.next_cells(10, rows, now=0)
        self.assertEqual(len(cells), 10)
        self.assertGreaterEqual(sum(1 for c in cells if c[1] in M.INNOVATION_LENSES), 4)
        self.assertNotIn(("gaming", "enforcement_trend", "high"), cells, "the crowded cell is not asked for again")

    def test_report_counts(self):
        rows = [row(1, "gaming", "sandbox pilot under the gaming commission rules?"),
                row(2, "data", "felony unlicensed activity under the act?", priority="medium")]
        with patch.object(M, "_docket", lambda *a, **k: rows), patch.object(M, "verticals", lambda: ["gaming", "data"]):
            r = M.report()
        self.assertEqual(r["questions"], 2)
        self.assertEqual(r["innovation_share"], 0.5)
        self.assertEqual(r["high_priority_share"], 0.5)


class PriorityTest(unittest.TestCase):
    def test_high_is_refused_once_it_stops_ordering_anything(self):
        crowded = [{"priority": "high"}] * 8 + [{"priority": "medium"}] * 2
        self.assertEqual(M.calibrated_priority("high", crowded), "medium")
        self.assertEqual(M.calibrated_priority("existential", crowded), "high", "existential always earns it")
        calm = [{"priority": "high"}] * 2 + [{"priority": "medium"}] * 8
        self.assertEqual(M.calibrated_priority("high", calm), "high")
        self.assertEqual(M.calibrated_priority("upside", calm), "medium")
        self.assertEqual(M.calibrated_priority("low", calm), "low")


class PickTest(unittest.TestCase):
    def test_fair_share_and_value_rank_replace_alphabetical_priority(self):
        rows = [row(i, "gaming", "What disclosure policy applies under the gaming act?",
                    created="2026-08-%02dT00:00:00+00:00" % (i + 1)) for i in range(20)]
        rows += [row(100, "data", "Is row-level security without policies a violation exposing us to class action liability?",
                     priority="medium", created="2026-09-13T00:00:00+00:00"),
                 row(101, "gaming", "Is this unlicensed gambling a felony leading to license revocation?",
                     priority="low", created="2026-09-20T00:00:00+00:00"),
                 row(200, "gaming", "answered already under the act?", status="answered")]
        picked = M.pick(4, rows)
        self.assertEqual(picked[0]["id"], "d100", "the never-served vertical goes first")
        self.assertEqual(picked[1]["id"], "d101", "existential beats twenty older 'high' disclosure questions")
        self.assertNotIn("d200", [p["id"] for p in picked])
        self.assertEqual(len(picked), 4)

    def test_pick_handles_empty(self):
        self.assertEqual(M.pick(5, []), [])


class BackfillTest(unittest.TestCase):
    def test_untagged_rows_are_patched_in_groups_not_one_by_one(self):
        rows = [row(i, "gaming", "Could a regulatory sandbox pilot apply under the gaming act?") for i in range(150)]
        rows.append(row(999, "data", "tagged already?", lens="red_team", risk_band="low"))
        calls = []
        with patch.object(M, "_docket", lambda *a, **k: rows), \
                patch.object(M.db, "_req", lambda method, path, body=None, headers=None, params=None: calls.append((method, body, params))):
            n = M.backfill_tags()
        self.assertEqual(n, 150)
        self.assertEqual(len(calls), 2, "150 rows in one group -> two PATCHes of <=100 ids")
        self.assertEqual(calls[0][1], {"lens": "innovation_pathway", "risk_band": "upside", "origin": "legacy"})
        self.assertNotIn("d999", calls[0][2]["id"] + calls[1][2]["id"])


class GenerateTest(unittest.TestCase):
    def test_only_graded_candidates_reach_the_docket(self):
        inserted = []
        reply = '["%s", "Here are some thoughts?", "%s"]' % (GOOD, GOOD)
        with patch.object(M, "_docket", lambda *a, **k: []), \
                patch.object(M, "verticals", lambda: ["gaming"]), \
                patch.object(M, "insert_question", lambda v, q, l, b, o, priority=None, rows=None: inserted.append((v, l, b, o)) or [{}]):
            out = M.generate(1, per_cell=3, complete=lambda p: reply)
        self.assertEqual(out["admitted"], 1, "the duplicate and the boilerplate are refused")
        self.assertEqual(inserted[0][3], "matrix")
        self.assertEqual(sum(out["rejected"].values()), 2)

    def test_model_failure_is_counted_not_raised(self):
        def boom(p):
            raise RuntimeError("no model")
        with patch.object(M, "_docket", lambda *a, **k: []), patch.object(M, "verticals", lambda: ["gaming"]):
            out = M.generate(2, complete=boom)
        self.assertEqual(out["admitted"], 0)
        self.assertEqual(out["rejected"].get("model unavailable"), 2)

    def test_silent_empty_reply_is_counted(self):
        with patch.object(M, "_docket", lambda *a, **k: []), patch.object(M, "verticals", lambda: ["gaming"]):
            out = M.generate(2, complete=lambda p: "")
        self.assertEqual(out["rejected"].get("model returned nothing"), 2)

    def test_insert_falls_back_when_matrix_columns_are_absent(self):
        calls = []

        def insert(table, row_, **k):
            calls.append(dict(row_))
            if "lens" in row_:
                raise RuntimeError("column legal_docket.lens does not exist")
            return [row_]
        with patch.object(M.db, "insert", insert):
            self.assertIsNotNone(M.insert_question("data", GOOD, "red_team", "high", "matrix", priority="medium"))
        self.assertNotIn("lens", calls[-1])

    def test_analog_prompt_names_donor_industries(self):
        p = M._prompt(("data", "cross_industry_analog", "medium"), 3)
        self.assertIn("donor industry", p)
        self.assertIn("JSON array", p)


if __name__ == "__main__":
    unittest.main()

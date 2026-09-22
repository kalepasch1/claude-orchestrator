"""output_grader: every model output graded, every call named."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import output_grader as G  # noqa: E402


class GradeTest(unittest.TestCase):
    def setUp(self):
        G._recent.clear()

    def test_good_prose_is_ok(self):
        g = G.grade("The operator must file the report within five days under the act. It must also retain records.")
        self.assertEqual((g["verdict"], g["score"]), ("ok", 1.0))

    def test_the_failures_the_audit_found(self):
        self.assertEqual(G.grade("")["verdict"], "empty")
        self.assertEqual(G.grade("   \n")["score"], 0.0)
        self.assertEqual(G.grade("**MEMORANDUM**\nTo: [GC's Name]\nThe position is sound.")["verdict"], "placeholder")
        g = G.grade('Here are 5 questions:\n```\n[{"question": "x"', prompt="Return ONLY a JSON array")
        self.assertEqual(g["verdict"], "malformed_json")
        self.assertIn("boilerplate", g["flags"])
        self.assertEqual(G.grade("I'm sorry, but I cannot help with that request.")["verdict"], "refusal")
        self.assertEqual(G.grade("word " * 120)["verdict"], "truncated")
        rep = "\n".join(["The same sentence is repeated here again and again."] * 8)
        self.assertIn("repetition", G.grade(rep)["flags"])

    def test_valid_json_in_a_fence_is_ok_and_short_ratings_are_fine(self):
        self.assertEqual(G.grade('```json\n{"verdict":"go","score":9,"basis":"x"}\n```', prompt="return JSON")["verdict"], "ok")
        self.assertEqual(G.grade("YES", task_class="rating", prompt="x" * 3000)["verdict"], "ok")
        self.assertEqual(G.grade("YES", task_class="unknown", prompt="x" * 3000)["verdict"], "too_short")

    def test_rubber_stamp_is_the_same_structured_verdict_over_and_over(self):
        out = '{"verdict":"conditional","score":7,"conviction":8,"basis":"%s"}'
        verdicts = [G.grade(out % i, operation="completion:committees", prompt="json")["verdict"] for i in range(6)]
        self.assertEqual(verdicts[:4], ["ok"] * 4)
        self.assertEqual(verdicts[-1], "rubber_stamp")
        self.assertEqual(G.grade(out % "z", operation="completion:other", prompt="json")["verdict"], "ok", "per caller")

    def test_grader_never_raises(self):
        self.assertIn(G.grade(12345)["verdict"], ("ok", "too_short"))
        self.assertEqual(G.grade(None)["verdict"], "empty")


class CallerTest(unittest.TestCase):
    def test_names_the_asking_module(self):
        self.assertEqual(G.caller(), "test_output_grader")


class TelemetryTest(unittest.TestCase):
    """model_gateway writes the grade and the caller on every app_operations row."""

    def _record(self, **kw):
        import model_gateway
        rows = []
        fake_db = type("D", (), {"insert": staticmethod(lambda t, r: rows.append((t, r)))})
        with patch.dict(sys.modules, {"db": fake_db}):
            model_gateway._record_operation("proj", kw.pop("operation", "completion"), kw.pop("task_class", "unknown"),
                                            "local", "llama3.1:8b", "prompt", 0, kw.pop("latency", 1200), **kw)
        return rows[0][1]

    def test_fresh_output_is_graded_and_named(self):
        row = self._record(text="To: [GC's Name] the position holds.", caller_name="committees")
        self.assertEqual(row["operation"], "completion:committees")
        self.assertEqual(row["verdict"], "placeholder")
        self.assertEqual(row["quality_score"], 0.5)

    def test_cache_replay_error_and_named_operation(self):
        self.assertEqual(self._record(text="A fine sentence that ends properly.", cached=True, latency=0)["verdict"], "cached:ok")
        err = self._record(ok=False, error="boom", caller_name="x")
        self.assertEqual((err["verdict"], err["quality_score"], err["ok"]), ("error", 0, False))
        named = self._record(operation="docket_matrix.generate", text="Fine sentence here.", caller_name="docket_matrix")
        self.assertEqual(named["operation"], "docket_matrix.generate", "an explicit operation is never overwritten")

    def test_no_text_means_no_grade_but_the_row_still_lands(self):
        row = self._record()
        self.assertNotIn("quality_score", row)
        self.assertEqual(row["ok"], True)


class AuditTest(unittest.TestCase):
    def test_audit_separates_fresh_work_from_cache_echo(self):
        rows = [{"operation": "completion:committees", "latency_ms": 0, "quality_score": 1.0, "verdict": "cached:ok"},
                {"operation": "completion:committees", "latency_ms": 900, "quality_score": 0.5, "verdict": "placeholder"},
                {"operation": "completion", "latency_ms": 0, "quality_score": None, "verdict": None}]
        fake_db = type("D", (), {"select": staticmethod(lambda t, p: rows)})
        with patch.dict(sys.modules, {"db": fake_db}):
            a = G.audit()
        self.assertEqual((a["rows"], a["graded"], a["cache_replays"]), (3, 2, 2))
        c = a["callers"]["completion:committees"]
        self.assertEqual((c["calls"], c["fresh"], c["mean_quality"]), (2, 1, 0.75))
        self.assertEqual(c["verdicts"], {"ok": 1, "placeholder": 1})


if __name__ == "__main__":
    unittest.main()

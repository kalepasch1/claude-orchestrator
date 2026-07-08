import os
import sys
import json
import types
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import prompt_assembler as pa


def _tmp_log_path():
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    os.remove(path)
    return path


def _blank_module(**attrs):
    m = types.SimpleNamespace(**attrs)
    return m


class CapTest(unittest.TestCase):
    def test_short_prompt_unchanged(self):
        self.assertEqual(pa._cap("short"), "short")

    def test_long_prompt_truncated_with_marker(self):
        text = "x" * (pa.MAX_AGENT_PROMPT_CHARS * 2)
        capped = pa._cap(text)
        self.assertLess(len(capped), len(text))
        self.assertIn("ORCHESTRATOR COMPACTION", capped)

    def test_capped_prompt_keeps_head_and_tail(self):
        text = "HEAD_MARKER" + "x" * (pa.MAX_AGENT_PROMPT_CHARS * 2) + "TAIL_MARKER"
        capped = pa._cap(text)
        self.assertIn("HEAD_MARKER", capped)
        self.assertIn("TAIL_MARKER", capped)

    def test_empty_prompt(self):
        self.assertEqual(pa._cap(""), "")

    def test_none_prompt(self):
        self.assertEqual(pa._cap(None), "")


class ProjectBriefTest(unittest.TestCase):
    def test_no_project_returns_empty(self):
        self.assertEqual(pa._project_brief("", "/tmp"), "")

    def test_no_repo_returns_empty(self):
        self.assertEqual(pa._project_brief("proj", ""), "")

    def test_missing_claude_md_and_no_db_returns_empty(self):
        repo = tempfile.mkdtemp()
        with patch.dict(sys.modules, {"db": _blank_module(select=lambda *a, **kw: [])}):
            brief = pa._project_brief("proj", repo)
        self.assertEqual(brief, "")

    def test_extracts_bullets_from_claude_md(self):
        repo = tempfile.mkdtemp()
        with open(os.path.join(repo, "CLAUDE.md"), "w") as f:
            f.write("# header\n- Use fail-soft error handling\n- Prefix keys with ORCH_\n")
        with patch.dict(sys.modules, {"db": _blank_module(select=lambda *a, **kw: [])}):
            brief = pa._project_brief("proj", repo)
        self.assertIn("fail-soft", brief)
        self.assertIn("ORCH_", brief)

    def test_includes_outcomes_signal(self):
        repo = tempfile.mkdtemp()
        open(os.path.join(repo, "CLAUDE.md"), "w").close()
        rows = [{"tests_passed": True, "integrated": True} for _ in range(5)] + \
               [{"tests_passed": False, "integrated": False} for _ in range(5)]
        with patch.dict(sys.modules, {"db": _blank_module(select=lambda *a, **kw: rows)}):
            brief = pa._project_brief("proj", repo)
        self.assertIn("5/10 merged", brief)

    def test_db_failure_is_fail_soft(self):
        repo = tempfile.mkdtemp()
        with open(os.path.join(repo, "CLAUDE.md"), "w") as f:
            f.write("- a bullet\n- another bullet\n")
        broken_db = _blank_module(select=lambda *a, **kw: (_ for _ in ()).throw(OSError("down")))
        with patch.dict(sys.modules, {"db": broken_db}):
            brief = pa._project_brief("proj", repo)
        self.assertIn("bullet", brief)  # file-read layer still worked

    def test_brief_capped_at_max_bytes(self):
        repo = tempfile.mkdtemp()
        with open(os.path.join(repo, "CLAUDE.md"), "w") as f:
            for i in range(500):
                f.write(f"- convention number {i} with some extra padding text here\n")
        with patch.dict(sys.modules, {"db": _blank_module(select=lambda *a, **kw: [])}):
            brief = pa._project_brief("proj", repo)
        self.assertLessEqual(len(brief.encode("utf-8")), pa.BRIEF_MAX_BYTES)

    def test_only_recent_bullets_included_not_whole_file(self):
        repo = tempfile.mkdtemp()
        with open(os.path.join(repo, "CLAUDE.md"), "w") as f:
            f.write("- OLDEST_BULLET_MARKER\n")
            for i in range(20):
                f.write(f"- filler {i}\n")
            f.write("- NEWEST_BULLET_MARKER\n")
        with patch.dict(sys.modules, {"db": _blank_module(select=lambda *a, **kw: [])}):
            brief = pa._project_brief("proj", repo)
        self.assertIn("NEWEST_BULLET_MARKER", brief)
        self.assertNotIn("OLDEST_BULLET_MARKER", brief)


class DistilledBodyTest(unittest.TestCase):
    def test_no_match_returns_original_body(self):
        pd = _blank_module(find_distilled=lambda *a, **kw: None)
        with patch.dict(sys.modules, {"prompt_distillation": pd}):
            body, used = pa._distilled_body("original", {"prompt": "original"}, "proj")
        self.assertEqual(body, "original")
        self.assertFalse(used)

    def test_match_applies_distilled_template(self):
        pd = _blank_module(find_distilled=lambda *a, **kw: {"template": "T"},
                           apply_distilled=lambda orig, d: "DISTILLED:" + d["template"])
        with patch.dict(sys.modules, {"prompt_distillation": pd}):
            body, used = pa._distilled_body("original", {"prompt": "original"}, "proj")
        self.assertEqual(body, "DISTILLED:T")
        self.assertTrue(used)

    def test_import_error_falls_back_to_original(self):
        with patch.dict(sys.modules, {"prompt_distillation": None}):
            body, used = pa._distilled_body("original", {"prompt": "original"}, "proj")
        self.assertEqual(body, "original")
        self.assertFalse(used)

    def test_lookup_exception_falls_back_to_original(self):
        pd = _blank_module(find_distilled=lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("x")))
        with patch.dict(sys.modules, {"prompt_distillation": pd}):
            body, used = pa._distilled_body("original", {"prompt": "original"}, "proj")
        self.assertEqual(body, "original")
        self.assertFalse(used)


class AssembleTest(unittest.TestCase):
    def setUp(self):
        self._orig_log = pa.ASSEMBLY_LOG
        pa.ASSEMBLY_LOG = _tmp_log_path()
        # stub every optional dependency to a harmless no-op so assemble() is deterministic
        self._patches = [
            patch.dict(sys.modules, {
                "prompt_distillation": _blank_module(find_distilled=lambda *a, **kw: None),
                "caching": _blank_module(load_prefix=lambda repo: ""),
                "db": _blank_module(select=lambda *a, **kw: []),
                "context_retrieval": _blank_module(focus_note=lambda repo, body: ""),
                "blast_radius": _blank_module(note_for_task=lambda repo, body: ""),
                "capability": _blank_module(reuse_note=lambda body, project=None: ""),
                "pipeline_contract": _blank_module(wrap_prompt=lambda body, **kw: body),
                "knowledge_embed": _blank_module(inject=lambda p: p),
                "regression": _blank_module(inject=lambda p: p),
                "feedback": _blank_module(INSTRUCTION=""),
            })
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        try:
            os.remove(pa.ASSEMBLY_LOG)
        except OSError:
            pass
        pa.ASSEMBLY_LOG = self._orig_log

    def test_minimal_assembly_returns_prompt_and_token_estimate(self):
        result = pa.assemble("do the thing", project="proj", repo="/tmp")
        self.assertIn("do the thing", result["prompt"])
        self.assertIn("REUSE_FIRST".lower(), result["prompt"].lower().replace(" ", "_")) \
            if False else None  # REUSE_FIRST text itself is checked below
        self.assertIn("Reuse before you draft", result["prompt"])
        self.assertGreater(result["token_estimate"], 0)
        self.assertEqual(result["layers"], [])  # every optional layer stubbed to contribute nothing

    def test_caching_prefix_layer_recorded(self):
        with patch.dict(sys.modules, {"caching": _blank_module(load_prefix=lambda repo: "PREFIX\n")}):
            result = pa.assemble("task", project="proj", repo="/tmp")
        self.assertIn("cached_prefix", result["layers"])
        self.assertIn("PREFIX", result["prompt"])

    def test_pipeline_contract_layer_recorded_when_it_changes_body(self):
        wrap = lambda body, **kw: "WRAPPED:" + body
        with patch.dict(sys.modules, {"pipeline_contract": _blank_module(wrap_prompt=wrap)}):
            result = pa.assemble("task", project="proj", repo="/tmp")
        self.assertIn("pipeline_contract", result["layers"])
        self.assertIn("WRAPPED:task", result["prompt"])

    def test_knowledge_inject_layer_recorded(self):
        inj = lambda p: "KNOWLEDGE:" + p
        with patch.dict(sys.modules, {"knowledge_embed": _blank_module(inject=inj)}):
            result = pa.assemble("task", project="proj", repo="/tmp")
        self.assertIn("knowledge_inject", result["layers"])

    def test_regression_inject_layer_recorded(self):
        inj = lambda p: "REG:" + p
        with patch.dict(sys.modules, {"regression": _blank_module(inject=inj)}):
            result = pa.assemble("task", project="proj", repo="/tmp")
        self.assertIn("regression_inject", result["layers"])

    def test_missing_optional_module_does_not_raise(self):
        with patch.dict(sys.modules, {"blast_radius": None, "context_retrieval": None,
                                       "capability": None, "pipeline_contract": None,
                                       "knowledge_embed": None, "regression": None,
                                       "feedback": None}):
            result = pa.assemble("task", project="proj", repo="/tmp")
        self.assertIn("task", result["prompt"])

    def test_use_retrieval_false_skips_focus_and_blast(self):
        focus = _blank_module(focus_note=lambda repo, body: "FOCUS_MARKER")
        blast = _blank_module(note_for_task=lambda repo, body: "BLAST_MARKER")
        with patch.dict(sys.modules, {"context_retrieval": focus, "blast_radius": blast}):
            result = pa.assemble("task", project="proj", repo="/tmp", use_retrieval=False)
        self.assertNotIn("FOCUS_MARKER", result["prompt"])
        self.assertNotIn("BLAST_MARKER", result["prompt"])

    def test_final_prompt_is_capped(self):
        huge = _blank_module(load_prefix=lambda repo: "x" * (pa.MAX_AGENT_PROMPT_CHARS * 3))
        with patch.dict(sys.modules, {"caching": huge}):
            result = pa.assemble("task", project="proj", repo="/tmp")
        self.assertLessEqual(len(result["prompt"]), pa.MAX_AGENT_PROMPT_CHARS + 500)

    def test_assembly_is_logged(self):
        pa.assemble("task", project="proj", repo="/tmp", slug="s1")
        with open(pa.ASSEMBLY_LOG) as f:
            row = json.loads(f.readline())
        self.assertEqual(row["project"], "proj")
        self.assertEqual(row["slug"], "s1")
        self.assertIn("token_estimate", row)

    def test_distilled_template_layer_recorded_and_used(self):
        pd = _blank_module(find_distilled=lambda *a, **kw: {"template": "T"},
                           apply_distilled=lambda orig, d: "DISTILLED_BODY")
        with patch.dict(sys.modules, {"prompt_distillation": pd}):
            result = pa.assemble("original task", project="proj", repo="/tmp")
        self.assertIn("distilled_template", result["layers"])
        self.assertIn("DISTILLED_BODY", result["prompt"])
        self.assertNotIn("original task", result["prompt"])

    def test_task_dict_passed_through_to_distillation_lookup(self):
        seen = {}

        def fake_find(task, current_project=None):
            seen["task"] = task
            seen["project"] = current_project
            return None

        pd = _blank_module(find_distilled=fake_find)
        with patch.dict(sys.modules, {"prompt_distillation": pd}):
            pa.assemble("task body", project="proj", repo="/tmp",
                       task={"prompt": "task body", "kind": "build", "id": "abc"})
        self.assertEqual(seen["task"]["id"], "abc")
        self.assertEqual(seen["project"], "proj")


class StatsInvalidateTest(unittest.TestCase):
    def setUp(self):
        self._orig_log = pa.ASSEMBLY_LOG
        pa.ASSEMBLY_LOG = _tmp_log_path()

    def tearDown(self):
        try:
            os.remove(pa.ASSEMBLY_LOG)
        except OSError:
            pass
        pa.ASSEMBLY_LOG = self._orig_log

    def test_stats_empty_log(self):
        s = pa.stats()
        self.assertEqual(s["count"], 0)
        self.assertEqual(s["avg_tokens"], 0)

    def test_stats_computes_average(self):
        pa._log_assembly("p", "s1", 100, [])
        pa._log_assembly("p", "s2", 200, [])
        s = pa.stats()
        self.assertEqual(s["count"], 2)
        self.assertEqual(s["avg_tokens"], 150)

    def test_stats_respects_limit(self):
        for i in range(10):
            pa._log_assembly("p", f"s{i}", i, [])
        s = pa.stats(limit=3)
        self.assertEqual(s["count"], 3)

    def test_corrupt_log_does_not_crash(self):
        with open(pa.ASSEMBLY_LOG, "w") as f:
            f.write("not json\n")
        s = pa.stats()
        self.assertIn("error", s)

    def test_invalidate_removes_log(self):
        pa._log_assembly("p", "s1", 100, [])
        pa.invalidate()
        self.assertEqual(pa.stats()["count"], 0)

    def test_invalidate_on_missing_log_does_not_raise(self):
        pa.invalidate()  # log doesn't exist yet


if __name__ == "__main__":
    unittest.main()

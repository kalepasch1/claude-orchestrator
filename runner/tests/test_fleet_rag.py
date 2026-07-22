"""
test_fleet_rag.py - fleet_rag chunking, budget enforcement, dedupe, fail-soft.
All hermetic — no live DB.
"""
import os, sys, json, unittest
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fleet_rag


class TestChunking(unittest.TestCase):

    def test_short_text_single_chunk(self):
        chunks = fleet_rag._chunk_text("short text", max_chars=100)
        self.assertEqual(len(chunks), 1)

    def test_long_text_multiple_chunks(self):
        text = "\n".join([f"line {i} with some content" for i in range(100)])
        chunks = fleet_rag._chunk_text(text, max_chars=200)
        self.assertTrue(len(chunks) > 1)
        # All content preserved
        joined = "\n".join(chunks)
        self.assertEqual(joined, text)

    def test_empty_text(self):
        chunks = fleet_rag._chunk_text("")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], "")


class TestKeywordScore(unittest.TestCase):

    def test_full_match(self):
        score = fleet_rag._keyword_score(["auth", "bypass"], "auth bypass vulnerability")
        self.assertEqual(score, 1.0)

    def test_partial_match(self):
        score = fleet_rag._keyword_score(["auth", "bypass", "sql"], "auth bypass found")
        self.assertAlmostEqual(score, 2.0 / 3.0, places=2)

    def test_no_match(self):
        score = fleet_rag._keyword_score(["xyz", "abc"], "nothing relevant here")
        self.assertEqual(score, 0.0)

    def test_empty_query(self):
        score = fleet_rag._keyword_score([], "some text")
        self.assertEqual(score, 0.0)


class TestRetrieve(unittest.TestCase):

    @patch("fleet_rag.db")
    def test_returns_relevant_chunks(self, mock_db):
        mock_db.select.return_value = [
            {"id": "c1", "content": "auth bypass in login flow", "source_type": "postmortem",
             "source_id": "fix-auth", "content_hash": "h1"},
            {"id": "c2", "content": "updated readme formatting", "source_type": "report",
             "source_id": "docs", "content_hash": "h2"},
        ]
        results = fleet_rag.retrieve("fix auth bypass", top_k=1)
        self.assertEqual(len(results), 1)
        self.assertIn("auth", results[0]["content"])

    @patch("fleet_rag.db")
    def test_dedupe_against_patterns(self, mock_db):
        mock_db.select.return_value = [
            {"id": "c1", "content": "existing pattern content", "source_type": "pattern",
             "source_id": "p1", "content_hash": "already_injected"},
            {"id": "c2", "content": "new relevant chunk", "source_type": "postmortem",
             "source_id": "pm1", "content_hash": "new_hash"},
        ]
        results = fleet_rag.retrieve("some query", existing_patterns={"already_injected"})
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content"], "new relevant chunk")

    @patch("fleet_rag.db")
    def test_budget_enforcement(self, mock_db):
        # Create chunks that exceed budget
        mock_db.select.return_value = [
            {"id": f"c{i}", "content": f"chunk {i} " * 200, "source_type": "report",
             "source_id": f"r{i}", "content_hash": f"h{i}"}
            for i in range(10)
        ]
        results = fleet_rag.retrieve("chunk content", budget=500)
        total_chars = sum(len(r["content"]) for r in results)
        self.assertLessEqual(total_chars, 500)

    @patch("fleet_rag.db")
    def test_failsoft_on_db_error(self, mock_db):
        mock_db.select.side_effect = Exception("db down")
        results = fleet_rag.retrieve("any query")
        self.assertEqual(results, [])


class TestBuildFleetMemory(unittest.TestCase):

    @patch("fleet_rag.db")
    def test_returns_section(self, mock_db):
        mock_db.select.return_value = [
            {"id": "c1", "content": "relevant info", "source_type": "claude_md",
             "source_id": "CLAUDE.md", "content_hash": "h1"},
        ]
        section = fleet_rag.build_fleet_memory_section("some task query")
        self.assertIn("FLEET MEMORY", section)
        self.assertIn("relevant info", section)

    @patch("fleet_rag.db")
    def test_returns_empty_on_no_results(self, mock_db):
        mock_db.select.return_value = []
        section = fleet_rag.build_fleet_memory_section("obscure query")
        self.assertEqual(section, "")

    @patch("fleet_rag.db")
    def test_failsoft_returns_empty(self, mock_db):
        mock_db.select.side_effect = Exception("db down")
        section = fleet_rag.build_fleet_memory_section("query")
        self.assertEqual(section, "")


class TestIndexDocument(unittest.TestCase):

    @patch("fleet_rag.db")
    def test_indexes_chunks(self, mock_db):
        content = "line one\nline two\nline three"
        count = fleet_rag.index_document("report", "test.md", content)
        self.assertEqual(count, 1)  # short text = 1 chunk
        self.assertTrue(mock_db.upsert.called)

    @patch("fleet_rag.db")
    def test_failsoft_on_upsert_error(self, mock_db):
        mock_db.upsert.side_effect = Exception("db error")
        count = fleet_rag.index_document("report", "test.md", "content")
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()

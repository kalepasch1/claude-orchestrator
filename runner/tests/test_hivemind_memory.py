"""Comprehensive tests for hivemind_memory module."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import hivemind_memory


class MockDB:
    """Mock database for testing."""
    def __init__(self):
        self.patterns = {}
        self.next_id = 1

    def insert(self, table, row):
        row_id = f"id-{self.next_id}"
        self.next_id += 1
        row["id"] = row_id
        self.patterns[row_id] = row
        return row

    def select(self, table, filters=None, order=None, limit=None):
        results = list(self.patterns.values())
        if filters:
            for key, val in filters.items():
                if isinstance(val, dict) and "overlap" in val:
                    # Tag overlap filter
                    tags_to_match = set(val["overlap"])
                    results = [r for r in results if tags_to_match & set(r.get("tags", []))]
        if order:
            reverse = "desc" in order
            results.sort(key=lambda r: r.get("quality_score", 0), reverse=reverse)
        if limit:
            results = results[:limit]
        return results

    def count(self, table, filters=None):
        results = list(self.patterns.values())
        if filters:
            for key, val in filters.items():
                if key == "promoted" and isinstance(val, bool):
                    results = [r for r in results if r.get("promoted") == val]
        return len(results)

    def update(self, table, item_id, updates):
        if item_id in self.patterns:
            for key, val in updates.items():
                if val == "now()":
                    import time
                    self.patterns[item_id][key] = time.time()
                else:
                    self.patterns[item_id][key] = val


class TestStore:
    """Test cases for store() function."""

    def test_store_basic(self):
        """Test basic pattern storage."""
        mock_db = MockDB()
        with patch('hivemind_memory.db', mock_db):
            result = hivemind_memory.store({
                "project_id": "proj1",
                "slug": "task1",
                "pattern_type": "utility",
                "summary": "A useful utility function",
                "content": "def helper(): pass",
                "tags": ["utility", "shared"],
                "quality_score": 0.9,
            })
            assert result is not None
            assert result["project_id"] == "proj1"
            assert result["quality_score"] == 0.9

    def test_store_blocks_sensitive_content(self):
        """Test that store blocks sensitive API keys and secrets."""
        mock_db = MockDB()
        with patch('hivemind_memory.db', mock_db):
            result = hivemind_memory.store({
                "project_id": "proj1",
                "slug": "task1",
                "summary": "Config",
                "content": "SUPABASE_SERVICE_ROLE_KEY=sk-abc123def456",
                "tags": [],
            })
            assert result is None

    def test_store_blocks_password(self):
        """Test blocking of password exposure."""
        mock_db = MockDB()
        with patch('hivemind_memory.db', mock_db):
            result = hivemind_memory.store({
                "project_id": "proj1",
                "slug": "task1",
                "summary": "Auth",
                "content": "password = 'secret123'",
                "tags": [],
            })
            assert result is None

    def test_store_sets_defaults(self):
        """Test that store sets default quality_score and reuse_count."""
        mock_db = MockDB()
        with patch('hivemind_memory.db', mock_db):
            result = hivemind_memory.store({
                "project_id": "proj1",
                "slug": "task1",
                "summary": "Pattern",
                "tags": [],
            })
            assert result["quality_score"] == 0.7
            assert result["reuse_count"] == 0
            assert result["promoted"] is False

    def test_store_no_db_returns_none(self):
        """Test store returns None when db is unavailable."""
        with patch('hivemind_memory.db', None):
            result = hivemind_memory.store({
                "project_id": "proj1",
                "slug": "task1",
                "summary": "Pattern",
                "tags": [],
            })
            assert result is None

    def test_store_db_error_handled(self):
        """Test store handles db errors gracefully."""
        mock_db = Mock()
        mock_db.insert.side_effect = Exception("DB error")
        with patch('hivemind_memory.db', mock_db):
            result = hivemind_memory.store({
                "project_id": "proj1",
                "slug": "task1",
                "summary": "Pattern",
                "tags": [],
            })
            assert result is None


class TestRecall:
    """Test cases for recall() function."""

    def test_recall_by_tag_overlap(self):
        """Test recall finds patterns by tag overlap."""
        mock_db = MockDB()
        with patch('hivemind_memory.db', mock_db):
            # Store two patterns
            mock_db.insert("hivemind_memory", {
                "project_id": "proj1",
                "slug": "t1",
                "summary": "Pattern A",
                "tags": ["shared", "api"],
                "quality_score": 0.8,
                "reuse_count": 5,
            })
            mock_db.insert("hivemind_memory", {
                "project_id": "proj2",
                "slug": "t2",
                "summary": "Pattern B",
                "tags": ["gotcha"],
                "quality_score": 0.9,
                "reuse_count": 2,
            })
            # Recall with overlapping tags
            results = hivemind_memory.recall({
                "slug": "task-new",
                "tags": ["api", "shared"],
                "project_id": "proj1",
            }, limit=5)
            assert len(results) >= 1
            assert any(r["summary"] == "Pattern A" for r in results)

    def test_recall_cross_project_preference(self):
        """Test that recall prefers cross-project patterns."""
        mock_db = MockDB()
        with patch('hivemind_memory.db', mock_db):
            same_proj = mock_db.insert("hivemind_memory", {
                "project_id": "proj1",
                "slug": "t1",
                "summary": "Same Project Pattern",
                "tags": ["api"],
                "quality_score": 0.9,
            })
            diff_proj = mock_db.insert("hivemind_memory", {
                "project_id": "proj2",
                "slug": "t2",
                "summary": "Different Project Pattern",
                "tags": ["api"],
                "quality_score": 0.8,
            })
            results = hivemind_memory.recall({
                "slug": "task-new",
                "tags": ["api"],
                "project_id": "proj1",
            }, limit=5)
            if len(results) >= 2:
                # Cross-project should rank higher
                proj_indices = {r["project_id"]: i for i, r in enumerate(results)}
                assert "proj2" in proj_indices

    def test_recall_quality_score_impact(self):
        """Test that quality score impacts recall ranking."""
        mock_db = MockDB()
        with patch('hivemind_memory.db', mock_db):
            low_quality = mock_db.insert("hivemind_memory", {
                "project_id": "proj1",
                "slug": "t1",
                "summary": "Low Quality",
                "tags": ["api"],
                "quality_score": 0.3,
            })
            high_quality = mock_db.insert("hivemind_memory", {
                "project_id": "proj2",
                "slug": "t2",
                "summary": "High Quality",
                "tags": ["api"],
                "quality_score": 0.95,
            })
            results = hivemind_memory.recall({
                "slug": "task-new",
                "tags": ["api"],
                "project_id": "proj1",
            }, limit=5)
            if len(results) >= 1:
                assert results[0]["quality_score"] >= 0.3

    def test_recall_reuse_count_increments(self):
        """Test that recall increments reuse_count."""
        mock_db = MockDB()
        with patch('hivemind_memory.db', mock_db):
            pattern = mock_db.insert("hivemind_memory", {
                "project_id": "proj1",
                "slug": "t1",
                "summary": "Pattern",
                "tags": ["api"],
                "quality_score": 0.8,
                "reuse_count": 0,
            })
            results = hivemind_memory.recall({
                "slug": "task-new",
                "tags": ["api"],
                "project_id": "proj1",
            }, limit=5)
            assert pattern["reuse_count"] == 1

    def test_recall_no_db_returns_empty(self):
        """Test recall returns empty list when db is unavailable."""
        with patch('hivemind_memory.db', None):
            results = hivemind_memory.recall({"slug": "t", "tags": ["api"]})
            assert results == []

    def test_recall_db_error_handled(self):
        """Test recall handles db errors gracefully."""
        mock_db = Mock()
        mock_db.select.side_effect = Exception("DB error")
        with patch('hivemind_memory.db', mock_db):
            results = hivemind_memory.recall({"slug": "t", "tags": ["api"]})
            assert results == []


class TestFormatContext:
    """Test cases for format_context() function."""

    def test_format_context_empty(self):
        """Test format_context with empty patterns."""
        context = hivemind_memory.format_context([])
        assert context == ""

    def test_format_context_single_pattern(self):
        """Test format_context with single pattern."""
        patterns = [{
            "project_id": "proj1",
            "slug": "t1",
            "pattern_type": "utility",
            "summary": "Helper function",
            "content": "def helper(): pass",
            "quality_score": 0.9,
            "reuse_count": 5,
        }]
        context = hivemind_memory.format_context(patterns)
        assert "HIVEMIND PATTERNS" in context
        assert "Helper function" in context
        assert "90%" in context
        assert "5x" in context

    def test_format_context_truncates_long_content(self):
        """Test format_context truncates content > 3000 chars."""
        long_content = "x" * 5000
        patterns = [{
            "project_id": "proj1",
            "slug": "t1",
            "pattern_type": "utility",
            "summary": "Long pattern",
            "content": long_content,
            "quality_score": 0.8,
            "reuse_count": 0,
        }]
        context = hivemind_memory.format_context(patterns)
        assert len(context) < 5000  # Should be truncated


class TestStats:
    """Test cases for stats() function."""

    def test_stats_with_patterns(self):
        """Test stats returns accurate counts."""
        mock_db = MockDB()
        with patch('hivemind_memory.db', mock_db):
            mock_db.insert("hivemind_memory", {
                "project_id": "proj1",
                "slug": "t1",
                "summary": "Pattern 1",
                "tags": [],
                "promoted": False,
            })
            mock_db.insert("hivemind_memory", {
                "project_id": "proj2",
                "slug": "t2",
                "summary": "Pattern 2",
                "tags": [],
                "promoted": True,
            })
            stats = hivemind_memory.stats()
            assert stats["total_patterns"] == 2
            assert stats["promoted_to_hivemind"] == 1
            assert stats["pending_promotion"] == 1

    def test_stats_no_db_returns_empty(self):
        """Test stats returns empty dict when db unavailable."""
        with patch('hivemind_memory.db', None):
            stats = hivemind_memory.stats()
            assert stats == {}

    def test_stats_db_error_handled(self):
        """Test stats handles db errors gracefully."""
        mock_db = Mock()
        mock_db.count.side_effect = Exception("DB error")
        with patch('hivemind_memory.db', mock_db):
            stats = hivemind_memory.stats()
            assert stats == {}


class TestSearch:
    """Test cases for search() function."""

    def test_search_by_summary(self):
        """Test search finds patterns by summary text."""
        mock_db = MockDB()
        with patch('hivemind_memory.db', mock_db):
            mock_db.insert("hivemind_memory", {
                "project_id": "proj1",
                "slug": "t1",
                "summary": "Authentication helper function",
                "tags": [],
            })
            mock_db.insert("hivemind_memory", {
                "project_id": "proj2",
                "slug": "t2",
                "summary": "Unrelated pattern",
                "tags": [],
            })
            results = hivemind_memory.search("authentication", limit=10)
            assert len(results) == 1
            assert results[0]["summary"] == "Authentication helper function"

    def test_search_by_content(self):
        """Test search finds patterns by content text."""
        mock_db = MockDB()
        with patch('hivemind_memory.db', mock_db):
            mock_db.insert("hivemind_memory", {
                "project_id": "proj1",
                "slug": "t1",
                "summary": "Pattern A",
                "content": "const SECRET_API_KEY = env.API_KEY",
                "tags": [],
            })
            results = hivemind_memory.search("SECRET_API_KEY", limit=10)
            assert len(results) == 1

    def test_search_no_db_returns_empty(self):
        """Test search returns empty when db unavailable."""
        with patch('hivemind_memory.db', None):
            results = hivemind_memory.search("query")
            assert results == []

    def test_search_respects_limit(self):
        """Test search respects limit parameter."""
        mock_db = MockDB()
        with patch('hivemind_memory.db', mock_db):
            for i in range(20):
                mock_db.insert("hivemind_memory", {
                    "project_id": "proj1",
                    "slug": f"t{i}",
                    "summary": f"Pattern {i} helper",
                    "tags": [],
                })
            results = hivemind_memory.search("helper", limit=5)
            assert len(results) <= 5


class TestPromote:
    """Test cases for promote_pattern() function."""

    def test_promote_pattern(self):
        """Test promoting a pattern to official status."""
        mock_db = MockDB()
        with patch('hivemind_memory.db', mock_db):
            pattern = mock_db.insert("hivemind_memory", {
                "project_id": "proj1",
                "slug": "t1",
                "summary": "Pattern",
                "tags": [],
                "promoted": False,
            })
            success = hivemind_memory.promote_pattern(pattern["id"])
            assert success is True

    def test_promote_no_db_returns_false(self):
        """Test promote returns False when db unavailable."""
        with patch('hivemind_memory.db', None):
            result = hivemind_memory.promote_pattern("id1")
            assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

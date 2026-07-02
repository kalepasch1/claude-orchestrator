"""
test_portfolio_digest.py - tests for portfolio_strategy_digest.

Tests cover:
- Reading proposals from DB
- Clustering into themes (happy path + failures)
- Impact score validation (1-100 range)
- Approval card generation
- Edge cases (empty proposals, min threshold, malformed responses)
"""
import os, sys, json, unittest
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPortfolioDigestReadProposals(unittest.TestCase):

    def test_read_pending_proposals_returns_list(self):
        """read_pending_proposals must query the approvals table for pending proposals."""
        import portfolio_strategy_digest as digest
        import db

        fake_rows = [
            {"id": "p1", "title": "Reduce latency", "project": "api",
             "kind": "proposal", "status": "pending", "value": "10% faster"},
            {"id": "p2", "title": "Add caching", "project": "web",
             "kind": "proposal", "status": "pending", "value": "cache miss reduction"},
        ]
        orig_select = db.select
        def mock_select(table, params=None):
            if table == "approvals" and params and params.get("kind") == "eq.proposal":
                return fake_rows
            return []
        db.select = mock_select
        try:
            result = digest.read_pending_proposals()
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["title"], "Reduce latency")
        finally:
            db.select = orig_select

    def test_read_pending_proposals_empty(self):
        """read_pending_proposals must return empty list when no proposals."""
        import portfolio_strategy_digest as digest
        import db

        orig_select = db.select
        db.select = lambda table, params=None: None
        try:
            result = digest.read_pending_proposals()
            self.assertEqual(result, [])
        finally:
            db.select = orig_select


class TestPortfolioDigestClustering(unittest.TestCase):

    def test_cluster_and_impact_valid_response(self):
        """cluster_and_impact must parse Claude's JSON response correctly."""
        import portfolio_strategy_digest as digest
        import claude_cli

        fake_proposals = [
            {"title": "Prop 1", "project": "api", "value": "value1"},
            {"title": "Prop 2", "project": "web", "value": "value2"},
            {"title": "Prop 3", "project": "api", "value": "value3"},
        ]

        fake_response = json.dumps([
            {
                "theme": "Performance",
                "titles": ["Prop 1", "Prop 3"],
                "impact": 75,
                "rationale": "Both improve API speed"
            },
            {
                "theme": "UX",
                "titles": ["Prop 2"],
                "impact": 50,
                "rationale": "Improves user experience"
            }
        ])

        orig_run = claude_cli.run
        claude_cli.run = lambda prompt, model, **kw: {
            "returncode": 0,
            "text": fake_response
        }
        try:
            themes = digest.cluster_and_impact(fake_proposals)
            self.assertEqual(len(themes), 2)
            self.assertEqual(themes[0]["theme"], "Performance")
            self.assertEqual(themes[0]["impact"], 75)
            self.assertIn("Prop 1", themes[0]["titles"])
        finally:
            claude_cli.run = orig_run

    def test_cluster_and_impact_clamps_invalid_scores(self):
        """cluster_and_impact must clamp impact scores outside 1-100 to 50."""
        import portfolio_strategy_digest as digest
        import claude_cli

        fake_proposals = [{"title": "P1", "project": "x", "value": "v"}]

        fake_response = json.dumps([
            {
                "theme": "Bad Score",
                "titles": ["P1"],
                "impact": 999,  # Invalid
                "rationale": "test"
            }
        ])

        orig_run = claude_cli.run
        claude_cli.run = lambda prompt, model, **kw: {
            "returncode": 0,
            "text": fake_response
        }
        try:
            themes = digest.cluster_and_impact(fake_proposals)
            self.assertEqual(themes[0]["impact"], 50, "invalid score must be clamped to 50")
        finally:
            claude_cli.run = orig_run

    def test_cluster_and_impact_limits_to_3_themes(self):
        """cluster_and_impact must return at most 3 themes."""
        import portfolio_strategy_digest as digest
        import claude_cli

        fake_proposals = [{"title": f"P{i}", "project": "x", "value": "v"} for i in range(5)]

        fake_response = json.dumps([
            {"theme": f"Theme {i}", "titles": [f"P{i}"], "impact": 50 + i*10, "rationale": "x"}
            for i in range(5)  # More than 3
        ])

        orig_run = claude_cli.run
        claude_cli.run = lambda prompt, model, **kw: {
            "returncode": 0,
            "text": fake_response
        }
        try:
            themes = digest.cluster_and_impact(fake_proposals)
            self.assertLessEqual(len(themes), 3, "must return at most 3 themes")
        finally:
            claude_cli.run = orig_run

    def test_cluster_and_impact_handles_model_failure(self):
        """cluster_and_impact must return [] when model call fails."""
        import portfolio_strategy_digest as digest
        import claude_cli

        fake_proposals = [{"title": "P1", "project": "x", "value": "v"}]

        orig_run = claude_cli.run
        claude_cli.run = lambda prompt, model, **kw: {
            "returncode": 1,
            "text": "error"
        }
        try:
            themes = digest.cluster_and_impact(fake_proposals)
            self.assertEqual(themes, [])
        finally:
            claude_cli.run = orig_run

    def test_cluster_and_impact_handles_json_parse_error(self):
        """cluster_and_impact must handle malformed JSON gracefully."""
        import portfolio_strategy_digest as digest
        import claude_cli

        fake_proposals = [{"title": "P1", "project": "x", "value": "v"}]

        orig_run = claude_cli.run
        claude_cli.run = lambda prompt, model, **kw: {
            "returncode": 0,
            "text": "not valid json {{{{"
        }
        try:
            themes = digest.cluster_and_impact(fake_proposals)
            self.assertEqual(themes, [], "malformed JSON should return empty list")
        finally:
            claude_cli.run = orig_run

    def test_cluster_and_impact_handles_markdown_code_blocks(self):
        """cluster_and_impact must extract JSON from markdown code blocks."""
        import portfolio_strategy_digest as digest
        import claude_cli

        fake_proposals = [{"title": "P1", "project": "x", "value": "v"}]

        fake_response = """Here's the clustered themes:
```json
[{"theme": "T1", "titles": ["P1"], "impact": 60, "rationale": "x"}]
```
Done!"""

        orig_run = claude_cli.run
        claude_cli.run = lambda prompt, model, **kw: {
            "returncode": 0,
            "text": fake_response
        }
        try:
            themes = digest.cluster_and_impact(fake_proposals)
            self.assertEqual(len(themes), 1)
            self.assertEqual(themes[0]["theme"], "T1")
        finally:
            claude_cli.run = orig_run

    def test_cluster_and_impact_empty_proposals(self):
        """cluster_and_impact must handle empty proposal list."""
        import portfolio_strategy_digest as digest

        themes = digest.cluster_and_impact([])
        self.assertEqual(themes, [])

    def test_cluster_and_impact_skips_incomplete_themes(self):
        """cluster_and_impact must skip themes missing required fields."""
        import portfolio_strategy_digest as digest
        import claude_cli

        fake_proposals = [{"title": "P1", "project": "x", "value": "v"}]

        fake_response = json.dumps([
            {"theme": "Good", "titles": ["P1"], "impact": 60, "rationale": "x"},
            {"theme": "Bad", "titles": ["P1"]},  # Missing impact and rationale
            {"theme": "Good2", "titles": ["P1"], "impact": 70, "rationale": "y"},
        ])

        orig_run = claude_cli.run
        claude_cli.run = lambda prompt, model, **kw: {
            "returncode": 0,
            "text": fake_response
        }
        try:
            themes = digest.cluster_and_impact(fake_proposals)
            # Should skip the incomplete one but still return valid themes (up to 3)
            theme_names = [t["theme"] for t in themes]
            self.assertIn("Good", theme_names)
            self.assertNotIn("Bad", theme_names)
        finally:
            claude_cli.run = orig_run


class TestPortfolioDigestApprovalCard(unittest.TestCase):

    def test_build_approval_card_happy_path(self):
        """build_approval_card must create a well-formed approval dict."""
        import portfolio_strategy_digest as digest

        fake_proposals = [
            {"id": "p1", "title": "Proposal 1"},
            {"id": "p2", "title": "Proposal 2"},
            {"id": "p3", "title": "Proposal 3"},
        ]
        fake_themes = [
            {"theme": "Performance", "titles": ["Proposal 1"], "impact": 75, "rationale": "Speed"},
            {"theme": "UX", "titles": ["Proposal 2", "Proposal 3"], "impact": 60, "rationale": "Experience"},
        ]

        card = digest.build_approval_card(fake_proposals, fake_themes)

        self.assertIsNotNone(card)
        self.assertEqual(card["project"], "ORCHESTRATOR")
        self.assertEqual(card["kind"], "digest")
        self.assertIn("3 proposals", card["title"])
        self.assertIn("2 themes", card["title"])
        self.assertIn("Performance", card["detail"])
        self.assertIn("UX", card["detail"])
        # Average impact should be (75 + 60) / 2 = 67.5
        import re
        impacts = re.findall(r'impact: (\d+)/100', card["detail"])
        self.assertTrue(len(impacts) >= 2)

    def test_build_approval_card_empty_themes(self):
        """build_approval_card must return None for empty themes."""
        import portfolio_strategy_digest as digest

        fake_proposals = [{"id": "p1", "title": "Proposal 1"}]
        card = digest.build_approval_card(fake_proposals, [])

        self.assertIsNone(card)

    def test_build_approval_card_includes_proposal_count(self):
        """build_approval_card title must include the proposal count."""
        import portfolio_strategy_digest as digest

        fake_proposals = [{"id": f"p{i}", "title": f"P{i}"} for i in range(10)]
        fake_themes = [
            {"theme": "T1", "titles": ["P1"], "impact": 50, "rationale": "x"}
        ]

        card = digest.build_approval_card(fake_proposals, fake_themes)

        self.assertIn("10 proposals", card["title"])

    def test_build_approval_card_caps_theme_count_in_title(self):
        """build_approval_card must limit themes to 3 in the title."""
        import portfolio_strategy_digest as digest

        fake_proposals = [{"id": "p1", "title": "P1"}]
        fake_themes = [
            {"theme": f"T{i}", "titles": ["P1"], "impact": 50, "rationale": "x"}
            for i in range(3)
        ]

        card = digest.build_approval_card(fake_proposals, fake_themes)

        self.assertIn("3 themes", card["title"])
        # detail should include all 3
        self.assertIn("T0", card["detail"])


class TestPortfolioDigestRun(unittest.TestCase):

    def test_run_happy_path(self):
        """run must orchestrate reading, clustering, filing approval, and notifying."""
        import portfolio_strategy_digest as digest
        import db
        import notify

        fake_proposals = [
            {"id": "p1", "title": "P1", "project": "a", "value": "v1"},
            {"id": "p2", "title": "P2", "project": "b", "value": "v2"},
            {"id": "p3", "title": "P3", "project": "a", "value": "v3"},
            {"id": "p4", "title": "P4", "project": "c", "value": "v4"},
            {"id": "p5", "title": "P5", "project": "b", "value": "v5"},
        ]

        inserted_approvals = []
        inserted_notifs = []

        orig_select = db.select
        orig_insert = db.insert
        orig_notify = notify.send

        def mock_select(table, params=None):
            if table == "approvals" and params and params.get("kind") == "eq.proposal":
                return fake_proposals
            return []

        db.select = mock_select
        db.insert = lambda table, row, **kw: inserted_approvals.append(row)
        notify.send = lambda msg: inserted_notifs.append(msg)

        with patch("portfolio_strategy_digest.claude_cli.run") as mock_run:
            mock_run.return_value = {
                "returncode": 0,
                "text": json.dumps([{
                    "theme": "T1", "titles": ["P1"], "impact": 70, "rationale": "x"
                }])
            }
            try:
                result = digest.run()
                self.assertEqual(result, 1, "run must return 1 (made 1 approval)")
                self.assertEqual(len(inserted_approvals), 1)
                self.assertEqual(inserted_approvals[0]["kind"], "digest")
                self.assertEqual(len(inserted_notifs), 1)
            finally:
                db.select = orig_select
                db.insert = orig_insert
                notify.send = orig_notify

    def test_run_no_proposals(self):
        """run must return 0 when no proposals pending."""
        import portfolio_strategy_digest as digest
        import db

        orig_select = db.select
        db.select = lambda *a, **kw: []
        try:
            result = digest.run()
            self.assertEqual(result, 0)
        finally:
            db.select = orig_select

    def test_run_below_min_threshold(self):
        """run must return 0 when proposal count below MIN_PROPOSALS."""
        import portfolio_strategy_digest as digest
        import db
        import os

        # Temporarily set MIN_PROPOSALS to 10
        orig_min = os.environ.get("DIGEST_MIN_PROPOSALS")
        os.environ["DIGEST_MIN_PROPOSALS"] = "10"

        fake_proposals = [
            {"id": f"p{i}", "title": f"P{i}", "project": "x", "value": "v"}
            for i in range(5)
        ]

        orig_select = db.select
        db.select = lambda *a, **kw: fake_proposals if kw.get("kind") == "eq.proposal" else []
        try:
            result = digest.run()
            self.assertEqual(result, 0, "run must skip if below MIN_PROPOSALS")
        finally:
            db.select = orig_select
            if orig_min:
                os.environ["DIGEST_MIN_PROPOSALS"] = orig_min
            else:
                os.environ.pop("DIGEST_MIN_PROPOSALS", None)

    def test_run_clustering_failure(self):
        """run must return 0 when clustering produces no themes."""
        import portfolio_strategy_digest as digest
        import db

        fake_proposals = [
            {"id": f"p{i}", "title": f"P{i}", "project": "x", "value": "v"}
            for i in range(5)
        ]

        orig_select = db.select
        db.select = lambda *a, **kw: fake_proposals if kw.get("kind") == "eq.proposal" else []
        try:
            with patch("portfolio_strategy_digest.claude_cli.run") as mock_run:
                mock_run.return_value = {"returncode": 1, "text": "error"}
                result = digest.run()
                self.assertEqual(result, 0, "run must return 0 if clustering fails")
        finally:
            db.select = orig_select

    def test_run_db_insert_failure(self):
        """run must handle DB insert errors gracefully."""
        import portfolio_strategy_digest as digest
        import db

        fake_proposals = [
            {"id": f"p{i}", "title": f"P{i}", "project": "x", "value": "v"}
            for i in range(5)
        ]

        orig_select = db.select
        orig_insert = db.insert

        db.select = lambda *a, **kw: fake_proposals if kw.get("kind") == "eq.proposal" else []
        db.insert = lambda *a, **kw: (_ for _ in ()).throw(Exception("DB error"))

        try:
            with patch("portfolio_strategy_digest.claude_cli.run") as mock_run:
                mock_run.return_value = {
                    "returncode": 0,
                    "text": json.dumps([{
                        "theme": "T1", "titles": ["P1"], "impact": 70, "rationale": "x"
                    }])
                }
                result = digest.run()
                self.assertEqual(result, 0, "run must return 0 on DB error")
        finally:
            db.select = orig_select
            db.insert = orig_insert


class TestPortfolioDigestIntegration(unittest.TestCase):

    def test_end_to_end_proposal_to_approval(self):
        """End-to-end: read proposals → cluster → file approval."""
        import portfolio_strategy_digest as digest
        import db

        # Simulate real proposal data
        fake_proposals = [
            {
                "id": "p1", "title": "Reduce API latency by 20%",
                "project": "api", "value": "Performance improvement",
                "kind": "proposal", "status": "pending"
            },
            {
                "id": "p2", "title": "Add Redis caching layer",
                "project": "api", "value": "Cache hit improvement",
                "kind": "proposal", "status": "pending"
            },
            {
                "id": "p3", "title": "Optimize database queries",
                "project": "db", "value": "Query performance",
                "kind": "proposal", "status": "pending"
            },
            {
                "id": "p4", "title": "Add request batching",
                "project": "api", "value": "Reduce roundtrips",
                "kind": "proposal", "status": "pending"
            },
            {
                "id": "p5", "title": "Implement circuit breaker",
                "project": "infra", "value": "Fault tolerance",
                "kind": "proposal", "status": "pending"
            },
        ]

        fake_clustering = json.dumps([
            {
                "theme": "API Optimization",
                "titles": [
                    "Reduce API latency by 20%",
                    "Add request batching",
                    "Add Redis caching layer"
                ],
                "impact": 85,
                "rationale": "These three proposals collectively reduce latency and improve throughput"
            },
            {
                "theme": "Reliability & Resilience",
                "titles": ["Implement circuit breaker"],
                "impact": 60,
                "rationale": "Improves fault tolerance and system stability"
            }
        ])

        inserted_approvals = []
        orig_select = db.select
        orig_insert = db.insert

        def mock_select(table, params=None):
            if table == "approvals" and params and params.get("kind") == "eq.proposal":
                return fake_proposals
            return []

        db.select = mock_select
        db.insert = lambda table, row, **kw: inserted_approvals.append((table, row))

        try:
            with patch("portfolio_strategy_digest.claude_cli.run") as mock_run:
                mock_run.return_value = {
                    "returncode": 0,
                    "text": fake_clustering
                }
                with patch("portfolio_strategy_digest.notify.send"):
                    result = digest.run()

            self.assertEqual(result, 1)
            self.assertEqual(len(inserted_approvals), 1)

            table, card = inserted_approvals[0]
            self.assertEqual(table, "approvals")
            self.assertIn("5 proposals", card["title"])
            self.assertIn("2 themes", card["title"])
            self.assertIn("API Optimization", card["detail"])
            self.assertIn("85", card["detail"])
            self.assertIn("Reliability", card["detail"])
        finally:
            db.select = orig_select
            db.insert = orig_insert


if __name__ == "__main__":
    unittest.main(verbosity=2)

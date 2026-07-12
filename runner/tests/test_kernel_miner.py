"""
test_kernel_miner.py - kernel_miner clustering, card payload, task generation.
"""
import os, sys, json, unittest
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import kernel_miner


class TestExtractChunks(unittest.TestCase):

    def test_extracts_functions(self):
        content = "\n".join([
            "import os",
            "def foo():",
            "    x = 1",
            "    y = 2",
            "    z = 3",
            "    w = 4",
            "    return x + y + z + w",
            "",
            "def bar():",
            "    a = 10",
            "    b = 20",
            "    c = 30",
            "    d = 40",
            "    return a + b + c + d",
        ])
        chunks = kernel_miner.extract_chunks("test.py", content)
        self.assertTrue(len(chunks) >= 1)
        for c in chunks:
            self.assertIn("file", c)
            self.assertIn("content", c)


    def test_empty_content(self):
        chunks = kernel_miner.extract_chunks("empty.py", "")
        self.assertEqual(chunks, [])


class TestClusterChunks(unittest.TestCase):

    def _make_chunk(self, repo, content="def foo():\n    return 1\n    x=2\n    y=3\n    z=4"):
        return {"file": f"{repo}/utils.py", "repo": repo, "content": content,
                "start": 0, "end": 5}

    def test_clusters_across_repos(self):
        chunks = [self._make_chunk(f"repo{i}") for i in range(4)]
        clusters = kernel_miner.cluster_chunks(chunks)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 4)

    def test_below_threshold_ignored(self):
        chunks = [self._make_chunk(f"repo{i}") for i in range(2)]
        clusters = kernel_miner.cluster_chunks(chunks)
        self.assertEqual(len(clusters), 0)

    def test_different_content_not_clustered(self):
        chunks = [
            self._make_chunk("repo1", "def a():\n    return 1\n    x=1\n    y=1\n    z=1"),
            self._make_chunk("repo2", "def b():\n    return 2\n    x=2\n    y=2\n    z=2"),
            self._make_chunk("repo3", "def c():\n    return 3\n    x=3\n    y=3\n    z=3"),
        ]
        clusters = kernel_miner.cluster_chunks(chunks)
        self.assertEqual(len(clusters), 0)


class TestApprovalCard(unittest.TestCase):

    def test_card_payload(self):
        cluster = [
            {"file": "repo1/utils.py", "repo": "repo1", "content": "def foo(): pass\n" * 5, "start": 0, "end": 5},
            {"file": "repo2/utils.py", "repo": "repo2", "content": "def foo(): pass\n" * 5, "start": 0, "end": 5},
            {"file": "repo3/utils.py", "repo": "repo3", "content": "def foo(): pass\n" * 5, "start": 0, "end": 5},
        ]
        card = kernel_miner.build_approval_card(cluster)
        self.assertEqual(card["kind"], "proposal")
        self.assertIn("kernel-extract-", card["slug"])
        self.assertIn("3 repos", card["title"])
        detail = json.loads(card["detail"])
        self.assertIn("repos", detail)
        self.assertIn("files", detail)
        self.assertIn("sample", detail)


class TestExtractionTasks(unittest.TestCase):

    def test_task_generation(self):
        cluster = [
            {"file": "repo1/utils.py", "repo": "repo1", "content": "def foo(): pass\n" * 5, "start": 0, "end": 5},
            {"file": "repo2/utils.py", "repo": "repo2", "content": "def foo(): pass\n" * 5, "start": 0, "end": 5},
        ]
        tasks = kernel_miner.build_extraction_tasks(cluster, "test-slug")
        self.assertTrue(len(tasks) >= 2)  # 1 create + N adopt
        self.assertEqual(tasks[0]["kind"], "build")
        self.assertTrue(tasks[0]["slug"].startswith("kernel-create-"))
        for t in tasks[1:]:
            self.assertEqual(t["kind"], "mechanical")
            self.assertIn("Proof:", t["prompt"])


class TestRun(unittest.TestCase):

    @patch("kernel_miner.db")
    def test_run_files_cards(self, mock_db):
        content = "def shared_util():\n    x = 1\n    y = 2\n    z = 3\n    w = 4\n    return x + y\n"
        repo_map = {
            f"repo{i}": [{"file": f"repo{i}/utils.py", "content": content}]
            for i in range(4)
        }
        filed = kernel_miner.run(repo_map)
        self.assertTrue(len(filed) >= 1)
        self.assertTrue(mock_db.insert.called)


if __name__ == "__main__":
    unittest.main()

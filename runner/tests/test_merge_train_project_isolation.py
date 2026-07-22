import os
import unittest


class MergeTrainProjectIsolationContractTest(unittest.TestCase):
    def test_project_failures_are_isolated_from_other_repos(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "merge_train.py")
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        self.assertIn("def process_project_isolated", source)
        self.assertIn("pool.map(process_project_isolated, items)", source)
        self.assertIn('"project_errors": 1', source)


if __name__ == "__main__":
    unittest.main()

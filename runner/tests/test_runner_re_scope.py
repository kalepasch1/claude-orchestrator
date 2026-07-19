import ast
import os
import unittest


class RunnerRegexScopeTest(unittest.TestCase):
    def test_run_task_does_not_shadow_module_regex(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "runner.py")
        with open(path) as handle:
            tree = ast.parse(handle.read())
        run_task = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "run_task")
        imported = [alias.name for node in ast.walk(run_task)
                    if isinstance(node, ast.Import) for alias in node.names]
        self.assertNotIn("re", imported)


if __name__ == "__main__":
    unittest.main()

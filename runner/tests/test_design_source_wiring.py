import os
import unittest


RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def source(name):
    with open(os.path.join(RUNNER_DIR, name), encoding="utf-8") as handle:
        return handle.read()


class DesignSourceWiringTest(unittest.TestCase):
    def test_planner_uses_canonical_contract(self):
        self.assertIn("design_sources.contract(repo)", source("planner.py"))

    def test_prompt_assembler_injects_canonical_contract(self):
        assembler = source("prompt_assembler.py")
        self.assertIn("design_sources.contract(repo)", assembler)
        self.assertIn('"design_sources": design["paths"]', assembler)

    def test_result_cache_keys_on_design_fingerprint(self):
        cache = source("result_cache.py")
        self.assertIn("design_fingerprint", cache)
        self.assertIn("_norm(prompt)}|{design_fingerprint}", cache)

    def test_standard_completion_runs_design_gate_before_integration(self):
        runner = source("runner.py")
        gate = runner.index("design_sources.completion_check(")
        integrate = runner.index("result = integrate(", gate)
        self.assertLess(gate, integrate)

    def test_api_swarm_assembles_and_checks_design_contract(self):
        dispatch = source("parallel_dispatch.py")
        self.assertIn("design_sources.contract(cwd)", dispatch)
        self.assertIn("design_sources.completion_check(", dispatch)
        self.assertLess(
            dispatch.index("design_sources.completion_check("),
            dispatch.index('"state": "DONE"', dispatch.index("design_sources.completion_check(")),
        )

    def test_cowork_executor_assembles_and_checks_design_contract(self):
        cowork = source("cowork_executor.py")
        self.assertIn("design_sources.contract(repo)", cowork)
        self.assertIn("design_sources.completion_check(", cowork)


if __name__ == "__main__":
    unittest.main()

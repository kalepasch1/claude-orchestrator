import os
import re
import unittest

RUNNER_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner.py")


class RunnerUsesPromptAssemblerTest(unittest.TestCase):
    """runner.py used to hand-concatenate prompt layers inline in run_task() — prompt_assembler.py
    is now the single composition point (see its module docstring). These are source-level
    regression guards (not behavioral tests — prompt_assembler.assemble() itself has 34 behavioral
    tests in test_prompt_assembler.py) so a future edit can't silently reintroduce a second,
    diverging hand-rolled concatenation at this call site."""

    def setUp(self):
        self.src = open(RUNNER_PY, encoding="utf-8").read()

    def test_imports_prompt_assembler(self):
        self.assertIn("\nimport prompt_assembler\n", self.src)

    def test_run_task_calls_assemble(self):
        run_task_start = self.src.index("def run_task(")
        # next top-level `def ` after run_task marks the end of its body
        next_def = self.src.index("\ndef ", run_task_start + 1)
        body = self.src[run_task_start:next_def]
        self.assertIn("prompt_assembler.assemble(", body)

    def test_run_task_no_longer_hand_concatenates_layers(self):
        run_task_start = self.src.index("def run_task(")
        next_def = self.src.index("\ndef ", run_task_start + 1)
        body = self.src[run_task_start:next_def]
        # the old pattern this replaced
        self.assertNotIn('prompt = prefix + focus + blast + reuse', body)

    def test_assemble_call_passes_task_dict_for_distillation_matching(self):
        run_task_start = self.src.index("def run_task(")
        next_def = self.src.index("\ndef ", run_task_start + 1)
        body = self.src[run_task_start:next_def]
        call_start = body.index("prompt_assembler.assemble(")
        window = body[call_start:call_start + 400]
        self.assertIn("task=t", window)

    def test_assemble_call_forwards_material_flag(self):
        run_task_start = self.src.index("def run_task(")
        next_def = self.src.index("\ndef ", run_task_start + 1)
        body = self.src[run_task_start:next_def]
        call_start = body.index("prompt_assembler.assemble(")
        call_end = body.index("\n", call_start)
        # material flag spans a couple lines — widen the window
        window = body[call_start:call_start + 400]
        self.assertIn("material=", window)


if __name__ == "__main__":
    unittest.main()

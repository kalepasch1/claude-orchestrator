"""Two defects that let memory_guard fire fifteen times and fix nothing.

FOUND BY READING .runtime/medic.jsonl, after a claim in commit d5dd1105 that the guard
"never ran once" turned out to be false. It ran 15 times between 2026-09-06 and 09-08:

    09-07T05:35  unloaded-model  nomic-embed-text:latest (370.0GB) at free=20% (warn)
    09-07T05:38  unloaded-model  nomic-embed-text:latest (370.0GB) at free=18% (warn)
    09-08T09:42  unloaded-model  codestral:22b (16.0GB)            at free=18% (warn)
    09-08T16:46  unloaded-model  qwen2.5-coder:32b (23.0GB)        at free=20% (warn)
    09-08T16:51  unloaded-model  qwen2.5-coder:32b (23.0GB)        at free=23% (warn)
    09-08T16:54  unloaded-model  qwen2.5-coder:32b (23.0GB)        at free=19% (warn)

Every single row is `unloaded-model`. Not one is `durable-lower-lanes`. Fifteen
interventions, zero durable fixes, on a machine that sat at 44 GB of swap throughout.

DEFECT 1 -- the size column. `ollama ps` prints SIZE as a number and its unit in separate
columns, and _loaded_models read float(p[2]) as gigabytes. Verified against the live
command: p[2]="370", p[3]="MB". A 370 MB embedding model therefore sorted as 370 GB,
ahead of every real model, and _unload_heaviest_model takes models[0] -- so on those two
09-07 cycles the guard unloaded the SMALLEST thing on the box and journalled 370 GB freed.
Three minutes apart, because the first could not have helped.

DEFECT 2 -- the streak. `mem_warn_streak` counted CONSECUTIVE cycles below the warn
threshold, and the guard's own first action is to unload a 16-23 GB model, which reliably
pushes free% back above it. The next cycle recovered and reset the streak to zero. The
durable fix behind it needs five, so it could never reach two. The counter was reset by
the success of the thing it was counting.
"""
import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import resource_medic

#: The real `ollama ps` output shape, captured from the live command on 2026-09-08.
OLLAMA_PS_OUTPUT = (
    "NAME                       ID              SIZE      PROCESSOR    CONTEXT    UNTIL\n"
    "nomic-embed-text:latest    0a109f422b47    370 MB    100% GPU     2048       4 minutes from now\n"
    "codestral:22b              f2f0f1cbd1a4    16 GB     100% GPU     8192       11 minutes from now\n"
)
PRESSURED_FREE_PCT = 20
HEALTHY_FREE_PCT = 83
EXPECTED_NONE = 0
EPISODES_JUST_BELOW_DURABLE = 4


class ModelSizesAreReadWithTheirUnits(unittest.TestCase):

    def _models(self, output):
        class Result:
            stdout = output
        with patch.object(resource_medic, "sh", return_value=Result()):
            return resource_medic._loaded_models()

    def test_the_biggest_model_is_the_one_that_is_actually_biggest(self):
        """370 MB must not outrank 16 GB. It did, by a factor of a thousand."""
        models = self._models(OLLAMA_PS_OUTPUT)
        self.assertEqual(models[0][1], "codestral:22b")
        self.assertAlmostEqual(models[0][0], 16.0)

    def test_megabytes_are_converted_not_taken_as_gigabytes(self):
        models = self._models(OLLAMA_PS_OUTPUT)
        embed = [size for size, name in models if name.startswith("nomic")][0]
        self.assertLess(embed, 1.0, "370 MB was read as 370 GB again")

    def test_a_small_model_no_longer_clears_the_unload_floor(self):
        """MEDIC_UNLOAD_MIN_GB exists to stop the guard thrashing small models.

        With the units wrong, 370 cleared a floor of 8 comfortably.
        """
        class Result:
            stdout = ("NAME  ID  SIZE  PROCESSOR  CONTEXT  UNTIL\n"
                      "nomic-embed-text:latest  0a1  370 MB  100% GPU  2048  4 minutes from now\n")
        with patch.object(resource_medic, "sh", return_value=Result()):
            self.assertIsNone(resource_medic._unload_heaviest_model())

    def test_an_unrecognised_unit_is_skipped_rather_than_guessed_at(self):
        class Result:
            stdout = ("NAME  ID  SIZE  PROCESSOR  CONTEXT  UNTIL\n"
                      "weird:model  0a1  12 PB  100% GPU  2048  4 minutes from now\n")
        with patch.object(resource_medic, "sh", return_value=Result()):
            self.assertEqual(resource_medic._loaded_models(), [])


class PressureEpisodesSurviveTheGuardsOwnSuccess(unittest.TestCase):

    def _guard(self, state, free_pct=PRESSURED_FREE_PCT, unloaded="codestral:22b (16GB)"):
        with patch.object(resource_medic, "memory_free_pct", return_value=free_pct), \
             patch.object(resource_medic, "swapout_rate_pps", return_value=None), \
             patch.object(resource_medic, "_unload_heaviest_model", return_value=unloaded), \
             patch.object(resource_medic, "_reap_oldest_agent", return_value=None), \
             patch.object(resource_medic, "journal"):
            resource_medic.memory_guard(state)
        return state

    def test_a_recovered_cycle_no_longer_erases_the_record(self):
        """The whole defect in one assertion.

        Pressure, then recovery (which the unload itself causes), then pressure again.
        The old counter was back to 1 here; five was unreachable.
        """
        state = {}
        self._guard(state)
        self._guard(state, free_pct=HEALTHY_FREE_PCT)     # the unload worked
        self._guard(state)
        self.assertEqual(len(state["mem_episodes"]), 2,
                         "recovery erased the earlier episode, as it always did")

    def test_the_fifth_episode_lowers_lanes_durably(self):
        now = time.time()
        state = {"mem_episodes": [now - 60, now - 50, now - 40, now - 30]}
        with patch.object(resource_medic, "memory_free_pct",
                          return_value=PRESSURED_FREE_PCT), \
             patch.object(resource_medic, "swapout_rate_pps", return_value=None), \
             patch.object(resource_medic, "_unload_heaviest_model", return_value=None), \
             patch.object(resource_medic, "_reap_oldest_agent", return_value=None), \
             patch.dict(os.environ, {"MAX_PARALLEL": "10"}), \
             patch.object(resource_medic, "_set_fleet_config", return_value=True) as config, \
             patch.object(resource_medic, "_escalate"), \
             patch.object(resource_medic, "journal"):
            resource_medic.memory_guard(state)
        config.assert_any_call("MAX_PARALLEL", 8)
        self.assertEqual(state["mem_episodes"], [], "the record must clear after the fix")

    def test_episodes_older_than_the_window_stop_counting(self):
        """Pressure last week is not pressure now. The window is what ages them out."""
        stale = time.time() - (resource_medic.MEM_EPISODE_WINDOW_H + 1) * 3600
        state = {"mem_episodes": [stale] * EPISODES_JUST_BELOW_DURABLE}
        with patch.dict(os.environ, {"MAX_PARALLEL": "10"}), \
             patch.object(resource_medic, "_set_fleet_config", return_value=True) as config:
            self._guard(state)
        self.assertEqual(len(state["mem_episodes"]), 1, "stale episodes were still counted")
        config.assert_not_called()

    def test_a_healthy_fleet_accumulates_nothing(self):
        state = {}
        for _cycle in range(10):
            self._guard(state, free_pct=HEALTHY_FREE_PCT)
        self.assertEqual(len(state.get("mem_episodes") or []), EXPECTED_NONE)


if __name__ == "__main__":
    unittest.main()

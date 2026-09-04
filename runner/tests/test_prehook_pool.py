"""prehook_pool.run_hooks — the pre-hooks must actually run in parallel.

Acceptance from the backlog batch: five hooks that each sleep 100ms must complete in
under 300ms, not 500ms. That assertion is the whole point — a future edit that moves a
`.result()` inside the submit loop serialises the fan-out and changes no other test,
because the ThreadPoolExecutor would still be there, doing one thing at a time.
"""
import logging
import threading
import time
import unittest

import prehook_pool


def _sleeper(seconds=0.1, value=None):
    def hook():
        time.sleep(seconds)
        return value
    return hook


class ParallelismTest(unittest.TestCase):
    def test_five_100ms_hooks_finish_in_under_300ms(self):
        hooks = {f"h{i}": _sleeper(0.1) for i in range(5)}
        t0 = time.time()
        out = prehook_pool.run_hooks(hooks)
        wall = time.time() - t0
        assert wall < 0.3, f"pre-hooks serialised: {wall:.3f}s for 5x100ms"
        assert out["wall_s"] < 0.3
        assert not out["errors"]

    def test_reported_wall_time_matches_measured(self):
        t0 = time.time()
        out = prehook_pool.run_hooks({"a": _sleeper(0.1), "b": _sleeper(0.1)})
        measured = time.time() - t0
        assert abs(out["wall_s"] - measured) < 0.1

    def test_worker_count_bounds_the_fan_out(self):
        # workers=1 must serialise — proves the width is honoured, not decorative
        t0 = time.time()
        prehook_pool.run_hooks({f"h{i}": _sleeper(0.05) for i in range(4)}, workers=1)
        assert (time.time() - t0) >= 0.2

    def test_hooks_really_run_concurrently(self):
        # timing alone can be fooled by a fast machine; count overlap directly
        live = {"now": 0, "peak": 0}
        lock = threading.Lock()

        def hook():
            with lock:
                live["now"] += 1
                live["peak"] = max(live["peak"], live["now"])
            time.sleep(0.05)
            with lock:
                live["now"] -= 1

        prehook_pool.run_hooks({f"h{i}": hook for i in range(5)}, workers=5)
        assert live["peak"] > 1, "no two hooks were ever in flight at the same time"


class ResultsContractTest(unittest.TestCase):
    def test_non_none_results_are_collected(self):
        out = prehook_pool.run_hooks({
            "a": _sleeper(0, {"hook": "a", "data": 1}),
            "b": _sleeper(0, None),
            "c": _sleeper(0, {"hook": "c", "data": 2}),
        })
        names = sorted(r["hook"] for r in out["results"])
        assert names == ["a", "c"], names

    def test_a_raising_hook_does_not_stop_the_others(self):
        def boom():
            raise RuntimeError("hook exploded")

        out = prehook_pool.run_hooks({
            "boom": boom,
            "ok": _sleeper(0, {"hook": "ok", "data": 1}),
        })
        assert out["errors"] == {"boom": "hook exploded"}
        assert [r["hook"] for r in out["results"]] == ["ok"]

    def test_accepts_pairs_as_well_as_a_mapping(self):
        out = prehook_pool.run_hooks([("a", _sleeper(0, {"hook": "a", "data": 1}))])
        assert [r["hook"] for r in out["results"]] == ["a"]

    def test_empty_input_is_a_no_op(self):
        for empty in ({}, [], None):
            with self.subTest(empty=empty):
                out = prehook_pool.run_hooks(empty)
                assert out == {"results": [], "wall_s": 0.0, "errors": {}}


class WorkerConfigTest(unittest.TestCase):
    def test_env_override(self, ):
        import os
        os.environ["ORCH_HOOK_WORKERS"] = "3"
        try:
            assert prehook_pool.hook_workers() == 3
        finally:
            os.environ.pop("ORCH_HOOK_WORKERS", None)

    def test_garbage_and_zero_fall_back_to_the_default(self):
        import os
        for bad in ("", "six", "0", "-2"):
            os.environ["ORCH_HOOK_WORKERS"] = bad
            try:
                assert prehook_pool.hook_workers() == prehook_pool.DEFAULT_WORKERS, bad
            finally:
                os.environ.pop("ORCH_HOOK_WORKERS", None)

    def test_unset_is_the_default(self):
        import os
        os.environ.pop("ORCH_HOOK_WORKERS", None)
        assert prehook_pool.hook_workers() == prehook_pool.DEFAULT_WORKERS


class WallTimeIsLoggedTest(unittest.TestCase):
    def test_total_wall_time_is_logged_at_info(self):
        # ORCH_PREHOOK_MAX_S is judged against this number; nothing used to emit it
        with self.assertLogs("prehook_pool", level=logging.INFO) as cm:
            prehook_pool.run_hooks({"a": _sleeper(0)}, label="pre-hooks")
        assert any("pre-hooks" in line and "s (" in line for line in cm.output), cm.output


if __name__ == "__main__":
    unittest.main()

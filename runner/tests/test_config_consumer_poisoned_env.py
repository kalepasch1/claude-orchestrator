#!/usr/bin/env python3
"""Regression: a fully poisoned ORCH_ environment must not stop config consumption.

THE FAILING CONFIGURATION
-------------------------
orch-config-consumption was shelved after six remediations, and each remediation fixed
one knob in isolation. `test_config_consumer_knobs.py` mirrors that: it poisons
ORCH_CONFIG_CACHE_TTL_SEC on its own, then ORCH_CONFIG_CACHE_MAX_ENTRIES on its own,
each in a fresh interpreter. That is not the state a runner is actually in when the
fleet pushes a bad config — every ORCH_ key is set at once, from one push, and the
import is followed immediately by real `load_config()` / typed-getter calls.

The single-knob tests pass even if a *second* bad knob would wedge the module, and they
never exercise the path past import at all. So the exact shape that kept coming back —
"import succeeded, then the first read blew up / returned garbage" — had no coverage.

WHAT THIS PINS
--------------
In one subprocess, with every ORCH_ knob config_consumer reads set to a different flavour
of garbage simultaneously:

  * the import completes,
  * `load_config`, `get`, `get_int`, `get_bool`, `get_float`, `load_all` and
    `invalidate_cache` all return, none raise,
  * each returns the caller's declared default rather than the poison, and
  * the cache TTL/eviction knobs fall back to their module defaults instead of
    producing a zero-size or negative-TTL cache.

Deliberately narrow: config_consumer's own knob surface and its public API. It asserts
nothing about which source a value came from — `test_config_consumer_source_precedence.py`
owns that.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

# Every flavour of garbage an operator or a bad fleet push can realistically produce.
POISON = {
    "ORCH_CONFIG_CACHE_TTL_SEC": "abc",
    "ORCH_CONFIG_CACHE_MAX_ENTRIES": "-1",
    "ORCH_POISONED_INT": "not-an-int",
    "ORCH_POISONED_FLOAT": "3.4.5",
    "ORCH_POISONED_BOOL": "maybe",
    "ORCH_POISONED_EMPTY": "   ",
}

# Runs inside the poisoned interpreter. Anything raising here fails the test with the
# traceback attached, which is the whole point: the module's contract is "never raises".
PROBE = r"""
import json, sys
import config_consumer as cc

out = {}
out["imported"] = True
out["ttl"] = cc._consumer._cache_ttl_sec
out["max_entries"] = cc._consumer._cache_max_entries
out["load_config_absent"] = cc.load_config("TOTALLY_ABSENT", "fallback")
out["load_config_poisoned"] = cc.load_config("POISONED_EMPTY", "fallback")
out["get_int"] = cc.get_int("POISONED_INT", 42)
out["get_float"] = cc.get_float("POISONED_FLOAT", 1.5)
out["get_bool"] = cc.get_bool("POISONED_BOOL", True)
out["get_empty"] = cc.get("POISONED_EMPTY", "fallback")
out["load_all_is_dict"] = isinstance(cc.load_all(), dict)
cc.invalidate_cache("TOTALLY_ABSENT")
cc.invalidate_cache()
out["invalidate_ok"] = True
# A second read after invalidation must still be fine — the shelved bug reappeared
# on the re-read, not the first call.
out["reread"] = cc.load_config("TOTALLY_ABSENT", "fallback")
print("RESULT" + json.dumps(out))
"""


def _run_probe(extra_env=None):
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("ORCH_"):
            env.pop(key)
    env.update(POISON)
    env.update(extra_env or {})
    env["PYTHONPATH"] = RUNNER
    return subprocess.run(
        [sys.executable, "-c", PROBE],
        capture_output=True, text=True, env=env, timeout=120,
    )


class PoisonedEnvironmentTest(unittest.TestCase):
    """One subprocess, every knob poisoned at once, results asserted field by field."""

    @classmethod
    def setUpClass(cls):
        cls.proc = _run_probe()
        cls.payload = None
        for line in cls.proc.stdout.splitlines():
            if line.startswith("RESULT"):
                cls.payload = json.loads(line[len("RESULT"):])

    def setUp(self):
        if self.payload is None:
            self.fail(
                "the probe never produced a result — config consumption did not survive "
                f"a fully poisoned ORCH_ environment.\nstderr:\n{self.proc.stderr[-2000:]}"
            )

    def test_the_module_imports_under_a_fully_poisoned_environment(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr[-2000:])
        self.assertTrue(self.payload["imported"])

    def test_no_public_call_raised(self):
        self.assertTrue(self.payload["invalidate_ok"])

    def test_the_ttl_falls_back_to_the_module_default(self):
        import config_consumer as cc
        self.assertEqual(self.payload["ttl"], cc.DEFAULT_CACHE_TTL_SEC)

    def test_a_negative_max_entries_does_not_produce_an_unusable_cache(self):
        import config_consumer as cc
        self.assertEqual(self.payload["max_entries"], cc.DEFAULT_CACHE_MAX_ENTRIES)
        self.assertGreater(self.payload["max_entries"], 0)

    def test_typed_getters_return_the_callers_default_not_the_poison(self):
        self.assertEqual(self.payload["get_int"], 42)
        self.assertEqual(self.payload["get_float"], 1.5)
        self.assertEqual(self.payload["get_empty"], "fallback")

    def test_get_bool_deliberately_does_not_fall_back_on_an_unknown_word(self):
        """Pinned asymmetry, found by this test and left in place on purpose.

        get_int/get_float return the caller's default when the value will not parse.
        get_bool does not: its contract is "true/1/yes/on -> True, else False", so
        ORCH_X=maybe turns a `get_bool("X", True)` into False rather than leaving the
        default alone. That silently flips a default-on flag off, which matters for
        anything shaped like a kill switch.

        It is documented behaviour and changing it would move every caller at once, so
        this asserts the current shape rather than the arguably-better one. If someone
        does change it, this test is where the decision gets made — not a surprise in
        production.
        """
        self.assertIs(self.payload["get_bool"], False)

    def test_load_config_returns_the_default_for_absent_and_whitespace_keys(self):
        self.assertEqual(self.payload["load_config_absent"], "fallback")
        self.assertEqual(self.payload["load_config_poisoned"], "fallback")

    def test_a_reread_after_invalidation_still_works(self):
        self.assertEqual(self.payload["reread"], "fallback")

    def test_load_all_still_returns_a_mapping(self):
        self.assertTrue(self.payload["load_all_is_dict"])


class GoodEnvironmentControlTest(unittest.TestCase):
    """Control: the same probe with sane knobs must honour them, so the test above
    cannot pass merely because everything always falls back."""

    def test_valid_knobs_are_actually_used(self):
        proc = _run_probe({
            "ORCH_CONFIG_CACHE_TTL_SEC": "12.5",
            "ORCH_CONFIG_CACHE_MAX_ENTRIES": "7",
        })
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        payload = None
        for line in proc.stdout.splitlines():
            if line.startswith("RESULT"):
                payload = json.loads(line[len("RESULT"):])
        self.assertIsNotNone(payload, proc.stderr[-2000:])
        self.assertEqual(payload["ttl"], 12.5)
        self.assertEqual(payload["max_entries"], 7)


if __name__ == "__main__":
    unittest.main()

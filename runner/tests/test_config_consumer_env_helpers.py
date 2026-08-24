#!/usr/bin/env python3
"""Fail-soft module-scope env helpers, and the audit that measures their adoption.

A module-scope `int(os.environ.get("ORCH_X", "8"))` runs at import time, so one bad
fleet push of ORCH_X raises ValueError mid-import and takes down every importer of that
module. `config_consumer.env_int/env_float/env_bool/env_str` are the fail-soft
replacements; `tools.env_cast_audit` finds the call sites still using a bare cast.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(RUNNER)
for _p in (RUNNER, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config_consumer as cc  # noqa: E402
from tools.env_cast_audit import audit_paths, find_module_scope_env_casts  # noqa: E402

KEY = "ORCH_ENV_HELPER_PROBE"


class EnvHelperTestCase(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get(KEY)
        os.environ.pop(KEY, None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(KEY, None)
        else:
            os.environ[KEY] = self._saved


class EnvIntTest(EnvHelperTestCase):
    def test_reads_a_valid_value(self):
        os.environ[KEY] = "17"
        self.assertEqual(cc.env_int(KEY, 8), 17)

    def test_negative_values_are_allowed_without_a_minimum(self):
        os.environ[KEY] = "-4"
        self.assertEqual(cc.env_int(KEY, 8), -4)

    def test_minimum_is_enforced(self):
        os.environ[KEY] = "0"
        self.assertEqual(cc.env_int(KEY, 8, minimum=1), 8)

    def test_garbage_falls_back(self):
        for bad in ("abc", "1.5", "", "   ", "8,000"):
            os.environ[KEY] = bad
            self.assertEqual(cc.env_int(KEY, 8), 8, bad)

    def test_absent_uses_default(self):
        self.assertEqual(cc.env_int(KEY, 8), 8)

    def test_whitespace_is_stripped(self):
        os.environ[KEY] = "  12  "
        self.assertEqual(cc.env_int(KEY, 8), 12)

    def test_never_raises_on_a_bad_name(self):
        for name in (None, "", 5, []):
            self.assertEqual(cc.env_int(name, 3), 3)


class EnvFloatTest(EnvHelperTestCase):
    def test_reads_a_valid_value(self):
        os.environ[KEY] = "2.25"
        self.assertEqual(cc.env_float(KEY, 1.0), 2.25)

    def test_an_int_is_accepted(self):
        os.environ[KEY] = "3"
        self.assertEqual(cc.env_float(KEY, 1.0), 3.0)

    def test_minimum_is_enforced(self):
        os.environ[KEY] = "0.5"
        self.assertEqual(cc.env_float(KEY, 1.5, minimum=1.0), 1.5)

    def test_garbage_falls_back(self):
        for bad in ("3.4.5", "abc", "  "):
            os.environ[KEY] = bad
            self.assertEqual(cc.env_float(KEY, 1.5), 1.5, bad)


class EnvBoolTest(EnvHelperTestCase):
    def test_truthy_words(self):
        for good in ("true", "TRUE", "1", "yes", "on", " On "):
            os.environ[KEY] = good
            self.assertIs(cc.env_bool(KEY, False), True, good)

    def test_falsy_words(self):
        for good in ("false", "0", "no", "off", " OFF "):
            os.environ[KEY] = good
            self.assertIs(cc.env_bool(KEY, True), False, good)

    def test_an_unknown_word_keeps_the_default_instead_of_flipping_it(self):
        """The difference from get_bool, and the reason these helpers exist.

        get_bool maps anything unrecognised to False, so ORCH_KILL_SWITCH=maybe
        silently turns a default-on switch off. At module scope that is how a guard
        disappears. env_bool ignores the typo and keeps the declared default."""
        os.environ[KEY] = "maybe"
        self.assertIs(cc.env_bool(KEY, True), True)
        self.assertIs(cc.env_bool(KEY, False), False)

    def test_absent_uses_default(self):
        self.assertIs(cc.env_bool(KEY, True), True)


class EnvStrTest(EnvHelperTestCase):
    def test_reads_and_strips(self):
        os.environ[KEY] = "  hello  "
        self.assertEqual(cc.env_str(KEY, "d"), "hello")

    def test_empty_and_whitespace_fall_back(self):
        for bad in ("", "   "):
            os.environ[KEY] = bad
            self.assertEqual(cc.env_str(KEY, "d"), "d")


class ImportIsFailSoftTest(unittest.TestCase):
    """The regression: a poisoned knob must not break `import adaptive_budget`."""

    def _import_with(self, **overrides):
        env = dict(os.environ)
        env.update(overrides)
        env["PYTHONPATH"] = RUNNER
        return subprocess.run(
            [sys.executable, "-c",
             "import adaptive_budget as a;"
             "print(a.DEFAULT_BUDGET, a.MIN_BUDGET, a.BUDGET_HEADROOM)"],
            capture_output=True, text=True, env=env, timeout=120,
        )

    def test_a_poisoned_budget_knob_no_longer_wedges_the_import(self):
        proc = self._import_with(
            ORCH_DEFAULT_TOKEN_BUDGET="oops",
            ORCH_MIN_TOKEN_BUDGET="-3",
            ORCH_BUDGET_HEADROOM="not-a-float",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-1500:])
        self.assertIn("8192 1024 1.5", proc.stdout)

    def test_valid_knobs_are_still_honoured(self):
        proc = self._import_with(
            ORCH_DEFAULT_TOKEN_BUDGET="4096",
            ORCH_MIN_TOKEN_BUDGET="512",
            ORCH_BUDGET_HEADROOM="2.0",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-1500:])
        self.assertIn("4096 512 2.0", proc.stdout)


class EnvCastAuditTest(unittest.TestCase):
    def test_flags_a_module_scope_cast(self):
        source = 'import os\nMAX = int(os.environ.get("ORCH_MAX", "8"))\n'
        found = find_module_scope_env_casts(source, "sample.py")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["cast"], "int")
        self.assertEqual(found[0]["line"], 2)
        self.assertIn("env_int", found[0]["suggestion"])

    def test_ignores_a_cast_inside_a_function(self):
        source = 'import os\ndef f():\n    return int(os.environ.get("ORCH_MAX", "8"))\n'
        self.assertEqual(find_module_scope_env_casts(source, "sample.py"), [])

    def test_ignores_a_cast_that_does_not_read_the_environment(self):
        source = 'MAX = int("8")\n'
        self.assertEqual(find_module_scope_env_casts(source, "sample.py"), [])

    def test_catches_getenv_and_module_level_conditionals(self):
        source = ('import os\n'
                  'if True:\n'
                  '    LIMIT = float(os.getenv("ORCH_LIMIT", "1.0"))\n')
        self.assertEqual(len(find_module_scope_env_casts(source, "s.py")), 1)

    def test_unparseable_source_is_skipped_not_fatal(self):
        self.assertEqual(find_module_scope_env_casts("def (:\n", "bad.py"), [])

    def test_audit_paths_never_raises_on_a_missing_directory(self):
        self.assertEqual(audit_paths(["definitely-not-here"], REPO_ROOT), [])

    def test_adaptive_budget_is_now_clean(self):
        """The exemplar migration: this file must have no import-time casts left."""
        findings = audit_paths(["runner/adaptive_budget.py"], REPO_ROOT)
        self.assertEqual(findings, [], findings)

    def test_the_audit_finds_the_remaining_backlog(self):
        """Sanity: the tool is actually looking at the repo, not returning empty."""
        self.assertGreater(len(audit_paths(["runner"], REPO_ROOT)), 0)


if __name__ == "__main__":
    unittest.main()

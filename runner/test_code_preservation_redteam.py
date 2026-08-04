#!/usr/bin/env python3
"""
test_code_preservation_redteam.py — regression tests for the 2026-08-04 adversarial sweep.

Every test here corresponds to a HOLE that was open in the guards on 2026-08-04 and that a
red-team merge walked straight through. Each is anchored on the real incident where one
exists. If any of these fails, that specific historical loss can happen again.

Holes closed, in the order they appear below:

  1. regression_guard's symbol and undefined-name detectors were gated on `.py`. The fleet's
     apps are TypeScript and Vue, so the module's most important detector was not running on
     the code it most needed to protect. (tomorrow / apparently / illuminati are all TS.)
  2. divergent_authorship_guard.gate() returned ok=True on `guard_error` — an unreachable
     merge base produced ZERO blocking findings and a "no divergent authorship" verdict.
  3. stub_guard's `guard_error` was advisory, so an unevaluable repo reported "stub gate clean".
  4. scan_shadowed only matched a stub whose whole declaration fitted on ONE line starting at
     column 0: multi-line bodies, `export default`, minified barrels, function expressions and
     NON-EMPTY wrong constants all slipped past. (tomorrow 114a6c081 / 0ef37d685, 206 stubs.)
  5. `export { x } from './y'` contributed no names, so a two-hop barrel was invisible.
  6. scan_fabricated only matched `function NAME(){return X}` — arrow, async-arrow and class
     -method stubs with CRITICAL names were missed. assertEcpCounterparty WAS an arrow.
  7. divergent_authorship_guard._defined_or_referenced only looked INSIDE the file that lost
     the symbol, so a symbol dropped from f.ts and still imported by u.ts scored "referenced
     by nobody" and was skipped. (The 71cfd4ca6 read happened to be intra-file.)
  8. .json was not analysable, so add/add on a config/locale/manifest was skipped entirely.
  9. bulk_update_guard.check() returned True when row_count was None — and db.update()
     computes that count inside a bare `except: _n = None`. (9,236 tasks -> MERGED.)
 10. divergent_authorship_guard and stub_guard were wired into merge_train ONLY. The
     auto_conflict_resolver path — which authored 71cfd4ca6, the exact add/add loss the
     divergent guard was written for — never called either of them.
 11. FALSE POSITIVE: a symbol MOVED to another file in the same commit was reported as
     `missing`. A guard that blocks ordinary refactors gets switched off, which is itself a
     loss vector.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import regression_guard as rg              # noqa: E402
import divergent_authorship_guard as dag   # noqa: E402
import stub_guard                          # noqa: E402
import bulk_update_guard                   # noqa: E402


def _sh(repo, *args):
    return subprocess.run(list(args), cwd=repo, capture_output=True, text=True)


class _Repo:
    """A throwaway git repo."""

    def __init__(self):
        self.path = tempfile.mkdtemp(prefix="redteam-")
        _sh(self.path, "git", "init", "-q", "-b", "master")
        _sh(self.path, "git", "config", "user.email", "t@t.t")
        _sh(self.path, "git", "config", "user.name", "t")
        _sh(self.path, "git", "config", "commit.gpgsign", "false")

    def write(self, rel, text):
        full = os.path.join(self.path, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write(text)

    def commit(self, msg):
        _sh(self.path, "git", "add", "-A")
        _sh(self.path, "git", "commit", "-q", "--no-verify", "-m", msg)
        return _sh(self.path, "git", "rev-parse", "HEAD").stdout.strip()

    def git(self, *args):
        return _sh(self.path, "git", *args)

    def destroy(self):
        shutil.rmtree(self.path, ignore_errors=True)


# ---------------------------------------------------------------------------
# HOLE 1 — TS / Vue / JS symbol loss was invisible to regression_guard
# ---------------------------------------------------------------------------

class TestTypeScriptSymbolLoss(unittest.TestCase):
    """Pattern 7 (symbol deleted while still imported) in the fleet's actual languages."""

    LANGS = {
        "ts": ("export function assessCredit(a: any) {\n  const s = a.score * 2;\n"
               "  return s > 10;\n}\nexport function other() { return 1; }\n",
               "export function other() { return 1; }\n",
               "import { assessCredit } from './m';\n"
               "export const run = (a: any) => assessCredit(a);\n"),
        "tsx": ("export const Panel = (p: any) => <div>{p.x}</div>;\n"
                "export const WIDTH = 10;\n",
                "export const WIDTH = 10;\n",
                "import { Panel } from './m';\nexport const App = () => Panel({});\n"),
        "vue": ("<script setup lang=\"ts\">\nexport function assessCredit(a: any) {\n"
                "  const s = a.score * 2;\n  return s > 10;\n}\n</script>\n",
                "<script setup lang=\"ts\">\n</script>\n",
                "<script setup lang=\"ts\">\nimport { assessCredit } from './m.vue';\n"
                "</script>\n"),
        "mjs": ("export function assessCredit(a) {\n  const s = a.score * 2;\n"
                "  return s > 10;\n}\n", "",
                "import { assessCredit } from './m.mjs';\nassessCredit(1);\n"),
        "js": ("export function assessCredit(a) {\n  const s = a.score * 2;\n"
               "  return s > 10;\n}\n", "",
               "import { assessCredit } from './m.js';\nassessCredit(1);\n"),
    }

    def test_deleted_exported_symbol_blocks_the_merge(self):
        for ext, (real, gutted, importer) in self.LANGS.items():
            with self.subTest(lang=ext):
                r = _Repo()
                try:
                    r.write("m." + ext, real)
                    r.write("u." + ext, importer)
                    base = r.commit("init")
                    r.write("m." + ext, gutted)
                    r.commit("Merge branch 'agent/x' (auto-resolved)")
                    ok, findings = rg.check_merge(r.path, base, "HEAD")
                    self.assertFalse(
                        ok, "%s: deleting an exported symbol that another module imports "
                            "must block the merge" % ext)
                    self.assertTrue(
                        any(f["kind"] in ("missing", "net-deletion") for f in findings),
                        "%s: expected a symbol-loss finding, got %s"
                        % (ext, [f["kind"] for f in findings]))
                finally:
                    r.destroy()

    def test_exported_symbol_stubbed_to_a_constant_blocks_the_merge(self):
        """A real body replaced by a constant: no crash, permanent wrong behaviour."""
        for ext, before, after in (
            ("ts", "export function computeWarrantyEconomics(a: any) {\n"
                   "  const npv = a.cash / a.rate;\n  return { npv, irr: npv * 0.1 };\n}\n",
                   "export function computeWarrantyEconomics(a: any) { return { npv: 0 }; }\n"),
            ("ts", "export const assertEcpCounterparty = (x: any) => {\n"
                   "  if (!x.eligible) throw new Error('ineligible');\n  return true;\n};\n",
                   "export const assertEcpCounterparty = () => ({ ok: true });\n"),
            ("vue", "<script setup lang=\"ts\">\nexport const priceLeg = (a: any) => {\n"
                    "  const n = a.notional * a.rate;\n  return n;\n};\n</script>\n",
                    "<script setup lang=\"ts\">\nexport const priceLeg = () => 0;\n</script>\n"),
        ):
            with self.subTest(lang=ext, after=after[:40]):
                r = _Repo()
                try:
                    r.write("m." + ext, before)
                    base = r.commit("init")
                    r.write("m." + ext, after)
                    r.commit("merge")
                    ok, findings = rg.check_merge(r.path, base, "HEAD")
                    self.assertFalse(ok, "stubbing %s must block" % ext)
                    self.assertTrue(any(f["kind"] == "stubbed" for f in findings),
                                    "expected 'stubbed', got %s"
                                    % [f["kind"] for f in findings])
                finally:
                    r.destroy()

    def test_minified_one_line_module_is_still_analysed(self):
        """A ^-anchored regex sees nothing in a bundled/one-line file."""
        r = _Repo()
        try:
            r.write("m.ts", "export const a=1;export function priceLeg(x:any){"
                            "const n=x.n*x.r;return n;}export const b=2;\n")
            r.write("u.ts", "import { priceLeg } from './m';\npriceLeg({});\n")
            base = r.commit("init")
            r.write("m.ts", "export const a=1;export const b=2;\n")
            r.commit("merge")
            ok, findings = rg.check_merge(r.path, base, "HEAD")
            self.assertFalse(ok, "minified module lost priceLeg and must block")
            self.assertIn("priceLeg", [f.get("symbol") for f in findings])
        finally:
            r.destroy()


# ---------------------------------------------------------------------------
# HOLE 11 — must NOT false-positive
# ---------------------------------------------------------------------------

class TestNoFalsePositives(unittest.TestCase):

    def test_symbol_moved_to_a_new_file_is_not_loss(self):
        """A refactor that lifts a helper into another module keeps every caller working."""
        for ext, before_a, after_a, new_b in (
            ("py", "def helper():\n    x = 1\n    return x + 2\n\n"
                   "def keep():\n    return helper()\n",
                   "from b import helper\n\ndef keep():\n    return helper()\n",
                   "def helper():\n    x = 1\n    return x + 2\n"),
            ("ts", "export function helper() {\n  const x = 1;\n  return x + 2;\n}\n"
                   "export function keep() { return helper(); }\n",
                   "import { helper } from './b';\n"
                   "export function keep() { return helper(); }\n",
                   "export function helper() {\n  const x = 1;\n  return x + 2;\n}\n"),
        ):
            with self.subTest(lang=ext):
                r = _Repo()
                try:
                    r.write("a." + ext, before_a)
                    base = r.commit("init")
                    r.write("a." + ext, after_a)
                    r.write("b." + ext, new_b)
                    r.commit("refactor: move helper into its own module")
                    ok, findings = rg.check_merge(r.path, base, "HEAD")
                    self.assertTrue(
                        ok, "%s: relocating a symbol is a refactor, not a loss; got %s"
                            % (ext, [(f["kind"], f.get("symbol")) for f in findings]))
                finally:
                    r.destroy()

    def test_identical_edits_from_both_sides_do_not_conflict(self):
        r = _Repo()
        try:
            r.write("f.ts", "export const a = 1;\n")
            base = r.commit("base")
            r.git("checkout", "-q", "-b", "A")
            r.write("f.ts", "export const a = 1;\nexport const b = 2;\n")
            r.commit("A")
            r.git("checkout", "-q", "master")
            r.git("checkout", "-q", "-b", "B")
            r.write("f.ts", "export const a = 1;\nexport const b = 2;\n")
            r.commit("B")
            findings = dag.check_pair(r.path, "A", "B", merge_base=base)
            self.assertEqual(
                [], [f for f in findings if f["severity"] == "block"],
                "both sides making the SAME edit is agreement, not divergence")
        finally:
            r.destroy()


# ---------------------------------------------------------------------------
# HOLES 2, 3, 9 — fail-open error paths
# ---------------------------------------------------------------------------

class TestGuardsFailClosed(unittest.TestCase):

    def test_divergent_gate_refuses_when_merge_base_is_unreachable(self):
        """Was: gate() reported "no divergent authorship" on a comparison it never made."""
        r = _Repo()
        try:
            r.write("a.ts", "export const a = 1;\n")
            r.commit("a")
            ok, log = dag.gate(r.path, "deadbeef" * 5, "HEAD")
            self.assertFalse(ok, "an unreachable merge base must FAIL CLOSED, got: %s" % log)
        finally:
            r.destroy()

    def test_divergent_guard_error_is_blocking(self):
        self.assertIn("guard_error", dag.BLOCKING)
        self.assertEqual(
            "block",
            dag._finding("guard_error", "<repo>", "d", "f")["severity"])

    def test_stub_guard_error_is_blocking(self):
        self.assertIn("guard_error", stub_guard.BLOCKING)
        self.assertEqual(
            "block", stub_guard._violation("guard_error", "p", "d", "f")["severity"])

    def test_regression_guard_refuses_an_unreachable_base(self):
        r = _Repo()
        try:
            r.write("a.py", "def f():\n    return 1\n")
            r.commit("i")
            ok, log = rg.gate(r.path, "deadbeef" * 5, "HEAD")
            self.assertFalse(ok, "a bad base SHA must fail closed, got: %s" % log)
        finally:
            r.destroy()

    def test_regression_guard_refuses_an_unparseable_result(self):
        r = _Repo()
        try:
            r.write("a.py", "def f():\n    return 1\n")
            base = r.commit("i")
            r.write("a.py", "def f(:\n  ???\n")
            r.commit("broken merge")
            ok, findings = rg.check_merge(r.path, base, "HEAD")
            self.assertFalse(ok)
            self.assertTrue(any(f["kind"] == "unparseable" for f in findings))
        finally:
            r.destroy()

    def test_check_undefined_refuses_a_file_that_does_not_parse(self):
        """pyflakes exits 1 with a syntax-error line that matches no interest pattern, so
        this detector used to report an EMPTY undefined set — 'clean' — for a module the
        merge had syntactically destroyed. Invisible on any machine with pyflakes installed."""
        for use_pyflakes in (True, False):
            with self.subTest(pyflakes=use_pyflakes):
                out = rg.check_undefined("m.py", "x = 1\n", "def f(:\n  ???\n",
                                         use_pyflakes=use_pyflakes)
                self.assertTrue(out, "a syntactically broken result must never report clean")
                self.assertEqual("unparseable", out[0]["kind"])

    def test_bulk_state_change_with_unknown_row_count_is_refused(self):
        """db.update() computes the count inside a bare except; None must not mean 'allow'."""
        os.environ.pop("ORCH_ALLOW_BULK_STATE_CHANGE", None)
        with self.assertRaises(bulk_update_guard.BulkStateChangeRefused):
            bulk_update_guard.check("tasks", {"state": "MERGED"}, None, actor="test")

    def test_bulk_state_change_over_threshold_is_refused(self):
        os.environ.pop("ORCH_ALLOW_BULK_STATE_CHANGE", None)
        with self.assertRaises(bulk_update_guard.BulkStateChangeRefused):
            bulk_update_guard.check("tasks", {"state": "MERGED"}, 9236, actor="test")

    def test_single_row_state_change_still_passes(self):
        self.assertTrue(bulk_update_guard.check("tasks", {"state": "MERGED"}, 1))


# ---------------------------------------------------------------------------
# HOLES 4, 5, 6 — stub shapes that shadow real implementations
# ---------------------------------------------------------------------------

class TestShadowedStubShapes(unittest.TestCase):
    """tomorrow 114a6c081 / 0ef37d685, apparently dec963c4 — 206 shadowed re-exports."""

    IMPL = ("export function assertEcpCounterparty(x: any) {\n"
            "  if (!x.ok) throw new Error('ineligible');\n  return true;\n}\n"
            "export function computeWarrantyEconomics(a: any) { return { npv: a.x * 2 }; }\n"
            "export function priceLeg(a: any) { return a.n * a.r; }\n")

    SHAPES = {
        "arrow": ("src/a.ts", "export * from './impl';\n"
                              "export const assertEcpCounterparty = () => ({});\n"),
        "multiline_body": ("src/b.ts", "export * from './impl';\n"
                                       "export function assertEcpCounterparty(x: any): any {\n"
                                       "  return {};\n}\n"),
        "two_hop_named_reexport": ("src/d.ts", "export * from './mid';\n"
                                               "export const priceLeg = () => 0;\n"),
        "non_empty_wrong_constant": ("src/e.ts", "export * from './impl';\n"
                                                 "export const assertEcpCounterparty = "
                                                 "() => ({ ok: true });\n"),
        "vue_script_setup": ("src/f.vue", "<script setup lang=\"ts\">\n"
                                          "export * from './impl';\n"
                                          "export const priceLeg = () => 0;\n</script>\n"),
        "minified_one_line": ("src/g.ts", "export * from './impl';"
                                          "export const assertEcpCounterparty=()=>({});\n"),
        "mjs_barrel": ("src/h.mjs", "export * from './impl';\n"
                                    "export const priceLeg = () => 0;\n"),
        "function_expression": ("src/i.ts", "export * from './impl';\n"
                                            "export const computeWarrantyEconomics = "
                                            "function () { return {}; };\n"),
    }

    def test_every_stub_shape_is_detected(self):
        r = _Repo()
        try:
            r.write("src/impl.ts", self.IMPL)
            r.write("src/mid.ts",
                    "export { priceLeg, assertEcpCounterparty } from './impl';\n")
            for _name, (path, body) in self.SHAPES.items():
                r.write(path, body)
            r.commit("init")
            hits = {v["path"].split(":")[0]
                    for v in stub_guard.scan_shadowed(r.path)}
            for name, (path, _body) in self.SHAPES.items():
                with self.subTest(shape=name):
                    self.assertIn(
                        path, hits,
                        "%s: a constant-return stub shadowing a real re-export must be "
                        "detected — this is the 206-instance tomorrow/apparently shape" % name)
        finally:
            r.destroy()

    def test_named_reexport_counts_as_an_export(self):
        """`export { x } from './y'` was contributing zero names to the provided set."""
        r = _Repo()
        try:
            r.write("impl.ts", "export function priceLeg(a: any) { return a.n * a.r; }\n")
            r.write("mid.ts", "export { priceLeg } from './impl';\n")
            r.commit("init")
            names = stub_guard._exports_of(r.path, os.path.join(r.path, "mid.ts"), {})
            self.assertIn("priceLeg", names)
        finally:
            r.destroy()


class TestFabricatedCriticalReturns(unittest.TestCase):
    """Pattern 6 — a compliance/financial function whose body is a constant."""

    CASES = {
        "object_literal_fn": "export function computeWarrantyEconomics(a: any) "
                             "{ return { npv: 0, irr: 0 }; }\n",
        "arrow_scalar": "export const priceCollateral = () => 0;\n",
        "async_arrow": "export const enforceCompliance = async () => true;\n",
        "bare_return_void": "export function assertEcpCounterparty(x: any): void {\n"
                            "  return;\n}\n",
        "class_method": "export class Risk {\n  computeExposure() { return 0; }\n}\n",
        "vue_sfc": "<script setup lang=\"ts\">\n"
                   "export function computePricing(a: any) { return { fee: 0 }; }\n</script>\n",
        "mjs": "export function calculateInterest(p) { return 0; }\n",
    }

    def test_every_fabricated_shape_is_blocking(self):
        r = _Repo()
        try:
            for name, body in self.CASES.items():
                ext = ".vue" if name == "vue_sfc" else (".mjs" if name == "mjs" else ".ts")
                r.write("s/%s%s" % (name, ext), body)
            r.commit("init")
            hits = {v["path"].split(":")[0] for v in stub_guard.scan_fabricated(r.path)
                    if v["code"] == "fabricated_critical_return"}
            for name in self.CASES:
                ext = ".vue" if name == "vue_sfc" else (".mjs" if name == "mjs" else ".ts")
                with self.subTest(shape=name):
                    self.assertIn(
                        "s/%s%s" % (name, ext), hits,
                        "%s: a constant return from a compliance/financial name is a "
                        "BLOCKING defect — fabricated output is worse than a crash" % name)
        finally:
            r.destroy()


class TestStubCommitMessages(unittest.TestCase):
    """Pattern 9 — the commit message advertises the loss."""

    MESSAGES = [
        "add 12 missing export stubs to fix build",
        "chore: add stub exports for build",
        "fix: stubs to unblock the build",
        "bulk MISSING_EXPORT fix",
        "chore: add missing composable stubs",
        "wip: add placeholder implementations so the build passes",
        "fix(build): create no-op shims for missing exports",
    ]

    def test_every_phrasing_is_caught(self):
        for msg in self.MESSAGES:
            with self.subTest(msg=msg):
                self.assertTrue(stub_guard._STUB_COMMIT_MSG.search(msg),
                                "%r advertises stubbing-to-green-the-build" % msg)

    def test_ordinary_messages_are_not_caught(self):
        for msg in ("fix: correct the interest calculation",
                    "feat: add credit assessment endpoint",
                    "refactor: extract the pricing helper",
                    "test: add coverage for the eligibility gate"):
            with self.subTest(msg=msg):
                self.assertFalse(stub_guard._STUB_COMMIT_MSG.search(msg),
                                 "%r is an ordinary commit and must not be flagged" % msg)


# ---------------------------------------------------------------------------
# HOLES 7, 8 — divergent authorship
# ---------------------------------------------------------------------------

class TestDivergentAuthorship(unittest.TestCase):

    def _add_add(self, ext, a, b):
        r = _Repo()
        r.write("seed.txt", "x\n")
        base = r.commit("base")
        r.git("checkout", "-q", "-b", "A")
        r.write("f." + ext, a)
        r.commit("A authors f")
        r.git("checkout", "-q", "master")
        r.git("checkout", "-q", "-b", "B")
        r.write("f." + ext, b)
        r.commit("B authors f")
        return r, base

    def test_add_add_blocks_in_every_language(self):
        """illuminati ac9dd8f (rapidGradient.ts, -383 lines) and orchestrator 71cfd4ca6."""
        cases = {
            "ts": ("export type Grad = { r: number };\n"
                   "export function mk(a: any) { return { r: a }; }\n",
                   "export type Grad = { r: string; g: string };\n"
                   "export const STEPS = 12;\n"),
            "tsx": ("export const Panel = () => <div>a</div>;\nexport const WIDTH = 10;\n",
                    "export const Panel = () => <span>b</span>;\nexport const HEIGHT = 20;\n"),
            "vue": ("<script setup lang=\"ts\">\nexport const useA = () => 1;\n</script>\n",
                    "<script setup lang=\"ts\">\nexport const useA = () => 2;\n"
                    "export const LIMIT = 9;\n</script>\n"),
            "mjs": ("export const roll = () => 1;\nexport const N = 3;\n",
                    "export const roll = () => 2;\nexport const M = 4;\n"),
            "py": ("CANARY_ENABLED = True\ndef route_request(x):\n    return CANARY_ENABLED\n",
                   "CANARY_PERCENT = 5\ndef route_gpt1_request_canary(x):\n"
                   "    return CANARY_PERCENT\n"),
            "json": ('{"a": 1, "shared": "one"}\n', '{"b": 2, "shared": "two"}\n'),
        }
        for ext, (a, b) in cases.items():
            with self.subTest(lang=ext):
                r, base = self._add_add(ext, a, b)
                try:
                    findings = dag.check_pair(r.path, "A", "B", merge_base=base)
                    self.assertTrue(
                        [f for f in findings if f["severity"] == "block"],
                        "%s: both sides authored the same path from nothing — there is no "
                        "ancestor, so no resolver can keep both sides safely" % ext)
                finally:
                    r.destroy()

    def test_cross_file_symbol_loss_is_detected(self):
        """Was: only the file that LOST the symbol was searched for references."""
        for ext, a, b, user in (
            ("ts", "export const STEPS = 12;\nexport function mk(a: any) { return STEPS; }\n",
                   "export function build(a: any) { return a; }\nexport const RATE = 3;\n",
                   "import { RATE } from './f';\nexport const z = () => RATE + 1;\n"),
            ("py", "CANARY_ENABLED = True\ndef route_request(x):\n    return CANARY_ENABLED\n",
                   "CANARY_PERCENT = 5\ndef route_gpt1(x):\n    return CANARY_PERCENT\n",
                   "from f import CANARY_PERCENT\nprint(CANARY_PERCENT)\n"),
        ):
            with self.subTest(lang=ext):
                r = _Repo()
                try:
                    r.write("seed.txt", "x\n")
                    base = r.commit("base")
                    r.git("checkout", "-q", "-b", "A")
                    r.write("f." + ext, a)
                    r.commit("A")
                    r.git("checkout", "-q", "master")
                    r.git("checkout", "-q", "-b", "B")
                    r.write("f." + ext, b)
                    r.write("u." + ext, user)
                    r.commit("B")
                    # Resolve by keeping only A's version of f — B's symbols are dropped
                    # while B's consumer u survives. This is the union-merge loss shape.
                    r.git("checkout", "-q", "master")
                    r.git("checkout", "-q", "A", "--", "f." + ext)
                    r.git("checkout", "-q", "B", "--", "u." + ext)
                    r.git("add", "-A")
                    r.git("commit", "-q", "--no-verify", "-m", "merge (auto-resolved)")
                    result = r.git("rev-parse", "HEAD").stdout.strip()
                    findings = dag.check_pair(r.path, "A", "B", merge_base=base,
                                              result_ref=result)
                    self.assertTrue(
                        [f for f in findings if f["code"] == "union_merge_symbol_loss"],
                        "%s: a symbol dropped from f but still imported by u is a silent "
                        "break and must be reported" % ext)
                finally:
                    r.destroy()

    def test_json_objects_are_analysable(self):
        syms = dag.symbols_of("locales/en.json", '{"a": 1, "b": {"c": 2}}')
        self.assertIsNotNone(syms, "JSON must be analysable or add/add on it is skipped")
        self.assertEqual({"a", "b"}, set(syms))


# ---------------------------------------------------------------------------
# HOLE 10 — end-to-end wiring
# ---------------------------------------------------------------------------

class TestGuardsAreActuallyWired(unittest.TestCase):
    """A guard that exists but is never called is the failure this session found twice."""

    def test_auto_conflict_resolver_calls_every_gate(self):
        import auto_conflict_resolver as acr
        for fn in ("_regression_check", "_divergent_check", "_stub_check", "_verify_merge"):
            self.assertTrue(hasattr(acr, fn), "auto_conflict_resolver must define %s" % fn)
        src = open(acr.__file__).read()
        self.assertNotIn(
            "findings = _regression_check(repo, pre_sha, branch)", src,
            "resolve_branch must call _verify_merge (all three gates), not the regression "
            "check alone — the add/add shape is invisible to a base-vs-result diff")
        self.assertGreaterEqual(
            src.count("_verify_merge(repo, pre_sha, base, branch)"), 2,
            "both the clean-merge and the auto-resolved commit paths must be verified")

    def test_merge_train_calls_every_gate(self):
        import merge_train
        src = open(merge_train.__file__).read()
        for call in ("_regression_gate(", "_divergent_gate(", "_stub_gate("):
            self.assertGreaterEqual(src.count(call), 2,
                                    "merge_train must define AND call %s" % call)

    def test_verify_merge_fails_closed_when_a_gate_raises(self):
        import auto_conflict_resolver as acr
        original = acr._regression_check
        try:
            def boom(*_a, **_k):
                raise RuntimeError("guard exploded")
            acr._regression_check = boom
            out = acr._verify_merge("/tmp", "abc", "master", "agent/x")
            self.assertTrue(out, "a crashing gate must reject the merge, not wave it through")
            self.assertIn("fail-closed", out)
        finally:
            acr._regression_check = original


# ---------------------------------------------------------------------------
# Pattern 3 — committed conflict markers, every tracked file type
# ---------------------------------------------------------------------------

class TestConflictMarkersEveryFileType(unittest.TestCase):
    """racefeed 601342b06 shipped markers into .gitignore on master."""

    def test_markers_block_in_every_file_type(self):
        for name, body in (("f.ts", "export const a = 1;\n"),
                           ("f.tsx", "export const A = () => 1;\n"),
                           ("f.vue", "<template><div/></template>\n"),
                           ("f.json", '{"a":1}\n'),
                           ("f.mjs", "export const a=1;\n"),
                           ("f.py", "a = 1\n"),
                           (".gitignore", "node_modules\n")):
            with self.subTest(path=name):
                r = _Repo()
                try:
                    r.write(name, body)
                    base = r.commit("init")
                    r.write(name, "<" * 7 + " HEAD\n" + body + "=" * 7 + "\n"
                            + body + ">" * 7 + " other\n")
                    r.commit("merge (auto-resolved)")
                    ok, findings = rg.check_merge(r.path, base, "HEAD")
                    self.assertFalse(ok, "%s: committed markers must block" % name)
                    self.assertTrue(any(f["kind"] == "conflict-marker" for f in findings))
                finally:
                    r.destroy()


# ---------------------------------------------------------------------------
# Patterns 1 + 2 — semantic_merge edit collisions
# ---------------------------------------------------------------------------

class TestSemanticMergeEditCollisions(unittest.TestCase):

    def test_two_edits_at_the_same_eof_anchor_conflict(self):
        """Pattern 1: `edits[i1] = ...` silently clobbered one side (improvement_miner)."""
        import semantic_merge
        base = ["def a():\n", "    return 1\n"]
        a = base + ["def b():\n", "    return 2\n"]
        b = base + ["def c():\n", "    return 3\n"]
        self.assertIsNone(
            semantic_merge._three_way_merge(base, a, b),
            "two different appends at the same EOF anchor must CONFLICT, never silently "
            "keep one side")

    def test_identical_append_from_both_sides_merges_once(self):
        import semantic_merge
        base = ["def a():\n", "    return 1\n"]
        both = base + ["import os\n"]
        merged = semantic_merge._three_way_merge(base, both, both)
        self.assertIsNotNone(merged, "agreement is not a conflict")
        self.assertEqual(1, merged.count("import os\n"), "the agreed edit lands exactly once")


if __name__ == "__main__":
    unittest.main(verbosity=2)

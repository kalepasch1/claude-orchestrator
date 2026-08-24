#!/usr/bin/env python3
"""PATCH_TEMPLATE_REGISTRY.md must not be able to drift from the tree.

The registry maps each patch-template hash to its owner module and acceptance test so a
repair pass can REUSE existing work instead of reconstructing it. Its own footer says
"When adding a new hash-scoped test, add a row here in the same commit" — and nothing
enforced that. The convention was kept in sync by grep, by hand.

It did not stay in sync. The commit at the head of master is literally
"fix(tests): a stub registry kept in sync by grep was not in sync, and 35 files paid for
it". A registry that silently goes stale is worse than no registry: a recovery pass looks
up a template, finds nothing, concludes the work does not exist, and rebuilds it — which
is the single most expensive failure mode this fleet has.

This is the check that makes the convention self-enforcing. It asserts BOTH directions:
every row points at things that exist, and every hash-scoped test file has a row. One
direction alone is how a registry rots — you notice the dangling rows and never notice
the missing ones.

Proof: python3 -m pytest runner/tests/test_patch_template_registry_integrity.py -q
"""
import os
import re
import sys
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.dirname(TESTS)
REPO = os.path.dirname(RUNNER)
sys.path.insert(0, RUNNER)

REGISTRY = os.path.join(TESTS, "PATCH_TEMPLATE_REGISTRY.md")

#: A template hash as the registry and the template bodies write it.
_HASH_RE = re.compile(r"\b([0-9a-f]{12})\b")

#: `runner/tests/test_template_<hash>.py` and the transplant variant
#: `test_patch_transplant_<name>_<hash>.py` are the two hash-scoped shapes in the tree.
_HASH_SCOPED_RE = re.compile(r"^test_(?:template_|patch_transplant_.*_)([0-9a-f]{7,12})\.py$")

#: Backtick-quoted paths in the registry, e.g. `runner/patch_templates.py`.
_PATH_RE = re.compile(r"`([\w./-]+\.(?:py|md))`")


def _registry_text():
    with open(REGISTRY, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _rows():
    """Parsed table rows: (template_id, [referenced paths])."""
    rows = []
    for line in _registry_text().splitlines():
        line = line.strip()
        if not line.startswith("|") or line.startswith("|--") or "Template id" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        found = _HASH_RE.search(cells[0])
        if not found:
            continue
        rows.append((found.group(1), _PATH_RE.findall(" ".join(cells[1:]))))
    return rows


def _hash_scoped_tests():
    """Test files whose NAME pins them to a template hash."""
    out = {}
    for name in sorted(os.listdir(TESTS)):
        m = _HASH_SCOPED_RE.match(name)
        if m:
            out[m.group(1)] = name
    return out


class TestRegistryIsParseable(unittest.TestCase):
    def test_the_registry_exists(self):
        self.assertTrue(os.path.isfile(REGISTRY), f"{REGISTRY} is missing")

    def test_it_has_rows(self):
        self.assertTrue(_rows(), "registry table parsed to zero rows; the format moved "
                                 "and this check would silently pass forever")

    def test_template_ids_are_unique(self):
        ids = [tid for tid, _ in _rows()]
        self.assertEqual(len(ids), len(set(ids)), f"duplicate registry rows: {ids}")

    def test_it_still_states_the_convention_it_enforces(self):
        self.assertIn("add a row here in the same commit", _registry_text())


class TestNoDanglingRows(unittest.TestCase):
    """Direction 1: every row points at something that exists."""

    def test_every_referenced_file_exists(self):
        missing = []
        for tid, paths in _rows():
            for path in paths:
                full = path if os.path.isabs(path) else os.path.join(REPO, path)
                if not os.path.isfile(full):
                    missing.append(f"{tid} -> {path}")
        self.assertEqual([], missing,
                         "registry rows point at files that do not exist: "
                         + "; ".join(missing))

    def test_every_row_names_an_acceptance_test(self):
        for tid, paths in _rows():
            self.assertTrue(any("tests/" in p and p.endswith(".py") for p in paths),
                            f"row {tid} names no acceptance test")

    def test_every_row_names_an_owner_module(self):
        for tid, paths in _rows():
            self.assertTrue(any(p.startswith("runner/") and "tests/" not in p
                                for p in paths),
                            f"row {tid} names no owner module")


class TestNoUnregisteredTests(unittest.TestCase):
    """Direction 2 — the one that actually rots. A hash-scoped test with no row is
    invisible to the reuse path, so the work it proves gets rebuilt from scratch."""

    def test_every_hash_scoped_test_has_a_registry_row(self):
        registered = {tid for tid, _ in _rows()}
        orphans = []
        for short_hash, filename in _hash_scoped_tests().items():
            if not any(tid.startswith(short_hash) or short_hash.startswith(tid[:7])
                       for tid in registered):
                orphans.append(f"{filename} (hash {short_hash})")
        self.assertEqual(
            [], orphans,
            "hash-scoped tests with no registry row: " + "; ".join(orphans)
            + ". Add a row to runner/tests/PATCH_TEMPLATE_REGISTRY.md in the same commit, "
              "or a recovery pass will conclude this work does not exist and rebuild it.")

    def test_the_scan_actually_finds_the_known_hash_scoped_tests(self):
        """Guard the guard: if the naming convention moves, this check must fail loudly
        rather than pass by finding nothing."""
        found = _hash_scoped_tests()
        self.assertTrue(found, "no hash-scoped tests matched; the filename convention "
                               "changed and this check became a no-op")
        self.assertIn("95fc17a", found)


class TestRegistryPointsAtRealTemplates(unittest.TestCase):
    def test_each_registered_hash_resolves(self):
        """A row is only useful if patch_templates can actually resolve the id.

        Fail-soft on the store: with no DB and no local JSONL there is nothing to
        resolve against, and asserting otherwise would make this check depend on
        someone else's uptime — the thing the hermetic test guard exists to prevent.
        """
        import patch_templates
        unresolved = []
        for tid, _ in _rows():
            try:
                got = patch_templates.lookup(tid)
            except Exception:
                got = None
            # lookup() signals "not found" with an empty mapping, not None — checking
            # `is None` would treat every miss as a hit and make this assertion vacuous.
            if not got:
                unresolved.append(tid)
        if len(unresolved) == len(_rows()):
            self.skipTest("no template store reachable; nothing to resolve against")
        self.assertEqual([], unresolved,
                         f"registered but unresolvable template ids: {unresolved}")

    def test_lookup_is_fail_soft_on_an_unknown_id(self):
        """Miss is an empty mapping, not None and not an exception. Pinned because the
        registry check above depends on being able to tell a miss from a hit."""
        import patch_templates
        self.assertFalse(patch_templates.lookup("ffffffffffff"))

    def test_lookup_is_fail_soft_on_junk(self):
        import patch_templates
        for bad in (None, "", 7, [], {}):
            try:
                self.assertFalse(patch_templates.lookup(bad), bad)
            except Exception as e:  # pragma: no cover
                self.fail(f"lookup({bad!r}) raised {e}")


if __name__ == "__main__":
    unittest.main()

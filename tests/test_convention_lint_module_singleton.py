"""Rule 3 (MODULE_SINGLETON) must actually fire.

CONVENTION_LINT.md listed the module-level singleton rule in the Phase 1 set and
then stated, in the same file, that "detection is not fully implemented ... does
not currently flag violations". A documented rule that never fires is worse than
an absent one: the docs claim coverage the gate does not provide.

These tests pin both halves of the contract — that a real violation is reported,
and that the shapes which made the first draft unusable (imported infrastructure
primitives, constants, public names, delegated singletons) stay silent.
"""
import os
import sys
import textwrap

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "tools"))

import convention_lint as cl  # noqa: E402


def _rules(tmp_path, source, name="mod.py"):
    path = tmp_path / name
    path.write_text(textwrap.dedent(source))
    return [v for v in cl.check_file(str(path)) if v.rule == "MODULE_SINGLETON"]


VIOLATION = """
    class ResourcePool:
        def acquire(self):
            return 1

    _pool = ResourcePool()

    def unrelated():
        return 2
"""


def test_singleton_without_a_delegator_is_flagged():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        import pathlib
        found = _rules(pathlib.Path(tmp), VIOLATION)
    assert len(found) == 1
    assert "_pool" in found[0].message
    assert "ResourcePool" in found[0].message


def test_reported_as_a_warning_so_it_cannot_block_a_commit(tmp_path):
    found = _rules(tmp_path, VIOLATION)
    assert found[0].severity == "warning"


def test_delegating_module_function_clears_it(tmp_path):
    """The documented pass shape: acquire() -> _pool.acquire()."""
    assert _rules(tmp_path, """
        class ResourcePool:
            def acquire(self):
                return 1

        _pool = ResourcePool()

        def acquire():
            return _pool.acquire()
    """) == []


def test_global_rebinding_counts_as_delegation(tmp_path):
    """Lazy init via `global _pool` is the other documented spelling."""
    assert _rules(tmp_path, """
        class ResourcePool:
            pass

        _pool = ResourcePool()

        def reset():
            global _pool
            _pool = ResourcePool()
    """) == []


def test_imported_infrastructure_is_not_a_singleton(tmp_path):
    """threading.Lock / logging handlers / fake modules are not owned by the module.

    The looser 'any PascalCase call' draft reported 15 violations across
    runner/, tools/ and lib/, essentially all of this shape.
    """
    assert _rules(tmp_path, """
        import logging
        import threading
        from types import ModuleType

        class Thing:
            pass

        _lock = threading.Lock()
        _handler = logging.StreamHandler()
        _fake_db = ModuleType("db")

        def go():
            return Thing()
    """) == []


def test_public_module_state_is_untouched(tmp_path):
    assert _rules(tmp_path, """
        class ResourcePool:
            pass

        pool = ResourcePool()

        def unrelated():
            return 1
    """) == []


def test_screaming_case_is_a_constant_not_a_singleton(tmp_path):
    assert _rules(tmp_path, """
        class Registry:
            pass

        _REGISTRY = Registry()

        def unrelated():
            return 1
    """) == []


def test_pure_class_module_is_skipped(tmp_path):
    """No module-level functions means the convention has nothing to say."""
    assert _rules(tmp_path, """
        class ResourcePool:
            pass

        _pool = ResourcePool()
    """) == []


def test_non_call_assignment_is_not_a_singleton(tmp_path):
    assert _rules(tmp_path, """
        class ResourcePool:
            pass

        _cache = {}
        _pool = None

        def unrelated():
            return 1
    """) == []


def test_noqa_suppresses_the_rule(tmp_path):
    """Same escape hatch every other rule honours (CONVENTION_LINT.md)."""
    found = _rules(tmp_path, """
        class ResourcePool:
            pass

        _pool = ResourcePool()  # noqa: MODULE_SINGLETON

        def unrelated():
            return 1
    """)
    assert found == []


def test_rule_is_documented_as_implemented():
    """The docs must not keep claiming this rule does not flag violations."""
    doc = open(os.path.join(_REPO, "CONVENTION_LINT.md")).read()
    assert "detection is not fully implemented" not in doc

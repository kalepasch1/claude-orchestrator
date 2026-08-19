"""import_with_env must not leave the shared module rebound.

env_during_import exists because `os.environ["ORCH_X"] = "true"` at the top of a test file
leaks process-wide: pytest imports every test module during COLLECTION, before any fixture
runs, so conftest's per-test env restore cannot undo it -- the pollution is already inside
the snapshot it takes.

Its first implementation reintroduced the same bug one layer down. It ended with
`importlib.reload(module)`, and reload mutates the module object IN PLACE, so the constants
it rebinds are rebound for every module already holding that object, for the rest of the
process. Concretely: semantic_merge._ENABLED defaults TRUE, test_semantic_merge.py imports
it with ORCH_SEMANTIC_MERGE="false", and five other modules then ran with semantic merging
silently disabled -- during collection, so before a single test had executed.

The failure signature is the one this whole mechanism was built to stop: green standalone,
red in the release canary. It was harder to spot only because the offending line looks like
the fix.
"""
import importlib
import os
import sys
import textwrap

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from env_during_import import during_import, import_with_env  # noqa: E402


@pytest.fixture
def flagged_module(tmp_path, monkeypatch):
    """A throwaway module that binds a constant from the environment at import time."""
    name = "envimport_probe_mod"
    (tmp_path / f"{name}.py").write_text(textwrap.dedent("""
        import os
        ENABLED = os.environ.get("ORCH_PROBE_FLAG", "true").lower() == "true"
        SEEN = os.environ.get("ORCH_PROBE_VALUE", "default")
    """))
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop(name, None)
    try:
        yield name
    finally:
        sys.modules.pop(name, None)
        importlib.invalidate_caches()


# --- what it must do --------------------------------------------------------------------

def test_the_returned_module_sees_the_requested_value(flagged_module):
    mod = import_with_env(flagged_module, ORCH_PROBE_FLAG="false")
    assert mod.ENABLED is False


def test_it_works_when_the_module_was_already_imported(flagged_module):
    """The reason reload() was there at all -- rebinding must still happen."""
    importlib.import_module(flagged_module)          # first import: default true

    mod = import_with_env(flagged_module, ORCH_PROBE_FLAG="false")

    assert mod.ENABLED is False


def test_the_environment_is_restored(flagged_module):
    import_with_env(flagged_module, ORCH_PROBE_FLAG="false")
    assert "ORCH_PROBE_FLAG" not in os.environ


def test_a_pre_existing_value_is_put_back_not_dropped(flagged_module, monkeypatch):
    monkeypatch.setenv("ORCH_PROBE_FLAG", "original")
    import_with_env(flagged_module, ORCH_PROBE_FLAG="false")
    assert os.environ["ORCH_PROBE_FLAG"] == "original"


# --- what it must NOT do ----------------------------------------------------------------

def test_the_already_imported_module_is_not_rebound(flagged_module):
    """THE defect. reload() mutated in place, so this object flipped too."""
    shared = importlib.import_module(flagged_module)
    assert shared.ENABLED is True

    private = import_with_env(flagged_module, ORCH_PROBE_FLAG="false")

    assert private.ENABLED is False, "the caller must get the value it asked for"
    assert shared.ENABLED is True, (
        "import_with_env rebound the SHARED module — every other importer now runs with a "
        "flag it never set, for the rest of the process")


def test_the_two_objects_are_genuinely_distinct(flagged_module):
    shared = importlib.import_module(flagged_module)
    private = import_with_env(flagged_module, ORCH_PROBE_FLAG="false")
    assert private is not shared


def test_sys_modules_still_holds_the_original_afterwards(flagged_module):
    """A later plain `import x` anywhere must not pick up the test's private copy."""
    shared = importlib.import_module(flagged_module)

    import_with_env(flagged_module, ORCH_PROBE_FLAG="false")

    assert sys.modules[flagged_module] is shared
    assert importlib.import_module(flagged_module) is shared


def test_a_module_that_was_not_imported_before_is_not_left_registered(flagged_module):
    """Otherwise the private copy becomes the shared one for everything imported later."""
    assert flagged_module not in sys.modules

    import_with_env(flagged_module, ORCH_PROBE_FLAG="false")

    assert flagged_module not in sys.modules


def test_a_failing_import_still_restores_sys_modules(flagged_module, tmp_path):
    """A half-built module left under a name other code imports is worse than the leak."""
    shared = importlib.import_module(flagged_module)
    (tmp_path / f"{flagged_module}.py").write_text("raise RuntimeError('boom')")
    importlib.invalidate_caches()

    with pytest.raises(RuntimeError):
        import_with_env(flagged_module, ORCH_PROBE_FLAG="false")

    assert sys.modules[flagged_module] is shared
    assert "ORCH_PROBE_FLAG" not in os.environ, "and the env must be restored too"


# --- the real case that was broken ------------------------------------------------------

def test_semantic_merge_is_not_left_disabled_for_the_session():
    """The concrete regression: _ENABLED defaults true and was being flipped at collection.

    Imported the same way test_semantic_merge.py does it, then checked against a plain
    import -- which is what merge_train and friends get.
    """
    semantic_merge = importlib.import_module("semantic_merge")
    before = getattr(semantic_merge, "_ENABLED", None)
    if before is None:
        pytest.skip("semantic_merge no longer exposes _ENABLED")

    import_with_env("semantic_merge", ORCH_SEMANTIC_MERGE="false")

    assert importlib.import_module("semantic_merge")._ENABLED == before


# --- during_import itself ---------------------------------------------------------------

def test_during_import_removes_a_variable_that_was_absent():
    assert "ORCH_PROBE_ONLY_HERE" not in os.environ
    with during_import(ORCH_PROBE_ONLY_HERE="1"):
        assert os.environ["ORCH_PROBE_ONLY_HERE"] == "1"
    assert "ORCH_PROBE_ONLY_HERE" not in os.environ


def test_during_import_restores_even_when_the_body_raises():
    with pytest.raises(ValueError):
        with during_import(ORCH_PROBE_ONLY_HERE="1"):
            raise ValueError("boom")
    assert "ORCH_PROBE_ONLY_HERE" not in os.environ

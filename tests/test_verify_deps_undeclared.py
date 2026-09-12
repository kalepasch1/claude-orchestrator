"""The dependency manifest is now checked in BOTH directions.

`scripts/verify_deps.py` only proved that what IS declared can be imported. It said
nothing about a third-party module that `runner/` imports and the manifest never
mentions — which is precisely the failure requirements.txt's own header describes: a
fresh clone ran `pip install -r requirements.txt` and still could not import large parts
of runner/. That direction was unverified, so the manifest could rot again the moment
anyone added an import.

These tests pin the new check AND its exclusions, because a noisy check gets switched off:
stdlib, local modules, guarded (optional) imports and test files must never be reported.
"""
import os
import sys
import textwrap

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import verify_deps as vd  # noqa: E402


def _write(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


# --- import extraction ------------------------------------------------------------------

def test_plain_imports_are_found(tmp_path):
    path = _write(tmp_path, "m.py", """
        import requests
        from yaml import safe_load
        import os.path
    """)
    assert vd.imported_top_level(path) == {"requests", "yaml", "os"}


def test_a_guarded_import_is_optional_and_excluded(tmp_path):
    """`try: import x` is this repo's fail-soft convention — not a required dependency."""
    path = _write(tmp_path, "m.py", """
        try:
            import redis
        except ImportError:
            redis = None
    """)
    assert vd.imported_top_level(path) == set()
    assert "redis" in vd.imported_top_level(path, include_guarded=True)


def test_relative_imports_are_never_reported(tmp_path):
    path = _write(tmp_path, "m.py", "from . import sibling\nfrom .pkg import thing\n")
    assert vd.imported_top_level(path) == set()


def test_unparseable_file_is_fail_soft(tmp_path):
    path = _write(tmp_path, "broken.py", "def (:\n")
    assert vd.imported_top_level(path) == set()


def test_missing_file_is_fail_soft(tmp_path):
    assert vd.imported_top_level(tmp_path / "nope.py") == set()


# --- classification -----------------------------------------------------------------------

@pytest.mark.parametrize("module", ["os", "sys", "json", "math", "fcntl", "ast", "re"])
def test_stdlib_modules_are_recognised(module):
    """`math` and `fcntl` are compiled extensions — the 3.9 fallback missed them."""
    assert module in vd._stdlib_modules(), f"{module} misclassified as third-party"


@pytest.mark.parametrize("module", ["db", "canary", "runner", "convention_lint"])
def test_repo_modules_are_recognised_as_local(module):
    """Includes modules nested one level down (runner/tests, tools/)."""
    assert module in vd.local_module_names()


def test_local_scan_is_recursive():
    names = vd.local_module_names()
    assert "hivemind_v15" in names
    assert len(names) > 100, "a shallow scan would report hundreds of false positives"


# --- the check itself ---------------------------------------------------------------------

def test_the_live_manifest_is_complete():
    """The acceptance criterion: no undeclared runtime dependency in runner/."""
    assert vd.undeclared_imports() == []


def test_an_undeclared_dependency_is_caught(tmp_path, monkeypatch):
    """The check must actually be able to fail, or it proves nothing."""
    pkg = tmp_path / "fakepkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text("import totally_not_a_real_distribution\n", encoding="utf-8")
    monkeypatch.setattr(vd, "REPO_ROOT", tmp_path)

    found = vd.undeclared_imports(package_dirs=("fakepkg",))
    assert len(found) == 1
    assert "totally_not_a_real_distribution" in found[0]
    assert "not in any requirements file" in found[0]


def test_a_declared_dependency_is_not_reported(tmp_path, monkeypatch):
    pkg = tmp_path / "fakepkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text("import requests\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("requests>=2.28\n", encoding="utf-8")
    monkeypatch.setattr(vd, "REPO_ROOT", tmp_path)
    assert vd.undeclared_imports(package_dirs=("fakepkg",)) == []


def test_a_distribution_named_differently_from_its_module_is_matched(tmp_path, monkeypatch):
    """PyYAML declares `PyYAML`; the code imports `yaml`."""
    pkg = tmp_path / "fakepkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text("import yaml\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("PyYAML>=6.0\n", encoding="utf-8")
    monkeypatch.setattr(vd, "REPO_ROOT", tmp_path)
    assert vd.undeclared_imports(package_dirs=("fakepkg",)) == []


def test_test_files_are_excluded_from_the_runtime_check(tmp_path, monkeypatch):
    """A test importing a missing module is a broken test, not a missing distribution."""
    tests = tmp_path / "fakepkg" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_x.py").write_text("import nonexistent_helper\n", encoding="utf-8")
    monkeypatch.setattr(vd, "REPO_ROOT", tmp_path)
    assert vd.undeclared_imports(package_dirs=("fakepkg",)) == []


def test_missing_directory_is_fail_soft(tmp_path, monkeypatch):
    monkeypatch.setattr(vd, "REPO_ROOT", tmp_path)
    assert vd.undeclared_imports(package_dirs=("does_not_exist",)) == []

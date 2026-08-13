"""pareto — 2080 life-goal autonomy stack.

WHY THIS FILE HAS CODE IN IT
----------------------------
The stack lives under `pareto/2080/`, and '2080' is not a valid Python
identifier, so `import pareto.2080.household_legal` is a SyntaxError — the
package is unreachable by dotted path no matter what is on sys.path. The repo
has worked around that per-module (put the directory on sys.path, import by
bare name: see pareto/2080/contracts/test_contracts_smoke.py, household_legal/
doc_updater.py, household_legal/test_household_legal.py), which is fine inside
the tree but leaves no importable name for anything outside it.

This registers the subpackages under spellable aliases — `pareto.household_legal`,
`pareto.contracts` — so external callers get an ordinary import. The bare-name
convention inside `pareto/2080/` is untouched and keeps working.

Registration is EAGER, and that is deliberate. A PEP 562 `__getattr__` would be
lazier, but it is not consulted by `from pareto.household_legal import x`: that
statement resolves the submodule through the import machinery, which checks
`sys.modules` and the package `__path__` and raises ModuleNotFoundError before
any `__getattr__` on the parent runs. Populating `sys.modules` up front is what
makes the ordinary `from ... import ...` spelling work.

It is also fail-soft. One subpackage that cannot import must not take `import
pareto` down with it, so a failure is recorded in `_ALIAS_ERRORS` and re-raised
only if someone actually asks for that alias.
"""
import importlib.util
import os
import sys

_STACK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "2080")

#: alias exposed on `pareto` -> directory name under pareto/2080/
_ALIASES = {
    "household_legal": "household_legal",
    "contracts": "contracts",
}

__all__ = list(_ALIASES)

#: alias -> the exception that stopped it importing. Empty when all is well.
_ALIAS_ERRORS = {}


def _load(alias: str, dirname: str):
    """Import pareto/2080/<dirname> and register it as pareto.<alias>."""
    full_name = f"{__name__}.{alias}"
    existing = sys.modules.get(full_name)
    if existing is not None:
        return existing

    init_py = os.path.join(_STACK_DIR, dirname, "__init__.py")
    if not os.path.isfile(init_py):
        raise ImportError(f"no such subpackage: {full_name} ({init_py} missing)")

    spec = importlib.util.spec_from_file_location(
        full_name, init_py, submodule_search_locations=[os.path.join(_STACK_DIR, dirname)]
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not build a spec for {full_name}")

    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec so a subpackage that imports itself (or is imported
    # twice concurrently) sees the partially-initialised module rather than
    # recursing, which is what the normal import machinery does.
    sys.modules[full_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(full_name, None)
        raise
    setattr(sys.modules[__name__], alias, module)
    return module


for _alias, _dirname in _ALIASES.items():
    try:
        _load(_alias, _dirname)
    except Exception as _exc:                                   # fail-soft
        # Recorded, not raised: a broken subpackage must not make `import
        # pareto` fail for everything else in the tree.
        _ALIAS_ERRORS[_alias] = _exc
del _alias, _dirname


def __getattr__(name: str):
    """Retry a subpackage that failed at import time, and report why if it still fails."""
    dirname = _ALIASES.get(name)
    if dirname is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    try:
        return _load(name, dirname)
    except Exception as exc:
        earlier = _ALIAS_ERRORS.get(name)
        raise ImportError(f"pareto.{name} is unavailable: {earlier or exc}") from exc


def __dir__():
    return sorted(set(list(globals()) + __all__))

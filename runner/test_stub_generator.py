#!/usr/bin/env python3
"""
test_stub_generator.py — generate test stub files for untested runner modules.

Complements test_discovery.py by creating minimal pytest test files for
modules that lack tests. Each stub imports the module, verifies it loads
without error, and includes placeholder test functions for public callables.

Env vars:
    ORCH_TEST_STUB_ENABLED    "true" to enable (default "true")
    ORCH_RUNNER_DIR            path to runner directory (auto-detected)
    ORCH_TESTS_DIR             path to tests directory (auto-detected)
"""
import os
import sys
import inspect
import importlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ENABLED = os.environ.get("ORCH_TEST_STUB_ENABLED", "true").lower() in ("1", "true", "yes")
RUNNER_DIR = os.environ.get("ORCH_RUNNER_DIR", os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.environ.get("ORCH_TESTS_DIR",
                           os.path.join(os.path.dirname(RUNNER_DIR), "tests"))


def _get_public_callables(module_name):
    """Try to import module and return list of public callable names."""
    try:
        mod = importlib.import_module(module_name)
        return [name for name, obj in inspect.getmembers(mod)
                if callable(obj) and not name.startswith("_")]
    except Exception:
        return []


def generate_stub(module_name, output_dir=None):
    """Generate a pytest test stub for the given module.

    Returns the generated test file content as a string.
    """
    output_dir = output_dir or TESTS_DIR
    callables = _get_public_callables(module_name)

    lines = [
        f'"""Auto-generated test stub for {module_name}."""',
        "",
        "import sys",
        "import os",
        "import types",
        "",
        "# Ensure runner/ is importable",
        'sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runner"))',
        "",
        "# Mock db module to avoid database dependency",
        'mock_db = types.ModuleType("db")',
        "mock_db.select = lambda *a, **kw: []",
        "mock_db.insert = lambda *a, **kw: {}",
        "mock_db.upsert = lambda *a, **kw: {}",
        "mock_db.count = lambda *a, **kw: 0",
        'sys.modules.setdefault("db", mock_db)',
        "",
    ]
    lines.append(f"")
    lines.append(f"def test_{module_name}_imports():")
    lines.append(f'    """Verify {module_name} loads without error."""')
    lines.append(f"    import {module_name}  # noqa: F401")
    lines.append(f"    assert True")
    lines.append("")

    for fn_name in callables[:10]:  # cap at 10 stubs
        lines.append(f"")
        lines.append(f"def test_{module_name}_{fn_name}():")
        lines.append(f'    """Stub test for {module_name}.{fn_name}."""')
        lines.append(f"    import {module_name}")
        lines.append(f"    assert hasattr({module_name}, '{fn_name}')")
        lines.append(f"    assert callable({module_name}.{fn_name})")

    return "\n".join(lines) + "\n"


def generate_missing_stubs(runner_dir=None, tests_dir=None, dry_run=True):
    """Generate test stubs for all untested modules.

    Returns dict with 'generated': list of filenames, 'skipped': int.
    """
    try:
        import test_discovery
    except ImportError:
        return {"generated": [], "skipped": 0, "error": "test_discovery not available"}

    gaps = test_discovery.coverage_gaps(runner_dir, tests_dir)
    td = tests_dir or TESTS_DIR
    generated = []
    skipped = 0

    for module_name in gaps:
        test_file = os.path.join(td, f"test_{module_name}.py")
        if os.path.exists(test_file):
            skipped += 1
            continue
        content = generate_stub(module_name, td)
        if not dry_run:
            os.makedirs(td, exist_ok=True)
            with open(test_file, "w") as f:
                f.write(content)
        generated.append(f"test_{module_name}.py")

    return {"generated": generated, "skipped": skipped, "dry_run": dry_run}


def run():
    """CLI entry point — report what stubs would be generated."""
    if not ENABLED:
        print("test_stub_generator: disabled")
        return {}
    result = generate_missing_stubs(dry_run=True)
    print(f"test_stub_generator: {len(result['generated'])} stubs would be generated")
    if result["generated"]:
        print(f"  files: {', '.join(result['generated'][:10])}")
    return result


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))

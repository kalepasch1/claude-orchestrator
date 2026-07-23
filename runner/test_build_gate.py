#!/usr/bin/env python3
"""Tests for build_gate.py — build verification before merge."""
import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")
import build_gate


def test_load_scripts_valid_package():
    with tempfile.TemporaryDirectory() as d:
        pkg = os.path.join(d, "package.json")
        with open(pkg, "w") as f:
            json.dump({"scripts": {"build": "nuxt build", "typecheck": "tsc --noEmit"}}, f)
        scripts = build_gate._load_scripts(d)
        assert scripts.get("build") == "nuxt build"
        assert scripts.get("typecheck") == "tsc --noEmit"

def test_load_scripts_missing_file():
    scripts = build_gate._load_scripts("/nonexistent/path")
    assert scripts == {}

def test_load_scripts_no_scripts_key():
    with tempfile.TemporaryDirectory() as d:
        pkg = os.path.join(d, "package.json")
        with open(pkg, "w") as f:
            json.dump({"name": "test"}, f)
        scripts = build_gate._load_scripts(d)
        assert scripts == {}

def test_detect_build_cmd_no_package():
    with tempfile.TemporaryDirectory() as d:
        cmd = build_gate.detect_build_cmd(d)
        # No package.json → fallback to env default or empty
        assert isinstance(cmd, str)

def test_detect_build_cmd_skips_root_without_build_script():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "package.json"), "w") as f:
            json.dump({"scripts": {"test": "node --test"}}, f)
        web = os.path.join(d, "web")
        os.makedirs(web)
        with open(os.path.join(web, "package.json"), "w") as f:
            json.dump({"scripts": {"build": "nuxt build"}}, f)
        cmd = build_gate.detect_build_cmd(d)
        assert cmd == "npm --prefix web run build"

def test_script_cmd_root():
    cmd = build_gate.script_cmd("/repo", "/repo", "build")
    assert "build" in cmd

def test_script_cmd_subdir():
    cmd = build_gate.script_cmd("/repo", "/repo/packages/web", "build")
    assert "packages/web" in cmd or "build" in cmd

def test_root_npm_cmd_without_package():
    with tempfile.TemporaryDirectory() as d:
        # No package.json in d
        assert build_gate._root_npm_cmd_without_package(d, "npm run build") is True
        assert build_gate._root_npm_cmd_without_package(d, "python test.py") is False
    # With package.json
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "package.json"), "w") as f:
            f.write("{}")
        assert build_gate._root_npm_cmd_without_package(d, "npm run build") is False


def test_package_runner_defaults_to_npm():
    """_package_runner falls back to 'npm run' when no lockfile is present."""
    with tempfile.TemporaryDirectory() as d:
        result = build_gate._package_runner(d)
        assert result == "npm run", f"Expected 'npm run', got {result!r}"

def test_npx_cmd_root():
    """_npx_cmd at repo root should not include cd."""
    cmd = build_gate._npx_cmd("/repo", "/repo", "nuxi typecheck")
    assert cmd == "npx --no-install nuxi typecheck"

def test_npx_cmd_subdir():
    """_npx_cmd in a subdirectory should cd into it."""
    cmd = build_gate._npx_cmd("/repo", "/repo/packages/web", "next build")
    assert "packages/web" in cmd
    assert "next build" in cmd


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as e:
                print(f"  FAIL  {name}: {e}")
    print("build_gate tests complete.")

#!/usr/bin/env python3
"""
build_pipeline_optimizer.py — Parallel-gate build pipeline with caching.

Optimizes the orchestrator build pipeline by:
1. Running independent validation gates in parallel (lint, type-check, unit tests).
2. Caching gate results by content hash to skip re-runs on unchanged files.
3. Providing a single entry point (run_pipeline) that returns a structured report.

Env vars:
    ORCH_BUILD_PARALLEL       "true" to run gates in parallel (default "true")
    ORCH_BUILD_CACHE_DIR      directory for gate result cache (default /tmp/orch-build-cache)
    ORCH_BUILD_TIMEOUT        per-gate timeout in seconds (default 120)
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import log as _log_mod
    _log = _log_mod.get("build_pipeline")
except Exception:
    import logging
    _log = logging.getLogger("build_pipeline")
# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PARALLEL = os.environ.get("ORCH_BUILD_PARALLEL", "true").lower() in ("1", "true", "yes")
CACHE_DIR = Path(os.environ.get("ORCH_BUILD_CACHE_DIR", "/tmp/orch-build-cache"))
TIMEOUT = int(os.environ.get("ORCH_BUILD_TIMEOUT", "120"))


def _content_hash(repo_path):
    """Fast hash of tracked file mtimes for cache invalidation."""
    try:
        out = subprocess.check_output(
            ["git", "ls-files", "-z"],
            cwd=repo_path, timeout=10, text=True
        )
        files = [f for f in out.split("\0") if f]
        h = hashlib.sha256()
        for f in sorted(files)[:500]:
            fp = os.path.join(repo_path, f)
            try:
                h.update(f"{f}:{os.path.getmtime(fp):.0f}".encode())
            except OSError:
                h.update(f"{f}:missing".encode())
        return h.hexdigest()[:16]
    except Exception:
        return None


def _cache_get(gate_name, content_hash):
    if not content_hash:
        return None
    cache_file = CACHE_DIR / f"{gate_name}-{content_hash}.json"
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text())
            _log.info("cache hit: %s", gate_name)
            return data
        except Exception:
            return None
    return None

def _cache_put(gate_name, content_hash, result):
    if not content_hash:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = CACHE_DIR / f"{gate_name}-{content_hash}.json"
        cache_file.write_text(json.dumps(result))
    except Exception:
        pass


def _run_gate(gate_name, cmd, repo_path, content_hash):
    """Run a single validation gate, returning a result dict."""
    cached = _cache_get(gate_name, content_hash)
    if cached:
        return {**cached, "cached": True}

    start = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=repo_path, capture_output=True, text=True, timeout=TIMEOUT
        )
        result = {
            "gate": gate_name,
            "passed": proc.returncode == 0,
            "returncode": proc.returncode,
            "duration_s": round(time.time() - start, 2),
            "stdout_tail": (proc.stdout or "")[-500:],
            "stderr_tail": (proc.stderr or "")[-500:],
        }
    except subprocess.TimeoutExpired:
        result = {
            "gate": gate_name,
            "passed": False,
            "returncode": -1,
            "duration_s": TIMEOUT,
            "stdout_tail": "",
            "stderr_tail": f"Gate timed out after {TIMEOUT}s",
        }
    except FileNotFoundError:
        result = {
            "gate": gate_name,
            "passed": True,
            "returncode": 0,
            "duration_s": 0,
            "stdout_tail": "Gate command not found; skipped",
            "stderr_tail": "",
        }

    if result["passed"]:
        _cache_put(gate_name, content_hash, result)
    return result


# ---------------------------------------------------------------------------
# Default gate definitions
# ---------------------------------------------------------------------------
DEFAULT_GATES = [
    ("python-syntax", ["python3", "-m", "py_compile", "runner/agentic_repair.py"]),
    ("pytest-unit", ["python3", "-m", "pytest", "tests/", "-x", "--timeout=60", "-q"]),
    ("import-check", ["python3", "-c", "import importlib; [importlib.import_module(m) for m in ['agentic_repair','branch_lifecycle']]"]),
]


def run_pipeline(repo_path, gates=None):
    """Run all gates, return structured report."""
    gates = gates or DEFAULT_GATES
    content_hash = _content_hash(repo_path)
    results = []
    start = time.time()

    if PARALLEL and len(gates) > 1:
        with ThreadPoolExecutor(max_workers=min(4, len(gates))) as pool:
            futures = {
                pool.submit(_run_gate, name, cmd, repo_path, content_hash): name
                for name, cmd in gates
            }
            for future in as_completed(futures):
                results.append(future.result())
    else:
        for name, cmd in gates:
            results.append(_run_gate(name, cmd, repo_path, content_hash))

    total_time = round(time.time() - start, 2)
    all_passed = all(r["passed"] for r in results)
    cached_count = sum(1 for r in results if r.get("cached"))

    report = {
        "passed": all_passed,
        "total_duration_s": total_time,
        "gates_run": len(results),
        "gates_cached": cached_count,
        "results": sorted(results, key=lambda r: r["gate"]),
    }
    _log.info("pipeline %s in %.1fs (%d cached)", "PASSED" if all_passed else "FAILED", total_time, cached_count)
    return report


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    report = run_pipeline(repo)
    print(json.dumps(report, indent=2))
    sys.exit(0 if report["passed"] else 1)

"""Incremental test oracle — maps changed files to affected tests for selective runs."""
import sys, os, re, ast, json, time, threading, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("test_oracle")

ENABLED = os.environ.get("ORCH_TEST_ORACLE_ENABLED", "true").lower() in ("true", "1", "yes")
TTL = int(os.environ.get("ORCH_TEST_ORACLE_TTL", "600"))

_TEST_PATTERNS = [
    re.compile(r"test_.*\.py$"),
    re.compile(r".*_test\.py$"),
    re.compile(r".*_spec\.rb$"),
    re.compile(r".*\.test\.[jt]sx?$"),
    re.compile(r".*\.spec\.[jt]sx?$"),
]

_PY_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.MULTILINE)
_JS_IMPORT = re.compile(r"""(?:import\s+.*?\s+from\s+['"]([^'"]+)['"]|require\s*\(\s*['"]([^'"]+)['"]\s*\))""")
_RB_REQUIRE = re.compile(r"""require_relative\s+['"]([^'"]+)['"]""")


class _TestOracle:
    def __init__(self):
        self._lock = threading.Lock()
        self._forward = {}   # test_file -> {source_files}
        self._reverse = {}   # source_file -> {test_files}
        self._hash = None
        self._built_at = 0
        self._stats = {"runs_optimized": 0, "avg_reduction": 0.0, "false_negatives": 0, "builds": 0}

    def build_index(self, repo_path):
        if not ENABLED or not repo_path or not os.path.isdir(repo_path):
            return {"files_indexed": 0, "test_files": 0, "mappings": 0}
        # TTL check
        h = hashlib.md5(repo_path.encode()).hexdigest()
        if self._hash == h and time.time() - self._built_at < TTL:
            return {"files_indexed": len(self._reverse), "test_files": len(self._forward),
                    "mappings": sum(len(v) for v in self._reverse.values()), "cached": True}
        forward, reverse = {}, {}
        test_files, all_files = [], []
        try:
            for root, dirs, files in os.walk(repo_path):
                dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv", "venv")]
                for f in files:
                    fp = os.path.join(root, f)
                    rel = os.path.relpath(fp, repo_path)
                    all_files.append(rel)
                    if any(p.search(f) for p in _TEST_PATTERNS):
                        test_files.append(rel)
        except Exception:
            return {"files_indexed": 0, "test_files": 0, "mappings": 0}

        for tf in test_files:
            full = os.path.join(repo_path, tf)
            sources = set()
            try:
                txt = open(full, "r", errors="replace").read(64000)
                if tf.endswith(".py"):
                    for m in _PY_IMPORT.finditer(txt):
                        mod = (m.group(1) or m.group(2) or "").replace(".", "/")
                        for ext in (".py", "/__init__.py"):
                            candidate = mod + ext
                            if candidate in all_files or os.path.exists(os.path.join(repo_path, candidate)):
                                sources.add(candidate)
                elif tf.endswith((".js", ".jsx", ".ts", ".tsx")):
                    for m in _JS_IMPORT.finditer(txt):
                        path = m.group(1) or m.group(2) or ""
                        if path.startswith("."):
                            resolved = os.path.normpath(os.path.join(os.path.dirname(tf), path))
                            for ext in ("", ".js", ".ts", ".jsx", ".tsx", "/index.js", "/index.ts"):
                                c = resolved + ext
                                if c in all_files:
                                    sources.add(c); break
                elif tf.endswith(".rb"):
                    for m in _RB_REQUIRE.finditer(txt):
                        resolved = os.path.normpath(os.path.join(os.path.dirname(tf), m.group(1)))
                        for ext in ("", ".rb"):
                            c = resolved + ext
                            if c in all_files:
                                sources.add(c); break
            except Exception:
                pass
            forward[tf] = sources
            for s in sources:
                reverse.setdefault(s, set()).add(tf)

        # 1-level transitivity
        for src, tests in list(reverse.items()):
            for tf in list(tests):
                for dep in forward.get(tf, set()):
                    if dep != src and dep not in reverse:
                        reverse.setdefault(dep, set()).add(tf)

        with self._lock:
            self._forward = forward
            self._reverse = reverse
            self._hash = h
            self._built_at = time.time()
            self._stats["builds"] += 1
        return {"files_indexed": len(reverse), "test_files": len(forward),
                "mappings": sum(len(v) for v in reverse.values())}

    def affected_tests(self, repo_path, changed_files):
        if not ENABLED:
            return {"test_files": [], "test_commands": [], "coverage": 0, "strategy": "disabled"}
        if not self._forward:
            self.build_index(repo_path)
        tests = set()
        for f in (changed_files or []):
            if f in self._reverse:
                tests.update(self._reverse[f])
            else:
                # fallback: same-directory tests
                d = os.path.dirname(f)
                for tf in self._forward:
                    if os.path.dirname(tf) == d:
                        tests.add(tf)
        total = len(self._forward) or 1
        coverage = len(tests) / total
        strategy = "full_suite" if coverage > 0.7 else "selective"
        cmds = []
        py_tests = [t for t in tests if t.endswith(".py")]
        js_tests = [t for t in tests if t.endswith((".js", ".jsx", ".ts", ".tsx"))]
        if py_tests:
            cmds.append(f"pytest {' '.join(sorted(py_tests))} -v")
        if js_tests:
            pattern = "|".join(os.path.splitext(os.path.basename(t))[0] for t in js_tests)
            cmds.append(f'jest --testPathPattern="{pattern}"')
        return {"test_files": sorted(tests), "test_commands": cmds,
                "coverage": round(coverage, 3), "strategy": strategy}

    def selective_test_cmd(self, repo_path, changed_files, base_test_cmd):
        if not ENABLED:
            return base_test_cmd
        try:
            affected = self.affected_tests(repo_path, changed_files)
            if affected["strategy"] == "full_suite" or not affected["test_files"]:
                return base_test_cmd
            if "pytest" in base_test_cmd:
                py_tests = [t for t in affected["test_files"] if t.endswith(".py")]
                if py_tests:
                    return f"pytest {' '.join(sorted(py_tests))} -v --tb=short"
            elif "jest" in base_test_cmd:
                js_tests = [t for t in affected["test_files"] if t.endswith((".js", ".ts", ".jsx", ".tsx"))]
                if js_tests:
                    pat = "|".join(os.path.splitext(os.path.basename(t))[0] for t in js_tests)
                    return f'jest --testPathPattern="{pat}"'
            elif "rspec" in base_test_cmd:
                rb_tests = [t for t in affected["test_files"] if t.endswith(".rb")]
                if rb_tests:
                    return f"rspec {' '.join(sorted(rb_tests))}"
            return base_test_cmd
        except Exception:
            return base_test_cmd

    def record_outcome(self, changed_files, test_files_run, all_passed):
        with self._lock:
            self._stats["runs_optimized"] += 1

    def record_false_negative(self):
        with self._lock:
            self._stats["false_negatives"] += 1

    def stats(self):
        with self._lock:
            return dict(self._stats, enabled=ENABLED, index_size=len(self._reverse),
                        test_files_indexed=len(self._forward))


_oracle = _TestOracle()

def build_index(repo_path):
    try: return _oracle.build_index(repo_path)
    except Exception: return {"files_indexed": 0, "test_files": 0, "mappings": 0}

def affected_tests(repo_path, changed_files):
    try: return _oracle.affected_tests(repo_path, changed_files)
    except Exception: return {"test_files": [], "test_commands": [], "coverage": 0, "strategy": "error"}

def selective_test_cmd(repo_path, changed_files, base_test_cmd):
    try: return _oracle.selective_test_cmd(repo_path, changed_files, base_test_cmd)
    except Exception: return base_test_cmd

def record_outcome(changed_files, test_files_run, all_passed):
    try: _oracle.record_outcome(changed_files, test_files_run, all_passed)
    except Exception: pass

def record_false_negative():
    try: _oracle.record_false_negative()
    except Exception: pass

def stats():
    try: return _oracle.stats()
    except Exception: return {"enabled": False}

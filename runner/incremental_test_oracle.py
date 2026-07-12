#!/usr/bin/env python3
"""
incremental_test_oracle.py - persistent (file_changed -> tests_affected) mapping.

Instead of running the full test suite after every agent edit, the runner queries
this oracle to get the minimal set of affected tests.  Mappings are built from:

  (a) static analysis of Python import graphs  (confidence 0.5)
  (b) recording which tests historically fail when a given source file changes
      (confidence 0.8 after 1 run, 0.95 after 3+ confirming runs)

Stored in Supabase table `test_oracle`:
    project_id   text
    source_file  text
    test_files   jsonb   (array of {path, confidence, confirm_count})
    confidence   real    (max across test_files)
    updated_at   timestamptz

On any DB error, falls back to running all tests (fail-soft).

Env vars:
    ORCH_TEST_ORACLE              "true" (default) to enable
    ORCH_TEST_ORACLE_MIN_CONFIDENCE  minimum confidence to include a test (default 0.7)
"""
import sys, os, json, ast, time, threading, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("test_oracle")
import db

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ENABLED = os.environ.get("ORCH_TEST_ORACLE", "true").lower() in ("1", "true", "yes", "on")
MIN_CONFIDENCE = float(os.environ.get("ORCH_TEST_ORACLE_MIN_CONFIDENCE", "0.7") or 0.7)

CONF_STATIC = 0.5
CONF_ONE_RUN = 0.8
CONF_CONFIRMED = 0.95
_CONFIRM_THRESHOLD = 3


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
class _TestOracle:
    def __init__(self):
        self._lock = threading.Lock()
        self._cache: dict = {}  # (project_id, source_file) -> {test_files, ts}
        self._cache_ttl = 300
        self._stats = {"queries": 0, "hits": 0, "fallbacks": 0, "records": 0}

    # -------------------------------------------------------------------
    # Public: affected_tests
    # -------------------------------------------------------------------
    def affected_tests(self, changed_files, project_id):
        """Return the minimal set of test file paths to run for *changed_files*.

        Falls back to empty list (caller should run all tests) on any error or
        when oracle data is insufficient.
        """
        if not ENABLED or not changed_files:
            return []
        self._stats["queries"] += 1
        tests = set()
        any_miss = False
        for src in changed_files:
            mapping = self._lookup(src, project_id)
            if mapping is None:
                any_miss = True
                continue
            for entry in mapping:
                if entry.get("confidence", 0) >= MIN_CONFIDENCE:
                    tests.add(entry["path"])
        if any_miss and not tests:
            # No oracle data for at least one file and nothing found — caller
            # should fall back to full suite.
            self._stats["fallbacks"] += 1
            return []
        self._stats["hits"] += 1
        return sorted(tests)

    # -------------------------------------------------------------------
    # Public: record_test_run
    # -------------------------------------------------------------------
    def record_test_run(self, changed_files, failed_tests, passed_tests, project_id):
        """Update mappings from actual test outcomes after a build.

        For each changed source file, every failed test is strongly associated,
        and passed tests get a weak negative signal (confidence stays, but
        confirm_count does not increase).
        """
        if not ENABLED or not changed_files:
            return
        for src in changed_files:
            try:
                existing = self._fetch_row(src, project_id)
                entries = existing.get("test_files", []) if existing else []
                by_path = {e["path"]: e for e in entries}

                # Failed tests: strong positive signal
                for tf in (failed_tests or []):
                    if tf in by_path:
                        by_path[tf]["confirm_count"] = by_path[tf].get("confirm_count", 0) + 1
                        cc = by_path[tf]["confirm_count"]
                        by_path[tf]["confidence"] = CONF_CONFIRMED if cc >= _CONFIRM_THRESHOLD else CONF_ONE_RUN
                    else:
                        by_path[tf] = {"path": tf, "confidence": CONF_ONE_RUN, "confirm_count": 1}

                entries_out = list(by_path.values())
                max_conf = max((e["confidence"] for e in entries_out), default=0)
                self._upsert_row(src, project_id, entries_out, max_conf)
                self._stats["records"] += 1
            except Exception:
                _log.debug("record_test_run error for %s", src, exc_info=True)

    # -------------------------------------------------------------------
    # Public: build_import_graph
    # -------------------------------------------------------------------
    def build_import_graph(self, repo_path, project_id):
        """Seed oracle from static analysis of Python imports.

        Walks *repo_path*, parses each .py file's imports, and for every test
        file records which source modules it imports (confidence = CONF_STATIC).
        Only adds entries that don't already exist at higher confidence.
        """
        if not ENABLED or not repo_path or not os.path.isdir(repo_path):
            return 0
        imports_map = self._parse_imports(repo_path)
        # Invert: source_file -> [test_files that import it]
        src_to_tests: dict = {}
        for tf, imported_srcs in imports_map.items():
            if not _is_test_file(tf):
                continue
            for src in imported_srcs:
                src_to_tests.setdefault(src, set()).add(tf)

        seeded = 0
        for src, test_set in src_to_tests.items():
            try:
                existing = self._fetch_row(src, project_id)
                by_path = {}
                if existing:
                    by_path = {e["path"]: e for e in existing.get("test_files", [])}
                changed = False
                for tf in test_set:
                    if tf not in by_path:
                        by_path[tf] = {"path": tf, "confidence": CONF_STATIC, "confirm_count": 0}
                        changed = True
                if changed:
                    entries = list(by_path.values())
                    max_conf = max((e["confidence"] for e in entries), default=0)
                    self._upsert_row(src, project_id, entries, max_conf)
                    seeded += 1
            except Exception:
                _log.debug("build_import_graph error for %s", src, exc_info=True)
        _log.info("seeded %d source->test mappings for project %s", seeded, project_id)
        return seeded

    # -------------------------------------------------------------------
    # Stats
    # -------------------------------------------------------------------
    def stats(self):
        return dict(self._stats)

    def invalidate(self, project_id=None):
        with self._lock:
            if project_id:
                self._cache = {k: v for k, v in self._cache.items() if k[0] != project_id}
            else:
                self._cache.clear()

    # -------------------------------------------------------------------
    # Internal: DB helpers
    # -------------------------------------------------------------------
    def _lookup(self, source_file, project_id):
        key = (project_id, source_file)
        with self._lock:
            cached = self._cache.get(key)
            if cached and time.time() - cached["ts"] < self._cache_ttl:
                return cached["test_files"]
        row = self._fetch_row(source_file, project_id)
        if row is None:
            return None
        entries = row.get("test_files", [])
        with self._lock:
            self._cache[key] = {"test_files": entries, "ts": time.time()}
        return entries

    def _fetch_row(self, source_file, project_id):
        try:
            rows = db.select("test_oracle", {
                "select": "*",
                "project_id": f"eq.{project_id}",
                "source_file": f"eq.{source_file}",
                "limit": "1",
            })
            return rows[0] if rows else None
        except Exception:
            _log.debug("DB fetch error for test_oracle", exc_info=True)
            return None

    def _upsert_row(self, source_file, project_id, test_files, confidence):
        try:
            db.upsert("test_oracle", {
                "project_id": project_id,
                "source_file": source_file,
                "test_files": test_files,
                "confidence": round(confidence, 3),
                "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
            })
        except Exception:
            _log.debug("DB upsert error for test_oracle", exc_info=True)

    # -------------------------------------------------------------------
    # Internal: static import analysis
    # -------------------------------------------------------------------
    def _parse_imports(self, repo_path):
        """Return {rel_path: set(imported_rel_paths)} for all .py files."""
        py_files = []
        for root, _dirs, files in os.walk(repo_path):
            for f in files:
                if f.endswith(".py"):
                    py_files.append(os.path.join(root, f))

        mod_to_file: dict = {}
        for fp in py_files:
            rel = os.path.relpath(fp, repo_path)
            mod = rel.replace(os.sep, ".").removesuffix(".py")
            if mod.endswith(".__init__"):
                mod = mod.removesuffix(".__init__")
            mod_to_file[mod] = rel

        result: dict = {}
        for fp in py_files:
            rel = os.path.relpath(fp, repo_path)
            imported = set()
            try:
                with open(fp, "r", errors="replace") as fh:
                    tree = ast.parse(fh.read(), filename=fp)
            except (SyntaxError, ValueError):
                continue
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names if a.name]
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        names = [node.module]
                for name in names:
                    # Try progressively shorter prefixes
                    parts = name.split(".")
                    for i in range(len(parts), 0, -1):
                        candidate = ".".join(parts[:i])
                        if candidate in mod_to_file:
                            imported.add(mod_to_file[candidate])
                            break
            if imported:
                result[rel] = imported
        return result


def _is_test_file(rel_path):
    base = os.path.basename(rel_path)
    return base.startswith("test_") or base.endswith("_test.py") or "/tests/" in rel_path


# ---------------------------------------------------------------------------
# Module-level singleton + public functions
# ---------------------------------------------------------------------------
_oracle = _TestOracle()


def affected_tests(changed_files, project_id):
    """Return minimal test set for *changed_files*. Empty list = run all."""
    return _oracle.affected_tests(changed_files, project_id)


def record_test_run(changed_files, failed_tests, passed_tests, project_id):
    """Update oracle from actual test outcomes."""
    return _oracle.record_test_run(changed_files, failed_tests, passed_tests, project_id)


def build_import_graph(repo_path, project_id):
    """Seed oracle via static import analysis. Returns count of mappings seeded."""
    return _oracle.build_import_graph(repo_path, project_id)


def stats():
    return _oracle.stats()


def invalidate(project_id=None):
    return _oracle.invalidate(project_id)

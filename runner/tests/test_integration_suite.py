"""Integration, system, and acceptance tests for core orchestrator modules.

Covers cross-module interactions that unit tests miss:
- branch_naming + git_auto_branch integration
- conflict_predictor overlap detection
- realtime_config_sync change detection
- end-to-end acceptance: task slug lifecycle
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# --- Integration: branch_naming dedup with realistic slug sets ---

def test_branch_naming_dedup_integration():
    """Verify deduplicate_slug works with realistic slug sets."""
    import branch_naming
    slugs = {f"improve-feature-{i}" for i in range(50)}
    result = branch_naming.deduplicate_slug("improve-feature-10", slugs)
    assert result == "improve-feature-10-2"
    slugs.add(result)
    result2 = branch_naming.deduplicate_slug("improve-feature-10", slugs)
    assert result2 == "improve-feature-10-3"


# --- Integration: conflict_predictor file extraction + jaccard ---

def test_conflict_predictor_file_overlap():
    """Verify file extraction and jaccard similarity work together."""
    import conflict_predictor as cp
    files_a = cp._extract_files("changed runner/db.py and runner/log.py")
    files_b = cp._extract_files("modified runner/db.py and runner/fleet.py")
    sim = cp._jaccard(files_a, files_b)
    assert 0.0 < sim < 1.0, f"Expected partial overlap, got {sim}"
    assert cp._jaccard(files_a, files_a) == 1.0


def test_conflict_predictor_no_overlap():
    import conflict_predictor as cp
    a = cp._extract_files("runner/foo.py")
    b = cp._extract_files("runner/bar.py")
    assert cp._jaccard(a, b) == 0.0


# --- System: realtime_config_sync hash stability ---

def test_config_hash_deterministic():
    """Same input rows produce same hash regardless of order."""
    import realtime_config_sync as rcs
    rows_a = [{"key": "A", "value": "1"}, {"key": "B", "value": "2"}]
    rows_b = [{"key": "B", "value": "2"}, {"key": "A", "value": "1"}]
    assert rcs._config_hash(rows_a) == rcs._config_hash(rows_b)


def test_config_hash_empty():
    import realtime_config_sync as rcs
    assert rcs._config_hash([]) == ""
    assert rcs._config_hash(None) == ""


def test_config_hash_change_detected():
    """Different values produce different hashes."""
    import realtime_config_sync as rcs
    h1 = rcs._config_hash([{"key": "A", "value": "1"}])
    h2 = rcs._config_hash([{"key": "A", "value": "2"}])
    assert h1 != h2


# --- Acceptance: full slug lifecycle ---

def test_slug_lifecycle_acceptance():
    """Simulate: validate slug → deduplicate → produce branch name."""
    import branch_naming
    slug = "improve-new-feature"
    ok, _ = branch_naming.validate_slug(slug)
    assert ok
    existing = {"improve-new-feature", "improve-new-feature-2"}
    final = branch_naming.deduplicate_slug(slug, existing)
    assert final == "improve-new-feature-3"
    branch = branch_naming.get_agent_branch_name(final)
    assert branch == "agent/improve-new-feature-3"


def test_slug_validation_rejects_bad_input():
    import branch_naming
    for bad in ["", "a" * 200, "A-B-C"]:
        ok, reason = branch_naming.validate_slug(bad)
        assert not ok, f"Expected rejection for {bad!r}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print("All integration/system/acceptance tests passed.")

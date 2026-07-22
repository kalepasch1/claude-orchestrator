"""Tests for rootcause_cluster.py - comprehensive test suite covering all patterns and edge cases."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from rootcause_cluster import (
    extract_signature, cluster_failures, get_recurring_patterns,
    generate_guard_rule, FailureRecord, FailureCluster,
    KNOWN_PATTERNS, GUARD_RULES,
)


class TestExtractSignature:
    """Test signature extraction for all known patterns."""

    def test_capacity_exhaustion(self):
        assert extract_signature("capacity circuit: call cap: 510/500 per hour") == "capacity-exhaustion"
        assert extract_signature("CAPACITY CIRCUIT call cap: 600/500") == "capacity-exhaustion"
        assert extract_signature("Capacity Circuit with call cap limits") == "capacity-exhaustion"

    def test_auth_not_logged_in(self):
        assert extract_signature("Not logged in · Please run /login") == "auth-not-logged-in"
        assert extract_signature("not logged in please run /login") == "auth-not-logged-in"

    def test_git_conflict_409(self):
        assert extract_signature("runner exception: HTTP Error 409: Conflict") == "git-conflict-409"
        assert extract_signature("HTTP Error 409 Conflict during push") == "git-conflict-409"

    def test_missing_spec(self):
        assert extract_signature("Prompt contains only error messages with no real specification") == "missing-spec"
        assert extract_signature("no actionable specification provided") == "missing-spec"
        assert extract_signature("no spec given") == "missing-spec"

    def test_patch_template_corrupt(self):
        assert extract_signature("PATCH TEMPLATE corrupted hash a1b2c3d4e5f6") == "patch-template-corrupt"
        assert extract_signature("PATCH TEMPLATE xyz 123456 problem") == "patch-template-corrupt"

    def test_budget_guard(self):
        assert extract_signature("budget guard: spend limit exceeded") == "budget-guard"
        assert extract_signature("exceeded budget guard threshold") == "budget-guard"

    def test_remediation_cap(self):
        assert extract_signature("shelved after 6 remediations without merge") == "remediation-cap"
        assert extract_signature("shelved after 3 remediations") == "remediation-cap"

    def test_file_not_found(self):
        assert extract_signature("FileNotFoundError: No such file or directory") == "file-not-found"
        assert extract_signature("FileNotFoundError: No such file: /path/to/missing/file") == "file-not-found"

    def test_module_not_found(self):
        assert extract_signature("ModuleNotFoundError: No module named 'xyz'") == "module-not-found"

    def test_type_error(self):
        sig = extract_signature("TypeError: unsupported operand type")
        assert sig in ("type-error",)
        sig2 = extract_signature("AttributeError: 'NoneType' has no attribute 'foo'")
        assert sig2 in ("type-error",)

    def test_test_failure(self):
        assert extract_signature("test suite fails on integration test") == "test-failure"
        assert extract_signature("tests fail: assertion error in main") == "test-failure"

    def test_build_failure(self):
        assert extract_signature("build failed: production build red") == "build-failure"
        assert extract_signature("build fails in npm run build") == "build-failure"

    def test_prisma_schema(self):
        assert extract_signature("Prisma schema migration error") == "prisma-schema"
        assert extract_signature("Invalid Prisma schema encountered") == "prisma-schema"

    def test_git_index_lock(self):
        assert extract_signature("index.lock: File exists") == "git-index-lock"

    def test_orphaned_task(self):
        assert extract_signature("Task was stuck RUNNING >2.0h and hit the janitor retry cap") == "orphaned-task"
        assert extract_signature("orphaned-running task detected") == "orphaned-task"

    def test_unknown_signature_consistency(self):
        """Unknown signatures should be consistent for the same note."""
        note = "some totally novel error xyz that we've never seen"
        sig1 = extract_signature(note)
        sig2 = extract_signature(note)
        assert sig1 == sig2
        assert sig1.startswith("unknown-")

    def test_unknown_different_notes(self):
        """Different unknown notes should produce different signatures."""
        sig1 = extract_signature("novel error A")
        sig2 = extract_signature("novel error B")
        assert sig1 != sig2
        assert sig1.startswith("unknown-")
        assert sig2.startswith("unknown-")

    def test_none_note(self):
        """None or empty note should return 'unknown'."""
        assert extract_signature(None) == "unknown"
        assert extract_signature("") == "unknown"

    def test_case_insensitivity(self):
        """Pattern matching should be case-insensitive."""
        assert extract_signature("CAPACITY CIRCUIT CALL CAP") == "capacity-exhaustion"
        assert extract_signature("http error 409 conflict") == "git-conflict-409"
        assert extract_signature("NOT LOGGED IN PLEASE RUN /LOGIN") == "auth-not-logged-in"


class TestFailureRecord:
    """Test FailureRecord dataclass."""

    def test_basic_creation(self):
        rec = FailureRecord(task_id="t1", slug="task-a", state="BLOCKED", note="some error")
        assert rec.task_id == "t1"
        assert rec.slug == "task-a"
        assert rec.state == "BLOCKED"
        assert rec.note == "some error"

    def test_auto_signature_on_init(self):
        """Signature should be auto-computed if not provided."""
        rec = FailureRecord(task_id="t1", slug="x", state="BLOCKED", note="capacity circuit: call cap")
        assert rec.error_signature == "capacity-exhaustion"

    def test_explicit_signature_preserved(self):
        """Explicit signature should not be overwritten."""
        rec = FailureRecord(
            task_id="t1", slug="x", state="BLOCKED",
            note="capacity circuit: call cap",
            error_signature="custom-sig"
        )
        assert rec.error_signature == "custom-sig"

    def test_empty_note_defaults_to_unknown(self):
        rec = FailureRecord(task_id="t1", slug="x", state="BLOCKED", note="")
        assert rec.error_signature == "unknown"

    def test_none_note_defaults_to_unknown(self):
        rec = FailureRecord(task_id="t1", slug="x", state="BLOCKED", note=None)
        assert rec.error_signature == "unknown"


class TestFailureCluster:
    """Test FailureCluster dataclass."""

    def test_cluster_count(self):
        recs = [
            FailureRecord(task_id="1", slug="a", state="BLOCKED", note="error"),
            FailureRecord(task_id="2", slug="b", state="BLOCKED", note="error"),
        ]
        cluster = FailureCluster(pattern_id="p1", pattern_name="test", signature="test", records=recs)
        assert cluster.count == 2

    def test_is_recurring_threshold(self):
        """Recurring is true for count >= 2."""
        cluster_single = FailureCluster(
            pattern_id="p1", pattern_name="test", signature="test",
            records=[FailureRecord(task_id="1", slug="a", state="BLOCKED", note="error")]
        )
        assert not cluster_single.is_recurring

        cluster_double = FailureCluster(
            pattern_id="p2", pattern_name="test", signature="test",
            records=[
                FailureRecord(task_id="1", slug="a", state="BLOCKED", note="error"),
                FailureRecord(task_id="2", slug="b", state="BLOCKED", note="error"),
            ]
        )
        assert cluster_double.is_recurring

    def test_cluster_properties(self):
        cluster = FailureCluster(
            pattern_id="p123", pattern_name="capacity-exhaustion", signature="capacity-exhaustion",
            records=[], guard_rule="pre_check: verify capacity"
        )
        assert cluster.pattern_id == "p123"
        assert cluster.pattern_name == "capacity-exhaustion"
        assert cluster.signature == "capacity-exhaustion"
        assert cluster.guard_rule == "pre_check: verify capacity"
        assert cluster.count == 0
        assert not cluster.is_recurring


class TestClusterFailures:
    """Test failure clustering logic."""

    def test_cluster_empty_list(self):
        clusters = cluster_failures([])
        assert clusters == []

    def test_cluster_single_record(self):
        records = [FailureRecord(task_id="1", slug="a", state="BLOCKED", note="capacity circuit: call cap")]
        clusters = cluster_failures(records)
        assert len(clusters) == 1
        assert clusters[0].count == 1
        assert not clusters[0].is_recurring

    def test_cluster_single_signature(self):
        records = [
            FailureRecord(task_id="1", slug="a", state="BLOCKED", note="capacity circuit: call cap: 510/500"),
            FailureRecord(task_id="2", slug="b", state="BLOCKED", note="capacity circuit: call cap: 600/500"),
            FailureRecord(task_id="3", slug="c", state="BLOCKED", note="capacity circuit: call cap: 700/500"),
        ]
        clusters = cluster_failures(records)
        assert len(clusters) == 1
        assert clusters[0].count == 3
        assert clusters[0].is_recurring
        assert clusters[0].pattern_name == "capacity-exhaustion"

    def test_cluster_multiple_signatures(self):
        records = [
            FailureRecord(task_id="1", slug="a", state="BLOCKED", note="capacity circuit: call cap"),
            FailureRecord(task_id="2", slug="b", state="BLOCKED", note="capacity circuit: call cap"),
            FailureRecord(task_id="3", slug="c", state="BLOCKED", note="Not logged in · Please run /login"),
            FailureRecord(task_id="4", slug="d", state="BLOCKED", note="HTTP Error 409: Conflict"),
        ]
        clusters = cluster_failures(records)
        assert len(clusters) == 3
        sigs = {c.pattern_name for c in clusters}
        assert "capacity-exhaustion" in sigs
        assert "auth-not-logged-in" in sigs
        assert "git-conflict-409" in sigs

    def test_cluster_ordering_by_count(self):
        """Clusters should be ordered by count (descending)."""
        records = [
            FailureRecord(task_id="1", slug="a", state="BLOCKED", note="capacity circuit: call cap"),
            FailureRecord(task_id="2", slug="b", state="BLOCKED", note="capacity circuit: call cap"),
            FailureRecord(task_id="3", slug="c", state="BLOCKED", note="capacity circuit: call cap"),
            FailureRecord(task_id="4", slug="d", state="BLOCKED", note="Not logged in · Please run /login"),
            FailureRecord(task_id="5", slug="e", state="BLOCKED", note="Not logged in · Please run /login"),
            FailureRecord(task_id="6", slug="f", state="BLOCKED", note="HTTP Error 409: Conflict"),
        ]
        clusters = cluster_failures(records)
        assert clusters[0].count == 3  # capacity-exhaustion
        assert clusters[1].count == 2  # auth-not-logged-in
        assert clusters[2].count == 1  # git-conflict-409

    def test_cluster_preserves_records(self):
        """Cluster should contain original records."""
        rec1 = FailureRecord(task_id="1", slug="a", state="BLOCKED", note="capacity circuit: call cap")
        rec2 = FailureRecord(task_id="2", slug="b", state="BLOCKED", note="capacity circuit: call cap")
        clusters = cluster_failures([rec1, rec2])
        assert len(clusters[0].records) == 2
        assert rec1 in clusters[0].records
        assert rec2 in clusters[0].records

    def test_cluster_large_dataset(self):
        """Should handle large datasets efficiently."""
        records = []
        for i in range(1000):
            note = "capacity circuit: call cap" if i % 3 == 0 else f"error type {i % 5}"
            records.append(FailureRecord(task_id=f"t{i}", slug=f"s{i}", state="BLOCKED", note=note))
        clusters = cluster_failures(records)
        assert len(clusters) > 0
        cap_cluster = next((c for c in clusters if c.pattern_name == "capacity-exhaustion"), None)
        assert cap_cluster is not None
        assert cap_cluster.count >= 300


class TestGetRecurringPatterns:
    """Test recurring pattern filtering."""

    def test_no_recurring(self):
        records = [
            FailureRecord(task_id="1", slug="a", state="BLOCKED", note="error 1"),
            FailureRecord(task_id="2", slug="b", state="BLOCKED", note="error 2"),
            FailureRecord(task_id="3", slug="c", state="BLOCKED", note="error 3"),
        ]
        clusters = cluster_failures(records)
        recurring = get_recurring_patterns(clusters)
        assert recurring == []

    def test_one_recurring(self):
        records = [
            FailureRecord(task_id="1", slug="a", state="BLOCKED", note="capacity circuit: call cap"),
            FailureRecord(task_id="2", slug="b", state="BLOCKED", note="capacity circuit: call cap"),
            FailureRecord(task_id="3", slug="c", state="BLOCKED", note="error 3"),
        ]
        clusters = cluster_failures(records)
        recurring = get_recurring_patterns(clusters)
        assert len(recurring) == 1
        assert recurring[0].pattern_name == "capacity-exhaustion"

    def test_multiple_recurring(self):
        records = [
            FailureRecord(task_id="1", slug="a", state="BLOCKED", note="capacity circuit: call cap"),
            FailureRecord(task_id="2", slug="b", state="BLOCKED", note="capacity circuit: call cap"),
            FailureRecord(task_id="3", slug="c", state="BLOCKED", note="Not logged in · Please run /login"),
            FailureRecord(task_id="4", slug="d", state="BLOCKED", note="Not logged in · Please run /login"),
            FailureRecord(task_id="5", slug="e", state="BLOCKED", note="error 5"),
        ]
        clusters = cluster_failures(records)
        recurring = get_recurring_patterns(clusters)
        assert len(recurring) == 2
        sigs = {c.pattern_name for c in recurring}
        assert "capacity-exhaustion" in sigs
        assert "auth-not-logged-in" in sigs

    def test_threshold_boundary(self):
        """Exactly 2 should be recurring."""
        records = [
            FailureRecord(task_id="1", slug="a", state="BLOCKED", note="capacity circuit: call cap"),
            FailureRecord(task_id="2", slug="b", state="BLOCKED", note="capacity circuit: call cap"),
        ]
        clusters = cluster_failures(records)
        recurring = get_recurring_patterns(clusters)
        assert len(recurring) == 1


class TestGenerateGuardRule:
    """Test guard rule generation."""

    def test_all_known_patterns_have_rules(self):
        """Every known pattern should have a guard rule."""
        for pattern, name in KNOWN_PATTERNS:
            rule = generate_guard_rule(name)
            assert rule is not None
            assert len(rule) > 0
            assert name in rule or "pre_check" in rule or "post_check" in rule or "janitor" in rule

    def test_specific_guard_rules(self):
        assert "capacity" in generate_guard_rule("capacity-exhaustion").lower()
        assert "auth" in generate_guard_rule("auth-not-logged-in").lower()
        assert "409" in generate_guard_rule("git-conflict-409") or "rebase" in generate_guard_rule("git-conflict-409").lower()
        assert "spec" in generate_guard_rule("missing-spec").lower()
        assert "budget" in generate_guard_rule("budget-guard").lower()
        assert "remediation" in generate_guard_rule("remediation-cap").lower()
        assert "type checker" in generate_guard_rule("type-error").lower()
        assert "test" in generate_guard_rule("test-failure").lower()
        assert "build" in generate_guard_rule("build-failure").lower()

    def test_unknown_pattern_triggers_manual_review(self):
        rule = generate_guard_rule("totally-unknown-pattern-xyz")
        assert "manual_review" in rule
        assert "totally-unknown-pattern-xyz" in rule

    def test_guard_rule_all_in_dict(self):
        """All guard rules should be in GUARD_RULES dict."""
        for sig in GUARD_RULES:
            rule = generate_guard_rule(sig)
            assert rule == GUARD_RULES[sig]


class TestEndToEndScenarios:
    """End-to-end integration tests."""

    def test_full_workflow_single_pattern(self):
        """Complete workflow: create records → cluster → filter → generate rules."""
        records = [
            FailureRecord(task_id="t1", slug="s1", state="BLOCKED", note="HTTP Error 409: Conflict"),
            FailureRecord(task_id="t2", slug="s2", state="BLOCKED", note="HTTP Error 409: Conflict"),
        ]
        clusters = cluster_failures(records)
        recurring = get_recurring_patterns(clusters)

        assert len(recurring) == 1
        cluster = recurring[0]
        assert cluster.pattern_name == "git-conflict-409"
        assert cluster.count == 2
        assert cluster.guard_rule is not None
        assert "rebase" in cluster.guard_rule.lower()

    def test_full_workflow_multiple_patterns(self):
        """Complex scenario with multiple patterns of varying frequency."""
        records = [
            # High frequency pattern
            FailureRecord(task_id="t1", slug="s1", state="BLOCKED", note="capacity circuit: call cap"),
            FailureRecord(task_id="t2", slug="s2", state="BLOCKED", note="capacity circuit: call cap"),
            FailureRecord(task_id="t3", slug="s3", state="BLOCKED", note="capacity circuit: call cap"),
            # Medium frequency pattern
            FailureRecord(task_id="t4", slug="s4", state="BLOCKED", note="HTTP Error 409: Conflict"),
            FailureRecord(task_id="t5", slug="s5", state="BLOCKED", note="HTTP Error 409: Conflict"),
            # Low frequency patterns (no recurring)
            FailureRecord(task_id="t6", slug="s6", state="BLOCKED", note="FileNotFoundError: No such file"),
            FailureRecord(task_id="t7", slug="s7", state="BLOCKED", note="ModuleNotFoundError"),
        ]

        clusters = cluster_failures(records)
        recurring = get_recurring_patterns(clusters)

        assert len(clusters) == 4
        assert len(recurring) == 2

        # Check ordering
        assert recurring[0].count == 3
        assert recurring[1].count == 2

        # All recurring should have guard rules
        for cluster in recurring:
            assert cluster.guard_rule is not None
            assert len(cluster.guard_rule) > 0

    def test_all_patterns_in_single_batch(self):
        """Test behavior when all patterns appear once in same batch."""
        records = []
        for pattern, name in KNOWN_PATTERNS:
            records.append(FailureRecord(
                task_id=f"t_{name}", slug=f"s_{name}", state="BLOCKED",
                note=pattern.split("|")[0]  # Use first alt from pattern
            ))

        clusters = cluster_failures(records)
        recurring = get_recurring_patterns(clusters)

        assert len(clusters) >= len(KNOWN_PATTERNS)
        assert len(recurring) == 0  # None should be recurring (count=1 each)

        # Each cluster should have a guard rule
        for cluster in clusters:
            rule = generate_guard_rule(cluster.pattern_name)
            assert rule is not None

    def test_mixed_with_unknown_patterns(self):
        """Test clustering with mix of known and unknown patterns."""
        records = [
            FailureRecord(task_id="t1", slug="s1", state="BLOCKED", note="HTTP Error 409: Conflict"),
            FailureRecord(task_id="t2", slug="s2", state="BLOCKED", note="HTTP Error 409: Conflict"),
            FailureRecord(task_id="t3", slug="s3", state="BLOCKED", note="completely bizarre error message xyz"),
            FailureRecord(task_id="t4", slug="s4", state="BLOCKED", note="another novel error abc"),
        ]

        clusters = cluster_failures(records)
        recurring = get_recurring_patterns(clusters)

        assert len(clusters) == 3
        assert len(recurring) == 1
        assert recurring[0].pattern_name == "git-conflict-409"

        # Unknown patterns should get manual_review rules
        for cluster in clusters:
            if cluster.pattern_name.startswith("unknown-"):
                assert "manual_review" in cluster.guard_rule

    def test_consistency_across_runs(self):
        """Same input should produce same clusters across multiple runs."""
        records = [
            FailureRecord(task_id="1", slug="a", state="BLOCKED", note="capacity circuit: call cap"),
            FailureRecord(task_id="2", slug="b", state="BLOCKED", note="capacity circuit: call cap"),
            FailureRecord(task_id="3", slug="c", state="BLOCKED", note="Not logged in · Please run /login"),
        ]

        clusters1 = cluster_failures(records)
        clusters2 = cluster_failures(records)

        assert len(clusters1) == len(clusters2)
        for c1, c2 in zip(clusters1, clusters2):
            assert c1.pattern_name == c2.pattern_name
            assert c1.count == c2.count
            assert c1.guard_rule == c2.guard_rule


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_string_note(self):
        rec = FailureRecord(task_id="1", slug="a", state="BLOCKED", note="")
        assert rec.error_signature == "unknown"

    def test_whitespace_only_note(self):
        rec = FailureRecord(task_id="1", slug="a", state="BLOCKED", note="   ")
        sig = extract_signature("   ")
        assert sig.startswith("unknown-")  # Whitespace-only gets hashed

    def test_very_long_note(self):
        long_note = "x" * 10000 + "capacity circuit: call cap"
        sig = extract_signature(long_note)
        assert sig == "capacity-exhaustion"

    def test_special_characters_in_note(self):
        note = "Error: capacity circuit: call cap (emoji: 🔥)"
        sig = extract_signature(note)
        assert sig == "capacity-exhaustion"

    def test_note_with_newlines(self):
        note = "Error:\ncapacity circuit: call cap\ndetails here"
        sig = extract_signature(note)
        assert sig == "capacity-exhaustion"

    def test_null_in_note(self):
        note = "Error with\0null character"
        sig = extract_signature(note)
        assert sig is not None  # Should not crash

    def test_cluster_with_none_guard_rule(self):
        cluster = FailureCluster(
            pattern_id="p1", pattern_name="test", signature="test",
            records=[], guard_rule=""
        )
        assert cluster.guard_rule == ""

    def test_pattern_id_uniqueness(self):
        """Each cluster should have unique pattern_id."""
        records = [
            FailureRecord(task_id="1", slug="a", state="BLOCKED", note="capacity circuit: call cap"),
            FailureRecord(task_id="2", slug="b", state="BLOCKED", note="capacity circuit: call cap"),
            FailureRecord(task_id="3", slug="c", state="BLOCKED", note="HTTP Error 409: Conflict"),
        ]
        clusters = cluster_failures(records)
        ids = [c.pattern_id for c in clusters]
        assert len(ids) == len(set(ids))  # All unique


class TestPatternCoverage:
    """Verify all defined patterns are tested."""

    def test_all_patterns_covered(self):
        """Each pattern in KNOWN_PATTERNS should be testable."""
        tested_patterns = set()

        # These should all map to known patterns
        test_cases = [
            ("capacity circuit: call cap", "capacity-exhaustion"),
            ("Not logged in · Please run /login", "auth-not-logged-in"),
            ("HTTP Error 409: Conflict", "git-conflict-409"),
            ("no spec", "missing-spec"),
            ("PATCH TEMPLATE abc123", "patch-template-corrupt"),
            ("budget guard", "budget-guard"),
            ("shelved after 3 remediations", "remediation-cap"),
            ("FileNotFoundError: No such file", "file-not-found"),
            ("ModuleNotFoundError", "module-not-found"),
            ("TypeError", "type-error"),
            ("test fail", "test-failure"),
            ("build fail", "build-failure"),
            ("Prisma schema", "prisma-schema"),
            ("index.lock: File exists", "git-index-lock"),
            ("stuck RUNNING", "orphaned-task"),
        ]

        for note, expected_pattern in test_cases:
            sig = extract_signature(note)
            assert sig == expected_pattern, f"Failed for {note}: got {sig}, expected {expected_pattern}"
            tested_patterns.add(expected_pattern)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])

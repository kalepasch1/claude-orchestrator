"""Tests for loop_cadence: cadence wiring + auto-apply blast-radius gate."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from loop_cadence import (
    CADENCE_TABLE, HOURLY_JOBS, NIGHTLY_JOBS, WEEKLY_JOBS,
    score_blast_radius, is_auto_appliable, partition_proposals,
    build_approval_digest, verify_hourly_coordination,
    TemplateVariantManager, get_cadence_summary,
    NEVER_AUTO_APPLY, CHALLENGER_TRAFFIC_FRACTION,
)


# --- Cadence table wiring ---

def test_hourly_jobs_in_cadence_table():
    for job in HOURLY_JOBS:
        assert job in CADENCE_TABLE
        assert CADENCE_TABLE[job]["interval_seconds"] == 3600

def test_nightly_jobs_in_cadence_table():
    for job in NIGHTLY_JOBS:
        assert job in CADENCE_TABLE
        assert CADENCE_TABLE[job]["interval_seconds"] == 86400

def test_weekly_jobs_in_cadence_table():
    for job in WEEKLY_JOBS:
        assert job in CADENCE_TABLE
        assert CADENCE_TABLE[job]["interval_seconds"] == 604800

def test_generator_feedback_coordinated_with_queue_velocity():
    gf = CADENCE_TABLE["generator_feedback"]
    qv = CADENCE_TABLE["queue_velocity"]
    assert gf["coordinated_with"] == "queue_velocity"
    assert qv["coordinated_with"] == "generator_feedback"

def test_cadence_summary():
    s = get_cadence_summary()
    assert set(s.keys()) == {"hourly", "nightly", "weekly"}
    assert "generator_feedback" in s["hourly"]
    assert "self_review_auto_apply" in s["nightly"]
    assert "template_ab_rotation" in s["weekly"]


# --- Blast-radius scoring ---

def test_config_change_low_blast_radius():
    p = {"category": "config", "change_type": "config", "affected_files": ["runner.toml"]}
    assert score_blast_radius(p) < 0.3

def test_prompt_template_low_blast_radius():
    p = {"category": "prompt", "change_type": "prompt_template", "affected_files": ["templates/qa.txt"]}
    assert score_blast_radius(p) < 0.3

def test_billing_guard_always_high():
    p = {"category": "billing_guard", "change_type": "config", "affected_files": []}
    assert score_blast_radius(p) == 1.0

def test_kill_switch_always_high():
    p = {"category": "kill_switch", "change_type": "config", "affected_files": []}
    assert score_blast_radius(p) == 1.0

def test_schema_in_files_always_high():
    p = {"category": "update", "change_type": "config", "affected_files": ["db/schema.sql"]}
    assert score_blast_radius(p) == 1.0

def test_deploy_category_blocked():
    p = {"category": "deploy", "change_type": "config", "affected_files": []}
    assert score_blast_radius(p) == 1.0

def test_security_category_blocked():
    p = {"category": "security", "change_type": "config", "affected_files": []}
    assert score_blast_radius(p) == 1.0

def test_code_change_medium_blast_radius():
    p = {"category": "improvement", "change_type": "code", "affected_files": ["runner/foo.py"]}
    assert score_blast_radius(p) >= 0.3

def test_many_files_increases_blast_radius():
    p = {"category": "improvement", "change_type": "config", "affected_files": [f"f{i}.py" for i in range(12)]}
    assert score_blast_radius(p) >= 0.3

def test_test_change_very_low():
    p = {"category": "test", "change_type": "test", "affected_files": ["tests/test_foo.py"]}
    assert score_blast_radius(p) < 0.1

def test_migration_high_blast_radius():
    p = {"category": "db", "change_type": "migration", "affected_files": ["migrations/001.sql"]}
    assert score_blast_radius(p) >= 0.3


# --- Auto-apply logic ---

def test_is_auto_appliable_config():
    p = {"category": "config", "change_type": "config", "affected_files": ["x.toml"]}
    assert is_auto_appliable(p) is True

def test_is_not_auto_appliable_code():
    p = {"category": "feature", "change_type": "code", "affected_files": ["runner/main.py"]}
    assert is_auto_appliable(p) is False

def test_partition_proposals():
    safe = {"category": "config", "change_type": "config", "affected_files": ["x.toml"]}
    risky = {"category": "billing_guard", "change_type": "code", "affected_files": ["billing.py"]}
    auto, needs = partition_proposals([safe, risky])
    assert len(auto) == 1
    assert len(needs) == 1

def test_approval_digest_clusters():
    proposals = [
        {"id": "a", "category": "code", "summary": "fix", "change_type": "code", "affected_files": ["x.py"]},
        {"id": "b", "category": "schema", "summary": "migrate", "change_type": "migration", "affected_files": ["s.sql"]},
    ]
    digest = build_approval_digest(proposals)
    assert digest["type"] == "clustered_approval_digest"
    assert digest["count"] == 2
    assert len(digest["proposals"]) == 2


# --- Hourly coordination ---

def test_verify_hourly_coordination_ok():
    entries = [
        {"name": "generator_feedback", "interval_seconds": 3600, "offset_seconds": 0},
        {"name": "queue_velocity", "interval_seconds": 3600, "offset_seconds": 120},
    ]
    assert verify_hourly_coordination(entries) is True

def test_verify_hourly_coordination_missing():
    entries = [{"name": "generator_feedback", "interval_seconds": 3600, "offset_seconds": 0}]
    assert verify_hourly_coordination(entries) is False

def test_verify_hourly_coordination_wrong_interval():
    entries = [
        {"name": "generator_feedback", "interval_seconds": 7200, "offset_seconds": 0},
        {"name": "queue_velocity", "interval_seconds": 3600, "offset_seconds": 0},
    ]
    assert verify_hourly_coordination(entries) is False

def test_verify_hourly_coordination_too_far_apart():
    entries = [
        {"name": "generator_feedback", "interval_seconds": 3600, "offset_seconds": 0},
        {"name": "queue_velocity", "interval_seconds": 3600, "offset_seconds": 600},
    ]
    assert verify_hourly_coordination(entries) is False


# --- Template A/B rotation ---

def test_template_variant_register_and_get():
    mgr = TemplateVariantManager()
    mgr.register_challenger("build", "tmpl_v2", "content here")
    assert mgr.get_active_variant("build", random_val=0.05) == "tmpl_v2"

def test_template_variant_above_threshold():
    mgr = TemplateVariantManager()
    mgr.register_challenger("build", "tmpl_v2", "content")
    assert mgr.get_active_variant("build", random_val=0.5) is None

def test_template_variant_unregistered():
    mgr = TemplateVariantManager()
    assert mgr.get_active_variant("build", random_val=0.01) is None

def test_template_variant_remove():
    mgr = TemplateVariantManager()
    mgr.register_challenger("build", "tmpl_v2", "content")
    assert mgr.remove_variant("build") is True
    assert mgr.get_active_variant("build", random_val=0.01) is None

def test_challenger_traffic_fraction():
    assert CHALLENGER_TRAFFIC_FRACTION == 0.10

def test_never_auto_apply_contains_critical():
    for item in ["billing_guard", "kill_switch", "schema", "deploy", "security"]:
        assert item in NEVER_AUTO_APPLY

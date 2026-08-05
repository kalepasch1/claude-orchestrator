"""The merge guard must refuse real work and ignore machine output.

Both halves are load-bearing. Refuse too little and the fleet resumes
destroying uncommitted edits (four separate loss paths, 2026-08-05). Refuse
too much and the merge train deadlocks on files the fleet rewrites itself —
which is exactly what happened hours after the guard shipped: 24 merges/hour
fell to zero for five straight hours while completions kept climbing.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from regenerable_artifacts import (  # noqa: E402
    describe,
    is_regenerable,
    partition_dirt,
)


# ── things that must NEVER block a merge ────────────────────────────────────
REGENERABLE = [
    ".orch-context-cache.json",
    ".runner_boot_commit",
    "runner/.restart_requested",
    "runner/.runtime/preflight_verdicts.json",
    "generated/capability-contracts.json",
    "server/data/verdict-cards.json",
    "server/data/ecosystem-capability-registry.generated.json",
    "supabase/schema.sql",
    "supabase/baseline/production_schema.sql",
    "reports/cost_intelligence_internal.md",
    "node_modules",
    ".recovery-intent-qafix-smarter-llm-api-retry.txt",
]

# ── things that must ALWAYS block a merge ───────────────────────────────────
REAL_WORK = [
    "runner/db.py",
    "lib/commerce/coppa.ts",
    "lib/economy/referral.ts",
    "components/EventCodeRedemption.tsx",
    "server/api/apparently/ploeh/risk-vector.post.ts",
    "runner/prompt_evolver.py",
    "pages/index.vue",
    # Deliberately not exempt: a lockfile diff changes what ships, and a
    # submodule gitlink records which commit a child repo is pinned to.
    "package-lock.json",
    "pasch",
    "prediction-markets-institute/pmi",
]


def test_regenerable_paths_are_recognised():
    for path in REGENERABLE:
        assert is_regenerable(path), "%s should be regenerable" % path


def test_real_work_is_never_regenerable():
    for path in REAL_WORK:
        assert not is_regenerable(path), "%s must still block a merge" % path


def test_partition_splits_mixed_dirt():
    porcelain = "\n".join([
        " M .orch-context-cache.json",
        " M lib/commerce/coppa.ts",
        " M supabase/schema.sql",
        " D node_modules",
    ])
    blocking, regenerable = partition_dirt(porcelain)
    assert [ln[3:] for ln in blocking] == ["lib/commerce/coppa.ts"]
    assert len(regenerable) == 3


def test_all_regenerable_means_no_blocking():
    porcelain = "\n".join([" M .orch-context-cache.json", " D node_modules"])
    blocking, regenerable = partition_dirt(porcelain)
    assert blocking == []
    assert len(regenerable) == 2


def test_a_single_real_edit_still_blocks_everything():
    """One human edit among a hundred artifacts must still refuse the merge."""
    lines = [" M .orch-context-cache.json"] * 100 + [" M runner/db.py"]
    blocking, _ = partition_dirt("\n".join(lines))
    assert len(blocking) == 1


def test_clean_tree_partitions_to_nothing():
    assert partition_dirt("") == ([], [])
    assert partition_dirt("   \n  \n") == ([], [])


def test_rename_entries_use_the_destination_path():
    blocking, regenerable = partition_dirt(' R  old/thing.ts -> generated/thing.json')
    assert blocking == []
    assert len(regenerable) == 1

    blocking, _ = partition_dirt(' R  generated/x.json -> lib/real.ts')
    assert len(blocking) == 1


def test_describe_names_both_halves_and_never_hides_a_block():
    blocking, regenerable = partition_dirt(
        " M runner/db.py\n M .orch-context-cache.json"
    )
    text = describe(blocking, regenerable)
    assert "1 blocking" in text
    assert "runner/db.py" in text
    assert "regenerable (ignored)" in text
    assert ".orch-context-cache.json" in text


def test_describe_truncates_but_reports_the_true_count():
    blocking, regenerable = partition_dirt(
        "\n".join(" M src/file%d.ts" % i for i in range(20))
    )
    text = describe(blocking, regenerable, limit=3)
    assert "20 blocking" in text
    assert "+17 more" in text


def test_describe_on_a_clean_tree():
    assert describe([], []) == "clean"


def test_leading_dot_slash_is_normalised():
    assert is_regenerable("./.orch-context-cache.json")

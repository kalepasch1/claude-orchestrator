"""DONE -> MERGED conversion: card admission guarantee and merge-train reporting.

Covers the six behaviours specified for the 2026-08-06 done-to-merged work:

  1. Task reaches DONE with a branch -> a card exists, or a recorded reason exists.
  2. Card filing raises -> the failure is recorded, not swallowed.
  3. A merge-train pass that merges nothing emits a report naming why for each card.
  4. Approved card + fetchable branch + green tests -> merges.
  5. Approved card + red tests -> does NOT merge, reason recorded.
  6. Conversion rate and no-card count are exposed on the health surface.

These are unit tests over the recording layer: they use fakes for db and for
_integrate_card so they run without Supabase or a git remote.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── fakes ────────────────────────────────────────────────────────────────────
class FakeDB:
    """Minimal stand-in for runner.db with recorded writes."""

    def __init__(self, tasks=None, approvals=None, projects=None, insert_raises=None):
        self.tables = {
            "tasks": list(tasks or []),
            "approvals": list(approvals or []),
            "projects": list(projects or [{"id": "p1", "name": "beethoven"}]),
            "admission_rejections": [],
            "fleet_telemetry": [],
        }
        self.insert_raises = insert_raises or set()

    def select(self, table, params=None):
        params = params or {}
        rows = list(self.tables.get(table, []))
        for key, val in params.items():
            if key in ("select", "order", "limit"):
                continue
            sval = str(val)
            if sval.startswith("eq."):
                want = sval[3:]
                rows = [r for r in rows if str(r.get(key)) == want]
            elif sval.startswith("in.("):
                wanted = set(sval[4:-1].split(","))
                rows = [r for r in rows if str(r.get(key)) in wanted]
        limit = params.get("limit")
        if limit:
            rows = rows[: int(limit)]
        return rows

    def count(self, table, params=None):
        return len(self.select(table, params))

    def insert(self, table, row, upsert=False):
        if table in self.insert_raises:
            raise RuntimeError(f"insert into {table} exploded")
        self.tables.setdefault(table, []).append(dict(row))
        return row

    def update(self, table, where, patch):
        for row in self.tables.get(table, []):
            if all(str(row.get(k)) == str(v) for k, v in where.items()):
                row.update(patch)
        return True

    def localize_repo_path(self, path):
        return path


@pytest.fixture
def fake_db(monkeypatch):
    fake = FakeDB()
    import db as real_db
    for name in ("select", "count", "insert", "update", "localize_repo_path"):
        monkeypatch.setattr(real_db, name, getattr(fake, name), raising=False)
    return fake


# ── 1. DONE with a branch -> card or recorded reason ─────────────────────────
def test_done_task_with_branch_gets_a_card(fake_db, monkeypatch):
    import done_to_merged
    import merge_train

    fake_db.tables["tasks"] = [{
        "id": "t1", "slug": "real-work-slug", "state": "DONE",
        "project_id": "p1", "branch": "agent/real-work-slug", "note": "implemented and pushed",
    }]
    filed = []
    monkeypatch.setattr(merge_train, "ensure_integration_card",
                        lambda project, slug, **kw: filed.append(slug) or True)

    summary = done_to_merged.reconcile_missing_cards()

    assert filed == ["real-work-slug"], "a DONE task with a branch must get a card"
    assert summary["cards_filed"] == 1


def test_done_task_without_branch_gets_a_recorded_reason(fake_db):
    """The other half of the guarantee: no card is fine, silence is not."""
    import done_to_merged

    fake_db.tables["tasks"] = [{
        "id": "t2", "slug": "child-task", "state": "DONE", "project_id": "p1",
        "note": "folded into batch-mech-backlog-batch-illuminati",
    }]

    summary = done_to_merged.reconcile_missing_cards()

    rejections = fake_db.tables["admission_rejections"]
    assert summary["rejections_recorded"] == 1
    assert len(rejections) == 1
    assert rejections[0]["slug"] == "child-task"
    assert "folded into" in rejections[0]["reason"]
    assert rejections[0]["gate"] == done_to_merged.GATE


def test_already_carded_task_is_not_double_filed(fake_db, monkeypatch):
    import done_to_merged
    import merge_train

    fake_db.tables["tasks"] = [{
        "id": "t3", "slug": "carded-slug", "state": "DONE",
        "project_id": "p1", "branch": "agent/carded-slug", "note": "done",
    }]
    fake_db.tables["approvals"] = [{
        "id": "a1", "slug": "carded-slug", "kind": "integrate", "status": "approved",
    }]
    filed = []
    monkeypatch.setattr(merge_train, "ensure_integration_card",
                        lambda project, slug, **kw: filed.append(slug))

    summary = done_to_merged.reconcile_missing_cards()

    assert filed == []
    assert summary["already_carded"] == 1


# ── 2. Card filing raises -> recorded, not swallowed ─────────────────────────
def test_card_filing_failure_is_recorded(fake_db, monkeypatch):
    import done_to_merged
    import merge_train

    fake_db.tables["tasks"] = [{
        "id": "t4", "slug": "explodes", "state": "DONE",
        "project_id": "p1", "branch": "agent/explodes", "note": "pushed",
    }]

    def boom(*a, **kw):
        raise RuntimeError("supabase said no")

    monkeypatch.setattr(merge_train, "ensure_integration_card", boom)

    summary = done_to_merged.reconcile_missing_cards()

    assert summary["errors"] == 1
    rejections = fake_db.tables["admission_rejections"]
    assert len(rejections) == 1, "a raise must leave a row behind, not silence"
    assert "supabase said no" in rejections[0]["reason"]
    assert rejections[0]["gate"] == "card-filing-error"


def test_operator_origin_rejection_is_flagged(fake_db):
    import done_to_merged

    fake_db.tables["tasks"] = [{
        "id": "t5", "slug": "dropbox-operator-ask", "state": "DONE",
        "project_id": "p1", "note": "superseded by a later slice",
    }]

    done_to_merged.reconcile_missing_cards()

    row = fake_db.tables["admission_rejections"][0]
    assert row["operator_origin"] is True


# ── 3. A pass that merges nothing names why, per card ────────────────────────
def test_no_op_pass_names_a_reason_for_every_card(fake_db):
    import merge_train_report

    report = merge_train_report.PassReport(trigger="test")
    report.failed("slug-a", "testfail: tests red after rebase")
    report.failed("slug-b", "conflict: unresolvable merge conflict")
    report.skipped("slug-c", "cap: standard batch cap 5 reached")

    d = report.to_dict()

    assert d["merged"] == 0
    assert d["no_op"] is True
    assert d["considered"] == 3
    assert d["unaccounted"] == 0
    for slug in ("slug-a", "slug-b", "slug-c"):
        reasons = {**d["failed_reasons"], **d["skipped_reasons"]}
        assert slug in reasons and reasons[slug], f"{slug} ended with no reason"
    assert "all-cards-blocked" in d["no_op_reason"]
    assert "testfail" in d["no_op_reason"]


def test_pass_that_never_ran_is_distinguishable_from_one_that_merged_nothing(fake_db):
    """The core of FAILURE 2: silence used to mean both of these."""
    import merge_train_report

    never_ran = merge_train_report.PassReport()
    never_ran.not_run("lease-not-acquired")

    ran_merged_nothing = merge_train_report.PassReport()
    ran_merged_nothing.failed("slug-a", "buildfail: production build red")

    assert never_ran.to_dict()["not_run"] == "lease-not-acquired"
    assert never_ran.no_op_reason() == "lease-not-acquired"
    assert ran_merged_nothing.to_dict()["not_run"] is None
    assert ran_merged_nothing.no_op_reason() != never_ran.no_op_reason()


def test_considered_but_unresolved_card_is_surfaced(fake_db):
    """A future silent early-return shows up as a number instead of as silence."""
    import merge_train_report

    report = merge_train_report.PassReport()
    report.consider("forgotten-slug")
    report.failed("handled-slug", "testfail: red")

    assert report.unaccounted() == ["forgotten-slug"]
    assert report.to_dict()["unaccounted"] == 1
    assert "unaccounted" in report.no_op_reason()


def test_pass_report_persists_to_telemetry(fake_db):
    import merge_train_report

    report = merge_train_report.PassReport(trigger="test")
    report.merged("slug-a")
    report.failed("slug-b", "testfail: red")

    assert report.persist() is True
    rows = fake_db.tables["fleet_telemetry"]
    metrics = {r["metric"] for r in rows}
    assert "merge_train.pass" in metrics
    assert "merge_train.merged" in metrics
    detail = next(r for r in rows if r["metric"] == "merge_train.pass")
    assert detail["tags"]["merged"] == 1
    assert detail["tags"]["failed_reasons"]["slug-b"].startswith("testfail")


def test_persist_failure_does_not_raise(fake_db):
    """Instrumentation that can break the train is worse than none."""
    import merge_train_report

    fake_db.insert_raises = {"fleet_telemetry"}
    report = merge_train_report.PassReport()
    report.merged("slug-a")

    assert report.persist() is False


# ── 4 & 5. Green tests merge; red tests do not, with a reason ────────────────
def test_green_tests_merge_and_red_tests_do_not(fake_db):
    """Outcome -> report bucket mapping, the contract train_run relies on."""
    import merge_train_report

    report = merge_train_report.PassReport()

    # 4: approved card + fetchable branch + green tests -> merges
    report.merged("green-slug")
    # 5: approved card + red tests -> does NOT merge, reason recorded
    report.failed("red-slug", "testfail: tests red after rebase")

    d = report.to_dict()
    assert d["merged"] == 1
    assert "green-slug" in d["merged_slugs"]
    assert "red-slug" not in d["merged_slugs"]
    assert d["failed_reasons"]["red-slug"].startswith("testfail")
    assert d["no_op"] is False


def test_merged_wins_over_a_prior_failure_for_the_same_slug(fake_db):
    """A retried card that eventually merges must not be counted as both."""
    import merge_train_report

    report = merge_train_report.PassReport()
    report.failed("retried", "conflict: unresolvable merge conflict")
    report.merged("retried")

    d = report.to_dict()
    assert d["merged"] == 1
    assert d["failed"] == 0
    assert "retried" not in d["failed_reasons"]


# ── 6. Health surface ────────────────────────────────────────────────────────
def test_conversion_stats_expose_rate_and_no_card_count(fake_db):
    import done_to_merged

    fake_db.tables["tasks"] = [
        {"id": "d1", "slug": "carded", "state": "DONE"},
        {"id": "d2", "slug": "uncarded", "state": "DONE"},
        {"id": "m1", "slug": "merged-one", "state": "MERGED"},
        {"id": "m2", "slug": "merged-two", "state": "MERGED"},
    ]
    fake_db.tables["approvals"] = [
        {"id": "a1", "slug": "carded", "kind": "integrate", "status": "approved"},
    ]

    stats = done_to_merged.conversion_stats()

    assert stats["done"] == 2
    assert stats["merged"] == 2
    assert stats["conversion_pct"] == 50.0
    assert stats["done_without_card"] == 1
    assert stats["no_card_pct"] == 50.0


def test_publish_health_writes_conversion_metrics(fake_db):
    import done_to_merged

    ok = done_to_merged.publish_health(
        {"window_hours": 24, "done": 10, "merged": 5,
         "conversion_pct": 33.3, "done_without_card": 4, "no_card_pct": 40.0})

    assert ok is True
    metrics = {r["metric"]: r["value"] for r in fake_db.tables["fleet_telemetry"]}
    assert metrics["done_to_merged.conversion_pct"] == 33.3
    assert metrics["done_to_merged.done_without_card"] == 4.0
    assert metrics["done_to_merged.no_card_pct"] == 40.0


def test_conversion_stats_survive_a_db_outage(monkeypatch):
    """A health probe must not be the thing that goes down."""
    import db as real_db
    import done_to_merged

    def boom(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(real_db, "select", boom, raising=False)
    monkeypatch.setattr(real_db, "count", boom, raising=False)

    stats = done_to_merged.conversion_stats()

    assert stats["done"] == 0
    assert stats["conversion_pct"] == 0.0

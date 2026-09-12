#!/usr/bin/env python3
"""db_memo keeps internal legal-memo drafts current from the db_findings ledger.

What must hold, and why each is tested rather than trusted:

* Routing is deterministic and total. A finding that lands in no argument is evidence
  the firm silently lost; a finding routed to a key the contract does not define is a
  memo that cannot be scored. Every probe in the routing table, every advisor lint and
  every unknown probe must resolve to keys inside MEMO_KINDS[memo]["arguments"].
* Weights encode direction. A critical gap weighs 3, a positive fact weighs 1 whatever
  its "severity", and a RESOLVED gap weighs 0 but keeps its row, so a memo can say
  "was a gap, closed on <date>" instead of forgetting it ever existed.
* The evidence hash is the cost gate. It moves when a finding is added or resolved and
  stays put otherwise — and no model call happens unless it moved.
* Hollow drafts never replace prose. Short, uncited or invented-citation drafts are
  refused; the previous body stays and the row goes 'stale'. When the model is
  unreachable the deterministic rendering is persisted so a memo always exists.
* Memos are internal. No row ever carries a publication_state other than 'internal'.
"""
import hashlib
import os
import re
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import db_memo  # noqa: E402
from db_steering_contract import MEMO_KINDS  # noqa: E402

AC = "access_control_and_least_privilege"
RI = "records_integrity_and_audit_trail"
DP = "data_protection_posture"
OR = "operational_resilience"
CC = "change_control_and_schema_governance"
AI = "ai_use_disclosure_and_logging"

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


class FakeDb:
    """In-memory stand-in for db.select/insert/upsert/update keyed by table, honouring the
    PostgREST filters db_memo uses (eq., in.(...), order, limit) and the two unique keys."""

    def __init__(self):
        self.tables = {"legal_memo_drafts": [], "legal_memo_evidence": [], "db_findings": []}
        self.log = []
        self._n = 0

    @staticmethod
    def _match(row, params):
        for k, v in params.items():
            if k in ("select", "order", "limit") or not isinstance(v, str):
                continue
            if v.startswith("eq."):
                if str(row.get(k)) != v[3:]:
                    return False
            elif v.startswith("in.(") and v.endswith(")"):
                if str(row.get(k)) not in v[4:-1].split(","):
                    return False
            elif v.startswith("neq."):
                if str(row.get(k)) == v[4:]:
                    return False
        return True

    def select(self, table, params=None):
        params = params or {}
        rows = [dict(r) for r in self.tables.get(table, []) if self._match(r, params)]
        order = params.get("order")
        if order:
            col, _, direction = order.partition(".")
            rows.sort(key=lambda r: str(r.get(col) or ""), reverse=(direction == "desc"))
        if params.get("limit"):
            rows = rows[:int(params["limit"])]
        return rows

    def select_all(self, table, params=None, page_size=None, max_rows=None, order=None):
        q = dict(params or {})
        q.pop("limit", None)
        # Only the first order key matters for the fake: the real db orders by the full list.
        q["order"] = (order or q.get("order") or "id.asc").split(",")[0]
        return self.select(table, q)

    def insert(self, table, row, upsert=False):
        r = dict(row)
        rows = self.tables.setdefault(table, [])
        if table == "legal_memo_drafts":
            if any(x["project"] == r["project"] and x["memo_kind"] == r["memo_kind"] for x in rows):
                return None
        if table == "legal_memo_evidence":
            if any((x["memo_id"], x["finding_id"], x["argument_key"]) ==
                   (r["memo_id"], r["finding_id"], r["argument_key"]) for x in rows):
                return None
        self._n += 1
        r.setdefault("id", f"{table[:4]}-{self._n}")
        r.setdefault("created_at", (NOW + timedelta(seconds=self._n)).isoformat())
        if table == "legal_memo_drafts":
            r.setdefault("publication_state", "internal")
            r.setdefault("status", "draft")
        rows.append(r)
        self.log.append(("insert", table, dict(r)))
        return [dict(r)]  # PostgREST echoes the representation as a list

    def upsert(self, table, row):
        return self.insert(table, row, upsert=True)

    def update(self, table, match, patch):
        out = []
        for r in self.tables.get(table, []):
            if all(str(r.get(k)) == str(v) for k, v in match.items()):
                r.update(patch)
                out.append(dict(r))
        self.log.append(("update", table, dict(match), dict(patch)))
        return out

    # convenience
    def memo(self, project, kind):
        rows = self.select("legal_memo_drafts", {"project": f"eq.{project}", "memo_kind": f"eq.{kind}"})
        return rows[0] if rows else None

    def evidence(self, memo_id):
        return self.select("legal_memo_evidence", {"memo_id": f"eq.{memo_id}"})


def _finding(n, probe, category, severity, kinds, direction="undermines", status="open",
             object_name="users", title=None, **extra):
    fp = hashlib.sha256(f"{probe}|{object_name}|{n}".encode()).hexdigest()[:32]
    row = {"id": f"f{n}", "source_id": "src1", "project": "proj", "probe_id": probe, "category": category,
           "severity": severity, "fingerprint": fp, "title": title or f"{probe} on {object_name}",
           "detail": "detail", "object_schema": "public", "object_name": object_name, "metrics": {"n": n},
           "evidence_kinds": list(kinds), "direction": direction,
           "remediation": f"fix {probe} on {object_name}", "status": status,
           "first_seen_at": (NOW - timedelta(days=3)).isoformat(), "last_seen_at": NOW.isoformat(),
           "resolved_at": None, "occurrences": 1}
    row.update(extra)
    return row


class _FakeModel:
    """A model that writes a well-formed memo citing exactly the fingerprints in the prompt,
    unless told to return a fixed body or to fail."""

    def __init__(self):
        self.calls = 0
        self.fixed = None
        self.raise_exc = None
        self.prompts = []

    def choose(self, task_class, agentic=True, need=None, **kw):
        return "fakeprov", "fake-model", "test"

    def complete(self, prov, model, prompt, **kw):
        self.calls += 1
        self.prompts.append(prompt)
        if self.raise_exc:
            raise self.raise_exc
        if self.fixed is not None:
            return {"text": self.fixed}
        fps = sorted(set(re.findall(r"- fp:([0-9a-f]{12})", prompt)))
        return {"text": good_memo(fps)}


def good_memo(fps, extra_cites=()):
    cites = "\n".join(f"- The probe recorded this condition on the named object; it stands as of the "
                      f"last-seen date and is unrebutted by any positive finding. [fp:{fp}]" for fp in fps)
    for e in extra_cites:
        cites += f"\n- An assertion the ledger does not contain. [fp:{e}]"
    return (
        "# Access control in the production data layer\n\n"
        "## Question presented\n\nWhether the evidence supports row-level isolation and a minimal anonymous surface.\n\n"
        "## Short answer\n\n- row_level_isolation: UNDERMINED — the ledger records tables with RLS disabled.\n"
        "- anon_surface_minimal: UNASSESSED — no probe has reported on grants.\n\n"
        f"## Evidence\n\n{cites}\n\n"
        f"## Gaps and remediation\n\n- Enable RLS and add a tenant policy on each listed table. [fp:{fps[0] if fps else '000000000000'}]\n\n"
        "## What would change the conclusion\n\n- A resolved finding for every listed table would move row_level_isolation to supported.\n\n"
        + db_memo.CLOSING_LINE + "\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.db = FakeDb()
        for fn in ("select", "insert", "upsert", "update"):
            self.enterContext(mock.patch.object(db_memo.db, fn, getattr(self.db, fn)))
        self.model = _FakeModel()
        self.rag_calls = []
        self.gauntlet = mock.MagicMock(return_value=None)
        self.committees = mock.MagicMock(return_value=None)
        fake_modules = {
            "model_policy": types.SimpleNamespace(choose=self.model.choose),
            "model_gateway": types.SimpleNamespace(complete=self.model.complete),
            "fleet_rag": types.SimpleNamespace(index_document=lambda *a, **k: self.rag_calls.append((a, k))),
            "gauntlet": types.SimpleNamespace(run=self.gauntlet),
            "committees": types.SimpleNamespace(review=self.committees),
        }
        self.enterContext(mock.patch.dict(sys.modules, fake_modules))
        self.enterContext(mock.patch.dict(os.environ, {"ORCH_DB_MEMO_GAUNTLET": "true"}))

    def seed(self, findings):
        for f in findings:
            self.db.tables["db_findings"].append(dict(f))
        return db_memo.attach_evidence("proj", findings)

    def resolve(self, fid):
        for f in self.db.tables["db_findings"]:
            if f["id"] == fid:
                f["status"] = "resolved"
                f["resolved_at"] = NOW.isoformat()
        rows = self.db.select("db_findings", {"id": f"eq.{fid}"})
        return db_memo.attach_evidence("proj", rows)

    def assert_all_internal(self):
        for r in self.db.tables["legal_memo_drafts"]:
            self.assertEqual(r.get("publication_state"), "internal")
        for entry in self.db.log:
            payload = entry[2] if entry[0] == "insert" else entry[3]
            if "publication_state" in payload:
                self.assertEqual(payload["publication_state"], "internal")


# ── argument routing ───────────────────────────────────────────────────────────────────

class TestArgumentRouting(unittest.TestCase):
    CASES = [
        (AC, "rls_disabled_tables", "security", {}, ["row_level_isolation"]),
        (DP, "rls_disabled_tables", "security", {}, ["pii_not_exposed"]),
        (AC, "rls_enabled_no_policy", "security", {}, ["row_level_isolation"]),
        (AC, "pii_exposed_tables", "privacy", {}, ["row_level_isolation"]),
        (DP, "pii_exposed_tables", "privacy", {}, ["pii_not_exposed"]),
        (AC, "anon_or_public_grants", "security", {}, ["anon_surface_minimal"]),
        (DP, "anon_or_public_grants", "security", {"object_name": "customers"}, ["pii_not_exposed"]),
        (DP, "anon_or_public_grants", "security", {"object_name": "countries", "title": "public grant on countries",
                                                   "detail": "reference table"}, []),
        (AC, "security_definer_functions", "security", {}, ["privileged_paths_bounded"]),
        (RI, "missing_audit_columns", "audit", {}, ["contemporaneous_records"]),
        # audit_trail evidence also lands in the AI memo, but a business table without
        # created_at says nothing about model-call logging; an AI log table does.
        (AI, "missing_audit_columns", "audit", {"object_name": "invoices"}, []),
        (AI, "missing_audit_columns", "audit", {"object_name": "model_calls"}, ["model_calls_logged"]),
        (RI, "audit_trail_presence", "audit", {}, ["regular_practice"]),
        (AI, "audit_trail_presence", "audit", {}, ["provenance_traceable"]),
        (RI, "unvalidated_constraints", "integrity", {}, ["referential_integrity"]),
        (RI, "tables_without_primary_key", "integrity", {}, ["referential_integrity"]),
        (RI, "unindexed_foreign_keys", "integrity", {}, ["referential_integrity"]),
        (OR, "unindexed_foreign_keys", "integrity", {}, []),
        (OR, "unindexed_foreign_keys", "performance", {}, ["performance_headroom"]),
        (RI, "unindexed_foreign_keys", "performance", {}, []),
        (DP, "pii_columns_inventory", "privacy", {}, ["pii_inventory_known"]),
        (DP, "soft_delete_without_purge", "retention", {}, ["retention_enforced"]),
        (DP, "pg_cron_jobs", "retention", {}, ["retention_enforced"]),
        (OR, "slow_query_classes", "performance", {}, ["performance_headroom"]),
        (OR, "unused_indexes", "performance", {}, ["performance_headroom"]),
        (OR, "dead_tuple_bloat", "availability", {}, ["maintenance_current"]),
        (OR, "vacuum_stale", "availability", {}, ["maintenance_current"]),
        (OR, "sequence_headroom", "availability", {}, ["maintenance_current"]),
        (OR, "long_running_transactions", "availability", {}, ["maintenance_current"]),
        (OR, "replica_lag_excessive", "availability", {}, ["failure_modes_known"]),
        (CC, "schema_migrations_drift", "schema_drift", {}, ["schema_matches_migrations", "changes_reviewable"]),
        (CC, "schema_migrations_unapplied", "schema_drift", {}, ["schema_matches_migrations", "changes_reviewable"]),
        (CC, "extensions_in_public", "schema_drift", {}, ["schema_matches_migrations", "changes_reviewable"]),
        (AI, "ai_call_logging_presence", "ai_governance", {}, ["model_calls_logged"]),
        (AC, "advisor:0002_auth_users_exposed", "security", {}, ["row_level_isolation"]),
        (RI, "advisor:0013_something", "audit", {}, ["contemporaneous_records"]),
        (AC, "never_heard_of_this_probe", "security", {}, ["row_level_isolation"]),
        (DP, "never_heard_of_this_probe", "privacy", {}, ["pii_inventory_known"]),
    ]

    def test_rules_table(self):
        for memo_kind, probe, category, extra, expected in self.CASES:
            f = _finding(1, probe, category, "high", [], **extra)
            with self.subTest(memo=memo_kind, probe=probe, category=category):
                self.assertEqual(db_memo.argument_keys_for(memo_kind, f), expected)

    def test_every_route_lands_on_a_defined_argument(self):
        probes = list(db_memo.ROUTES) + ["advisor:x", "unknown_probe", "schema_migrations_zzz"]
        for memo_kind, spec in MEMO_KINDS.items():
            for probe in probes:
                for category in ("security", "integrity", "performance", "availability", "audit"):
                    keys = db_memo.argument_keys_for(memo_kind, _finding(1, probe, category, "low", []))
                    self.assertTrue(set(keys) <= set(spec["arguments"]), (memo_kind, probe, keys))

    def test_unknown_memo_kind_is_empty(self):
        self.assertEqual(db_memo.argument_keys_for("no_such_memo", _finding(1, "x", "security", "low", [])), [])


# ── attach_evidence ────────────────────────────────────────────────────────────────────

class TestAttachEvidence(Base):
    def test_creates_skeletons_and_weighted_evidence(self):
        crit = _finding(1, "rls_disabled_tables", "security", "critical", ["access_control"])
        pos = _finding(2, "audit_trail_presence", "audit", "info", ["audit_trail"], direction="supports",
                       object_name="events")
        med = _finding(3, "vacuum_stale", "availability", "medium", ["availability"], object_name="orders")
        out = self.seed([crit, pos, med])
        self.assertEqual(set(out["memos_touched"]), {AC, DP, RI, AI, OR})
        # AC memo skeleton
        ac = self.db.memo("proj", AC)
        self.assertEqual(ac["title"], MEMO_KINDS[AC]["title"])
        self.assertEqual(ac["status"], "draft")
        self.assertEqual(ac["publication_state"], "internal")
        ev = {(e["finding_id"], e["argument_key"]): e for e in self.db.evidence(ac["id"])}
        self.assertEqual(ev[("f1", "row_level_isolation")]["weight"], 3.0)
        self.assertEqual(ev[("f1", "row_level_isolation")]["direction"], "undermines")
        # DP memo gets the same finding under pii_not_exposed
        dp_ev = self.db.evidence(self.db.memo("proj", DP)["id"])
        self.assertEqual([(e["argument_key"], e["weight"]) for e in dp_ev], [("pii_not_exposed", 3.0)])
        # supports weighs 1.0 regardless of its info severity
        ri_ev = self.db.evidence(self.db.memo("proj", RI)["id"])
        self.assertEqual([(e["argument_key"], e["direction"], e["weight"]) for e in ri_ev],
                         [("regular_practice", "supports", 1.0)])
        or_ev = self.db.evidence(self.db.memo("proj", OR)["id"])
        self.assertEqual([(e["argument_key"], e["weight"]) for e in or_ev], [("maintenance_current", 1.0)])
        self.assert_all_internal()

    def test_reattach_is_idempotent(self):
        f = _finding(1, "rls_disabled_tables", "security", "high", ["access_control"])
        self.seed([f])
        n_memos = len(self.db.tables["legal_memo_drafts"])
        n_ev = len(self.db.tables["legal_memo_evidence"])
        db_memo.attach_evidence("proj", [f])
        self.assertEqual(len(self.db.tables["legal_memo_drafts"]), n_memos)
        self.assertEqual(len(self.db.tables["legal_memo_evidence"]), n_ev)

    def test_resolved_finding_zeroes_weight_but_keeps_row(self):
        f = _finding(1, "missing_audit_columns", "audit", "high", ["audit_trail"], object_name="invoices")
        self.seed([f])
        ri = self.db.memo("proj", RI)
        self.assertEqual(self.db.evidence(ri["id"])[0]["weight"], 2.0)
        self.resolve("f1")
        rows = self.db.evidence(ri["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["weight"], 0.0)
        self.assertIn("resolved 2026-09-11", rows[0]["note"])

    def test_unknown_kinds_and_idless_rows_are_ignored_not_fatal(self):
        out = db_memo.attach_evidence("proj", [{"probe_id": "x", "evidence_kinds": ["access_control"]},
                                               _finding(9, "x", "security", "low", ["not_a_kind"])])
        self.assertEqual(out, {"memos_touched": [], "evidence_rows": 0})

    def test_db_failure_is_fail_soft(self):
        with mock.patch.object(db_memo.db, "select", side_effect=RuntimeError("boom")):
            out = db_memo.attach_evidence("proj", [_finding(1, "rls_disabled_tables", "security", "high",
                                                             ["access_control"])])
        self.assertEqual(out["evidence_rows"], 0)


# ── evidence_hash ──────────────────────────────────────────────────────────────────────

class TestEvidenceHash(Base):
    def test_stable_then_moves_on_resolution_and_addition(self):
        a = _finding(1, "rls_disabled_tables", "security", "high", ["access_control"])
        self.seed([a])
        ac = self.db.memo("proj", AC)
        h1 = db_memo.evidence_hash(ac["id"])
        self.assertEqual(len(h1), 64)
        db_memo.attach_evidence("proj", [a])
        self.assertEqual(db_memo.evidence_hash(ac["id"]), h1, "re-attaching unchanged evidence must not move the hash")
        self.resolve("f1")
        h2 = db_memo.evidence_hash(ac["id"])
        self.assertNotEqual(h1, h2, "a resolved gap must change the hash")
        b = _finding(2, "security_definer_functions", "security", "medium", ["access_control"], object_name="fn")
        self.seed([b])
        h3 = db_memo.evidence_hash(ac["id"])
        self.assertNotEqual(h2, h3)

    def test_metrics_change_does_not_move_hash(self):
        a = _finding(1, "slow_query_classes", "performance", "medium", ["availability"])
        self.seed([a])
        o = self.db.memo("proj", OR)
        h1 = db_memo.evidence_hash(o["id"])
        self.db.tables["db_findings"][0]["metrics"] = {"n": 999, "mean_ms": 4000}
        self.assertEqual(db_memo.evidence_hash(o["id"]), h1)

    def test_failure_returns_empty(self):
        with mock.patch.object(db_memo.db, "select", side_effect=RuntimeError("down")):
            self.assertEqual(db_memo.evidence_hash("nope"), "")


# ── rebuild_if_changed ─────────────────────────────────────────────────────────────────

class TestRebuild(Base):
    def setUp(self):
        super().setUp()
        self.seed([_finding(1, "rls_disabled_tables", "security", "critical", ["access_control"]),
                   _finding(2, "anon_or_public_grants", "security", "high", ["access_control"],
                            object_name="profiles")])
        self.ac = self.db.memo("proj", AC)

    def test_drafts_changed_memo_with_one_model_call_then_skips(self):
        out = db_memo.rebuild_if_changed("proj", max_memos=1)
        self.assertEqual(out["drafted"], 1)
        self.assertEqual(self.model.calls, 1)
        row = self.db.memo("proj", AC)
        self.assertEqual(row["status"], "draft")
        self.assertEqual(row["model_name"], "fake-model")
        self.assertEqual(row["model_provider"], "fakeprov")
        self.assertEqual(row["evidence_hash"], db_memo.evidence_hash(row["id"]))
        self.assertEqual(row["evidence_count"], 2)
        self.assertTrue(row["thesis"].startswith("row_level_isolation"))
        self.assertIn(db_memo.CLOSING_LINE, row["body"])
        strengths = {a["key"]: a["strength"] for a in row["arguments"]}
        self.assertEqual(strengths["row_level_isolation"], "undermined")
        self.assertEqual(strengths["anon_surface_minimal"], "undermined")
        self.assertEqual(strengths["privileged_paths_bounded"], "unassessed")
        self.assertEqual(self.rag_calls[0][0][:2], ("legal_memo", f"proj:{AC}"))
        self.assertEqual(self.rag_calls[0][1], {"project": "proj"})
        # prompt quality bar
        p = self.model.prompts[0]
        self.assertIn("firm's own counsel", p)
        self.assertIn("failing answer", p)
        self.assertIn("would change", p)
        self.assertLessEqual(len(p), db_memo.PROMPT_CAP)
        # The cap counts DRAFTS (ORCH_DB_MEMO_MAX_PER_RUN: "memos drafted per run"), so the
        # second memo was deferred, not skipped; checking a hash is free.
        self.assertEqual([m["outcome"] for m in out["memos"]], ["drafted", "deferred"])
        # Least-recently-updated first: the never-drafted DP memo takes this run's slot and
        # AC is deferred unchecked (once the budget is spent a hash check cannot draft).
        out2 = db_memo.rebuild_if_changed("proj", max_memos=1)
        by_kind = {m["memo_kind"]: m["outcome"] for m in out2["memos"]}
        self.assertEqual(by_kind, {DP: "drafted", AC: "deferred"})
        self.assertEqual(self.model.calls, 2)
        # everything drafted and unchanged -> all skips, still no model call
        out3 = db_memo.rebuild_if_changed("proj", max_memos=1)
        self.assertEqual([m["outcome"] for m in out3["memos"]], ["skipped", "skipped"])
        self.assertEqual(self.model.calls, 2)
        # force -> exactly one more call (the cap still holds)
        db_memo.rebuild_if_changed("proj", force=True, max_memos=1)
        self.assertEqual(self.model.calls, 3)
        self.assert_all_internal()

    def test_redrafts_after_resolution(self):
        db_memo.rebuild_if_changed("proj", max_memos=1)
        self.resolve("f1")
        out = db_memo.rebuild_if_changed("proj", max_memos=1)
        self.assertEqual(out["drafted"], 1)
        self.assertEqual(self.model.calls, 2)
        self.assertIn("f1", [x["finding_id"] for x in db_memo._load_ledger(self.ac["id"])])

    def _prime_body(self):
        """Draft EVERY memo (AC first, DP second). Memos are rebuilt least-recently-updated
        first, so a later cap-1 force run deterministically picks AC again."""
        db_memo.rebuild_if_changed("proj", max_memos=5)
        return self.db.memo("proj", AC)["body"]

    def test_short_draft_is_rejected_and_previous_body_kept(self):
        prev = self._prime_body()
        fp = db_memo._load_ledger(self.ac["id"])[0]["fp"]
        self.model.fixed = f"Fine. [fp:{fp}]"
        out = db_memo.rebuild_if_changed("proj", force=True, max_memos=1)
        self.assertEqual(out["rejected"], 1)
        row = self.db.memo("proj", AC)
        self.assertEqual(row["body"], prev)
        self.assertEqual(row["status"], "stale")

    def test_zero_cites_is_rejected(self):
        prev = self._prime_body()
        self.model.fixed = "We believe everything is fine. " * 40 + db_memo.CLOSING_LINE
        out = db_memo.rebuild_if_changed("proj", force=True, max_memos=1)
        self.assertEqual(out["memos"][0]["outcome"], "rejected")
        self.assertIn("zero valid citations", out["memos"][0]["reason"])
        self.assertEqual(self.db.memo("proj", AC)["body"], prev)

    def test_invented_cites_only_is_rejected(self):
        prev = self._prime_body()
        self.model.fixed = good_memo(["deadbeefcafe", "0123456789ab"])
        out = db_memo.rebuild_if_changed("proj", force=True, max_memos=1)
        self.assertEqual(out["memos"][0]["outcome"], "rejected")
        self.assertEqual(self.db.memo("proj", AC)["body"], prev)

    def test_mixed_cites_accepted_with_invented_stripped(self):
        self._prime_body()
        fps = [x["fp"] for x in db_memo._load_ledger(self.ac["id"])]
        self.model.fixed = good_memo(fps, extra_cites=["deadbeefcafe"])
        out = db_memo.rebuild_if_changed("proj", force=True, max_memos=1)
        self.assertEqual(out["memos"][0]["outcome"], "drafted")
        body = self.db.memo("proj", AC)["body"]
        self.assertNotIn("deadbeefcafe", body)
        for fp in fps:
            self.assertIn(f"[fp:{fp}]", body)

    def test_hash_not_consumed_by_rejection(self):
        self._prime_body()
        self.resolve("f2")  # evidence moved
        self.model.fixed = "too short"
        db_memo.rebuild_if_changed("proj", max_memos=1)
        row = self.db.memo("proj", AC)
        self.assertNotEqual(row["evidence_hash"], db_memo.evidence_hash(row["id"]),
                            "a rejected draft must leave the hash unmatched so the next run retries")

    def test_model_error_persists_deterministic_rendering(self):
        self.model.raise_exc = RuntimeError("no provider")
        out = db_memo.rebuild_if_changed("proj", max_memos=1)
        self.assertEqual(out["deterministic"], 1)
        row = self.db.memo("proj", AC)
        self.assertEqual(row["model_name"], "deterministic")
        self.assertIsNone(row["model_provider"])
        self.assertIn(db_memo.CLOSING_LINE, row["body"])
        self.assertIn("## Evidence", row["body"])
        for key in MEMO_KINDS[AC]["arguments"]:
            self.assertIn(key, row["body"])
        self.assertEqual(row["status"], "draft")
        self.assertIsNone(row["evidence_hash"], "deterministic body must not consume the hash")
        # a memo with no prior body and a hollow draft also ends up with prose
        self.model.raise_exc = None
        self.model.fixed = "hollow"
        self.db.tables["legal_memo_drafts"][0]["body"] = None
        out = db_memo.rebuild_if_changed("proj", max_memos=5)  # AC (hash unconsumed) and DP
        outcomes = {m["memo_kind"]: m["outcome"] for m in out["memos"]}
        self.assertEqual(outcomes[AC], "rejected_fallback_deterministic")
        self.assertIn(db_memo.CLOSING_LINE, self.db.memo("proj", AC)["body"])
        self.assertEqual(self.db.memo("proj", AC)["status"], "stale")

    def test_per_run_cap_defers(self):
        self.seed([_finding(3, "vacuum_stale", "availability", "medium", ["availability"], object_name="o")])
        self.assertEqual(len(self.db.tables["legal_memo_drafts"]), 3)  # AC, DP, OR
        out = db_memo.rebuild_if_changed("proj", max_memos=1)
        self.assertEqual(self.model.calls, 1)
        self.assertEqual(sorted(m["outcome"] for m in out["memos"]), ["deferred", "deferred", "drafted"])
        out = db_memo.rebuild_if_changed("proj", max_memos=5)
        self.assertEqual(self.model.calls, 3)
        self.assertEqual(out["skipped"], 1)
        self.assertEqual(out["drafted"], 2)
        self.assert_all_internal()

    def test_prompt_is_capped_with_large_ledger(self):
        many = [_finding(100 + i, "unused_indexes", "performance", "low", ["availability"], object_name=f"t{i}",
                         detail="x" * 300) for i in range(200)]
        self.seed(many)
        db_memo.rebuild_if_changed("proj", max_memos=5)
        self.assertTrue(all(len(p) <= db_memo.PROMPT_CAP for p in self.model.prompts))
        self.assertTrue(any("ledger truncated" in p for p in self.model.prompts))

    def test_no_memo_project_is_fail_soft(self):
        out = db_memo.rebuild_if_changed("ghost")
        self.assertEqual(out["checked"], 0)
        with mock.patch.object(db_memo.db, "select", side_effect=RuntimeError("down")):
            self.assertEqual(db_memo.rebuild_if_changed("proj")["checked"], 0)

    def test_run_covers_projects_with_open_findings(self):
        out = db_memo.run()
        self.assertEqual(list(out), ["proj"])
        self.assertEqual(self.model.calls, 2)  # AC + DP


# ── gauntlet ───────────────────────────────────────────────────────────────────────────

class TestGauntlet(Base):
    def setUp(self):
        super().setUp()
        self.seed([_finding(1, "rls_disabled_tables", "security", "critical", ["access_control"])])
        db_memo.rebuild_if_changed("proj", max_memos=1)
        self.memo = self.db.memo("proj", AC)
        self.material = [_finding(1, "rls_disabled_tables", "security", "critical", ["access_control"])]
        self.minor = [_finding(5, "unused_indexes", "performance", "low", ["availability"])]

    def test_should_gauntlet_gating(self):
        self.assertTrue(db_memo.should_gauntlet(self.memo, self.material))
        self.assertFalse(db_memo.should_gauntlet(self.memo, self.minor))
        self.assertFalse(db_memo.should_gauntlet(self.memo, []))
        recent = {**self.memo, "gauntlet_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}
        self.assertFalse(db_memo.should_gauntlet(recent, self.material))
        old = {**self.memo, "gauntlet_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()}
        self.assertTrue(db_memo.should_gauntlet(old, self.material))
        with mock.patch.dict(os.environ, {"ORCH_DB_MEMO_GAUNTLET_MIN_INTERVAL_S": "3000000"}):
            self.assertFalse(db_memo.should_gauntlet(old, self.material))
        with mock.patch.dict(os.environ, {"ORCH_DB_MEMO_GAUNTLET": "false"}):
            self.assertFalse(db_memo.should_gauntlet(self.memo, self.material))

    def test_review_stores_result_and_marks_reviewed(self):
        self.gauntlet.return_value = {"verdict": "overstated", "opinion": "row_level_isolation is fairly undermined."}
        res = db_memo.gauntlet_review(self.memo, self.material)
        self.assertEqual(res["verdict"], "overstated")
        kwargs = self.gauntlet.call_args.kwargs
        self.assertEqual(kwargs["vertical"], "data")
        self.assertLessEqual(len(kwargs["context"]), db_memo.GAUNTLET_CONTEXT_CAP)
        self.assertIn("EVIDENCE LEDGER", kwargs["context"])
        row = self.db.memo("proj", AC)
        self.assertEqual(row["status"], "reviewed")
        self.assertEqual(row["gauntlet"]["verdict"], "overstated")
        self.assertTrue(row["gauntlet_at"])
        self.committees.assert_not_called()
        self.assert_all_internal()

    def test_review_skipped_when_not_material(self):
        self.assertIsNone(db_memo.gauntlet_review(self.memo, self.minor))
        self.gauntlet.assert_not_called()

    def test_gauntlet_error_falls_back_to_committees(self):
        self.gauntlet.side_effect = RuntimeError("corps cold")
        self.committees.return_value = {"position": "reasonable", "verdict": None}
        res = db_memo.gauntlet_review(self.memo, self.material)
        self.assertEqual(res["position"], "reasonable")
        args = self.committees.call_args
        self.assertEqual(args.args[:2], ("legal_memo", self.memo["id"]))
        self.assertEqual(args.kwargs["app"], "proj")
        self.assertEqual(self.db.memo("proj", AC)["status"], "reviewed")

    def test_gauntlet_error_result_falls_back_and_total_failure_is_none(self):
        self.gauntlet.return_value = {"error": "expert corps too small"}
        self.committees.side_effect = RuntimeError("no panel")
        self.assertIsNone(db_memo.gauntlet_review(self.memo, self.material))
        self.assertEqual(self.db.memo("proj", AC)["status"], "draft")
        self.assertIsNone(self.db.memo("proj", AC).get("gauntlet_at"))


# ── render / summary / signals ─────────────────────────────────────────────────────────

class TestRenderAndReads(Base):
    def setUp(self):
        super().setUp()
        self.seed([
            _finding(1, "missing_audit_columns", "audit", "high", ["audit_trail"], object_name="invoices"),
            _finding(2, "missing_audit_columns", "audit", "high", ["audit_trail"], object_name="payments"),
            _finding(3, "missing_audit_columns", "audit", "medium", ["audit_trail"], object_name="notes"),
            _finding(4, "audit_trail_presence", "audit", "info", ["audit_trail"], direction="supports",
                     object_name="events"),
            _finding(5, "tables_without_primary_key", "integrity", "low", ["integrity"], object_name="tmp"),
            _finding(6, "rls_disabled_tables", "security", "critical", ["access_control"], object_name="users"),
            _finding(7, "vacuum_stale", "availability", "medium", ["availability"], object_name="orders"),
        ])
        self.resolve("f5")

    def test_render_markdown_has_every_argument_and_closing_line(self):
        ri = self.db.memo("proj", RI)
        ledger = db_memo._load_ledger(ri["id"])
        md = db_memo.render_markdown(ri, ledger)
        for key, claim in MEMO_KINDS[RI]["arguments"].items():
            self.assertIn(key, md)
            self.assertIn(claim, md)
        for section in ("## Question presented", "## Short answer", "## Evidence", "## Gaps and remediation",
                        "## What would change the conclusion"):
            self.assertIn(section, md)
        self.assertTrue(md.rstrip().endswith(db_memo.CLOSING_LINE))
        for x in ledger:
            self.assertIn(f"[fp:{x['fp']}]", md)
        self.assertIn("was a gap, closed on 2026-09-11", md)
        self.assertIn("CONTEMPORANEOUS_RECORDS: **UNDERMINED**".lower(), md.lower())
        self.assertIn("regular_practice: **SUPPORTED**", md)
        self.assertIn("tamper_evidence: **UNASSESSED**", md)
        self.assertIn("referential_integrity: **UNASSESSED**", md)  # its only gap was closed

    def test_score_arguments_contested(self):
        ledger = [{"argument_key": "k", "direction": "supports", "weight": 1.0, "status": "open", "fp": "a" * 12},
                  {"argument_key": "k", "direction": "undermines", "weight": 1.0, "status": "open", "fp": "b" * 12}]
        with mock.patch.dict(MEMO_KINDS, {"tmp_memo": {"arguments": {"k": "claim"}}}):
            self.assertEqual(db_memo.score_arguments("tmp_memo", ledger)[0]["strength"], "contested")

    def test_memo_summary(self):
        db_memo.rebuild_if_changed("proj", max_memos=10)
        summ = {s["memo_kind"]: s for s in db_memo.memo_summary("proj")}
        self.assertEqual(summ[RI]["strengths"], {"supported": 1, "contested": 0, "undermined": 1, "unassessed": 2})
        self.assertEqual(summ[RI]["evidence_count"], 4)
        self.assertEqual(summ[RI]["status"], "draft")
        self.assertEqual(summ[RI]["title"], MEMO_KINDS[RI]["title"])

    def test_steering_signals_order_and_caps(self):
        db_memo.rebuild_if_changed("proj", max_memos=10)
        lines = db_memo.steering_signals("proj")
        self.assertEqual(len(lines), 4)  # contemporaneous_records, row_level_isolation, pii_not_exposed, maintenance_current
        self.assertTrue(lines[0].startswith("records_integrity: 3 findings undermine contemporaneous_records"))
        self.assertIn("fix missing_audit_columns on invoices", lines[0])
        self.assertTrue(lines[1].startswith("access_control: 1 finding undermine row_level_isolation"))
        self.assertTrue(lines[-1].startswith("operational_resilience: 1 finding undermine maintenance_current"))
        self.assertTrue(all(len(l) <= 200 for l in lines))
        # cap at 6 lines
        for i in range(8):
            self.seed([_finding(50 + i, f"weird_probe_{i}", "security", "low", ["access_control", "availability",
                                                                                "change_control", "ai_logging"],
                                object_name=f"t{i}", remediation="r" * 500)])
        db_memo.rebuild_if_changed("proj", force=True, max_memos=10)
        lines = db_memo.steering_signals("proj")
        self.assertLessEqual(len(lines), 6)
        self.assertTrue(all(len(l) <= 200 for l in lines))

    def test_reads_are_fail_soft(self):
        with mock.patch.object(db_memo.db, "select", side_effect=RuntimeError("down")):
            self.assertEqual(db_memo.memo_summary("proj"), [])
            self.assertEqual(db_memo.steering_signals("proj"), [])
            self.assertEqual(db_memo.run("proj"), {"proj": mock.ANY})


# ── expert corps vertical ──────────────────────────────────────────────────────────────

class TestVertical(unittest.TestCase):
    def test_data_vertical_registered(self):
        import expert_corps
        self.assertIn("data", expert_corps.VERTICALS)
        self.assertEqual(len(expert_corps.VERTICALS["data"]), 5)
        self.assertIn("database security & row-level access", expert_corps.VERTICALS["data"])


if __name__ == "__main__":
    unittest.main()


def test_ensure_memo_accepts_list_or_dict_insert_echo(monkeypatch):
    """PostgREST echoes an insert as a one-element list; the first live cycle crashed
    because the skeleton row was used as a dict. Both shapes must resolve to a row."""
    for echo in (lambda row: [row], lambda row: row):
        fake = FakeDb()
        real_insert = fake.insert
        fake.insert = lambda table, row, upsert=False, _r=real_insert, _e=echo: _e(_r(table, row, upsert)[0])
        monkeypatch.setattr(db_memo, "db", fake)
        memo = db_memo._ensure_memo("proj", "operational_resilience", {})
        assert isinstance(memo, dict) and memo.get("id")


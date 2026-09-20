#!/usr/bin/env python3
"""Capability-silence immunity: the alert metrics, the rules, and the brief line.

Incident class this guards (measured 2026-09-20): a thinking model served the
fleet's strong tier; /api/generate returned empty responses; memos persisted
their deterministic template for six days while evidence refreshed daily, and
nothing in the fleet noticed. These tests pin the three surfaces that would
have caught it inside one cycle: the alert metrics, the default rules, and the
steering brief line.
"""
import datetime
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _iso(dt):
    return dt.isoformat()


# Rows in the shape the control plane actually stores (captured live 09-20):
# drafted_at frozen days back, updated_at ticking with each evidence pass.
def _template_memo(hours_old=120, evidence_moved=True):
    now = datetime.datetime.now(datetime.timezone.utc)
    drafted = now - datetime.timedelta(hours=hours_old)
    updated = now - datetime.timedelta(minutes=5) if evidence_moved else drafted
    return {"id": 1, "drafted_at": _iso(drafted), "updated_at": _iso(updated), "model_name": "deterministic", "project": "proj-x"}


class FakeDb:
    """Minimal db seam: canned tables, select/count only, exactly the surface used."""

    def __init__(self, tables=None):
        self.tables = tables or {}

    def select(self, table, params=None):
        rows = self.tables.get(table, [])
        params = params or {}
        out = []
        for r in rows:
            keep = True
            for k, v in params.items():
                if k == "select" or not isinstance(v, str):
                    continue
                if v.startswith("eq."):
                    want = v[3:]
                    got = r.get(k)
                    if want in ("true", "false"):
                        keep &= got is (want == "true")
                    else:
                        keep &= str(got) == want
                elif v.startswith("gte."):
                    keep &= str(r.get(k) or "") >= v[4:]
            if keep:
                out.append(r)
        return out

    def count(self, table, params=None):
        return len(self.select(table, params))


class AlertMetricTests(unittest.TestCase):
    def _collect(self, tables, env=None):
        from alert_rules_engine import _collect_metrics
        with patch.dict(sys.modules, {"db": FakeDb(tables)}), \
             patch.dict(os.environ, env or {}, clear=False):
            if not (env or {}).get("OLLAMA_STRONG_MODEL"):
                os.environ.pop("OLLAMA_STRONG_MODEL", None)
            return _collect_metrics()

    def test_template_memo_counts_only_stale_and_moving(self):
        m = self._collect({"legal_memo_drafts": [
            _template_memo(hours_old=120, evidence_moved=True),
            _template_memo(hours_old=2, evidence_moved=True),
            _template_memo(hours_old=120, evidence_moved=False),
        ]})
        self.assertEqual(m.get("template_memos_stale"), 1)

    def test_strong_tier_metric_absent_when_unconfigured(self):
        m = self._collect({"legal_memo_drafts": []}, env={"OLLAMA_STRONG_MODEL": ""})
        self.assertNotIn("strong_local_ops_24h_ok", m)

    def test_strong_tier_metric_counts_ok_calls(self):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        m = self._collect({
            "legal_memo_drafts": [],
            "app_operations": [
                {"id": 1, "provider": "local", "model": "qwen3.5:27b-mlx", "ok": True, "created_at": now},
                {"id": 2, "provider": "local", "model": "qwen3.5:27b-mlx", "ok": False, "created_at": now},
                {"id": 3, "provider": "local", "model": "llama3.1:8b", "ok": True, "created_at": now},
            ],
        }, env={"OLLAMA_STRONG_MODEL": "qwen3.5:27b-mlx"})
        self.assertEqual(m.get("strong_local_ops_24h_ok"), 1)

    def test_unmeasured_is_not_zero(self):
        class Exploding(FakeDb):
            def select(self, table, params=None):
                if table == "legal_memo_drafts":
                    raise RuntimeError("control plane down")
                return super().select(table, params)
        from alert_rules_engine import _collect_metrics
        with patch.dict(sys.modules, {"db": Exploding()}), \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OLLAMA_STRONG_MODEL", None)
            m = _collect_metrics()
        self.assertIsNone(m.get("template_memos_stale"))


class AlertRuleTests(unittest.TestCase):
    def test_default_rules_include_the_two_capability_rules(self):
        from alert_rules_engine import DEFAULT_RULES
        ids = {r["id"] for r in DEFAULT_RULES}
        self.assertIn("memo_template_standing_in", ids)
        self.assertIn("strong_tier_silent", ids)

    def test_rule_fires_and_does_not_fire(self):
        import importlib
        import alert_rules_engine
        importlib.reload(alert_rules_engine)
        firing = alert_rules_engine.evaluate(metrics={"template_memos_stale": 3, "quarantine_ratio": 0,
                                   "throughput_1h": 5, "pending_approvals": 0,
                                   "strong_local_ops_24h_ok": 0})
        fired_ids = {a["rule_id"] for a in firing}
        self.assertIn("memo_template_standing_in", fired_ids)
        self.assertIn("strong_tier_silent", fired_ids)
        importlib.reload(alert_rules_engine)
        calm = alert_rules_engine.evaluate(metrics={"template_memos_stale": 0, "quarantine_ratio": 0,
                                 "throughput_1h": 5, "pending_approvals": 0,
                                 "strong_local_ops_24h_ok": 4,
                                 "queued_count": 0, "running_count": 0,
                                 "merge_rate_24h": 1, "merge_rate_1h": 1})
        self.assertNotIn("memo_template_standing_in", {a["rule_id"] for a in calm})
        self.assertNotIn("strong_tier_silent", {a["rule_id"] for a in calm})


class BriefLineTests(unittest.TestCase):
    def test_capability_line_tracks_template_staleness(self):
        import importlib
        db_mod = FakeDb({"legal_memo_drafts": [_template_memo()],
                         "db_findings": [], "db_steering_briefs": []})
        with patch.dict(sys.modules, {"db": db_mod}):
            steering = importlib.import_module("db_steering")
            importlib.reload(steering)
            self.assertEqual(steering._template_memo_count("proj-x"), 1)
            text, _ = steering.build_brief("proj-x", findings=[{
                "probe_id": "rls_missing", "category": "security", "severity": "high",
                "title": "x", "fingerprint": "abc123", "direction": "undermines"}])
            self.assertIn("CAPABILITY:", text)
        db_fresh = FakeDb({"legal_memo_drafts": [_template_memo(hours_old=1)],
                           "db_findings": [], "db_steering_briefs": []})
        with patch.dict(sys.modules, {"db": db_fresh}):
            steering = importlib.import_module("db_steering")
            importlib.reload(steering)
            self.assertEqual(steering._template_memo_count("proj-x"), 0)
            text, _ = steering.build_brief("proj-x", findings=[{
                "probe_id": "rls_missing", "category": "security", "severity": "high",
                "title": "x", "fingerprint": "abc123", "direction": "undermines"}])
            self.assertNotIn("CAPABILITY:", text)


if __name__ == "__main__":
    unittest.main()

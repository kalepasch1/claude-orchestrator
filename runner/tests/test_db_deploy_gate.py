"""db_deploy_gate: posture -> commit-status gate. Gate rules and HTTP paths, fully faked."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import db_deploy_gate as G  # noqa: E402


def _decision_body(decision, target_url=""):
    import db_deploy_gate as G
    bullets = "\n".join("- %s" % t for t in (decision.get("top") or []))
    return ("%s %s: **%s** — %s%s\n\nDatabase Steering posture gate (read-only review).%s"
            % (G.COMMENT_MARKER, G.CONTEXT, decision["state"], decision["description"],
               "\n\nOpen high findings:\n" + bullets if bullets else "",
               " " + target_url if target_url else ""))


class EvaluateTest(unittest.TestCase):
    def _count(self, highs=(), drift=(), meds=()):
        def count(table, params):
            cat = params.get("category", "")
            sev = params.get("severity", "")
            probe = params.get("probe_id", "")
            if params.get("status") != "eq.open":
                return 0
            if probe == "eq.schema_drift_live_ahead":
                return len(drift)
            if sev == "eq.high" and "security" in cat:
                return len(highs)
            if "medium" in sev:
                return len(meds)
            return 0
        return count

    def test_high_security_fails_the_gate(self):
        with patch.object(G.db, "count", self._count(highs=(1,))), \
             patch.object(G.db, "select", lambda t, p: [{"title": "anon holds DELETE on public.users"}]):
            d = G.evaluate({"name": "x"})
        self.assertFalse(d["ok"])  and self.assertEqual(d["state"], "failure")
        self.assertIn("1 open high-severity security finding(s)", d["description"])
        self.assertEqual(d["top"], ["anon holds DELETE on public.users"])

    def test_drift_live_ahead_fails_the_gate(self):
        with patch.object(G.db, "count", self._count(drift=(1,))):
            d = G.evaluate({"name": "x"})
        self.assertFalse(d["ok"]) and "live schema ahead" in d["description"]

    def test_medium_only_is_a_warn_pass(self):
        with patch.object(G.db, "count", self._count(meds=(1, 2, 3))):
            d = G.evaluate({"name": "x"})
        self.assertTrue(d["ok"]) and d["state"] == "success"
        self.assertIn("3 medium/low open", d["description"])

    def test_db_error_is_fail_soft_warn(self):
        with patch.object(G.db, "count", side_effect=RuntimeError("down")):
            d = G.evaluate({"name": "x"})
        self.assertTrue(d["ok"])  # an unreachable control plane must not block deploys


class PostingTest(unittest.TestCase):
    def test_evaluate_only_mode_posts_nothing(self):
        with patch.object(G, "ENABLED", False), \
             patch.object(G.db, "count", lambda t, p: 0), \
             patch.object(G.db_remediate, "_gh", side_effect=AssertionError("no http")):
            out = G.check_project({"name": "x", "vercel_project": "vp"})
        self.assertIn("evaluate-only", out["mode"]) and out["posted"] is False

    def test_posts_to_deployment_sha_and_base_head(self):
        posts = []

        def gh(method, path, body=None):
            if method == "GET" and "/git/ref/heads/" in path:
                return {"object": {"sha": "h" * 40}}
            if method == "POST" and "/statuses/" in path:
                posts.append((path, body))
                return {"state": body["state"]}
            return {}

        with patch.object(G, "ENABLED", True), \
             patch.object(G.db, "count", lambda t, p: 0), \
             patch.object(G, "_vercel_latest_sha", lambda vp: ("d" * 40, "READY", "https://v.test")), \
             patch.object(G.db_remediate, "repo_for_project", lambda p: "me/x"), \
             patch.object(G.db_remediate, "_gh", gh):
            out = G.check_project({"name": "x", "vercel_project": "vp", "prod_branch": "main"})
        self.assertTrue(out["posted"])
        self.assertEqual({p[1]["context"] for p in posts}, {G.CONTEXT})
        self.assertEqual(len(posts), 2, "deployment sha + base head")

    def test_posting_failure_is_reported_not_raised(self):
        with patch.object(G, "ENABLED", True), \
             patch.object(G.db, "count", lambda t, p: 0), \
             patch.object(G.db_remediate, "repo_for_project", side_effect=RuntimeError("gh down")):
            out = G.check_project({"name": "x", "vercel_project": "vp"})
        self.assertIn("error", out)


class CommentFallbackTest(unittest.TestCase):
    def test_403_status_falls_back_to_comment_upsert(self):
        calls = []

        def gh(method, path, body=None):
            calls.append((method, path, body))
            if "/statuses/" in path:
                return {"_http_error": 403, "_message": "Resource not accessible by integration"}
            if "/comments" in path and method == "GET":
                return []
            if "/comments" in path and method == "POST":
                return {"id": 5}
            return {}

        with patch.object(G.db_remediate, "_gh", gh):
            ok = G.post_status("me/x", "s" * 40, {"state": "failure", "description": "2 high security"})
        self.assertTrue(ok)
        self.assertTrue(any(m == "POST" and "/comments" in p for _i, (m, p, _b) in enumerate(calls)
                            if True for m, p, _b in [(m, p, _b)]))
        body = [b for m, p, b in calls if m == "POST" and p.endswith("/comments")][0]["body"]
        self.assertIn(G.COMMENT_MARKER, body) and self.assertIn("failure", body)

    def test_comment_upsert_noop_when_state_unchanged(self):
        decision = {"state": "success", "description": "posture ok (3 medium/low open)", "top": []}
        existing = [{"id": 5, "body": _decision_body(decision)}]

        def gh(method, path, body=None):
            if "/comments" in path and method == "GET":
                return list(existing)
            if method in ("POST", "PATCH"):
                raise AssertionError("must not write when nothing changed")
            return {"_http_error": 403}

        with patch.object(G.db_remediate, "_gh", gh):
            self.assertTrue(G._comment_upsert("me/x", "s" * 40, decision))

    def test_comment_upsert_patches_on_state_change(self):
        existing = [{"id": 5, "body": _decision_body({"state": "success", "description": "posture ok"})}]
        patched = []

        def gh(method, path, body=None):
            if "/comments" in path and method == "GET":
                return list(existing)
            if method == "PATCH":
                patched.append((path, body))
                return {"id": 5}
            return {"_http_error": 403}

        with patch.object(G.db_remediate, "_gh", gh):
            self.assertTrue(G._comment_upsert("me/x", "s" * 40,
                                              {"state": "failure", "description": "2 high security",
                                               "top": ["anon holds DELETE on public.users"]}))
        self.assertTrue(patched and patched[0][0].endswith("/comments/5"))
        self.assertIn("failure", patched[0][1]["body"])
        self.assertIn("anon holds DELETE on public.users", patched[0][1]["body"])


class RunCycleTest(unittest.TestCase):
    def test_only_vercel_linked_non_superseded_projects(self):
        projects = [{"name": "a", "vercel_project": "vp"}, {"name": "b", "vercel_project": None},
                    {"name": "c", "vercel_project": "vp", "superseded_by": "a"}]
        with patch.object(G, "check_project", side_effect=lambda p: {"project": p["name"]}):
            out = G.run_cycle(projects)
        self.assertEqual([c["project"] for c in out["checked"]], ["a"])


if __name__ == "__main__":
    unittest.main()

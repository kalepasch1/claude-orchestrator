"""Tests for shared_world_model — the cross-app schema/endpoint/contract graph.

Everything here runs against a synthetic two-app fleet on a tmpdir, so the tests assert
behaviour rather than the current contents of any real repo.

The invariants worth defending:
  - a surface is DEFINITIONS only (a file that queries a table does not own it),
  - cross-app impact is reported for the OTHER app, never the source app,
  - noise symbols ("users", "data", short names) never generate a report,
  - every public function fails soft — no exception escapes, ever,
  - blast_radius keeps its old two-argument shape (additive change only).
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import shared_world_model as swm  # noqa: E402


def _write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    return path


class FleetFixture(unittest.TestCase):
    """Two apps: `alpha` owns a table + endpoint; `beta` consumes both by name."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        swm.invalidate()
        self.addCleanup(swm.invalidate)

        self.alpha = os.path.join(self.tmp.name, "alpha")
        self.beta = os.path.join(self.tmp.name, "beta")

        _write(self.alpha, "prisma/schema.prisma",
               'model LedgerEntry {\n  id Int @id\n  @@map("ledger_entries")\n}\n')
        _write(self.alpha, "supabase/migrations/001_init.sql",
               "CREATE TABLE IF NOT EXISTS settlement_proofs (id uuid primary key);\n")
        _write(self.alpha, "server/api/ledger/[id].get.ts",
               "export default defineEventHandler(() => ({}))\n")

        _write(self.beta, "server/api/report.get.ts",
               "const rows = await sql`select * from ledger_entries`\n"
               "await $fetch('/api/ledger/1')\n")
        _write(self.beta, "lib/unrelated.ts", "export const x = 1\n")

        self.projects = [{"name": "alpha", "repo_path": self.alpha},
                         {"name": "beta", "repo_path": self.beta}]

    def graph(self):
        return swm.build_graph(projects=self.projects)


class ScanTest(FleetFixture):
    def test_prisma_model_and_map_both_owned(self):
        s = swm.scan_project(self.projects[0])
        self.assertIn("LedgerEntry", s["tables"])
        self.assertIn("ledger_entries", s["tables"])

    def test_sql_create_table_owned(self):
        s = swm.scan_project(self.projects[0])
        self.assertIn("settlement_proofs", s["tables"])

    def test_nuxt_route_becomes_endpoint(self):
        s = swm.scan_project(self.projects[0])
        self.assertIn("/api/ledger/[id]", s["endpoints"])

    def test_consumer_does_not_own_what_it_queries(self):
        # beta only SELECTs from ledger_entries; ownership must stay with alpha
        s = swm.scan_project(self.projects[1])
        self.assertNotIn("ledger_entries", s["tables"])

    def test_missing_repo_is_empty_surface_not_an_error(self):
        s = swm.scan_project({"name": "ghost", "repo_path": "/no/such/dir"})
        self.assertEqual(s["tables"], {})
        self.assertEqual(s["files"], 0)

    def test_none_project_is_safe(self):
        self.assertEqual(swm.scan_project(None)["tables"], {})

    def test_python_modules_and_decorated_routes(self):
        root = os.path.join(self.tmp.name, "py")
        _write(root, "svc/handlers.py",
               '@app.get("/v1/widgets")\ndef widgets(): pass\n')
        s = swm.scan_project({"name": "py", "repo_path": root})
        self.assertIn("handlers", s["modules"])
        self.assertIn("/v1/widgets", s["endpoints"])


class PriorityWalkTest(unittest.TestCase):
    """The file cap must bound cost without ever starving the surface.

    Regression: a flat os.walk exhausted a 4,000-file cap on app/ before reaching
    server/api, so two large Nuxt apps reported 0 and 20 endpoints respectively. A world
    model that confidently says "nothing is shared" is worse than no world model.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        # 40 files of noise that sort before "server/", then one real endpoint
        for i in range(40):
            _write(self.root, f"app/components/c{i:03d}.vue", "<template/>")
        _write(self.root, "server/api/ledger.get.ts", "export default 1\n")
        _write(self.root, "prisma/schema.prisma",
               'model LedgerEntry {\n  @@map("ledger_entries")\n}\n')

    def test_surface_survives_a_cap_smaller_than_the_repo(self):
        with mock.patch.object(swm, "MAX_FILES", 3):
            s = swm.scan_project({"name": "big", "repo_path": self.root})
        self.assertIn("/api/ledger", s["endpoints"])
        self.assertIn("ledger_entries", s["tables"])

    def test_cap_is_still_enforced(self):
        with mock.patch.object(swm, "MAX_FILES", 3):
            self.assertLessEqual(len(swm._walk(self.root)), 3)

    def test_no_duplicate_files_across_priority_and_full_pass(self):
        files = swm._walk(self.root)
        self.assertEqual(len(files), len(set(files)))

    def test_missing_priority_dirs_are_skipped_not_fatal(self):
        empty = os.path.join(self.tmp.name, "empty")
        os.makedirs(empty)
        self.assertEqual(swm._walk(empty), [])


class GraphTest(FleetFixture):
    def test_owners_index(self):
        g = self.graph()
        owners = [o[0] for o in swm.owners_of("ledger_entries", graph=g)]
        self.assertEqual(owners, ["alpha"])

    def test_unknown_symbol_has_no_owner(self):
        self.assertEqual(swm.owners_of("nope_not_here", graph=self.graph()), [])

    def test_cache_is_reused_and_invalidatable(self):
        with mock.patch.object(swm, "_projects", return_value=self.projects) as p:
            swm.build_graph(force=True)
            swm.build_graph()
            self.assertEqual(p.call_count, 1)   # second call served from cache
            swm.invalidate()
            swm.build_graph()
            self.assertEqual(p.call_count, 2)

    def test_build_graph_survives_a_bad_project_row(self):
        rows = self.projects + [{"repo_path": "/x"}]  # no name
        g = swm.build_graph(projects=rows)
        self.assertEqual(sorted(g["projects"]), ["alpha", "beta"])

    def test_no_database_is_not_fatal(self):
        with mock.patch.dict(sys.modules, {"db": None}):
            self.assertEqual(swm._projects(), [])


class CrossAppRadiusTest(FleetFixture):
    def test_schema_change_names_the_other_app(self):
        r = swm.cross_app_radius("alpha", ["prisma/schema.prisma"], graph=self.graph())
        self.assertIn("ledger_entries", r["symbols"])
        self.assertIn("beta", {i["project"] for i in r["impacted"]})

    def test_endpoint_change_names_the_other_app(self):
        r = swm.cross_app_radius("alpha", ["server/api/ledger/[id].get.ts"],
                                 graph=self.graph())
        self.assertTrue(any(i["project"] == "beta" for i in r["impacted"]))

    def test_source_app_never_reports_itself(self):
        r = swm.cross_app_radius("alpha", ["prisma/schema.prisma"], graph=self.graph())
        self.assertNotIn("alpha", {i["project"] for i in r["impacted"]})

    def test_unreferenced_table_has_no_impact(self):
        r = swm.cross_app_radius("alpha", ["supabase/migrations/001_init.sql"],
                                 graph=self.graph())
        self.assertEqual(r["impacted"], [])

    def test_untouched_file_yields_nothing(self):
        r = swm.cross_app_radius("alpha", ["README.md"], graph=self.graph())
        self.assertEqual(r["symbols"], [])
        self.assertEqual(r["impacted"], [])

    def test_absolute_path_suffix_match(self):
        r = swm.cross_app_radius("alpha",
                                 [os.path.join(self.alpha, "prisma/schema.prisma")],
                                 graph=self.graph())
        self.assertIn("ledger_entries", r["symbols"])

    def test_unknown_project_is_empty_not_an_error(self):
        r = swm.cross_app_radius("nosuchapp", ["x.sql"], graph=self.graph())
        self.assertEqual(r["impacted"], [])

    def test_broken_graph_fails_soft(self):
        with mock.patch.object(swm, "build_graph", side_effect=RuntimeError("boom")):
            self.assertEqual(swm.cross_app_radius("alpha", ["a.sql"])["impacted"], [])


class NoiseFilterTest(unittest.TestCase):
    def test_short_symbols_rejected(self):
        self.assertFalse(swm._interesting("id"))
        self.assertFalse(swm._interesting("api"))

    def test_stopword_symbols_rejected(self):
        for word in ("users", "data", "config", "tasks"):
            self.assertFalse(swm._interesting(word), word)

    def test_real_symbol_accepted(self):
        self.assertTrue(swm._interesting("ledger_entries"))

    def test_noise_never_reaches_the_reference_scan(self):
        with mock.patch.object(swm, "_walk") as walk:
            self.assertEqual(swm._references("/repo", ["id", "users"]), {})
            walk.assert_not_called()


class DynamicRouteNeedleTest(unittest.TestCase):
    """A route DEFINED as /api/ledger/[id] is CALLED as /api/ledger/42.

    Searching for the declared name literally finds nothing, which would make the tool
    report a confident, wrong "no impact" for every parameterised endpoint.
    """

    def test_nuxt_bracket_param_reduced_to_static_prefix(self):
        self.assertEqual(swm._needle("/api/ledger/[id]"), "/api/ledger")

    def test_express_colon_param(self):
        self.assertEqual(swm._needle("/v1/orders/:orderId"), "/v1/orders")

    def test_flask_angle_param(self):
        self.assertEqual(swm._needle("/v1/orders/<oid>"), "/v1/orders")

    def test_brace_param(self):
        self.assertEqual(swm._needle("/v1/orders/{oid}"), "/v1/orders")

    def test_static_route_unchanged(self):
        self.assertEqual(swm._needle("/api/ledger"), "/api/ledger")

    def test_prefix_too_generic_is_dropped(self):
        # "/[id]" leaves nothing specific enough to search for
        self.assertIsNone(swm._needle("/[id]"))

    def test_table_names_pass_through_untouched(self):
        self.assertEqual(swm._needle("ledger_entries"), "ledger_entries")


class NoteTest(FleetFixture):
    def test_note_fires_when_prompt_names_a_shared_table(self):
        note = swm.note_for_task("alpha", "rename ledger_entries to postings",
                                 graph=self.graph())
        self.assertIn("beta", note)
        self.assertIn("ledger_entries", note)

    def test_note_is_empty_when_nothing_is_shared(self):
        self.assertEqual(
            swm.note_for_task("alpha", "tidy up the README", graph=self.graph()), "")

    def test_note_is_empty_for_unknown_project(self):
        self.assertEqual(swm.note_for_task("ghost", "ledger_entries",
                                           graph=self.graph()), "")

    def test_note_never_raises(self):
        with mock.patch.object(swm, "build_graph", side_effect=RuntimeError("boom")):
            self.assertEqual(swm.note_for_task("alpha", "ledger_entries"), "")

    def test_changed_files_override_prompt_matching(self):
        note = swm.note_for_task("alpha", "unrelated prompt text",
                                 changed_files=["prisma/schema.prisma"],
                                 graph=self.graph())
        self.assertIn("beta", note)


class CapabilityEdgeTest(unittest.TestCase):
    def _db(self, caps, instances):
        stub = mock.MagicMock()
        stub.select.side_effect = lambda table, *a, **k: (
            caps if table == "capabilities" else instances)
        return stub

    def test_active_instance_becomes_an_edge(self):
        db = self._db([{"id": 1, "slug": "kyc", "status": "active"}],
                      [{"capability_id": 1, "project": "beta", "version": "1.0.0",
                        "status": "active"}])
        with mock.patch.dict(sys.modules, {"db": db}):
            edges = swm.capability_edges()
        self.assertEqual(edges, [{"capability": "kyc", "consumer": "beta",
                                  "version": "1.0.0"}])

    def test_retired_capability_is_not_an_edge(self):
        db = self._db([{"id": 1, "slug": "kyc", "status": "retired"}],
                      [{"capability_id": 1, "project": "beta", "status": "active"}])
        with mock.patch.dict(sys.modules, {"db": db}):
            self.assertEqual(swm.capability_edges(), [])

    def test_inactive_instance_is_not_an_edge(self):
        db = self._db([{"id": 1, "slug": "kyc", "status": "active"}],
                      [{"capability_id": 1, "project": "beta", "status": "removed"}])
        with mock.patch.dict(sys.modules, {"db": db}):
            self.assertEqual(swm.capability_edges(), [])

    def test_filter_by_project(self):
        db = self._db([{"id": 1, "slug": "kyc", "status": "active"}],
                      [{"capability_id": 1, "project": "beta", "status": "active"},
                       {"capability_id": 1, "project": "gamma", "status": "active"}])
        with mock.patch.dict(sys.modules, {"db": db}):
            edges = swm.capability_edges("gamma")
        self.assertEqual([e["consumer"] for e in edges], ["gamma"])

    def test_registry_unavailable_is_empty_not_an_error(self):
        db = mock.MagicMock()
        db.select.side_effect = RuntimeError("no network")
        with mock.patch.dict(sys.modules, {"db": db}):
            self.assertEqual(swm.capability_edges(), [])


class BlastRadiusIntegrationTest(FleetFixture):
    """blast_radius must keep working exactly as before when no project is supplied."""

    def _blast_radius(self):
        sys.modules.pop("blast_radius", None)
        with mock.patch.dict(sys.modules, {"context_retrieval": mock.MagicMock()}):
            import blast_radius
            return blast_radius

    def test_note_for_task_still_accepts_two_arguments(self):
        br = self._blast_radius()
        br.cr.select_files.return_value = []
        with mock.patch.object(br, "_dependents", return_value=[]):
            self.assertEqual(br.note_for_task("/repo", "do a thing"), "")

    def test_cross_app_section_appended_when_project_given(self):
        br = self._blast_radius()
        br.cr.select_files.return_value = []
        with mock.patch.object(br, "_dependents", return_value=[]), \
             mock.patch.object(br._swm, "note_for_task", return_value="# cross\n\n"):
            self.assertIn("# cross", br.note_for_task("/repo", "x", project="alpha"))

    def test_radius_after_shape_unchanged_without_project(self):
        br = self._blast_radius()
        with mock.patch.object(br, "_changed_files", return_value=["a.py"]), \
             mock.patch.object(br, "_dependents", return_value=["b.py"]):
            out = br.radius_after("/repo")
        self.assertEqual(out, {"changed": ["a.py"], "dependents": ["b.py"]})

    def test_radius_after_adds_cross_app_when_project_given(self):
        br = self._blast_radius()
        with mock.patch.object(br, "_changed_files", return_value=["a.sql"]), \
             mock.patch.object(br, "_dependents", return_value=[]), \
             mock.patch.object(br._swm, "cross_app_radius",
                               return_value={"impacted": [{"project": "beta"}]}):
            out = br.radius_after("/repo", project="alpha")
        self.assertEqual(out["cross_app"], [{"project": "beta"}])

    def test_cross_app_radius_after_fails_soft(self):
        br = self._blast_radius()
        with mock.patch.object(br, "_changed_files", return_value=["a.sql"]), \
             mock.patch.object(br._swm, "cross_app_radius",
                               side_effect=RuntimeError("boom")):
            self.assertEqual(br.cross_app_radius_after("/repo", "alpha"), [])


if __name__ == "__main__":
    unittest.main()

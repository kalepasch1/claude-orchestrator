"""One shared module completing must unblock its dependents in a single wave.

Scenario-1 coverage proves a bare dep resolves inside its own project, and the
qualified-dep tests prove `project:slug` reaches across the namespace. Neither
covers the case the cross-project feature exists FOR: several projects waiting
on one shared module, which must all become claimable from the SAME completion —
not one project per pass.

The failure this guards against is partial-wave unblocking: if _done_slugs()
emitted only the bare slug, dependents that qualified their dep would stay
blocked forever; if it emitted only the qualified form, dependents using the
bare id would. Either way the wave fragments and the fleet stalls with no error.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

for _mod in ("supabase", "postgrest", "httpx", "gotrue", "realtime",
             "storage3", "supafunc"):
    if _mod not in sys.modules:
        try:
            __import__(_mod)
        except ImportError:
            import types as _types
            sys.modules[_mod] = _types.ModuleType(_mod)

import db  # noqa: E402


SHARED_PID = "p-shared"
PROJECTS = [
    {"id": SHARED_PID, "name": "shared"},
    {"id": "p-alpha", "name": "alpha"},
    {"id": "p-beta", "name": "beta"},
    {"id": "p-gamma", "name": "gamma"},
]

# One dependent per project, each spelling the same dependency differently —
# which is exactly how a real fleet writes them.
WAVE = {
    "alpha-consumer": ["shared:curation-layer-land"],
    "beta-consumer": ["shared:curation-layer-land", "beta-local-setup"],
    "gamma-consumer": ["curation-layer-land"],          # bare spelling
}


def _resolve(done_rows):
    db.invalidate_done_cache()
    with patch.object(db, "select_all", return_value=done_rows), \
         patch.object(db, "select", return_value=PROJECTS):
        try:
            return db._done_slugs()
        finally:
            db.invalidate_done_cache()


def _claimable(slugs):
    return {name for name, deps in WAVE.items() if all(d in slugs for d in deps)}


class TestSharedModuleWave(unittest.TestCase):
    def test_before_the_shared_module_lands_nothing_in_the_wave_is_claimable(self):
        slugs = _resolve([{"slug": "beta-local-setup", "project_id": "p-beta"}])
        self.assertEqual(_claimable(slugs), set())

    def test_one_completion_unblocks_every_project_in_the_same_wave(self):
        # The point of the feature: a single shared-module completion releases
        # all three dependents at once, whichever spelling they used.
        slugs = _resolve([
            {"slug": "curation-layer-land", "project_id": SHARED_PID},
            {"slug": "beta-local-setup", "project_id": "p-beta"},
        ])
        self.assertEqual(_claimable(slugs),
                         {"alpha-consumer", "beta-consumer", "gamma-consumer"})

    def test_the_wave_does_not_fragment_by_dependency_spelling(self):
        # Qualified and bare spellings of the same shared module must resolve
        # from one completion; emitting only one form would strand the others.
        slugs = _resolve([{"slug": "curation-layer-land", "project_id": SHARED_PID}])
        self.assertIn("shared:curation-layer-land", slugs)
        self.assertIn("curation-layer-land", slugs)

    def test_a_dependent_with_an_unfinished_local_dep_still_waits(self):
        # Guards the wave assertion from passing vacuously: the shared module is
        # necessary but not sufficient.
        slugs = _resolve([{"slug": "curation-layer-land", "project_id": SHARED_PID}])
        self.assertIn("alpha-consumer", _claimable(slugs))
        self.assertNotIn("beta-consumer", _claimable(slugs))

    def test_a_same_named_task_in_the_wrong_project_does_not_release_the_wave(self):
        # An impostor `curation-layer-land` in alpha must not satisfy a dep
        # qualified to `shared:`.
        slugs = _resolve([{"slug": "curation-layer-land", "project_id": "p-alpha"}])
        self.assertNotIn("shared:curation-layer-land", slugs)
        self.assertNotIn("alpha-consumer", _claimable(slugs))

    def test_the_wave_is_stable_across_repeated_resolution(self):
        # Claim passes call this repeatedly; the answer must not drift with the
        # 60s cache in play.
        rows = [{"slug": "curation-layer-land", "project_id": SHARED_PID},
                {"slug": "beta-local-setup", "project_id": "p-beta"}]
        first = _claimable(_resolve(rows))
        second = _claimable(_resolve(rows))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 3)


if __name__ == "__main__":
    unittest.main()

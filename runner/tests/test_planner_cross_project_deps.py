"""A dep may be a bare local id or a global `project:id` ref — and neither may be lost.

enqueue_task.parse_cross_project_dep has understood `project:slug` for a while, but the
planner emitted whatever the model produced and never settled the ambiguous middle case: a
BARE id naming a task that is not in this plan.

That case is not noise — it is usually a real reference to work already in the project's
queue. Dropping it lets a task run before the thing it depends on, silently, which is the
one failure a DAG exists to prevent. So it is QUALIFIED to a global ref, never pruned.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import planner  # noqa: E402
import enqueue_task  # noqa: E402


def _plan(*pairs):
    return [{"slug": slug, "deps": list(deps)} for slug, deps in pairs]


class TestBackwardCompatibility:
    def test_a_bare_dep_on_a_sibling_stays_bare(self):
        """The overwhelmingly common case — intra-plan chaining must not change."""
        out = planner.normalize_plan_deps(
            _plan(("contracts", []), ("impl", ["contracts"])), project="beethoven")
        assert out[1]["deps"] == ["contracts"]

    def test_an_empty_dep_list_stays_empty(self):
        out = planner.normalize_plan_deps(_plan(("contracts", [])), project="beethoven")
        assert out[0]["deps"] == []

    def test_a_plan_with_no_project_leaves_bare_deps_alone(self):
        """With nothing to qualify against, guessing would be worse than waiting."""
        out = planner.normalize_plan_deps(_plan(("impl", ["elsewhere"])), project=None)
        assert out[0]["deps"] == ["elsewhere"]

    def test_a_comma_string_is_accepted_like_a_list(self):
        tasks = [{"slug": "contracts", "deps": []},
                 {"slug": "impl", "deps": "contracts, other"}]
        out = planner.normalize_plan_deps(tasks, project="beethoven")
        assert out[1]["deps"] == ["contracts", "beethoven:other"]


class TestGlobalRefs:
    def test_an_existing_global_ref_is_left_verbatim(self):
        out = planner.normalize_plan_deps(
            _plan(("impl", ["tomorrow:contracts"])), project="beethoven")
        assert out[0]["deps"] == ["tomorrow:contracts"]

    def test_an_unknown_bare_dep_is_qualified_not_dropped(self):
        """The rule that matters: unknown deps are never pruned."""
        out = planner.normalize_plan_deps(
            _plan(("impl", ["already-queued-elsewhere"])), project="beethoven")
        assert out[0]["deps"] == ["beethoven:already-queued-elsewhere"]

    def test_a_self_referencing_project_qualification_still_resolves_downstream(self):
        """What the planner emits must parse on the enqueue side."""
        out = planner.normalize_plan_deps(
            _plan(("impl", ["missing-sibling"])), project="beethoven")
        proj, slug = enqueue_task.parse_cross_project_dep(out[0]["deps"][0])
        assert (proj, slug) == ("beethoven", "missing-sibling")

    def test_a_bare_sibling_dep_also_parses_downstream(self):
        out = planner.normalize_plan_deps(
            _plan(("contracts", []), ("impl", ["contracts"])), project="beethoven")
        assert enqueue_task.parse_cross_project_dep(out[1]["deps"][0]) == (None, "contracts")


class TestHygiene:
    def test_a_self_dep_is_removed(self):
        """A task depending on itself can never start."""
        out = planner.normalize_plan_deps(_plan(("impl", ["impl"])), project="beethoven")
        assert out[0]["deps"] == []

    def test_duplicates_collapse_and_order_is_preserved(self):
        out = planner.normalize_plan_deps(
            _plan(("contracts", []), ("other", []),
                  ("impl", ["contracts", "other", "contracts"])), project="beethoven")
        assert out[2]["deps"] == ["contracts", "other"]

    def test_blank_entries_are_dropped(self):
        out = planner.normalize_plan_deps(
            _plan(("impl", ["", "  ", "contracts"])), project=None)
        assert out[0]["deps"] == ["contracts"]

    def test_a_bare_and_a_qualified_form_of_the_same_dep_both_survive(self):
        """They are different identities; collapsing them would be a guess."""
        out = planner.normalize_plan_deps(
            _plan(("contracts", []), ("impl", ["contracts", "other:contracts"])),
            project="beethoven")
        assert out[1]["deps"] == ["contracts", "other:contracts"]


class TestFailSoft:
    @pytest.mark.parametrize("tasks", [None, [], [None], ["text"], [7]])
    def test_malformed_input_never_raises(self, tasks):
        planner.normalize_plan_deps(tasks, project="beethoven")

    def test_a_task_without_a_deps_key_gets_an_empty_list(self):
        tasks = [{"slug": "impl"}]
        assert planner.normalize_plan_deps(tasks, project="beethoven")[0]["deps"] == []

    def test_a_task_without_a_slug_does_not_break_the_plan(self):
        tasks = [{"deps": ["contracts"]}, {"slug": "contracts", "deps": []}]
        out = planner.normalize_plan_deps(tasks, project="beethoven")
        assert out[0]["deps"] == ["contracts"]

    def test_the_same_list_object_is_returned(self):
        """Callers assign the result back; returning a copy would drop later mutations."""
        tasks = _plan(("impl", []))
        assert planner.normalize_plan_deps(tasks, project="beethoven") is tasks


class TestWiredIntoPlan:
    def test_plan_calls_the_normaliser_before_returning(self):
        src = open(planner.__file__, encoding="utf-8").read()
        body = src[src.index("def plan("):]
        body = body[:body.index("\ndef normalize_plan_deps")]
        assert "normalize_plan_deps(tasks, project=project)" in body
        assert body.index("normalize_plan_deps") < body.rindex("return tasks")

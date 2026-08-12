"""Tests for runner/merged_diff_adapter.py.

Pure: no DB, no filesystem, no network. The adapter runs on the pre-claim path,
so the load-bearing property is that bad input degrades to an empty result
rather than raising and wedging the claim.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merged_diff_adapter as mda  # noqa: E402


DIFF = (
    "diff --git a/runner/alpha.py b/runner/alpha.py\n"
    "--- a/runner/alpha.py\n"
    "+++ b/runner/alpha.py\n"
    "@@ -1,2 +1,6 @@\n"
    " import os\n"
    "+import sys\n"
    "diff --git a/runner/beta.py b/runner/beta.py\n"
    "--- a/runner/beta.py\n"
    "+++ b/runner/beta.py\n"
    "@@ -10,1 +10,1 @@\n"
    "-old\n"
    "+new\n"
)

HIT = {
    "project": "beethoven",
    "slug": "some-prior-slice",
    "similarity": 0.42,
    "adapter_template": "dirs=runner exts=.py:2 shape=+2/-1",
    "diff": DIFF,
}


def test_plan_orders_files_by_how_much_of_the_diff_they_carried():
    p = mda.plan(HIT)
    assert p["reusable"] is True
    assert p["source"] == "beethoven/some-prior-slice"
    assert p["similarity"] == 0.42
    assert p["shape"] == "dirs=runner exts=.py:2 shape=+2/-1"
    # alpha covers 6 new-side lines, beta covers 1 -> alpha leads
    assert [f["path"] for f in p["files"]] == ["runner/alpha.py", "runner/beta.py"]
    assert p["files"][0]["ext"] == ".py"


def test_on_target_is_set_for_a_file_the_caller_already_named():
    p = mda.plan(HIT, target_files=["runner/beta.py"])
    by_path = {f["path"]: f for f in p["files"]}
    assert by_path["runner/beta.py"]["on_target"] is True
    assert by_path["runner/alpha.py"]["on_target"] is False


def test_basename_counts_as_on_target():
    p = mda.plan(HIT, target_files=["alpha.py"])
    by_path = {f["path"]: f for f in p["files"]}
    assert by_path["runner/alpha.py"]["on_target"] is True


def test_a_hit_with_no_recoverable_file_map_is_not_reusable():
    p = mda.plan({"slug": "s", "project": "p", "diff": "not a diff at all"})
    assert p["reusable"] is False
    assert p["files"] == []


def test_bad_input_never_raises_and_yields_a_neutral_result():
    for bad in (None, "", 0, [], "a string"):
        p = mda.plan(bad)
        assert p["reusable"] is False
        assert p["files"] == []
        assert p["similarity"] == 0.0
    assert mda.plans(None) == []
    assert mda.plans("not a list") == []
    assert mda.adapt(None) == ""
    assert mda.render(None) == ""


def test_plans_drops_unusable_hits_and_sorts_by_similarity():
    low = dict(HIT, similarity=0.10)
    high = dict(HIT, similarity=0.90)
    junk = {"slug": "junk", "diff": ""}
    out = mda.plans([low, junk, high])
    assert [p["similarity"] for p in out] == [0.9, 0.1]


def test_plans_respects_limit_including_a_bad_limit():
    out = mda.plans([HIT, dict(HIT, slug="b"), dict(HIT, slug="c")], limit=2)
    assert len(out) == 2
    assert len(mda.plans([HIT], limit="not a number")) == 1


def test_render_emits_the_mark_paths_and_shape():
    text = mda.adapt([HIT], target_files=["runner/beta.py"])
    assert text.startswith(mda.MARK)
    assert "beethoven/some-prior-slice" in text
    assert "runner/alpha.py" in text
    assert "shape=+2/-1" in text
    assert "adapt in place" in text  # beta was the named target


def test_render_truncates_the_file_list():
    many = "".join(
        f"diff --git a/f{i}.py b/f{i}.py\n@@ -1,1 +1,1 @@\n+x\n" for i in range(9)
    )
    text = mda.adapt([dict(HIT, diff=many)], max_files=2)
    assert "and 7 more file(s)" in text


def test_already_adapted_is_boundary_exact_on_the_slug():
    body = f"{mda.MARK}: SOURCE beethoven/some-prior-slice similarity=0.42"
    assert mda.already_adapted(body, "some-prior-slice") is True
    # a sibling slice must NOT read as already adapted
    assert mda.already_adapted(body, "some-prior-slice-slice-2") is False
    assert mda.already_adapted(body, "prior-slice") is False
    assert mda.already_adapted("no mark here", "some-prior-slice") is False
    assert mda.already_adapted(body) is True
    assert mda.already_adapted(None, "s") is False

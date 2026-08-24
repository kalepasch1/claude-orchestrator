"""Behavioural-equivalence tests for the patch-template scaffold/diff classifier.

Slice 1 integrated `classify_body` / `carries_diff` / `_classified` into
runner/patch_templates.py and rewired `build()` and `lookup()` through them.
This file is the verification slice: it asserts the integrated code produces the
SAME output as the functionality it replaced for every pre-existing contract,
and only then asserts the new behaviour on top.

The equivalence baselines are written out literally rather than diffed against
an imported old copy, because the old copy no longer exists — a test that
compares the code to itself proves nothing.

What the classifier is for: `build()` never emits a diff. It emits prose, and
its "Prior merged patterns to adapt" section splices in the body text of OTHER
scaffolds, so a scaffold quotes a scaffold and reads to a planner exactly like a
stored patch. The recon slice family was decomposed into "integrate the two
adapted diffs" work against templates containing zero hunks and churned to
attempt 43. These tests pin the labelling that prevents that.
"""
import json
import os
import sys

import pytest

RUNNER = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runner"))
sys.path.insert(0, RUNNER)

import patch_templates  # noqa: E402


TASK = {
    "slug": "add-a-webhook-route",
    "prompt": "Add a webhook route that validates the payload schema and writes a migration.",
    "kind": "build",
    "project_id": "p-1",
}

REAL_DIFF = """diff --git a/runner/x.py b/runner/x.py
--- a/runner/x.py
+++ b/runner/x.py
@@ -1,3 +1,3 @@
-old = 1
+new = 1
"""

SCAFFOLD_BODY = (
    "PATCH TEMPLATE abc123def456\n"
    "Intent: webhook route schema migration validate payload\n"
    "Acceptance: preserve existing behavior, make the smallest mergeable diff, run build/tests.\n"
    "Implementation slots:\n"
    "1. Locate the existing owner module/function before adding new files.\n"
)


@pytest.fixture
def no_library(monkeypatch):
    """Force the no-hits branch of build() deterministically."""
    monkeypatch.setitem(sys.modules, "merged_diff_library", None)
    return None


class FakeLibrary:
    def __init__(self, hits):
        self.hits = hits

    def find(self, task, limit=2):
        return self.hits[:limit]


def _install_library(monkeypatch, hits):
    monkeypatch.setitem(sys.modules, "merged_diff_library", FakeLibrary(hits))


# ── Equivalence: the parts that must NOT have changed ────────────────────────

def test_template_id_is_unchanged_and_deterministic():
    """`_id` feeds stored rows and the [patch-template:...] marker. If the id
    changed, every already-stored template would become unresolvable."""
    tid_a, _ = patch_templates.build(dict(TASK))
    tid_b, _ = patch_templates.build(dict(TASK))
    assert tid_a == tid_b
    assert len(tid_a) == 12 and all(c in "0123456789abcdef" for c in tid_a)


def test_id_still_depends_only_on_slug_and_intent():
    base, _ = patch_templates.build(dict(TASK))
    same_intent, _ = patch_templates.build(dict(TASK, kind="bugfix", project_id="p-9"))
    assert same_intent == base, "kind/project_id must not perturb the id"
    other, _ = patch_templates.build(dict(TASK, slug="something-else"))
    assert other != base


def test_scaffold_header_and_slots_are_byte_for_byte_unchanged(no_library):
    tid, body = patch_templates.build(dict(TASK))
    lines = body.split("\n")
    assert lines[0] == f"PATCH TEMPLATE {tid}"
    assert lines[1].startswith("Intent: ")
    assert lines[2] == (
        "Acceptance: preserve existing behavior, make the smallest mergeable "
        "diff, run build/tests."
    )
    assert lines[3] == "Implementation slots:"
    assert lines[4] == "1. Locate the existing owner module/function before adding new files."
    assert lines[5] == "2. Reuse matching project helpers and naming conventions."
    assert lines[6] == "3. Add or update the narrowest test/check that proves the requested behavior."


def test_the_no_hits_line_is_unchanged(no_library):
    _, body = patch_templates.build(dict(TASK))
    assert body.rstrip().endswith(
        "Prior merged patterns to adapt: none found; keep the patch template reusable."
    )
    assert "NOTE: none of the patterns above" not in body, (
        "the scaffold warning belongs to the has-hits path only"
    )


def test_build_returns_a_two_tuple_of_str(no_library):
    out = patch_templates.build(dict(TASK))
    assert isinstance(out, tuple) and len(out) == 2
    assert isinstance(out[0], str) and isinstance(out[1], str)


def test_build_still_survives_a_broken_library(monkeypatch):
    """The old code swallowed library errors; the new code must too."""
    class Exploding:
        def find(self, *a, **k):
            raise RuntimeError("library down")

    monkeypatch.setitem(sys.modules, "merged_diff_library", Exploding())
    tid, body = patch_templates.build(dict(TASK))
    assert tid and "PATCH TEMPLATE" in body


def test_hit_line_still_carries_project_slug_similarity_and_summary(monkeypatch):
    """The tag is a PREFIX. Everything the old line contained is still there,
    in the same order, so a consumer parsing the tail is unaffected."""
    summary = "PATCH TEMPLATE abc123def456 Intent: webhook route schema migration"
    _install_library(monkeypatch, [
        {"project": "smarter", "slug": "canary-20260725", "similarity": 0.385,
         "summary": summary},
    ])
    _, body = patch_templates.build(dict(TASK))
    line = [l for l in body.split("\n") if "smarter/canary-20260725" in l][0]
    assert line.endswith(f"smarter/canary-20260725 sim=0.385: {summary}")
    assert line.startswith("- [")


def test_lookup_preserves_every_pre_existing_key(tmp_path, monkeypatch):
    """`_classified` is additive: body/title/source/template_id are untouched."""
    runtime = tmp_path / ".runtime"
    runtime.mkdir()
    store = runtime / "patch_templates.jsonl"
    row = {"template_id": "aaaaaaaaaaaa", "body": SCAFFOLD_BODY,
           "title": "patch template x", "source": "jsonl", "extra": "kept"}
    store.write_text(json.dumps(row) + "\n", encoding="utf-8")
    monkeypatch.setattr(patch_templates, "_fallback_path", lambda: str(store))

    out = patch_templates.lookup("aaaaaaaaaaaa")
    for key, value in row.items():
        assert out[key] == value, f"{key} was altered by classification"


def test_lookup_still_fails_soft(monkeypatch, tmp_path):
    monkeypatch.setattr(patch_templates, "_fallback_path", lambda: str(tmp_path / "nope.jsonl"))
    monkeypatch.setattr(patch_templates.db, "select", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    assert patch_templates.lookup("bbbbbbbbbbbb") == {}
    assert patch_templates.lookup("") == {}
    assert patch_templates.lookup(None) == {}


def test_lookup_newest_matching_jsonl_entry_still_wins(tmp_path, monkeypatch):
    store = tmp_path / "patch_templates.jsonl"
    store.write_text(
        json.dumps({"template_id": "cccccccccccc", "body": "old"}) + "\n"
        + json.dumps({"template_id": "cccccccccccc", "body": "new"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(patch_templates, "_fallback_path", lambda: str(store))
    assert patch_templates.lookup("cccccccccccc")["body"] == "new"


# ── The new behaviour ────────────────────────────────────────────────────────

def test_classify_body_separates_a_diff_from_a_scaffold():
    assert patch_templates.classify_body(REAL_DIFF) == patch_templates.KIND_DIFF
    assert patch_templates.classify_body(SCAFFOLD_BODY) == patch_templates.KIND_SCAFFOLD


@pytest.mark.parametrize("body", [None, "", 0, [], {}, "just some prose"])
def test_classify_body_defaults_to_scaffold_on_junk(body):
    """Fail-soft in the safe direction: unknown is never 'this has a patch'."""
    assert patch_templates.classify_body(body) == patch_templates.KIND_SCAFFOLD


def test_carries_diff_accepts_a_body_a_dict_or_an_id(tmp_path, monkeypatch):
    assert patch_templates.carries_diff(REAL_DIFF) is True
    assert patch_templates.carries_diff({"body": REAL_DIFF}) is True
    assert patch_templates.carries_diff({"body": SCAFFOLD_BODY}) is False

    store = tmp_path / "patch_templates.jsonl"
    store.write_text(json.dumps({"template_id": "dddddddddddd", "body": REAL_DIFF}) + "\n",
                     encoding="utf-8")
    monkeypatch.setattr(patch_templates, "_fallback_path", lambda: str(store))
    assert patch_templates.carries_diff("dddddddddddd") is True


def test_carries_diff_on_an_unknown_id_is_false(tmp_path, monkeypatch):
    monkeypatch.setattr(patch_templates, "_fallback_path", lambda: str(tmp_path / "nope.jsonl"))
    monkeypatch.setattr(patch_templates.db, "select", lambda *a, **k: [])
    assert patch_templates.carries_diff("eeeeeeeeeeee") is False
    assert patch_templates.carries_diff(None) is False
    assert patch_templates.carries_diff(12345) is False


def test_a_scaffold_only_hit_set_gets_the_do_not_integrate_warning(monkeypatch):
    """The exact regression: two scaffolds quoting a third read like patches."""
    _install_library(monkeypatch, [
        {"project": "beethoven", "slug": "recon-slice-a", "similarity": 0.4,
         "summary": SCAFFOLD_BODY},
        {"project": "beethoven", "slug": "recon-slice-b", "similarity": 0.3,
         "summary": SCAFFOLD_BODY},
    ])
    _, body = patch_templates.build(dict(TASK))
    assert body.count("[scaffold — prose only, no diff to apply]") == 2
    assert "NOTE: none of the patterns above contain a diff" in body
    assert "read them as intent and write the change yourself" in body


def test_one_real_diff_suppresses_the_warning(monkeypatch):
    _install_library(monkeypatch, [
        {"project": "beethoven", "slug": "has-a-patch", "similarity": 0.6, "summary": REAL_DIFF},
        {"project": "beethoven", "slug": "prose-only", "similarity": 0.3, "summary": SCAFFOLD_BODY},
    ])
    _, body = patch_templates.build(dict(TASK))
    assert "- [diff] beethoven/has-a-patch" in body
    assert "[scaffold — prose only, no diff to apply] beethoven/prose-only" in body
    assert "NOTE: none of the patterns above contain a diff" not in body


def test_lookup_labels_a_scaffold_and_a_diff(tmp_path, monkeypatch):
    store = tmp_path / "patch_templates.jsonl"
    store.write_text(
        json.dumps({"template_id": "ffffffffffff", "body": SCAFFOLD_BODY}) + "\n"
        + json.dumps({"template_id": "111111111111", "body": REAL_DIFF}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(patch_templates, "_fallback_path", lambda: str(store))

    scaffold = patch_templates.lookup("ffffffffffff")
    assert scaffold["kind"] == patch_templates.KIND_SCAFFOLD
    assert scaffold["carries_diff"] is False

    diff = patch_templates.lookup("111111111111")
    assert diff["kind"] == patch_templates.KIND_DIFF
    assert diff["carries_diff"] is True


def test_kind_and_carries_diff_never_disagree(tmp_path, monkeypatch):
    store = tmp_path / "patch_templates.jsonl"
    store.write_text(json.dumps({"template_id": "222222222222", "body": REAL_DIFF}) + "\n",
                     encoding="utf-8")
    monkeypatch.setattr(patch_templates, "_fallback_path", lambda: str(store))
    out = patch_templates.lookup("222222222222")
    assert out["carries_diff"] == (out["kind"] == patch_templates.KIND_DIFF)


def test_classification_never_raises_when_the_detector_is_broken(monkeypatch):
    """`_looks_like_diff` delegates to patch_template_apply; if that import
    fails the fallback marker scan must still answer, not propagate."""
    monkeypatch.setitem(sys.modules, "patch_template_apply", None)
    assert patch_templates.classify_body(REAL_DIFF) == patch_templates.KIND_DIFF
    assert patch_templates.classify_body(SCAFFOLD_BODY) == patch_templates.KIND_SCAFFOLD

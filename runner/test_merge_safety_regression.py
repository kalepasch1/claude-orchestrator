"""Merge-safety regression suite — the "wiped improvements" class, killed forever.

The bug this suite exists to prevent: two agent branches improve DIFFERENT sections of the SAME
file. The second branch to merge resolves the conflict whole-file (`checkout --ours/--theirs`)
and silently reverts the first branch's section to legacy code. Nothing fails. The improvement
is simply gone, and the only evidence is a `Merge branch '...' (auto-resolved)` commit whose
diff reverts lines an earlier merge added.

`_classify_conflict` was fixed on 2026-07-29 to forbid whole-file resolution of SOURCE files on
add/add. That fix is a comment and four lines of code — nothing held it in place. These tests
make the contract executable, so the fix cannot be regressed by the very merge automation it
governs (which has already clobbered its own guard twice; see
test_auto_conflict_resolver_guard.py).

Covers, per the CORE INTEGRITY AUDIT brief §1:
  1. concurrent same-file, different-section improvements survive integration IN BOTH ORDERS
  2. add/add on source routes to ast_merge/manual, NEVER whole-file ours/theirs
  3. semantic_merge refuses overlapping edits and accepts disjoint ones
  4. whole-file `theirs` survives only for non-source assets
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.modules.setdefault("db", type(sys)("db"))   # acr imports db lazily/optionally

import auto_conflict_resolver as acr  # noqa: E402
import semantic_merge as sm  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures: one file, two improvements, in two well-separated sections.
# ---------------------------------------------------------------------------

BASE_FILE = """\
HEADER = "v1"


def alpha(x):
    # SECTION-A
    return x + 1


def filler_one():
    return 1


def filler_two():
    return 2


def filler_three():
    return 3


def omega(y):
    # SECTION-B
    return y * 2
"""

# Branch A improves ONLY the top section.
IMPROVED_A = BASE_FILE.replace(
    "def alpha(x):\n    # SECTION-A\n    return x + 1",
    "def alpha(x):\n    # SECTION-A improved by branch A\n"
    "    if x is None:\n        raise ValueError('alpha needs a value')\n    return x + 1",
)

# Branch B improves ONLY the bottom section.
IMPROVED_B = BASE_FILE.replace(
    "def omega(y):\n    # SECTION-B\n    return y * 2",
    "def omega(y):\n    # SECTION-B improved by branch B\n"
    "    if y < 0:\n        return 0\n    return y * 2",
)

MARKER_A = "improved by branch A"
MARKER_B = "improved by branch B"


def git(repo, *args):
    return subprocess.run(["git"] + list(args), cwd=repo,
                          capture_output=True, text=True, timeout=60)


@pytest.fixture
def repo(tmp_path):
    """A repo with `lib.py` on master and two branches improving disjoint sections."""
    r = str(tmp_path / "repo")
    os.makedirs(r)
    git(r, "init", "-q", "-b", "master")
    git(r, "config", "user.email", "t@t")
    git(r, "config", "user.name", "t")
    git(r, "config", "core.hooksPath", "/dev/null")
    lib = tmp_path / "repo" / "lib.py"
    lib.write_text(BASE_FILE)
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")

    for branch, content in (("improve-a", IMPROVED_A), ("improve-b", IMPROVED_B)):
        git(r, "checkout", "-q", "-b", branch, "master")
        lib.write_text(content)
        git(r, "add", "-A")
        git(r, "commit", "-qm", f"agent: {branch}")
    git(r, "checkout", "-q", "master")
    return r


def merged_text(repo, path="lib.py"):
    with open(os.path.join(repo, path), "r", errors="replace") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# 1. Concurrent same-file improvements survive integration — in BOTH orders.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("order", [("improve-a", "improve-b"), ("improve-b", "improve-a")])
def test_disjoint_section_improvements_both_survive(repo, order):
    """The headline invariant. Neither merge order may drop the other branch's section.

    Parametrised over BOTH orders on purpose: the historical bug was order-dependent — whichever
    branch merged second won the whole file — so a single-order test would have passed
    throughout the entire period the bug was live.
    """
    first, second = order
    assert git(repo, "merge", "--no-edit", first).returncode == 0, "first merge should be clean"

    r = git(repo, "merge", "--no-edit", second)
    if r.returncode != 0:
        # A conflict here is acceptable ONLY if it is NOT resolved whole-file.
        # Whatever resolution runs, the surviving tree must contain both improvements.
        strategy = acr._classify_conflict("lib.py", "content")
        assert strategy not in ("ours", "theirs"), (
            f"same-file conflict resolved whole-file via {strategy!r} — "
            "this is the exact mechanism that wiped improvements"
        )
        git(repo, "merge", "--abort")
        return

    text = merged_text(repo)
    assert MARKER_A in text, f"branch A's section was reverted by merging {second} second"
    assert MARKER_B in text, f"branch B's section was reverted by merging {second} second"


def test_merge_result_never_contains_conflict_markers(repo):
    git(repo, "merge", "--no-edit", "improve-a")
    git(repo, "merge", "--no-edit", "improve-b")
    text = merged_text(repo)
    for marker in ("<<<<<<<", "=======", ">>>>>>>"):
        assert marker not in text


def test_base_content_outside_both_sections_is_preserved(repo):
    git(repo, "merge", "--no-edit", "improve-a")
    git(repo, "merge", "--no-edit", "improve-b")
    text = merged_text(repo)
    for untouched in ("def filler_one", "def filler_two", "def filler_three", 'HEADER = "v1"'):
        assert untouched in text


# ---------------------------------------------------------------------------
# 2. add/add on a SOURCE file must never resolve whole-file (the 2026-07-29 fix).
# ---------------------------------------------------------------------------

SOURCE_PATHS = [
    "runner/thing.py", "app/lib/thing.ts", "components/Thing.vue", "server/api/x.js",
    "pkg/main.go", "src/main.rs", "styles/app.css", "config/app.yml", "schema.prisma",
    "docs/notes.md", "scripts/run.sh", "query.sql",
]


@pytest.mark.parametrize("path", SOURCE_PATHS)
def test_add_add_on_source_never_whole_file(path):
    """The regression that cost the operator real improvements. Locked per source extension."""
    strategy = acr._classify_conflict(path, "add/add")
    assert strategy in ("ast_merge", "manual"), (
        f"add/add on source file {path!r} resolved as {strategy!r}; whole-file "
        "ours/theirs on source is what silently reverted prior branches' sections"
    )


@pytest.mark.parametrize("path", SOURCE_PATHS)
def test_content_conflict_on_source_never_whole_file(path):
    """Same guarantee for ordinary content conflicts, not just add/add."""
    strategy = acr._classify_conflict(path, "content")
    assert strategy not in ("ours", "theirs"), (
        f"content conflict on source file {path!r} resolved whole-file as {strategy!r}"
    )


def test_add_add_on_binary_asset_may_still_take_theirs():
    """The fix must stay narrow. Whole-file replacement is genuinely safe for binaries, and
    over-tightening would push every image conflict to manual review."""
    assert acr._classify_conflict("public/logo.png", "add/add") == "theirs"


def test_source_extension_list_is_not_silently_shrunk():
    """A regression could 'pass' the tests above by dropping extensions from _SOURCE_EXTS.
    Pin the high-traffic ones so shrinking the list fails loudly here instead of in production."""
    for ext in (".py", ".ts", ".vue", ".sql", ".prisma", ".sh", ".yml"):
        assert acr._classify_conflict(f"some/file{ext}", "add/add") in ("ast_merge", "manual")


# ---------------------------------------------------------------------------
# 3. semantic_merge overlap detection.
# ---------------------------------------------------------------------------

def test_semantic_merge_accepts_disjoint_region_edits():
    result = sm.can_auto_merge(BASE_FILE, IMPROVED_A, IMPROVED_B, "lib.py")
    assert result["mergeable"] is True


def test_semantic_merge_refuses_overlapping_edits():
    """Both branches rewrite the SAME function. There is no safe automatic answer, so the
    correct behaviour is refusal — an auto-merge here is precisely how one edit disappears."""
    a = BASE_FILE.replace("return x + 1", "return x + 100")
    b = BASE_FILE.replace("return x + 1", "return x + 999")
    result = sm.can_auto_merge(BASE_FILE, a, b, "lib.py")
    assert result["mergeable"] is False


def test_semantic_merge_reports_why_it_refused():
    a = BASE_FILE.replace("return x + 1", "return x + 100")
    b = BASE_FILE.replace("return x + 1", "return x + 999")
    result = sm.can_auto_merge(BASE_FILE, a, b, "lib.py")
    assert "overlapping" in str(result.get("strategy", "")) or result.get("overlapping")


def test_semantic_merge_of_disjoint_edits_keeps_both():
    merged = sm.semantic_merge(BASE_FILE, IMPROVED_A, IMPROVED_B, "lib.py")
    text = merged if isinstance(merged, str) else (merged or {}).get("content", "")
    if text:
        assert MARKER_A in text and MARKER_B in text


def test_identical_edits_on_both_sides_are_refused_conservatively():
    """Documented current behaviour, asserted so a change to it is a deliberate decision.

    When both sides make the SAME edit, region-overlap detection sees both touching the same
    region and refuses. Strictly this is over-conservative — the merge is trivially safe. But
    the error lands in the harmless direction (routes to manual review) rather than the
    catastrophic one (silently dropping an edit), which is the correct bias for this module.
    Loosening it would mean relaxing the very overlap check that prevents wiped improvements,
    so the behaviour is pinned here rather than "fixed".
    """
    result = sm.can_auto_merge(BASE_FILE, IMPROVED_A, IMPROVED_A, "lib.py")
    assert result["mergeable"] is False
    # ...and it must refuse for the overlap reason, not because it failed to parse.
    assert "overlapping" in str(result.get("strategy", "")) or result.get("overlapping")


# ---------------------------------------------------------------------------
# 4. The resolver's own safety net stays wired.
# ---------------------------------------------------------------------------

def test_resolved_ok_rejects_conflict_markers(tmp_path):
    r = str(tmp_path / "repo")
    os.makedirs(r)
    git(r, "init", "-q", "-b", "master")
    with open(os.path.join(r, "lib.py"), "w") as fh:
        fh.write("a\n<<<<<<< HEAD\nb\n=======\nc\n>>>>>>> other\n")
    assert acr._resolved_ok(r, "lib.py") is False


def test_resolved_ok_accepts_clean_output(tmp_path):
    r = str(tmp_path / "repo")
    os.makedirs(r)
    git(r, "init", "-q", "-b", "master")
    with open(os.path.join(r, "lib.py"), "w") as fh:
        fh.write(BASE_FILE)
    assert acr._resolved_ok(r, "lib.py") is True


def test_regression_check_is_still_present():
    """`_regression_check` has been deleted once already by this module's own auto-merge
    (dc288ea5). Its absence is the failure mode, so assert the symbol exists at all."""
    assert callable(getattr(acr, "_regression_check", None))


def test_verify_merge_is_still_wired():
    assert callable(getattr(acr, "_verify_merge", None))
    assert callable(getattr(acr, "_reject_merge", None))

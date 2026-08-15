"""Regression tests for the committed-conflict-marker guard (regression_guard detector 5).

The incident: racefeed 601342b06 shipped `<<<<<<<` markers inside .gitignore on master.
auto_conflict_resolver._resolve_file's union branch ran `git merge-file --union` with the
same path as all three inputs and then returned True unconditionally, so the working tree
kept its markers and the caller `git add`ed them. That specific bug is fixed; these tests
make the OUTCOME impossible no matter which resolver reintroduces it.

Two properties are asserted:
  1. markers are caught in EVERY tracked file type, not just source — the incident file was
     .gitignore, which no source-only scan would ever have opened;
  2. the detector does not fire on the things that legitimately look like markers, which is
     what would get it disabled: RST section underlines, ASCII banners, and diff fixtures.

Marker strings are built with chr() so this test file does not itself contain a line that
starts with a conflict marker.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regression_guard as rg  # noqa: E402

LT = chr(60) * 7   # <<<<<<<
EQ = "=" * 7       # =======
GT = chr(62) * 7   # >>>>>>>

# The racefeed shape, verbatim in structure: a .gitignore that went through a bad union.
RACEFEED_GITIGNORE = "\n".join([
    "node_modules",
    LT + " HEAD",
    ".env",
    EQ,
    ".env.local",
    GT + " agent/racefeed-slice",
    "dist",
]) + "\n"


def git(repo, *args):
    return subprocess.run(["git"] + list(args), cwd=repo, capture_output=True,
                          text=True, timeout=60)


# --------------------------------------------------------------------------- fires

def test_fires_on_racefeed_gitignore_shape():
    findings = rg.check_conflict_markers(".gitignore", RACEFEED_GITIGNORE)
    assert len(findings) == 1
    f = findings[0]
    assert f["kind"] == "conflict-marker"
    assert f["detector"] == "markers"
    assert "601342b06" in f["reason"], "the finding should cite the incident it prevents"
    assert "2" in f["reason"], "the finding should name the offending line numbers"


def test_fires_across_every_tracked_file_type():
    """A source-only scan is what let the .gitignore case through."""
    for path in (".gitignore", "vercel.json", "config.yaml", "Dockerfile", "README.md",
                 "app.ts", "mod.py", ".env.example", "Makefile", "styles.css"):
        body = "line one\n" + LT + " HEAD\nmine\n" + EQ + "\ntheirs\n" + GT + " other\n"
        assert rg.check_conflict_markers(path, body), "missed markers in " + path


def test_closing_marker_alone_is_caught():
    assert rg.check_conflict_markers("a.py", "x = 1\n" + GT + " branch\n")


def test_merge_check_catches_markers_in_non_python_file(tmp_path):
    """End-to-end through check_merge(), the entry point merge_train actually calls."""
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    git(repo, "config", "user.email", "t@t.t")
    git(repo, "config", "user.name", "t")
    (repo / ".gitignore").write_text("node_modules\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD").stdout.strip()

    (repo / ".gitignore").write_text(RACEFEED_GITIGNORE)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "Merge branch 'agent/x' (auto-resolved)")
    head = git(repo, "rev-parse", "HEAD").stdout.strip()

    ok, findings = rg.check_merge(str(repo), base, head)
    assert ok is False, "a merge that commits conflict markers must not pass the gate"
    assert any(f["kind"] == "conflict-marker" and f["file"] == ".gitignore" for f in findings)


# --------------------------------------------------------------- clean controls (no FPs)

def test_clean_gitignore_does_not_fire():
    assert rg.check_conflict_markers(".gitignore", "node_modules\n.env\ndist\n") == []


def test_rst_section_underline_does_not_fire():
    """`=======` under a heading is standard reStructuredText, not a conflict."""
    assert rg.check_conflict_markers("README.rst", "Title\n" + EQ + "\n\nbody text\n") == []


def test_ascii_banner_does_not_fire():
    assert rg.check_conflict_markers("NOTES.md", "# Heading\n" + ("=" * 60) + "\n") == []


def test_shift_and_comparison_operators_do_not_fire():
    """Real code with << and >> must be untouched."""
    for body in ("x = 1 << 3\n", "y = a >> 2\n", "if a < b and c > d:\n    pass\n",
                 "cat <<EOF\nstuff\nEOF\n"):
        assert rg.check_conflict_markers("a.py", body) == [], body


def test_heredoc_and_markdown_quote_do_not_fire():
    assert rg.check_conflict_markers("doc.md", "> quoted line\n>> nested quote\n") == []


def test_binary_content_is_skipped():
    assert rg.check_conflict_markers("a.bin", "\x00\x01" + LT + " HEAD\n") == []


def test_diff_and_patch_fixtures_are_exempt():
    body = LT + " HEAD\nmine\n" + GT + " theirs\n"
    for path in ("fix.patch", "change.diff", "merge.rej"):
        assert rg.check_conflict_markers(path, body) == [], path


def test_clean_merge_passes_check_merge(tmp_path):
    """Control for the end-to-end test: same flow, properly resolved file."""
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    git(repo, "config", "user.email", "t@t.t")
    git(repo, "config", "user.name", "t")
    (repo / ".gitignore").write_text("node_modules\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD").stdout.strip()

    (repo / ".gitignore").write_text("node_modules\n.env\n.env.local\ndist\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "Merge branch 'agent/x' (auto-resolved)")
    head = git(repo, "rev-parse", "HEAD").stdout.strip()

    ok, findings = rg.check_merge(str(repo), base, head)
    assert ok is True, "a correctly resolved union must pass: %s" % findings
    assert not [f for f in findings if f["kind"] == "conflict-marker"]


def test_repo_source_tree_is_marker_free():
    """Standing assertion: master must never carry markers, in any tracked file."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tracked = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True,
                             text=True, timeout=120).stdout.splitlines()
    bad = []
    for path in tracked:
        full = os.path.join(repo, path)
        if not os.path.isfile(full) or os.path.getsize(full) > 2_000_000:
            continue
        try:
            with open(full, errors="replace") as fh:
                src = fh.read()
        except OSError:
            continue
        if rg.check_conflict_markers(path, src):
            bad.append(path)
    assert not bad, "tracked files carry unresolved conflict markers: %s" % bad[:20]

"""Activating a node_modules cost one syscall per file. It can cost one in total.

dependency_prewarm gives every ephemeral QA overlay and build overlay its own
node_modules by copy-on-write cloning a warm snapshot. It did that with `cp -cR`, which
clones each file individually — so the cost is the FILE COUNT of a node_modules, not its
size.

Measured on ~/Documents/tomorrow/tomorrow/node_modules (76,928 files), 2026-09-01:

    cp -cR         46.3s
    clonefile()     5.5s      identical file count, contents read back the same

macOS clonefile(2) clones a whole directory hierarchy in a single call. Under real fleet
load the same step was timed at 136.9s per merge candidate — and it is paid again in
full on every redo, of which the train does up to four per card.

Same semantics as `cp -c`: copy-on-write, an independent tree sharing blocks until
written. Every failure path falls through to the existing `cp`, so a non-APFS volume, a
cross-filesystem destination or an older kernel behaves exactly as it did before — which
is what most of these tests are about, because the failure mode of getting this wrong is
an overlay with no node_modules, and that is the bug that once made every branch report
TESTFAIL for an unresolvable import.
"""
import os

import pytest

import dependency_prewarm as dp


DARWIN = os.uname().sysname == "Darwin"


@pytest.fixture
def tree(tmp_path):
    src = tmp_path / "node_modules"
    (src / "pkg-a" / "dist").mkdir(parents=True)
    (src / "pkg-b").mkdir()
    (src / "pkg-a" / "package.json").write_text('{"name":"a"}')
    (src / "pkg-a" / "dist" / "index.js").write_text("export const a = 1\n")
    (src / "pkg-b" / "package.json").write_text('{"name":"b"}')
    return src


@pytest.mark.skipif(not DARWIN, reason="clonefile is a macOS syscall")
def test_a_directory_tree_is_cloned_whole(tree, tmp_path):
    dst = tmp_path / "clone"
    assert dp._clonefile_dir(str(tree), str(dst)) is True
    assert (dst / "pkg-a" / "dist" / "index.js").read_text() == "export const a = 1\n"
    assert (dst / "pkg-b" / "package.json").read_text() == '{"name":"b"}'


@pytest.mark.skipif(not DARWIN, reason="clonefile is a macOS syscall")
def test_the_clone_is_independent_of_its_source(tree, tmp_path):
    """Copy-on-write, not a hard link. A gate that edits the overlay must not edit
    the warm snapshot every other overlay is about to be cloned from."""
    dst = tmp_path / "clone"
    assert dp._clonefile_dir(str(tree), str(dst)) is True
    (dst / "pkg-a" / "package.json").write_text('{"name":"MUTATED"}')
    assert (tree / "pkg-a" / "package.json").read_text() == '{"name":"a"}'


@pytest.mark.skipif(not DARWIN, reason="clonefile is a macOS syscall")
def test_every_file_arrives(tree, tmp_path):
    dst = tmp_path / "clone"
    dp._clonefile_dir(str(tree), str(dst))
    n_src = sum(len(f) for _, _, f in os.walk(str(tree)))
    n_dst = sum(len(f) for _, _, f in os.walk(str(dst)))
    assert n_dst == n_src


def test_an_existing_destination_is_refused(tree, tmp_path):
    """clonefile requires a fresh destination, and silently overwriting a warm
    node_modules would be worse than not cloning."""
    dst = tmp_path / "clone"
    dst.mkdir()
    assert dp._clonefile_dir(str(tree), str(dst)) is False


def test_a_missing_source_does_not_raise(tmp_path):
    assert dp._clonefile_dir(str(tmp_path / "nope"), str(tmp_path / "out")) is False


def test_it_can_be_switched_off(tree, tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_DEPS_CLONEFILE", "false")
    assert dp._clonefile_dir(str(tree), str(tmp_path / "clone")) is False


def test_a_platform_without_clonefile_reports_false(tree, tmp_path, monkeypatch):
    """Linux, and any macOS old enough not to export the symbol."""
    monkeypatch.setattr(dp, "_CLONEFILE_PROBED", True)
    monkeypatch.setattr(dp, "_CLONEFILE", None)
    assert dp._clonefile_dir(str(tree), str(tmp_path / "clone")) is False


def test_a_failing_clone_leaves_nothing_behind(tree, tmp_path, monkeypatch):
    """The fallback `cp` refuses a destination that already exists, so a half-built
    tree here would block the very path that is supposed to rescue it."""
    dst = tmp_path / "clone"

    def _fail(s, d, flags):
        os.makedirs(d.decode(), exist_ok=True)      # a partial tree, as a bad clone leaves
        return -1

    monkeypatch.setattr(dp, "_CLONEFILE_PROBED", True)
    monkeypatch.setattr(dp, "_CLONEFILE", _fail)
    assert dp._clonefile_dir(str(tree), str(dst)) is False
    assert not dst.exists(), "a failed clone left a partial destination behind"


def test_a_raising_clone_reports_false(tree, tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise OSError("nope")
    monkeypatch.setattr(dp, "_CLONEFILE_PROBED", True)
    monkeypatch.setattr(dp, "_CLONEFILE", _boom)
    assert dp._clonefile_dir(str(tree), str(tmp_path / "clone")) is False


def test_a_clone_that_returns_zero_but_creates_nothing_is_not_trusted(tree, tmp_path,
                                                                     monkeypatch):
    """True must mean "there is a usable node_modules there". An overlay wrongly told
    it has one runs its suite against nothing and reports TESTFAIL — the exact failure
    this module was written to end."""
    monkeypatch.setattr(dp, "_CLONEFILE_PROBED", True)
    monkeypatch.setattr(dp, "_CLONEFILE", lambda s, d, f: 0)
    assert dp._clonefile_dir(str(tree), str(tmp_path / "clone")) is False


def test_activation_tries_the_clone_before_the_cp():
    """Structural. Placed after the cp, it would save nothing at all."""
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "dependency_prewarm.py")
    with open(src, encoding="utf-8") as fh:
        body = fh.read()
    start = body.index("def activate_modules(src, dst):")
    end = body.index("for shared in (", start)
    fn = body[start:end]
    assert "_clonefile_dir(src, dst)" in fn, (
        "activate_modules no longer tries clonefile; every overlay is back to one "
        "syscall per file"
    )
    assert fn.index("_clonefile_dir") < fn.index('"cp", "-cR"'), (
        "the clone is attempted after the cp, which saves nothing"
    )

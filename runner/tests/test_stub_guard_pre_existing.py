"""stub_guard must blame the candidate, not the branch it is being merged into.

scan_shadowed() and scan_fabricated() walk the whole working tree (_code_files), not the
candidate's diff. On the merge path that meant one stub already sitting on the base branch
blocked EVERY card in that project, forever, whatever the card contained.

Measured 2026-09-02 on darwn: a clean detached checkout of orchestrator/dev with zero card
changes applied produced 1 BLOCK violation -- src/utils/zkPrivilegeProof.ts:13,
fabricated_critical_return, a file that predates every one of those cards. 76 REGRESSFAILs
in the live merge-train log cite exactly that path. The gate was refusing the project, not
catching a candidate.

These tests pin both directions: a finding on an untouched file must not block, and a
finding on a file the candidate wrote must still block.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stub_guard  # noqa: E402


CRITICAL_STUB = (
    "export function computeSettlementPrice(a: number, b: number) {\n"
    "  return { price: 0, currency: 'USD' }\n"
    "}\n"
)


def _git(repo, *args):
    return subprocess.run(["git"] + list(args), cwd=repo, capture_output=True,
                          text=True, timeout=30)


@pytest.fixture()
def repo(tmp_path):
    """A repo whose BASE branch already carries a critical stub."""
    r = tmp_path / "repo"
    (r / "src").mkdir(parents=True)
    _git(str(r), "init", "-q", "-b", "base")
    _git(str(r), "config", "user.email", "t@t")
    _git(str(r), "config", "user.name", "t")
    (r / "src" / "legacyPrice.ts").write_text(
        "export function computeLegacyPrice(x: number) {\n"
        "  return { price: 0, currency: 'USD' }\n"
        "}\n")
    (r / "src" / "ok.ts").write_text("export function add(a: number, b: number) { return a + b }\n")
    _git(str(r), "add", "-A")
    _git(str(r), "commit", "-q", "-m", "base with a pre-existing stub")
    return str(r)


def _codes(res, severity):
    return sorted(v["code"] for v in res["violations"] if v.get("severity") == severity)


def test_base_alone_produces_a_blocking_violation_without_attribution(repo):
    """The condition being fixed: the base branch alone trips the gate."""
    res = stub_guard.check_repo(repo, "HEAD", "p", base=None)
    assert "fabricated_critical_return" in _codes(res, "block")


def test_pre_existing_stub_does_not_block_a_candidate_that_never_touched_it(repo):
    res = stub_guard.check_repo(repo, "HEAD", "p", base="base")
    assert _codes(res, "block") == []
    assert res["ok"] is True


def test_pre_existing_stub_is_still_reported_as_a_warning(repo):
    res = stub_guard.check_repo(repo, "HEAD", "p", base="base")
    pre = [v for v in res["violations"] if v.get("pre_existing")]
    assert len(pre) == 1
    assert pre[0]["code"] == "fabricated_critical_return"
    assert pre[0]["severity"] == "warn"
    assert "legacyPrice.ts" in pre[0]["path"]


def test_the_warning_says_it_is_pre_existing_and_names_the_base(repo):
    res = stub_guard.check_repo(repo, "HEAD", "p", base="base")
    pre = [v for v in res["violations"] if v.get("pre_existing")][0]
    assert pre["detail"].startswith("PRE-EXISTING on base")
    assert "does not touch" in pre["detail"]


def test_a_stub_the_candidate_adds_still_blocks(repo):
    with open(os.path.join(repo, "src", "settle.ts"), "w") as fh:
        fh.write(CRITICAL_STUB)
    res = stub_guard.check_repo(repo, "HEAD", "p", base="base")
    block = [v for v in res["violations"] if v.get("severity") == "block"]
    assert len(block) == 1
    assert "settle.ts" in block[0]["path"]
    assert res["ok"] is False


def test_a_stub_the_candidate_adds_blocks_even_when_committed(repo):
    with open(os.path.join(repo, "src", "settle.ts"), "w") as fh:
        fh.write(CRITICAL_STUB)
    _git(repo, "checkout", "-q", "-b", "cand")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add settlement")
    res = stub_guard.check_repo(repo, "cand", "p", base="base")
    block = [v for v in res["violations"] if v.get("severity") == "block"]
    assert [v["code"] for v in block] == ["fabricated_critical_return"]
    assert "settle.ts" in block[0]["path"]


def test_a_candidate_that_stubs_an_existing_file_still_blocks(repo):
    """Editing the pre-existing file makes it the candidate's problem again."""
    with open(os.path.join(repo, "src", "legacyPrice.ts"), "a") as fh:
        fh.write("\nexport function computeFee(n: number) { return { fee: 0 } }\n")
    res = stub_guard.check_repo(repo, "HEAD", "p", base="base")
    block = [v for v in res["violations"] if v.get("severity") == "block"]
    assert block, "a file the candidate edited must be attributed to the candidate"
    assert all("legacyPrice.ts" in v["path"] for v in block)


def test_periodic_sweep_keeps_full_blocking_behaviour(repo):
    """run() passes no base; nothing is downgraded there."""
    res = stub_guard.check_repo(repo, "HEAD", "p")
    assert _codes(res, "block") == ["fabricated_critical_return"]
    assert not any(v.get("pre_existing") for v in res["violations"])


def test_unreadable_base_changes_nothing(repo):
    """A base that git cannot resolve must leave the gate fail-closed."""
    res = stub_guard.check_repo(repo, "HEAD", "p", base="no-such-ref")
    assert "fabricated_critical_return" in _codes(res, "block")


def test_paths_touched_vs_base_returns_none_on_bad_ref(repo):
    assert stub_guard._paths_touched_vs_base(repo, "no-such-ref") is None


def test_paths_touched_vs_base_returns_none_without_a_base(repo):
    assert stub_guard._paths_touched_vs_base(repo, None) is None


def test_paths_touched_vs_base_sees_untracked_files(repo):
    with open(os.path.join(repo, "src", "brand-new.ts"), "w") as fh:
        fh.write("export const X = 1\n")
    touched = stub_guard._paths_touched_vs_base(repo, "base")
    assert "src/brand-new.ts" in touched


def test_paths_touched_vs_base_sees_modified_files(repo):
    with open(os.path.join(repo, "src", "ok.ts"), "a") as fh:
        fh.write("export const Y = 2\n")
    assert "src/ok.ts" in stub_guard._paths_touched_vs_base(repo, "base")


@pytest.mark.parametrize("path,expected", [
    ("src/a.ts:13", "src/a.ts"),
    ("src/a.ts", "src/a.ts"),
    ("src/a.ts:1:2", "src/a.ts:1"),
    ("", ""),
    (None, ""),
])
def test_violation_relpath_strips_the_line_suffix(path, expected):
    assert stub_guard._violation_relpath("/repo", path) == expected


def test_violation_relpath_strips_the_repo_prefix():
    assert stub_guard._violation_relpath("/repo", "/repo/src/a.ts:9") == "src/a.ts"


def test_diff_derived_codes_are_never_downgraded():
    """body_replaced_by_constant and stub_commit_message are already attributed."""
    for code in ("body_replaced_by_constant", "stub_commit_message", "guard_error"):
        assert code not in stub_guard._TREE_SCAN_BLOCKING


def test_only_the_two_whole_tree_shapes_are_downgradable():
    assert stub_guard._TREE_SCAN_BLOCKING == {
        "stub_shadows_reexport", "fabricated_critical_return"}


def test_attribute_to_candidate_is_a_noop_without_a_base(repo):
    viol = [{"severity": "block", "code": "fabricated_critical_return", "path": "src/x.ts:1",
             "detail": "d"}]
    out = stub_guard.attribute_to_candidate(repo, None, viol)
    assert out[0]["severity"] == "block"
    assert "pre_existing" not in out[0]


def test_attribute_to_candidate_leaves_warnings_alone(repo):
    viol = [{"severity": "warn", "code": "fabricated_constant_return", "path": "src/x.ts:1",
             "detail": "d"}]
    stub_guard.attribute_to_candidate(repo, "base", viol)
    assert viol[0]["severity"] == "warn"
    assert "pre_existing" not in viol[0]


def test_shadowed_reexport_on_an_untouched_barrel_does_not_block(tmp_path):
    r = tmp_path / "r"
    (r / "src").mkdir(parents=True)
    _git(str(r), "init", "-q", "-b", "base")
    _git(str(r), "config", "user.email", "t@t")
    _git(str(r), "config", "user.name", "t")
    (r / "src" / "real.ts").write_text(
        "export function assertEcpCounterparty(x: string) {\n"
        "  if (!x) throw new Error('no')\n  return true\n}\n")
    (r / "src" / "index.ts").write_text(
        "export * from './real'\n"
        "export const assertEcpCounterparty = () => ({})\n")
    _git(str(r), "add", "-A")
    _git(str(r), "commit", "-q", "-m", "base")
    res = stub_guard.check_repo(str(r), "HEAD", "p", base="base")
    assert [v for v in res["violations"] if v.get("severity") == "block"] == []
    assert any(v.get("pre_existing") for v in res["violations"])

"""When a person switches branch in a repo, the error must not blame the merge train.

On 2026-09-01 merge_train logged, for a project whose lane then produced nothing:

    merge_train: apparently-law isolation blocked: merge_train changed canonical
    checkout /Users/kpasch/Documents/apparently-law:
    branch: refs/heads/main -> refs/heads/fix/console-record-headers

The train had changed nothing. A person was working in that repo in an editor and
switched branch while the pass ran. The guard noticed correctly and stopped correctly --
but named the train as the mutator, so the obvious next move is to hunt a bug in the
train, and the thing an operator actually needs to know (a whole project cannot
integrate until that checkout goes back) appears nowhere in the sentence.

The distinction is sound by construction, not by guessing: every git call isolated_repo
makes against the canonical repo is a `worktree` subcommand -- add, remove, prune -- and
none of those can switch a branch or change a repo root. So `branch:` and `top:` are
always external.

`head:` is deliberately NOT in that set, and the test below pins it: the pass fetches
into the canonical repo, so a canonical checkout sitting on the integration branch can be
fast-forwarded by the pass itself. Calling that external would be the same misattribution
in the opposite direction.
"""
import inspect
import re

import pytest

import integration_runtime as ir


def test_the_external_error_is_still_a_mutation_error():
    """Every existing `except CanonicalCheckoutMutationError` must keep catching it.

    The pass must still stop for this project. Only the attribution changes.
    """
    assert issubclass(ir.CanonicalCheckoutMovedExternallyError,
                      ir.CanonicalCheckoutMutationError)
    assert issubclass(ir.CanonicalCheckoutMovedExternallyError,
                      ir.IntegrationRuntimeError)


@pytest.mark.parametrize("mutation", [
    "branch: refs/heads/main -> refs/heads/fix/console-record-headers",
    "top: /Users/k/Documents/a -> /Users/k/Documents/b",
])
def test_a_branch_or_root_change_is_classified_external(mutation):
    assert mutation.startswith(ir._EXTERNAL_MUTATION_PREFIXES)


@pytest.mark.parametrize("mutation", [
    "head: aaaaaaa -> bbbbbbb",
    "tracked file(s) appeared: M runner/x.py",
    "tracked file(s) vanished: D runner/y.py",
])
def test_everything_else_keeps_the_old_attribution(mutation):
    """head: in particular. The pass fetches into the canonical repo, so a checkout
    sitting on the integration branch CAN be fast-forwarded by the pass itself, and
    calling that external would be the same mistake pointing the other way."""
    assert not mutation.startswith(ir._EXTERNAL_MUTATION_PREFIXES)


def test_the_external_message_does_not_accuse_the_owner():
    """The whole point. The sentence must not read as 'the train did this'."""
    src = inspect.getsource(ir.isolated_repo)
    m = re.search(r"CanonicalCheckoutMovedExternallyError\((.*?)\)\n", src, re.S)
    assert m, "the external error is no longer raised from isolated_repo"
    text = m.group(1)
    assert "was moved by something" in text and "other than" in text
    assert "Nothing was lost" in text
    assert "cannot be integrated until that checkout is put" in text


def test_the_owner_is_still_blamed_for_a_real_mutation():
    """The guard keeps its teeth for the case it was written for."""
    src = inspect.getsource(ir.isolated_repo)
    assert 'f"{owner} changed canonical checkout' in src


def test_the_external_branch_is_checked_first():
    """Ordering: the generic raise below would otherwise swallow every case."""
    src = inspect.getsource(ir.isolated_repo)
    ext = src.index("_EXTERNAL_MUTATION_PREFIXES")
    generic = src.index('f"{owner} changed canonical checkout')
    assert ext < generic


def test_the_pass_only_ever_runs_worktree_commands_against_the_canonical_repo():
    """This is the ENTIRE justification for calling branch:/top: external.

    If some future edit adds a `git checkout` or `git switch` against the canonical
    repo, the classification silently becomes wrong and this test is what says so.
    """
    src = inspect.getsource(ir.isolated_repo)
    calls = re.findall(r"_git\(canonical_repo,\s*\"([a-z-]+)\"", src)
    assert calls, "no canonical-repo git calls found; the scan is not looking at anything"
    assert set(calls) == {"worktree"}, (
        f"isolated_repo now runs {sorted(set(calls))} against the canonical repo. "
        "If any of those can move HEAD or switch a branch, branch:/top: is no longer "
        "provably external and _EXTERNAL_MUTATION_PREFIXES must be reconsidered."
    )

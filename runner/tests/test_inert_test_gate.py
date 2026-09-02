"""A test file that imports nothing from the repo is not testing the repo.

On 2026-09-01 the fleet wrote runner/test_orchestration_coordinator.py into this
repo. Its docstring says "Tests for orchestration_coordinator.py". There is no
orchestration_coordinator.py. What the file contains is:

    # Mock orcestration coordinator for testing
    class OrchestrationCoordinator:
        ...

followed by assertions against that class. It passes, it will always pass, and it
can never fail because of anything in this repository.

It was not alone. Of the twenty-four test files the fleet wrote or changed here that
week, seven — 4,618 lines — imported nothing from the repo at all:

    837  test_enhanced_testing_infrastructure_slice4.py
    830  test_fail_soft_error_handling_slice_4.py
    759  test_enhanced_testing_infrastructure_slice5.py
    740  test_orchestration_pipeline_contract.py
    610  test_orchestration_pipeline.py
    465  tests/test_gitops_branch_management.py
    377  tests/test_queue_processing_slice5.py

This matters beyond the wasted work. Every downstream signal the fleet computes from
"the suite is green" — the merge gate, the improvement verifier's realized multiplier,
the CADE scorecard — reads those passes as evidence. They are not evidence.

quality_gate.run() now refuses a candidate carrying one. The tests below spend most
of their attention on NOT over-firing, because a false positive blocks a real task.
"""
import os
import subprocess
import textwrap

import pytest

import quality_gate as qg


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    """A tiny repo with a real module on main and a branch to put candidates on."""
    r = tmp_path / "proj"
    (r / "tests").mkdir(parents=True)
    (r / "widget.py").write_text("def add(a, b):\n    return a + b\n")
    _git(str(r), "init", "-q", "-b", "main")
    _git(str(r), "config", "user.email", "t@example.com")
    _git(str(r), "config", "user.name", "t")
    _git(str(r), "add", "-A")
    _git(str(r), "commit", "-q", "-m", "base")
    _git(str(r), "checkout", "-q", "-b", "candidate")
    return str(r)


def _commit(repo, rel, body):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(body))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"add {rel}")


def test_a_test_that_defines_its_own_subject_is_caught(repo):
    """The exact shape of test_orchestration_coordinator.py."""
    _commit(repo, "tests/test_coordinator.py", '''
        """Tests for coordinator.py."""

        # Mock coordinator for testing
        class Coordinator:
            def enqueue(self, x):
                return [x]

        def test_enqueue():
            assert Coordinator().enqueue(1) == [1]
    ''')
    assert qg.inert_test_files(repo, "main") == ["tests/test_coordinator.py"]


def test_a_test_that_imports_the_real_module_passes(repo):
    _commit(repo, "tests/test_widget.py", '''
        import widget

        def test_add():
            assert widget.add(1, 2) == 3
    ''')
    assert qg.inert_test_files(repo, "main") == []


def test_a_from_import_of_the_real_module_passes(repo):
    _commit(repo, "tests/test_widget2.py", '''
        from widget import add

        def test_add():
            assert add(2, 2) == 4
    ''')
    assert qg.inert_test_files(repo, "main") == []


def test_a_structural_test_that_names_a_real_file_passes(repo):
    """Second clause. Some good tests read a source file instead of importing it.

    tests/test_quiet_cooldown_escape_hatch.py in this repo does exactly that, and
    blocking it would be the gate eating its own best work.
    """
    _commit(repo, "tests/test_structure.py", '''
        from pathlib import Path

        def test_widget_has_no_todo():
            src = Path(__file__).resolve().parent.parent / "widget.py"
            assert "TODO" not in src.read_text()
    ''')
    assert qg.inert_test_files(repo, "main") == []


def test_a_javascript_test_with_a_relative_import_passes(repo):
    _commit(repo, "tests/thing.spec.ts", '''
        import { add } from '../widget'
        it('adds', () => { expect(add(1, 1)).toBe(2) })
    ''')
    assert qg.inert_test_files(repo, "main") == []


def test_a_javascript_test_importing_only_node_modules_is_caught(repo):
    _commit(repo, "tests/lodash.spec.ts", '''
        import { chunk } from 'lodash'
        it('chunks', () => { expect(chunk([1,2],1).length).toBe(2) })
    ''')
    assert qg.inert_test_files(repo, "main") == ["tests/lodash.spec.ts"]


def test_non_test_files_are_never_reported(repo):
    """The gate judges tests. A helper module that imports nothing is fine."""
    _commit(repo, "helpers.py", "CONST = 1\n")
    assert qg.inert_test_files(repo, "main") == []


def test_untouched_test_files_are_not_judged(repo):
    """Only what THIS branch changed. The gate is not a repo-wide audit."""
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "tests/test_legacy.py", '''
        class Fake:
            pass

        def test_fake():
            assert Fake()
    ''')
    _git(repo, "checkout", "-q", "candidate")
    _commit(repo, "tests/test_widget3.py", '''
        import widget

        def test_add():
            assert widget.add(0, 0) == 0
    ''')
    assert qg.inert_test_files(repo, "main") == []


def test_no_base_means_no_opinion(repo):
    """Without a base there is no candidate diff, so the gate must stay silent."""
    _commit(repo, "tests/test_x.py", "class F:\n    pass\n\ndef test_f():\n    assert F()\n")
    assert qg.inert_test_files(repo, None) == []
    assert qg.run(repo)["pass"] is True


def test_a_structural_test_that_walks_the_tree_passes(repo):
    """Third clause, and the one that cost the most to learn.

    The three best tests in this repo import nothing and are not inert at all --
    test_sys_modules_shadowing.py, test_env_import_side_effects.py and
    test_workflow_shell_syntax.py each walk the tree with os.listdir/ast.parse and
    assert a property over every file. All three were false positives on the first
    sweep. A gate that eats those is worse than no gate.
    """
    _commit(repo, "tests/test_no_todos_anywhere.py", '''
        import ast, os

        def test_every_module_parses():
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            for name in os.listdir(root):
                if name.endswith(".py"):
                    ast.parse(open(os.path.join(root, name)).read())
    ''')
    assert qg.inert_test_files(repo, "main") == []


def test_a_stdlib_import_does_not_count_as_reaching_the_repo(repo):
    """This repo has a types.py, so `import types` cleared two inert files on the
    first run. Any repo can shadow a stdlib name; the check must not be fooled by it."""
    _commit(repo, "types.py", "X = 1\n")
    _commit(repo, "tests/test_shadowed.py", '''
        import types

        class Fake:
            pass

        def test_it():
            assert isinstance(types, object) and Fake()
    ''')
    assert qg.inert_test_files(repo, "main") == ["tests/test_shadowed.py"]


def test_a_file_does_not_clear_itself_by_containing_its_own_name(repo):
    """test_queue_processing_slice5.py cleared itself exactly this way."""
    _commit(repo, "tests/test_selfnamed.py", '''
        """See tests/test_selfnamed.py for details."""
        PATH = "tests/test_selfnamed.py"

        class Fake:
            pass

        def test_it():
            assert Fake()
    ''')
    assert qg.inert_test_files(repo, "main") == ["tests/test_selfnamed.py"]


def test_naming_a_real_file_only_in_prose_does_not_clear(repo):
    """test_gitops_branch_management.py cleared itself by naming another module in a
    docstring. A mention is not a use."""
    _commit(repo, "tests/test_prose.py", '''
        """Related to widget.py, in spirit."""

        class Fake:
            pass

        def test_it():
            assert Fake()
    ''')
    assert qg.inert_test_files(repo, "main") == ["tests/test_prose.py"]


def test_run_flags_the_candidate_and_names_the_file(repo):
    """Advisory by DEFAULT: the note lands, the task is not blocked.

    A false positive here blocks real work, and the first sweep over this repo's own
    history flagged 4% of 611 changed test files. So the finding is recorded and can
    be measured from real traffic; ORCH_QUALITY_INERT_TEST_BLOCK=true makes it bite.
    """
    _commit(repo, "tests/test_coordinator.py", '''
        # Mock coordinator for testing
        class Coordinator:
            pass

        def test_it():
            assert Coordinator()
    ''')
    result = qg.run(repo, base="main")
    assert result["pass"] is True, "the scan must be advisory until its FP rate is known"
    assert "ADVISORY" in result["notes"]
    assert "tests/test_coordinator.py" in result["notes"]


def test_it_blocks_when_the_operator_asks_it_to(repo):
    _commit(repo, "tests/test_coordinator.py", '''
        # Mock coordinator for testing
        class Coordinator:
            pass

        def test_it():
            assert Coordinator()
    ''')
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(qg, "INERT_TEST_BLOCKS", True)
        result = qg.run(repo, base="main")
    assert result["pass"] is False
    assert "tests/test_coordinator.py" in result["notes"]


def test_run_passes_and_says_so_when_the_candidate_is_clean(repo):
    _commit(repo, "tests/test_widget4.py", "import widget\n\ndef test_a():\n    assert widget.add(1,1)==2\n")
    result = qg.run(repo, base="main")
    assert result["pass"] is True
    assert "inert-test scan clean" in result["notes"]


def test_the_gate_can_be_switched_off(repo):
    _commit(repo, "tests/test_coordinator.py", "class C:\n    pass\n\ndef test_c():\n    assert C()\n")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(qg, "INERT_TEST_GATE", False)
        mp.setattr(qg, "INERT_TEST_BLOCKS", True)
        result = qg.run(repo, base="main")
    assert result["pass"] is True
    assert "test_coordinator" not in result["notes"], "the scan ran despite being off"


def test_a_broken_git_does_not_block_the_task(repo):
    """Fail-soft: a gate bug must never wedge every task in the fleet."""
    assert qg.inert_test_files(repo, "no-such-ref-anywhere") == []
    assert qg.run(repo, base="no-such-ref-anywhere")["pass"] is True


def test_an_advisory_finding_on_a_passing_gate_is_not_discarded():
    """THE BUG THIS PINS. The scan is advisory, so it returns pass=True — and the call
    site read qg["notes"] ONLY inside `if not qg["pass"]`.

    So every finding was dropped one line after it was produced. Zero occurrences in the
    runner logs and zero in tasks.note over a full day, which also meant there was no way
    to collect the false-positive data the advisory period exists to collect. An advisory
    check whose advice is thrown away is not a check.
    """
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "runner.py")
    with open(src, encoding="utf-8") as fh:
        body = fh.read()
    call = body.index("qg = quality_gate.run(wt, base=base)")
    blocking = body.index('if not qg["pass"]:', call)
    surfaced = body[call:blocking]
    assert 'qg["pass"] and "ADVISORY"' in surfaced, (
        "an advisory quality finding is no longer surfaced on a passing gate — it will "
        "be discarded on every task, exactly as it was"
    )
    assert "_soft_flags.append" in surfaced, "the finding is not recorded on the task"
    assert "quality-advisory" in surfaced, "the finding is not logged"


def test_the_runner_passes_a_base_to_the_gate():
    """Structural. The scan is a no-op unless the call site supplies `base`.

    quality_gate.run(repo) with no base returns pass unconditionally, which is the
    correct fail-soft default and also a silent way for this whole gate to do
    nothing. So assert the one call site still passes it.
    """
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner.py")
    with open(src, encoding="utf-8") as fh:
        body = fh.read()
    assert "quality_gate.run(wt, base=base)" in body, (
        "runner.py no longer passes `base` to quality_gate.run — the inert-test scan "
        "is silently disabled for the whole fleet"
    )

"""The cowork-executor skills carry a third copy of the claim predicate. Keep it honest.

Dependency resolution is written down in three places:

  1. runner/db.py            _done_slugs() + the claim path      (authoritative, live)
  2. runner/migrations/001_claim_next_rpc.sql                    (flagged off)
  3. cowork-skills/cowork-executor*.SKILL.md                     (16 copies, live)

(1) and (2) were corrected on 2026-08-25. (3) was not, and nobody noticed for two days
because a stale predicate does not fail loudly -- it returns zero claimable rows, which
the skills then read as "queue empty" and report as a clean run. Sixteen executors did
exactly that against a 327-task queue for six weeks (QUEUE-DEADLOCK-2026-08-25.md).

These tests pin the three properties that drift silently. They read files only; no DB,
no network.
"""
import pathlib

import pytest

SKILL_DIR = pathlib.Path(__file__).resolve().parents[2] / "cowork-skills"
SKILLS = sorted(SKILL_DIR.glob("cowork-executor*.SKILL.md"))


def _read(p):
    return p.read_text()


def _executable_sql(p):
    """File text minus SQL comment lines.

    The corrected predicate documents the bug it replaced, so the old broken spelling
    appears verbatim in a `--` comment. A check for banned SQL has to look at what
    Postgres would actually run, not at prose about it.
    """
    return "\n".join(
        line for line in _read(p).splitlines()
        if not line.lstrip().startswith("--")
    )


def test_skill_files_are_present():
    """If the glob silently matches nothing, every test below vacuously passes."""
    assert len(SKILLS) >= 16, f"expected >=16 executor skills under {SKILL_DIR}, found {len(SKILLS)}"


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.name)
def test_deployed_and_verified_counts_as_satisfied(skill):
    """DEPLOYED_AND_VERIFIED is strictly stronger than DONE and must not block dependents."""
    text = _read(skill)
    assert "'DONE','MERGED','DEPLOYED_AND_VERIFIED'" in text or \
           "'DONE', 'MERGED', 'DEPLOYED_AND_VERIFIED'" in text, \
        f"{skill.name}: claim predicate omits DEPLOYED_AND_VERIFIED, so a dependent of " \
        f"fully delivered work is held back by its own success"


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.name)
def test_cross_project_deps_resolve(skill):
    """A dep written `project_name:slug` must be looked up in the named project."""
    text = _read(skill)
    assert "split_part(dep, ':', 1)" in text, \
        f"{skill.name}: qualified `project:slug` deps are matched only inside the task's " \
        f"own project, so they can never resolve"


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.name)
def test_no_three_valued_not_in_dependency_test(skill):
    """`dep NOT IN (SELECT ...)` fails OPEN if any candidate slug is NULL.

    With a NULL in the candidate set the comparison is NULL rather than TRUE for every
    dep, the row is filtered out, and the query reports all dependencies satisfied --
    claiming tasks whose deps are unmet. NOT EXISTS has no such hole.
    """
    assert "dep NOT IN (" not in _executable_sql(skill), \
        f"{skill.name}: uses `dep NOT IN (SELECT ...)`, which fails open on a NULL slug; " \
        f"use NOT EXISTS"


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.name)
def test_zero_rows_is_not_reported_as_empty_queue(skill):
    """A stalled queue and a finished queue must not produce the same report."""
    text = _read(skill)
    assert "queued_remaining" in text, \
        f"{skill.name}: does not distinguish 'nothing claimable' from 'queue empty'; a " \
        f"dependency-starved queue will be reported as a successful run"
    assert "STALLED" in text, \
        f"{skill.name}: missing the stall alert path for queued_remaining > 0"


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.name)
def test_kill_switch_is_checked_before_claiming(skill):
    """An executor must not claim or push through a deliberate halt.

    runner/db.py drops paused projects from its claim set and kill_switch.is_paused()
    gates the runner on the global and host scopes. The skills had no equivalent, so a
    scheduled executor would work straight through a global pause -- and on 2026-08-27
    a global pause had been in force for three days with every portfolio project also
    individually paused.
    """
    text = _read(skill)
    assert "FROM controls" in text, \
        f"{skill.name}: never reads the controls table, so it cannot see a pause"
    assert "remote-quarantine" in text, \
        f"{skill.name}: pause check does not exclude remote-quarantine rows, diverging " \
        f"from kill_switch.is_paused()"
    assert "stop this run now" in text, \
        f"{skill.name}: reads controls but does not halt on a global pause"

    # The gate has to sit ahead of the claim, or it gates nothing.
    assert text.index("FROM controls") < text.index("## Step 1"), \
        f"{skill.name}: kill-switch check appears after the claim step"


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.name)
def test_no_bulk_dep_clearing_shortcut(skill):
    """The obvious 'fix' -- wave the whole queue through -- is the expensive one.

    51 of the 58 DECOMPOSED blockers had zero children: the work was marked as split up
    and then never created. Unblocking their dependents launches work whose stated
    prerequisite never happened.
    """
    text = _read(skill)
    assert "do **not** bulk-clear deps" in text, \
        f"{skill.name}: missing the warning against force-opening the queue by clearing deps"

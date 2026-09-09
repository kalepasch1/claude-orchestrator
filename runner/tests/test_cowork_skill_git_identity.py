"""Every cowork-executor skill must commit as the canonical identity.

All sixteen skills instructed executors to commit with

    git -c user.name="Kale Pasch" -c user.email="kalepasch@gmail.com" commit ...

while every repo's CLAUDE.md mandates `kalepasch1`, and the release train's
`author_identity_guard` enforces it:

    author_identity_guard: name drift e69061a74340 'Kale Pasch' (canonical 'kalepasch1')
    author_identity_guard: REFUSED.
    error: failed to push some refs to 'https://github.com/kalepasch1/tomorrow.git'

So sixteen executors, on every run, produced commits the release train could not
ship — and the guard's own message named the correct value the whole time. The
work was not lost, but it could not reach production, and the failure surfaced
far away from its cause: as a relfix task about staging/prod divergence, not as
"the skills are wrong".

This is the cheap check that would have caught it. The live skills are not under
version control (see cowork-skills/README.md); these versioned copies are the
only thing a diff can see, which is exactly why they need a test rather than an
assumption.
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILLS_DIR = os.path.join(ROOT, "cowork-skills")

CANONICAL_NAME = "kalepasch1"
CANONICAL_EMAIL = "kalepasch@gmail.com"

_NAME_RE = re.compile(r'-c\s+user\.name=(?:"([^"]*)"|\'([^\']*)\'|(\S+))')
_EMAIL_RE = re.compile(r'-c\s+user\.email=(?:"([^"]*)"|\'([^\']*)\'|(\S+))')


def _values(pattern, text):
    return [next(g for g in m.groups() if g is not None)
            for m in pattern.finditer(text)]


def skill_files():
    if not os.path.isdir(SKILLS_DIR):
        return []
    return sorted(
        os.path.join(SKILLS_DIR, f)
        for f in os.listdir(SKILLS_DIR)
        if f.endswith(".SKILL.md")
    )


@pytest.mark.parametrize("path", skill_files(), ids=os.path.basename)
def test_every_skill_commits_as_the_canonical_name(path):
    """The regression. Any other name is refused by the release train."""
    src = open(path, errors="replace").read()
    wrong = [v for v in _values(_NAME_RE, src) if v != CANONICAL_NAME]
    assert not wrong, (
        f"{os.path.basename(path)} commits as {wrong!r}; the release train's "
        f"author_identity_guard only accepts {CANONICAL_NAME!r}"
    )


@pytest.mark.parametrize("path", skill_files(), ids=os.path.basename)
def test_every_skill_commits_as_the_canonical_email(path):
    # The email was already right; pinned so a future edit cannot fix one field
    # and break the other, which would fail identically and read as unrelated.
    src = open(path, errors="replace").read()
    wrong = [v for v in _values(_EMAIL_RE, src) if v != CANONICAL_EMAIL]
    assert not wrong, f"{os.path.basename(path)} commits as {wrong!r}"


def test_the_skills_are_actually_being_checked():
    """A parametrised suite over an empty list passes silently.

    If the directory moves or the glob stops matching, every test above vanishes
    and the file still reports green — the same shape of invisible failure this
    whole check exists to catch.
    """
    files = skill_files()
    assert len(files) >= 10, f"expected the executor skills, found {len(files)}"


def test_at_least_one_skill_actually_sets_a_git_identity():
    """Guards the detector, not the skills.

    If the commit line were reworded so `-c user.name=` no longer appears, the
    parametrised checks would pass by matching nothing at all.
    """
    found = any(_values(_NAME_RE, open(p, errors="replace").read())
                for p in skill_files())
    assert found, "no skill sets an explicit git identity; the pattern has drifted"


def test_the_canonical_identity_matches_the_repo_instructions():
    """CLAUDE.md is the source of this rule; a copy of it must not drift."""
    claude_md = os.path.join(ROOT, "CLAUDE.md")
    if not os.path.exists(claude_md):
        pytest.skip("CLAUDE.md not present")
    src = open(claude_md, errors="replace").read()
    assert f'git config user.name "{CANONICAL_NAME}"' in src
    assert f'git config user.email "{CANONICAL_EMAIL}"' in src

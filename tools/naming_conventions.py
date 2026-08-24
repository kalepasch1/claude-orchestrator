#!/usr/bin/env python3
"""One definition of what CLAUDE.md's naming conventions mean.

Slices 1-3 of the convention-lint backlog each added a CapWords class-name rule in a
different module, and the two that survived to master disagreed about the edge cases:

  * tools/convention_lint.py used a regex ``^_?[A-Z][A-Za-z0-9]*$`` — a single leading
    underscore is a documented private-type spelling and passes.
  * runner/tools/lint_conventions.py used ``name[0].isupper() and "_" not in name`` —
    which rejects ``_PrivateCache`` outright, so the caller had to special-case
    ``startswith("_")`` at the call site to get the same answer.

Two linters that answer differently for the same class name is worse than one linter,
because whichever one a contributor happens to run teaches them a different rule. This
module is the single source of truth; both linters delegate to it and neither keeps a
private copy of the predicate.

Fail-soft by contract: never raises, whatever it is handed.
"""

import re

#: PascalCase, with one optional leading underscore for a private type. Each remaining
#: word starts with a capital; digits are allowed after the first character; a run of
#: capitals is allowed so acronym-led names (HTTPClient, DBPool) pass unchanged. An
#: underscore anywhere after the first character makes it snake_case, which fails.
PASCAL_CASE_RE = re.compile(r"^_?[A-Z][A-Za-z0-9]*$")

#: Rule id both linters report under, so downstream filters and the ratchet see one name.
CLASS_NAMING_RULE = "CLASS_NAMING"

#: Style naming is a readability defect, not a correctness one. Warning severity keeps it
#: off the critical path of the unattended merge train.
CLASS_NAMING_SEVERITY = "warning"


def is_pascal_case(name) -> bool:
    """True when `name` is a valid PascalCase class name.

    Deliberately permissive, because a naming rule that fires on correct code is the
    thing that teaches people to run ``--no-verify``:

      * ``_PrivateCache``  -> True  (documented private-type spelling)
      * ``HTTPClient``     -> True  (acronym run)
      * ``Sha256Digest``   -> True  (digits after the first character)
      * ``taskRunner``     -> False (lowercase initial)
      * ``Task_Runner``    -> False (underscore inside the name)
      * ``TASK_RUNNER``    -> False (SCREAMING_CASE, via the same underscore clause)

    Never raises: None, ints and other junk return False.
    """
    try:
        return bool(PASCAL_CASE_RE.match(str(name or "")))
    except Exception:
        return False


def class_naming_message(name) -> str:
    """The message both linters emit, so their output is greppable as one rule."""
    try:
        return (
            "Class '{0}' is not PascalCase "
            "(CLAUDE.md: PascalCase for types/classes/components)".format(name)
        )
    except Exception:
        return "Class name is not PascalCase (CLAUDE.md: PascalCase for types/classes/components)"

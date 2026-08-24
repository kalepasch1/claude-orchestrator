"""hisanta package.

The domain modules (grandma, mastery, gifting, kindness, school) live one level down in
``hisanta/hisanta/``, but callers and tests import them as ``hisanta.grandma``,
``hisanta.mastery``, ... Which spelling resolves used to depend on which directory ended
up on sys.path first, so ``import hisanta.mastery.engine`` worked from one rootdir and
raised ModuleNotFoundError from the other.

Extending ``__path__`` over the nested tree makes both spellings resolve to the same
subpackage, without moving any file and without breaking the existing
``hisanta.hisanta.mastery.engine`` imports in school/classroom.py.

``__path__`` is bound explicitly from ``globals()`` rather than mutated in place: a bare
``__path__.append(...)`` reads a name a static checker cannot see defined here, which is
what tripped the pyflakes undefined-name guard.

RESOLVED 2026-08-24. This file was committed to master WITH ITS CONFLICT MARKERS STILL IN
IT — ``<<<<<<< HEAD`` / ``=======`` / ``>>>>>>>`` at lines 3, 23 and 41 — so it was a
SyntaxError, and importing it took out collection of tests/test_gifting_protocol.py,
tests/test_kindness_mint.py and tests/test_school_mode.py. Both sides of that conflict
were doing the same thing; this keeps the HEAD implementation (explicit ``globals()``
bind, append-never-prepend) plus the other side's ``abspath`` and its explanation of WHY
both spellings have to resolve, which is the part that was worth keeping.
"""
import os as _os

__path__ = list(globals().get("__path__", []))

_NESTED = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "hisanta")
if _os.path.isdir(_NESTED) and _NESTED not in __path__:
    # Appended, never prepended: hisanta/contracts stays the canonical
    # hisanta.contracts, so the nested copy can never shadow it.
    __path__.append(_NESTED)

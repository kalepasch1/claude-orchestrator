"""hisanta package.

The implementation subpackages (grandma, mastery, gifting, kindness, school) live
one level down, in ``hisanta/hisanta/``, but callers and tests import them as
``hisanta.grandma``, ``hisanta.mastery``, ... Depending on which directory ends up
on sys.path, ``hisanta`` resolves to either this directory or that one, so
``import hisanta.mastery.engine`` worked from one rootdir and raised
ModuleNotFoundError from the other.

Extending ``__path__`` over the nested tree makes both spellings resolve without
moving any file and without breaking the existing ``hisanta.hisanta.mastery.engine``
imports in school/classroom.py: ``hisanta.mastery`` and ``hisanta.hisanta.mastery``
become the same subpackage.

``__path__`` is bound explicitly from ``globals()`` rather than mutated in place: a
bare ``__path__.append(...)`` reads a name a static checker cannot see defined here,
which is what tripped the pyflakes undefined-name guard.

The nested path is appended, never prepended, so ``hisanta.contracts`` still resolves
to this directory first. That file is a re-export shim for the canonical contracts,
so there is exactly one definition either way and the nested copy can never shadow it.

NOTE (2026-08-24): this file reached origin/master carrying unresolved conflict
markers, which made it a SyntaxError and took three test modules out of collection.
The two sides were the same fix in different words; they are reconciled here into one.
"""
import os as _os

__path__ = list(globals().get("__path__", []))

_NESTED = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "hisanta")
if _os.path.isdir(_NESTED) and _NESTED not in __path__:
    __path__.append(_NESTED)

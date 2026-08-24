"""hisanta package.

The domain modules (grandma, mastery, gifting, kindness, school) live one level
down in ``hisanta/hisanta/``, but callers and tests import them as
``hisanta.grandma``, ``hisanta.mastery``, ... Depending on which directory ends
up on sys.path, ``hisanta`` resolved to either this directory or that one, so
``import hisanta.mastery.engine`` worked from one rootdir and raised
ModuleNotFoundError from the other.

Extending ``__path__`` over the nested tree makes both spellings resolve without
moving any file and without breaking the existing
``hisanta.hisanta.mastery.engine`` imports in school/classroom.py:
``hisanta.mastery`` and ``hisanta.hisanta.mastery`` become the same subpackage.

``__path__`` is bound explicitly from ``globals()`` rather than mutated in place.
A bare ``__path__.append(...)`` reads a name a static checker cannot see defined
here, which is what tripped the pyflakes undefined-name guard — so the two sides
of this merge agreed on the behaviour and differed only in whether they kept
that fix. This keeps it.
"""
import os as _os

__path__ = list(globals().get("__path__", []))

_nested = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "hisanta")
if _os.path.isdir(_nested) and _nested not in __path__:
    # Appended, never prepended: hisanta/contracts stays the canonical
    # hisanta.contracts, so the nested copy can never shadow it. That file is a
    # re-export shim for the canonical contracts, so there is exactly one
    # definition either way.
    __path__.append(_nested)

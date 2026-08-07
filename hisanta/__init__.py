"""hisanta package.

The domain modules (grandma, mastery, gifting, kindness, school) live one level
down in `hisanta/hisanta/`, but callers and tests import them as `hisanta.grandma`,
`hisanta.mastery`, ... Extending __path__ over the nested tree makes both spellings
resolve without moving any file or breaking the existing
`hisanta.hisanta.mastery.engine` imports in school/classroom.py.

__path__ is bound explicitly from globals() rather than mutated in place: a bare
`__path__.append(...)` reads a name a static checker cannot see defined here, which
is what tripped the pyflakes undefined-name guard.
"""
import os as _os

__path__ = list(globals().get("__path__", []))

_nested = _os.path.join(_os.path.dirname(__file__), "hisanta")
if _os.path.isdir(_nested) and _nested not in __path__:
    # Appended, never prepended: hisanta/contracts stays the canonical
    # hisanta.contracts, so the nested copy can never shadow it.
    __path__.append(_nested)

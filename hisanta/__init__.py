"""hisanta package.

The domain modules (grandma, mastery, gifting, kindness, school) live one level
down in ``hisanta/hisanta/``, but callers and tests import them as
``hisanta.grandma``, ``hisanta.mastery``, ... Depending on which directory ends up
on sys.path, ``hisanta`` resolves to either this directory or the nested one, so
``import hisanta.mastery.engine`` worked from one rootdir and raised
ModuleNotFoundError from the other.

Extending __path__ over the nested tree makes both spellings resolve without moving
any file and without breaking the existing ``hisanta.hisanta.mastery.engine``
imports in school/classroom.py.

__path__ is bound explicitly from globals() rather than mutated in place: a bare
``__path__.append(...)`` reads a name a static checker cannot see defined here,
which is what tripped the pyflakes undefined-name guard.

CONFLICT RESOLUTION (canary-claude-27-slice-1-run-checks): this file was committed
to master carrying literal `<<<<<<<` / `=======` / `>>>>>>>` markers. That is a
SyntaxError, and it broke *collection* of tests/test_gifting_protocol.py,
tests/test_kindness_mint.py and tests/test_school_mode.py — pytest aborted the whole
run with "Interrupted: 3 errors during collection", so every other test in the same
invocation stopped reporting too. Three more files were conflicted the same way:
hisanta/contracts/family.py, hisanta/hisanta/contracts/family.py and
hisanta/hisanta/mastery/engine.py.

Both sides of every conflict implemented the SAME de-duplication with the canonical
copy on opposite ends. Resolved consistently toward the
agent/dropbox-hisanta-mastery-engine-grandma-rail-family-slice-2 side — canonical
definitions in hisanta/hisanta/contracts/family.py, re-export shim at
hisanta/contracts/family.py — because a mixed resolution would have left both files
importing each other. Here, the HEAD side's explicit globals() binding of __path__ is
kept (a bare __path__.append trips the pyflakes undefined-name guard), with the other
side's clearer explanation folded in above.
"""
import os as _os

__path__ = list(globals().get("__path__", []))

_nested = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "hisanta")
if _os.path.isdir(_nested) and _nested not in __path__:
    # Appended, never prepended: hisanta/contracts stays the module that answers
    # `hisanta.contracts`. It is a re-export shim over the canonical definitions in
    # hisanta/hisanta/contracts/family.py, so both spellings yield the SAME objects
    # and an isinstance/enum-identity check cannot fail across the seam.
    __path__.append(_nested)

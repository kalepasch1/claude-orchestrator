"""hisanta package.

The implementation subpackages (mastery, grandma, gifting, kindness, school)
live one level down, in ``hisanta/hisanta/``. Depending on which directory ends
up on sys.path, ``hisanta`` resolves to either this directory or that one, so
``import hisanta.mastery.engine`` worked from one rootdir and raised
ModuleNotFoundError from the other.

Extending ``__path__`` makes both spellings resolve: ``hisanta.mastery`` and
``hisanta.hisanta.mastery`` are the same subpackage. ``hisanta.contracts``
still resolves to this directory first, and that file is a re-export shim for
the canonical contracts, so there is exactly one definition either way.
"""

import os as _os

_NESTED = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "hisanta")
if _os.path.isdir(_NESTED) and _NESTED not in __path__:
    __path__.append(_NESTED)

"""Re-export shim for the family contracts.

The definitions live exactly once, in ``hisanta/contracts/family.py``. This file
used to be a second, drifted copy of the same domain: it grew the
quest/grandma/gifting/school types while the canonical file kept the
approval/kindness types, and the two spellings of the same name were different
objects. An ``isinstance`` check or an enum comparison could therefore fail
across the seam depending on which directory ended up on ``sys.path`` as the
``hisanta`` package.

Re-exporting -- rather than re-declaring -- is what makes
``hisanta.contracts.family.X`` and ``hisanta.hisanta.contracts.family.X`` the
SAME object. ``hisanta/tests/test_family_contract_single_source.py`` is the
regression guard: it fails the moment a local definition grows back here.
"""

from hisanta.contracts import family as _canonical

#: Every public name the canonical module exports. Built from the canonical
#: module rather than hand-listed so a new contract type cannot be forgotten.
__all__ = [_n for _n in dir(_canonical) if not _n.startswith("_")]

for _name in __all__:
    globals()[_name] = getattr(_canonical, _name)
del _name

#: The module the names came from. Tests assert both import paths land here.
CANONICAL_MODULE = _canonical

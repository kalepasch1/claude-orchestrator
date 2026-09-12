"""Re-export shim.  The family contracts are defined once, in
`hisanta/contracts/family.py`.

Both this directory and its parent can end up on sys.path as the `hisanta`
package, so `hisanta.contracts.family` and `hisanta.hisanta.contracts.family`
are two spellings of one domain.  This module re-exports — it never declares —
so the two spellings are the SAME objects and an isinstance check or an enum
comparison cannot fail just because a caller arrived by the nested path.

Deliberately a plain `import`, not an importlib load-by-path: loading the
canonical file under a private third module name would give it a second set of
classes, which is the exact defect this shim exists to prevent.

Do not add definitions here.  Add them to `hisanta/contracts/family.py`; this
file picks them up from `__all__` with no edit.
"""

import hisanta.contracts.family as _canonical

#: The module the names come from.  Tests assert both import paths land here,
#: which is the check that keeps the duplicate from growing back.
CANONICAL_MODULE = _canonical
CANONICAL_PATH = _canonical.__file__

__all__ = list(_canonical.__all__)
for _name in __all__:
    globals()[_name] = getattr(_canonical, _name)
del _name

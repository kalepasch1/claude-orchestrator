"""Re-export shim for the family contracts.

The definitions live once, in ``hisanta/hisanta/contracts/family.py``. This file
exists because both this directory and ``hisanta/hisanta/`` can end up on
sys.path as the ``hisanta`` package (pytest picks a rootdir; the app imports
from the repo root), and the module path ``hisanta.contracts.family`` therefore
resolves to one file or the other depending on how you got here.

Before this shim the two files held DIFFERENT definitions of ParentApproval,
ParentVerificationReceipt, CoppaConsent and constitution_check, so an
`isinstance` check or an enum comparison could fail across the seam and
hisanta/tests/* could not be collected at all. Re-exporting the canonical
module — rather than re-declaring anything — is what makes the two spellings
the SAME objects.

Do not add definitions here. Add them to hisanta/hisanta/contracts/family.py
and to its __all__; they are picked up automatically.
"""

import hisanta.hisanta.contracts.family as _canonical

__all__ = list(_canonical.__all__)
for _name in __all__:
    globals()[_name] = getattr(_canonical, _name)
del _name

#: The module object the names came from, and the file it was read from. Tests
#: assert both import paths land here, which is the check that keeps the
#: duplicate from growing back.
CANONICAL_MODULE = _canonical.CANONICAL_MODULE
CANONICAL_PATH = _canonical.CANONICAL_PATH

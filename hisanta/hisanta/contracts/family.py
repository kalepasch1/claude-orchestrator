"""Re-export shim: the canonical family contracts live at hisanta/contracts/family.py.

This file used to be a second, independently-maintained copy of the same domain.
The two drifted — this one grew the quest/grandma/gifting/school types while the
top-level one grew the approval/kindness types — and because both directories can
end up on sys.path as the ``hisanta`` package, ``hisanta.contracts.family``
resolved to one file or the other depending on how you got here. The two then held
DIFFERENT definitions of ParentApproval, ParentVerificationReceipt, CoppaConsent
and constitution_check, so an isinstance check or an enum comparison could fail
across the seam and hisanta/tests/* could not be collected at all.

Imported BY MODULE NAME, not loaded by file path. Running the canonical source a
second time through spec_from_file_location under a synthetic module name would
produce a distinct set of classes, so isinstance across the seam would still be
False — a shim that looks like de-duplication while preserving the exact bug it
was written to remove.

Do not add definitions here. Add them to hisanta/contracts/family.py and extend
its ``__all__``; this module follows automatically.
"""

from hisanta.contracts import family as _canonical
from hisanta.contracts.family import *  # noqa: F401,F403  (re-export)

#: The module the names came from. hisanta/tests assert both import paths land
#: here, which is the check that keeps the duplicate from growing back.
CANONICAL_MODULE = _canonical
CANONICAL_PATH = _canonical.__file__

__all__ = list(getattr(_canonical, "__all__", []))

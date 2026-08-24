"""Re-export shim for the family contracts.

The definitions live once, in ``hisanta/hisanta/contracts/family.py``. This file
exists because both this directory and ``hisanta/hisanta/`` can end up on
sys.path as the ``hisanta`` package (pytest picks a rootdir; the app imports
from the repo root), and the module path ``hisanta.contracts.family`` therefore
resolves to one file or the other depending on how you got here.

Before this shim the two files held DIFFERENT definitions of ParentApproval,
ParentVerificationReceipt, CoppaConsent and constitution_check, so an
`isinstance` check or an enum comparison could fail across the seam and
hisanta/tests/* could not be collected at all. Loading the canonical file by
path — rather than re-declaring anything — is what makes the two spellings the
SAME objects.
"""

import importlib.util as _importlib_util
import os as _os
import sys as _sys

_CANONICAL_PATH = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
    "hisanta", "contracts", "family.py",
)
_CANONICAL_MODULE = "hisanta._canonical_contracts_family"

_module = _sys.modules.get(_CANONICAL_MODULE)
if _module is None:
    _spec = _importlib_util.spec_from_file_location(_CANONICAL_MODULE, _CANONICAL_PATH)
    if _spec is None or _spec.loader is None:  # pragma: no cover - packaging error
        raise ImportError(f"canonical family contracts not found at {_CANONICAL_PATH}")
    _module = _importlib_util.module_from_spec(_spec)
    # Registered before exec so a re-entrant import gets the same object.
    _sys.modules[_CANONICAL_MODULE] = _module
    _spec.loader.exec_module(_module)

# Re-export every public name, plus __all__ itself.
__all__ = list(getattr(_module, "__all__", []))
for _name in __all__:
    globals()[_name] = getattr(_module, _name)
del _name

#: The module object the names came from. Tests assert both import paths land
#: here, which is the check that keeps the duplicate from growing back.
CANONICAL_MODULE = _module
CANONICAL_PATH = _CANONICAL_PATH

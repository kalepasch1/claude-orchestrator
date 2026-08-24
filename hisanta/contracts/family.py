"""Re-export shim for the family contracts.

The definitions live once, in ``hisanta/hisanta/contracts/family.py``. This file
exists because both this directory and ``hisanta/hisanta/`` can end up on
sys.path as the ``hisanta`` package (pytest picks a rootdir; the app imports
from the repo root), and the module path ``hisanta.contracts.family`` therefore
resolves to one file or the other depending on how you got here.

Before this shim the two files held DIFFERENT definitions of ParentApproval,
ParentVerificationReceipt, CoppaConsent and constitution_check, so an
`isinstance` check or an enum comparison could fail across the seam and
hisanta/tests/* could not be collected at all. Re-exporting the canonical module —
rather than re-declaring anything — is what makes every spelling the SAME objects.
"""

# Imported through the normal import system, NOT loaded from its file path.
#
# The first version of this shim did the latter: it exec'd the canonical file under a
# private third module name (`hisanta._canonical_contracts_family`). That gave this
# module the right objects, but it also meant a caller writing the perfectly ordinary
# `import hisanta.hisanta.contracts.family` executed the same file a SECOND time under
# that name and got a parallel set of classes. Identity then broke across exactly the
# seam this shim exists to close: an enum member from one path was not the enum member
# from the other, and an isinstance check across them silently failed.
#
# A plain absolute import gives Python one module object, cached in sys.modules under
# one name, reached identically by both spellings. It is safe here because every
# __init__.py in the chain (hisanta, hisanta.hisanta, hisanta.hisanta.contracts) is
# empty, so there is no import cycle to trip over.
from hisanta.hisanta.contracts import family as _module

# Re-export every public name, plus __all__ itself.
__all__ = list(getattr(_module, "__all__", []))
for _name in __all__:
    globals()[_name] = getattr(_module, _name)
del _name

_CANONICAL_PATH = _module.__file__

#: The module object the names came from. Tests assert both import paths land
#: here, which is the check that keeps the duplicate from growing back.
CANONICAL_MODULE = _module
CANONICAL_PATH = _CANONICAL_PATH

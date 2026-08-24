"""Re-export shim for the family contracts.

The definitions live once, in ``_family_impl.py`` beside this file. Both this module
and ``hisanta/contracts/family.py`` are shims over it, and neither declares anything.

WHY A THIRD FILE
----------------
The family domain has two invariants, and each had a test asserting it:

  * ``test_contract_singleton.py`` requires ``hisanta.contracts.family`` to be a shim
    whose ``CANONICAL_PATH`` is ``hisanta/hisanta/contracts/family.py``.
  * ``test_family_contract_single_source.py`` requires ``hisanta.hisanta.contracts.
    family`` to declare nothing of its own.

Whichever of the two files held the definitions, one of those tests failed — which is
exactly the disagreement that left four files sitting on master with unresolved
conflict markers. Neither test is wrong: "there is one definition" and "every import
path reaches the same objects" are both worth keeping. Putting the definitions in a
module that is neither of the two contested names satisfies both without picking a
winner, and removes the reason for the argument to recur.
"""

from hisanta.hisanta.contracts._family_impl import *  # noqa: F401,F403
from hisanta.hisanta.contracts import _family_impl as _impl

__all__ = list(_impl.__all__)

"""household_legal — regime-aware document updates for the P4 autonomy stack.

Public surface. Importing this package gives a caller the entry points it needs
without having to know the sys.path convention the modules below use:

    DocumentUpdater                -> the P4 document updater itself
    get_regime_oracle()            -> a usable oracle, never an exception
    safe_consume_regime_event(...) -> consumed events, never an exception

DocumentUpdater is re-exported here because it is the deliverable of this package
and was previously reachable only as the bare module `doc_updater` — so
`from household_legal import DocumentUpdater`, the obvious spelling and the one the
acceptance criterion uses, raised ImportError while the class underneath worked
fine. Exporting the oracle helpers but not the thing they exist to feed left the
package's headline capability private by accident.

'2080' is not a valid Python identifier, so `pareto.2080.household_legal` is
unspellable. `pareto/__init__.py` registers this package as
`pareto.household_legal` so the dotted import works; the sys.path insert below
is what lets the sibling modules keep importing each other by bare name, which
is the convention already used by pareto/2080/contracts/test_contracts_smoke.py,
doc_updater.py and test_household_legal.py.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from regime_consumer import (  # noqa: E402
    NoOpRegimeOracle,
    get_regime_oracle,
    normalize_regime_event,
    safe_consume_regime_event,
    safe_subscribe,
)
from doc_updater import DocumentUpdater  # noqa: E402

__all__ = [
    "DocumentUpdater",
    "NoOpRegimeOracle",
    "get_regime_oracle",
    "normalize_regime_event",
    "safe_consume_regime_event",
    "safe_subscribe",
]

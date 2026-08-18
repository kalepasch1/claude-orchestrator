"""household_legal — regime-aware document updates for the P4 autonomy stack.

Public surface. Importing this package gives a caller the two entry points it
needs without having to know the sys.path convention the modules below use:

    get_regime_oracle()            -> a usable oracle, never an exception
    safe_consume_regime_event(...) -> consumed events, never an exception

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

__all__ = [
    "NoOpRegimeOracle",
    "get_regime_oracle",
    "normalize_regime_event",
    "safe_consume_regime_event",
    "safe_subscribe",
]

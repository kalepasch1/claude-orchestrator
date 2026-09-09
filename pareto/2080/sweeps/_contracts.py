"""Shared, guarded access to `pareto/2080/contracts/autonomy.py`.

'2080' is not a valid Python identifier, so this package cannot be reached by dotted
path. Follows the repo convention (mesh/passport.py, household_legal/regime_consumer.py):
put the contracts directory on sys.path and import by bare name, guarded, with a
duck-typed fallback so the sweeps stay usable in a stripped environment.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


def _load_contracts_module():
    """Import the autonomy contracts module, or return None."""
    try:
        contracts_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts"
        )
        if contracts_dir not in sys.path:
            sys.path.insert(0, contracts_dir)
        import autonomy  # noqa: PLC0415  (deliberately late and guarded)

        return autonomy
    except Exception as exc:  # pragma: no cover - import-environment specific
        log.warning("sweeps: contracts unavailable (%s); degrading to duck-typing", exc)
        return None


contracts = _load_contracts_module()


@dataclass
class _ShimReceipt:
    explanation: str = ""
    amount_saved: float = 0.0
    action: str = ""
    timestamp: float = 0.0
    signature: str = ""


def make_receipt(explanation: str = "", amount_saved: float = 0.0, action: str = "",
                 timestamp: float = 0.0, signature: str = "") -> Any:
    """A Receipt from contracts, or a duck-typed equivalent."""
    stamp = timestamp or time.time()
    if contracts is not None and hasattr(contracts, "Receipt"):
        return contracts.Receipt(
            explanation=explanation, amount_saved=amount_saved, action=action,
            timestamp=stamp, signature=signature,
        )
    return _ShimReceipt(
        explanation=explanation, amount_saved=amount_saved, action=action,
        timestamp=stamp, signature=signature,
    )

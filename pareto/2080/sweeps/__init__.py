"""P3v2 Daily micro-sweeps.

Continuous small-scale harvesting — round-ups, closing benefit windows, insurance
re-shopping, idle cash — plus the live "paid for itself ×N" meter computed purely
from the signed receipts those sweeps emit.

FAIL-SOFT: these run daily and unattended, so a failing sweep is recorded and skipped,
never fatal. A household whose sweeps silently stopped would have no way to know.

Nothing here moves money: a sweep reports an opportunity and mints the receipt that
records it. The meter only counts receipts whose signature verifies, so the product's
central claim about its own worth cannot be self-certified.

'2080' is not a valid Python identifier, so this package is imported by putting its
own directory on sys.path — the convention the sibling `mesh` package already follows.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from engine import (  # noqa: E402
    DEFAULT_SWEEPS,
    MIN_MATERIAL_USD,
    SWEEP_BENEFIT_WINDOW,
    SWEEP_HARVEST,
    SWEEP_IDLE_CASH,
    SWEEP_INSURANCE_RESHOP,
    SweepResult,
    SweepRun,
    benefit_window,
    harvest,
    idle_cash,
    insurance_reshop,
    run_all,
    sign_receipt,
    verify_receipt,
)
from meter import MeterReading, compute  # noqa: E402

__all__ = [
    "SweepResult", "SweepRun", "run_all", "DEFAULT_SWEEPS", "MIN_MATERIAL_USD",
    "harvest", "benefit_window", "insurance_reshop", "idle_cash",
    "SWEEP_HARVEST", "SWEEP_BENEFIT_WINDOW", "SWEEP_INSURANCE_RESHOP",
    "SWEEP_IDLE_CASH",
    "sign_receipt", "verify_receipt",
    "MeterReading", "compute",
]

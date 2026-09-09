"""Daily micro-sweeps: continuous small-scale harvesting.

Four sweeps, each looking for money the household is leaving on the table:

    harvest          round-up / spare-change harvesting into savings
    benefit_window   benefits and credits with a claim deadline approaching
    insurance_reshop re-shopping a policy whose renewal quote drifted upward
    idle_cash        cash sitting at a lower yield than an available account

FAIL-SOFT IS THE WHOLE DESIGN. These run daily and unattended, so one sweep raising
on a malformed account must not stop the other three — a household that silently
stopped being swept would never know. Every sweep is run inside `run_all`'s guard, a
failing sweep is recorded as `ok=False` with its error, and the run continues.

Every sweep that saves money emits a SIGNED savings Receipt. Sweeps that find nothing
emit no receipt at all: a zero-value receipt would dilute the `meter`'s "paid for
itself ×N" with events that paid for nothing.

Nothing here moves money. A sweep reports an opportunity and mints the receipt that
records it; acting on one is the caller's decision, behind the caller's own gate.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from _contracts import make_receipt

#: Signing key for savings receipts. A real deployment injects a per-household secret;
#: the default is a fixed, obviously-not-secret string so tests are deterministic and
#: an unconfigured deployment produces verifiable-but-clearly-unsigned receipts rather
#: than silently unsigned ones.
DEFAULT_SIGNING_KEY = b"pareto-2080-sweeps-unconfigured"

SWEEP_HARVEST = "harvest"
SWEEP_BENEFIT_WINDOW = "benefit_window"
SWEEP_INSURANCE_RESHOP = "insurance_reshop"
SWEEP_IDLE_CASH = "idle_cash"

#: Below this, an "opportunity" costs more attention than it returns. A daily sweep
#: that reports every $0.03 of drift trains the household to ignore the digest.
MIN_MATERIAL_USD = 1.00


def sign_receipt(receipt: Any, key: bytes = DEFAULT_SIGNING_KEY) -> str:
    """A deterministic HMAC over the receipt's meaningful fields."""
    payload = "|".join([
        str(getattr(receipt, "action", "")),
        str(getattr(receipt, "explanation", "")),
        f"{float(getattr(receipt, 'amount_saved', 0.0)):.2f}",
        f"{float(getattr(receipt, 'timestamp', 0.0)):.6f}",
    ]).encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def verify_receipt(receipt: Any, key: bytes = DEFAULT_SIGNING_KEY) -> bool:
    """True when the receipt's signature matches its contents.

    Constant-time compare: the meter multiplies these into a headline number, so a
    forgeable receipt is a forgeable claim about how much the product is worth.
    """
    claimed = str(getattr(receipt, "signature", "") or "")
    if not claimed:
        return False
    return hmac.compare_digest(claimed, sign_receipt(receipt, key=key))


@dataclass
class SweepResult:
    """What one sweep found."""
    name: str = ""
    ok: bool = True
    saved_usd: float = 0.0
    detail: str = ""
    receipt: Any = None
    error: str = ""

    def __bool__(self) -> bool:
        return bool(self.ok and self.saved_usd > 0)


def _num(value: Any, default: float = 0.0) -> float:
    """A finite float, or `default`. Never raises — this is the fail-soft boundary."""
    if isinstance(value, bool):
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out


def _emit(name: str, saved: float, detail: str, key: bytes) -> SweepResult:
    """Build a result, minting a signed receipt only when money was actually found."""
    saved = round(saved, 2)
    result = SweepResult(name=name, ok=True, saved_usd=saved, detail=detail)
    if saved >= MIN_MATERIAL_USD:
        receipt = make_receipt(explanation=detail, amount_saved=saved,
                               action=f"sweep:{name}")
        receipt.signature = sign_receipt(receipt, key=key)
        result.receipt = receipt
    return result


def harvest(account: Any, key: bytes = DEFAULT_SIGNING_KEY) -> SweepResult:
    """Round-up harvesting: the spare change on each transaction."""
    txns = (account or {}).get("transactions") or []
    total = 0.0
    for txn in txns:
        amount = _num(txn.get("amount") if isinstance(txn, dict) else txn)
        if amount <= 0:
            continue
        roundup = round((-amount) % 1.0, 2)
        if roundup > 0:
            total += roundup
    return _emit(SWEEP_HARVEST, total,
                 f"Rounded up {len(txns)} transaction(s) into savings.", key)


def benefit_window(benefits: Any, days_remaining_key: str = "days_remaining",
                   key: bytes = DEFAULT_SIGNING_KEY) -> SweepResult:
    """Unclaimed benefits or credits whose claim window is closing."""
    claimable = []
    total = 0.0
    for benefit in (benefits or []):
        if not isinstance(benefit, dict) or benefit.get("claimed"):
            continue
        days = _num(benefit.get(days_remaining_key), default=-1.0)
        value = _num(benefit.get("value_usd"))
        if 0 <= days <= 30 and value > 0:
            claimable.append(benefit.get("name", "a benefit"))
            total += value
    detail = ("No benefit windows closing." if not claimable else
              f"{len(claimable)} benefit window(s) closing within 30 days: "
              f"{', '.join(claimable[:5])}.")
    return _emit(SWEEP_BENEFIT_WINDOW, total, detail, key)


def insurance_reshop(policies: Any, key: bytes = DEFAULT_SIGNING_KEY) -> SweepResult:
    """Policies whose renewal quote exceeds the best available quote."""
    total = 0.0
    reshopped = []
    for policy in (policies or []):
        if not isinstance(policy, dict):
            continue
        current = _num(policy.get("renewal_usd"))
        best = _num(policy.get("best_quote_usd"))
        if current > 0 and 0 < best < current:
            total += current - best
            reshopped.append(policy.get("name", "a policy"))
    detail = ("No policy is above its best available quote." if not reshopped else
              f"{len(reshopped)} policy(ies) above market: {', '.join(reshopped[:5])}.")
    return _emit(SWEEP_INSURANCE_RESHOP, total, detail, key)


def idle_cash(accounts: Any, key: bytes = DEFAULT_SIGNING_KEY) -> SweepResult:
    """Cash earning less than an available account would pay, over one year."""
    total = 0.0
    moved = []
    for account in (accounts or []):
        if not isinstance(account, dict):
            continue
        balance = _num(account.get("balance_usd"))
        current = _num(account.get("apy"))
        available = _num(account.get("best_apy"))
        if balance > 0 and available > current:
            total += balance * (available - current)
            moved.append(account.get("name", "an account"))
    detail = ("No idle cash below market yield." if not moved else
              f"{len(moved)} account(s) below market yield: {', '.join(moved[:5])}.")
    return _emit(SWEEP_IDLE_CASH, total, detail, key)


#: The default daily battery. Each entry pulls its own slice out of the household dict,
#: so a household missing a key simply yields a zero-value sweep rather than a crash.
DEFAULT_SWEEPS: Dict[str, Callable[[Any, bytes], SweepResult]] = {
    SWEEP_HARVEST: lambda h, k: harvest(h.get("account") or {}, key=k),
    SWEEP_BENEFIT_WINDOW: lambda h, k: benefit_window(h.get("benefits") or [], key=k),
    SWEEP_INSURANCE_RESHOP: lambda h, k: insurance_reshop(h.get("policies") or [], key=k),
    SWEEP_IDLE_CASH: lambda h, k: idle_cash(h.get("accounts") or [], key=k),
}


@dataclass
class SweepRun:
    """One day's battery of sweeps."""
    results: List[SweepResult] = field(default_factory=list)
    receipts: List[Any] = field(default_factory=list)
    total_saved: float = 0.0
    failed: List[str] = field(default_factory=list)


def run_all(household: Any, sweeps: Optional[Dict[str, Callable]] = None,
            key: bytes = DEFAULT_SIGNING_KEY) -> SweepRun:
    """Run the daily battery. A failing sweep is skipped, never fatal.

    The guard is here rather than inside each sweep so a THIRD-PARTY sweep registered
    into `sweeps` gets the same containment as the built-ins — the fail-soft promise
    belongs to the runner, not to the good behaviour of every callable handed to it.
    """
    run = SweepRun()
    battery = sweeps if sweeps is not None else DEFAULT_SWEEPS
    context = household if isinstance(household, dict) else {}
    for name, fn in (battery or {}).items():
        try:
            result = fn(context, key)
        except Exception as exc:  # noqa: BLE001 - fail soft, by contract
            run.results.append(SweepResult(name=name, ok=False,
                                           error=f"{type(exc).__name__}: {exc}"))
            run.failed.append(name)
            continue
        if not isinstance(result, SweepResult):
            run.results.append(SweepResult(name=name, ok=False,
                                           error="sweep did not return a SweepResult"))
            run.failed.append(name)
            continue
        run.results.append(result)
        if result.receipt is not None:
            run.receipts.append(result.receipt)
            run.total_saved += result.saved_usd
    run.total_saved = round(run.total_saved, 2)
    return run

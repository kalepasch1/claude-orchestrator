"""Build the receipt shown to an operator after an autonomous action.

A receipt is what makes an autonomous action reversible in practice rather than
in principle. Two fields carry that weight and both are mandatory here:

  * `undo` — how to reverse it, and whether reversal is still possible AT ALL.
    An action presented as undoable that is not is worse than one honestly
    labelled irreversible, because the operator relaxes on the strength of it.
  * `counterfactual_cost` — what NOT acting would have cost. Without it the
    operator sees only the price of the action and never the price of doing
    nothing, so every autonomous action looks like pure expense.

Pure: no I/O, no clock reads (`now` is injected), no side effects. Total: bad
input yields a receipt that says so, never an exception — a receipt that fails
to render is an action with no audit trail.
"""
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

# Actions that cannot be reversed once taken, whatever the caller claims.
IRREVERSIBLE_ACTIONS = frozenset({
    "money_moved", "email_sent", "external_api_write", "deploy_promoted",
    "record_deleted",
})

UNKNOWN = "unknown"


@dataclass
class UndoPlan:
    """How to reverse an action. `available = False` is a first-class answer."""
    available: bool
    method: str = ""
    reason: str = ""


@dataclass
class Receipt:
    action: str
    explanation: str
    cost_usd: float
    counterfactual_cost_usd: float
    undo: UndoPlan
    actor: str = UNKNOWN
    at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def net_benefit_usd(self) -> float:
        """What acting saved versus not acting. Negative means it cost more."""
        return round(self.counterfactual_cost_usd - self.cost_usd, 6)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["net_benefit_usd"] = self.net_benefit_usd
        return data


def _num(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return default if result != result else result       # NaN guard


def _text(value: Any) -> str:
    return "" if value is None else f"{value}".strip()


def build_undo_plan(action: str, method: Any = None,
                    available: Optional[bool] = None) -> UndoPlan:
    """Decide whether an action can be undone. Fails CLOSED to unavailable.

    An irreversible action can never be marked undoable, regardless of what the
    caller passes — the allowlist wins over the argument, because the cost of
    wrongly promising reversibility is borne by the operator who trusted it.
    """
    name = _text(action).lower()
    if name in IRREVERSIBLE_ACTIONS:
        return UndoPlan(available=False, method="",
                        reason=f"'{name}' is irreversible once taken")

    resolved = _text(method)
    if available is False or (available is None and not resolved):
        return UndoPlan(available=False, method="",
                        reason="no undo method supplied")
    if not resolved:
        return UndoPlan(available=False, method="",
                        reason="undo claimed available but no method given")
    return UndoPlan(available=True, method=resolved, reason="")


def build_receipt(
    action: Any,
    explanation: Any = "",
    cost_usd: Any = 0.0,
    counterfactual_cost_usd: Any = None,
    undo_method: Any = None,
    undo_available: Optional[bool] = None,
    actor: Any = UNKNOWN,
    now: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Receipt:
    """Build a Receipt. Never raises.

    A missing counterfactual is recorded as 0.0 AND said so in the explanation,
    rather than quietly omitted: an unstated counterfactual reads as "acting
    saved nothing", which is a claim, not an absence.
    """
    name = _text(action) or UNKNOWN
    reason = _text(explanation)
    cost = max(0.0, _num(cost_usd))

    if counterfactual_cost_usd is None:
        counterfactual = 0.0
        note = "counterfactual cost not supplied; recorded as 0.00, not estimated"
        reason = f"{reason} ({note})" if reason else note
    else:
        counterfactual = max(0.0, _num(counterfactual_cost_usd))

    return Receipt(
        action=name,
        explanation=reason or "no explanation supplied",
        cost_usd=round(cost, 6),
        counterfactual_cost_usd=round(counterfactual, 6),
        undo=build_undo_plan(name, undo_method, undo_available),
        actor=_text(actor) or UNKNOWN,
        at=_text(now) or None,
        metadata=dict(metadata or {}),
    )


def build_receipt_dict(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Receipt as a plain dict, ready for the ReceiptCard component."""
    return build_receipt(*args, **kwargs).to_dict()

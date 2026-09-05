"""Package every financial action with its documentation as it happens.

N3 "Audit-proof life": an audit defense is not something you assemble in April
under duress. Every financial action, at the moment it happens, is packaged with
whatever documentation exists for it and appended to a STANDING audit-defense
file. When a notice arrives, the bundle is already there.

WHY THE SHAPE IS SPLIT IN TWO
-----------------------------
`Receipt` and `AuditBundle` are owned by pareto/2080/contracts/autonomy.py and
are consumed here as-is; this module defines no substitute for either. The
contract is deliberately narrow. A Receipt carries one plain-language line, one
amount, one action string and a signature. An AuditBundle carries receipts and
a period. Neither has anywhere to put the per-action documentation inventory or
the gap markers that are this module's entire purpose.

So the richer record lives BESIDE the contract rather than inside it:
`ActionEntry` holds the artifacts and the gaps, and `StandingFile` holds those
entries next to the contract `AuditBundle` they summarise. Two alternatives were
rejected. Widening the contract with an `entries` field changes a type shared
with every other consumer to suit one of them. Declaring a local class also
called `AuditBundle` is what an earlier draft of this module did, and the result
was a package that never touched the shared contract at all while looking like
it did.

The load-bearing property is FAIL-SOFT. A bundler that raises on a missing
receipt is a bundler nobody leaves running for a year, and a bundler nobody
leaves running produces no defense at all. A missing document records a gap
marker, malformed input yields an empty bundle, and nothing here raises.
"""
import copy
import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

#: Prefix on every recorded gap. A gap is DATA, not an error: an audit defense
#: that hides its own holes is worse than one that names them.
GAP = "GAP"

_NO_GAPS_NOTE = "No documentation gaps recorded."


def _load_contracts_module():
    """Import `pareto/2080/contracts/autonomy.py`, or return None.

    '2080' is not a valid Python identifier, so this package cannot be reached
    by dotted path. The repo convention (pareto/2080/contracts/test_contracts_smoke.py,
    household_legal/regime_consumer.py, household_legal/doc_updater.py) is to
    put the directory on sys.path and import by bare name; this follows it.
    """
    contracts_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts"
    )
    if contracts_dir not in sys.path:
        sys.path.insert(0, contracts_dir)
    import autonomy  # noqa: PLC0415  (deliberately late; see docstring)

    return autonomy


# Unguarded, unlike regime_consumer's fail-soft oracle lookup, and deliberately
# so: there is no local substitute to degrade to. Swallowing an ImportError here
# would only defer the same failure to an AttributeError three frames deeper.
_CONTRACTS = _load_contracts_module()

Receipt = _CONTRACTS.Receipt
AuditBundle = _CONTRACTS.AuditBundle
# Resolved here rather than in binder.py so the package has ONE place that
# reaches for the contracts module; binder.py imports the type from here.
ComplianceBinder = _CONTRACTS.ComplianceBinder


@dataclass
class ActionEntry:
    """One packaged financial action: its numbers, its documents, its holes.

    The contract `Receipt` has no artifacts, gaps or action_id field, so this is
    where the per-action documentation inventory lives.
    """
    action_id: str = ""
    kind: str = "unknown"
    amount: Optional[float] = None
    date: str = ""
    description: str = ""
    artifacts: List[str] = field(default_factory=list)
    gaps: List[str] = field(default_factory=list)
    packaged_at: float = field(default_factory=time.time)

    @property
    def complete(self) -> bool:
        """No gap markers. Not "has documents" — some kinds need none."""
        return not self.gaps

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["complete"] = self.complete
        return data


def _new_audit_bundle(year: Optional[int]) -> Any:
    """Build the contract `AuditBundle` for one tax year.

    The contract has no `year` field, so the year is expressed the way the
    contract does express time: as the period it covers.
    """
    label = str(year) if year is not None else "unspecified"
    return AuditBundle(
        bundle_id="audit-defense-%s" % label,
        receipts=[],
        period_start="%d-01-01" % year if year is not None else "",
        period_end="%d-12-31" % year if year is not None else "",
        notes=_NO_GAPS_NOTE,
    )


def _gap_note(entries: List[ActionEntry]) -> str:
    """Summarise the year's holes for the contract's one free-text field."""
    gapped = [entry for entry in entries if entry.gaps]
    if not gapped:
        return _NO_GAPS_NOTE
    named = "; ".join(
        "%s -> %s" % (entry.action_id, ", ".join(entry.gaps)) for entry in gapped
    )
    return "%d of %d action(s) missing documentation: %s" % (
        len(gapped), len(entries), named,
    )


def _signature(entry: ActionEntry) -> str:
    """Content hash of the packaged action.

    `Receipt.signature` is a plain string, not a crypto object, so the honest
    thing to put in it is something that is actually verifiable later: a digest
    over the entry, which detects a bundle edited after the fact.
    """
    payload = json.dumps(entry.to_dict(), sort_keys=True, default=str)
    return "sha256:%s" % hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _receipt_for(entry: ActionEntry) -> Any:
    """Build the contract `Receipt` paired with one packaged action.

    The contract offers one numeric slot and one action slot, so the action's
    signed amount goes in `amount_saved` (negative for a cost or deduction) and
    `kind:action_id` goes in `action`, which is what keeps a receipt traceable
    back to its entry. `explanation` is the plain-language line, and it is where
    the gaps get named because the contract has no field for them.
    """
    documented = ", ".join(entry.artifacts) if entry.artifacts else "no documents attached"
    explanation = "%s %s (%s): %s" % (
        entry.kind, entry.action_id, entry.date or "undated", documented,
    )
    if entry.gaps:
        explanation += " — missing %s" % ", ".join(entry.gaps)
    return Receipt(
        explanation=explanation,
        amount_saved=as_amount(entry.amount),
        action="%s:%s" % (entry.kind, entry.action_id),
        timestamp=entry.packaged_at,
        signature=_signature(entry),
    )


def as_amount(value: Any) -> float:
    """Money as a float, rounded to cents. Anything unusable is 0.0."""
    try:
        return round(float(value or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


def as_dict(obj: Any) -> Dict[str, Any]:
    """Best-effort dict view of an entry or receipt, whatever shape it arrives in."""
    if isinstance(obj, dict):
        return dict(obj)
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        try:
            return dict(to_dict())
        except Exception:                                        # fail-soft
            pass
    try:
        return dict(asdict(obj))
    except Exception:                                            # fail-soft
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}


@dataclass
class StandingFile:
    """The standing audit-defense file: append-only, one entry per action.

    Carries the contract `AuditBundle` at `.bundle` alongside the `ActionEntry`
    records the contract has no room for. `entries[i]` and `bundle.receipts[i]`
    describe the same action — that pairing is what lets a consumer who only
    speaks `AuditBundle` still see every action, and it is maintained by every
    mutating function in this module.
    """
    year: Optional[int] = None
    entries: List[ActionEntry] = field(default_factory=list)
    bundle: Optional[Any] = None

    def __post_init__(self) -> None:
        if self.bundle is None:
            self.bundle = _new_audit_bundle(self.year)

    @property
    def receipts(self) -> List[Any]:
        """The contract bundle's own receipt list, not a copy of it."""
        return self.bundle.receipts

    @property
    def gaps(self) -> List[ActionEntry]:
        return [entry for entry in self.entries if entry.gaps]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "year": self.year,
            "bundle_id": self.bundle.bundle_id,
            "period_start": self.bundle.period_start,
            "period_end": self.bundle.period_end,
            "notes": self.bundle.notes,
            "entries": [entry.to_dict() for entry in self.entries],
            "receipts": [as_dict(receipt) for receipt in self.receipts],
            "gap_count": len(self.gaps),
        }


def required_docs(kind: str) -> List[str]:
    """Documents an action of this kind is expected to carry.

    Deliberately conservative: only the documents whose absence a reviewer would
    actually ask about. Over-declaring turns every bundle into a wall of noise
    and trains the owner to ignore the gap list.
    """
    kind = str(kind or "").lower()
    if kind in ("donation", "charity"):
        return ["acknowledgment_letter"]
    if kind in ("expense", "business_expense", "deduction"):
        return ["receipt"]
    if kind in ("income", "wage", "dividend", "interest"):
        return ["statement"]
    if kind in ("trade", "sale", "disposal"):
        return ["confirmation", "cost_basis"]
    return []


def _artifacts_of(action: Dict[str, Any]) -> List[str]:
    docs = action.get("docs") or action.get("documents") or []
    if isinstance(docs, (str, bytes)):
        docs = [docs]
    try:
        return [str(doc) for doc in docs if doc]
    except TypeError:                                            # fail-soft
        return []


def package_action(standing: StandingFile, action: Any) -> ActionEntry:
    """Package one financial action with its documentation into `standing`.

    Returns the `ActionEntry`; the contract `Receipt` built alongside it is
    appended to `standing.bundle.receipts` at the same index. NEVER raises:
    anything malformed becomes a gap marker on an entry that is still recorded,
    because dropping the action entirely is what makes a bundle lie.
    """
    try:
        action = dict(action or {})
    except (TypeError, ValueError):                              # fail-soft
        action = {}

    action_id = str(
        action.get("id") or action.get("action_id")
        or "action-%d" % (len(standing.entries) + 1)
    )
    kind = str(action.get("kind") or "unknown")
    artifacts = _artifacts_of(action)

    gaps = [name for name in required_docs(kind)
            if not any(name in artifact for artifact in artifacts)]
    if not artifacts and not gaps and kind == "unknown":
        gaps = ["no_documentation"]
    gaps = [str(gap) if str(gap).startswith(GAP) else "%s:%s" % (GAP, gap)
            for gap in gaps]

    entry = ActionEntry(
        action_id=action_id,
        kind=kind,
        amount=action.get("amount"),
        date=str(action.get("date") or ""),
        description=str(action.get("description") or ""),
        artifacts=artifacts,
        gaps=gaps,
    )
    standing.entries.append(entry)
    standing.bundle.receipts.append(_receipt_for(entry))
    standing.bundle.notes = _gap_note(standing.entries)
    return entry


def bundle_actions(actions: Any, year: Optional[int] = None) -> StandingFile:
    """Package a whole sequence of actions into one standing file.

    A bad or empty action set yields an empty standing file rather than an
    exception, so a caller replaying a year never has to guard the call.
    """
    standing = StandingFile(year=year)
    try:
        pending = list(actions or [])
    except TypeError:                                            # fail-soft
        log.warning("bundler: actions is not iterable (%r); empty bundle", type(actions))
        pending = []
    for action in pending:
        package_action(standing, action)
    return standing


def write_bundle(standing: StandingFile, path: str) -> bool:
    """Persist the standing audit-defense file as JSON. Returns success.

    Reported rather than raised: a failed write must not take down the caller
    that was in the middle of recording a real financial action.
    """
    try:
        payload = standing.to_dict()
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w") as handle:
            json.dump(payload, handle, indent=2, default=str, sort_keys=True)
        return True
    except Exception as exc:                                     # fail-soft
        log.warning("bundler: could not write standing file to %s: %s", path, exc)
        return False


def merge_bundle(base: StandingFile, incoming: StandingFile) -> StandingFile:
    """Append `incoming`'s actions onto `base` without mutating `incoming`.

    Deep-copied because the two standing files outlive the merge; sharing an
    entry would let a later append to one silently rewrite the other's history,
    which for an append-only audit file is the one thing that must not happen.
    """
    try:
        for entry in list(incoming.entries):
            base.entries.append(copy.deepcopy(entry))
        for receipt in list(incoming.receipts):
            base.bundle.receipts.append(copy.deepcopy(receipt))
        base.bundle.notes = _gap_note(base.entries)
    except AttributeError as exc:                                # fail-soft
        log.warning("bundler: cannot merge %r: %s", type(incoming), exc)
    return base

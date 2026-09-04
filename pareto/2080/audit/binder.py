"""Assemble a drafted return plus an evidence binder at tax season.

The bundler runs all year and produces a standing audit-defense file. This
module is what happens in April: it reads that file once and emits

  * a DRAFTED RETURN — actions rolled into line items with totals, so every
    number on the return is traceable back to the action ids that produced it,
    and
  * an EVIDENCE BINDER — every supporting artifact indexed by line item, with
    the gaps named rather than quietly omitted.

WHERE THE CONTRACT ENDS
-----------------------
`ComplianceBinder` from pareto/2080/contracts/autonomy.py carries a binder id, a
jurisdiction, a list of `AuditBundle`s and a `status`. It has room for neither
the drafted return nor the evidence index, so those hang off the local
`TaxSeasonBinder` and the contract instance inside it holds exactly what it is
for. Completeness is reported through the contract's `status` field — 'complete'
or 'draft' — rather than a boolean of our own.

The load-bearing property: completeness is a REPORTED PROPERTY, never a
precondition for assembly. A year with holes still assembles a binder and names
its holes, because refusing to assemble would leave the owner with nothing at
all to hand the auditor — which is strictly worse than an honest partial file.
Nothing in this module raises on bad input.
"""
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# '2080' is not a valid Python identifier, so the sibling module cannot be
# reached by dotted path. Same convention as household_legal/doc_updater.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bundler import (  # noqa: E402
    GAP,
    ComplianceBinder,
    as_amount,
    as_dict,
)

STATUS_COMPLETE = "complete"
STATUS_DRAFT = "draft"


# How an action kind lands on the drafted return. Data rather than branching, so
# adding a kind is a change to one table.
_LINE_ITEMS = {
    "income": "income",
    "wage": "income",
    "dividend": "income",
    "interest": "income",
    "trade": "capital",
    "sale": "capital",
    "disposal": "capital",
    "expense": "deduction",
    "business_expense": "deduction",
    "deduction": "deduction",
    "donation": "deduction",
    "charity": "deduction",
}


def line_item_for(kind: Any) -> str:
    """Which line of the return an action of this kind rolls into."""
    return _LINE_ITEMS.get(str(kind or "").lower(), "other")


def _entries_of(standing: Any) -> List[Dict[str, Any]]:
    """Dict view of the standing file's entries. Never raises."""
    rows = []
    for entry in list(getattr(standing, "entries", None) or []):
        try:
            rows.append(as_dict(entry))
        except Exception:                                        # fail-soft
            continue
    return rows


def draft_return(standing: Any, year: Optional[int] = None) -> Dict[str, Any]:
    """Roll the standing file's entries into a drafted return. Never raises.

    Every line item keeps the action ids that produced its total, so a number on
    the return can always be walked back to the actions behind it.
    """
    entries = _entries_of(standing)
    if year is None:
        year = getattr(standing, "year", None)

    lines: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        name = line_item_for(entry.get("kind"))
        line = lines.setdefault(
            name, {"line_item": name, "total": 0.0, "action_ids": []}
        )
        line["total"] = round(line["total"] + as_amount(entry.get("amount")), 2)
        line["action_ids"].append(entry.get("action_id"))

    income = lines.get("income", {}).get("total", 0.0)
    capital = lines.get("capital", {}).get("total", 0.0)
    deductions = lines.get("deduction", {}).get("total", 0.0)

    return {
        "year": year,
        "line_items": [lines[name] for name in sorted(lines)],
        "totals": {
            "income": round(income, 2),
            "capital": round(capital, 2),
            "deductions": round(deductions, 2),
            "taxable": round(income + capital - deductions, 2),
        },
        "action_count": len(entries),
        "drafted": True,
    }


def collect_evidence(standing: Any) -> Dict[str, Any]:
    """Index every artifact by line item, naming the gaps. Never raises."""
    by_line: Dict[str, List[Dict[str, Any]]] = {}
    gaps: List[Dict[str, Any]] = []
    artifact_count = 0

    for entry in _entries_of(standing):
        name = line_item_for(entry.get("kind"))
        artifacts = list(entry.get("artifacts") or [])
        entry_gaps = list(entry.get("gaps") or [])
        artifact_count += len(artifacts)
        by_line.setdefault(name, []).append({
            "action_id": entry.get("action_id"),
            "kind": entry.get("kind"),
            "date": entry.get("date"),
            "amount": entry.get("amount"),
            "artifacts": artifacts,
            "gaps": entry_gaps,
        })
        for gap in entry_gaps:
            gaps.append({"action_id": entry.get("action_id"),
                         "kind": entry.get("kind"), "gap": gap})

    return {
        "by_line_item": {name: by_line[name] for name in sorted(by_line)},
        "artifact_count": artifact_count,
        "gaps": gaps,
        "gap_count": len(gaps),
    }


@dataclass
class TaxSeasonBinder:
    """What April produces: the drafted return, the evidence, and the contract.

    `compliance_binder` is the shared `ComplianceBinder`; the drafted return and
    the evidence index live here because the contract has no field for either.
    `status` and `complete` both read through to the contract, so there is one
    source of truth for whether the year is defensible.
    """
    year: Optional[int] = None
    drafted_return: Dict[str, Any] = field(default_factory=dict)
    evidence: Dict[str, Any] = field(default_factory=dict)
    compliance_binder: Optional[Any] = None
    summary: str = ""

    @property
    def status(self) -> str:
        return self.compliance_binder.status

    @property
    def complete(self) -> bool:
        return self.status == STATUS_COMPLETE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "year": self.year,
            "binder_id": self.compliance_binder.binder_id,
            "jurisdiction": self.compliance_binder.jurisdiction,
            "status": self.status,
            "drafted_return": self.drafted_return,
            "evidence": self.evidence,
            "summary": self.summary,
        }


def _summarize(drafted: Dict[str, Any], evidence: Dict[str, Any], complete: bool) -> str:
    """One plain-language line an owner can read without decoding the schema."""
    head = "Binder for %s: %d actions, %d supporting documents, taxable %s." % (
        drafted.get("year") if drafted.get("year") is not None else "unspecified year",
        drafted.get("action_count", 0),
        evidence.get("artifact_count", 0),
        drafted.get("totals", {}).get("taxable", 0.0),
    )
    if complete:
        return head + " Complete — every action carries its documentation."
    return head + " Incomplete — %d %s marker(s) to resolve." % (
        evidence.get("gap_count", 0), GAP,
    )


def assemble_binder(
    standing: Any,
    year: Optional[int] = None,
    jurisdiction: str = "US",
) -> TaxSeasonBinder:
    """Assemble the tax-season binder: drafted return plus evidence.

    Complete means a drafted return over at least one action with no unresolved
    gap markers. An incomplete year still assembles — see the module docstring.
    """
    drafted = draft_return(standing, year=year)
    evidence = collect_evidence(standing)
    complete = bool(drafted.get("action_count")) and evidence.get("gap_count") == 0

    audit_bundle = getattr(standing, "bundle", None)
    contract = ComplianceBinder(
        binder_id="binder-%s" % (drafted.get("year") if drafted.get("year") is not None
                                 else "unspecified"),
        jurisdiction=jurisdiction,
        bundles=[audit_bundle] if audit_bundle is not None else [],
        status=STATUS_COMPLETE if complete else STATUS_DRAFT,
    )
    return TaxSeasonBinder(
        year=drafted.get("year"),
        drafted_return=drafted,
        evidence=evidence,
        compliance_binder=contract,
        summary=_summarize(drafted, evidence, complete),
    )

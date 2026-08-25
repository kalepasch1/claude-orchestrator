"""audit — N3 "Audit-proof life" for the P4 autonomy stack.

Every financial action is packaged with its documentation as it happens
(`bundler`), so that at tax season a drafted return and an evidence binder can
be assembled from work already done (`binder`):

    standing = bundle_actions(actions_for_the_year, year=2080)
    binder = assemble_binder(standing)
    binder.complete   # True when no gap markers remain

The contract types — `Receipt`, `AuditBundle`, `ComplianceBinder` — are the ones
from pareto/2080/contracts/autonomy.py, re-exported here so a caller does not
have to know the sys.path convention the modules below use. `StandingFile` and
`TaxSeasonBinder` are this package's own; they carry the per-action documentation
and the drafted return, which the contracts have no fields for.

'2080' is not a valid Python identifier, so `pareto.2080.audit` is unspellable.
The sys.path insert below is what lets the sibling modules keep importing each
other by bare name, which is the convention already used by
pareto/2080/contracts/test_contracts_smoke.py and household_legal/doc_updater.py.

Fail-soft is the rule, not a special case: bad or empty input yields an empty
standing file, and a missing document records a gap marker. Nothing here raises.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from bundler import (  # noqa: E402
    GAP,
    ActionEntry,
    AuditBundle,
    Receipt,
    StandingFile,
    bundle_actions,
    merge_bundle,
    package_action,
    required_docs,
    write_bundle,
)
from binder import (  # noqa: E402
    STATUS_COMPLETE,
    STATUS_DRAFT,
    ComplianceBinder,
    TaxSeasonBinder,
    assemble_binder,
    collect_evidence,
    draft_return,
    line_item_for,
)

__all__ = [
    "GAP",
    "STATUS_COMPLETE",
    "STATUS_DRAFT",
    "ActionEntry",
    "AuditBundle",
    "ComplianceBinder",
    "Receipt",
    "StandingFile",
    "TaxSeasonBinder",
    "assemble_binder",
    "bundle_actions",
    "collect_evidence",
    "draft_return",
    "line_item_for",
    "merge_bundle",
    "package_action",
    "required_docs",
    "write_bundle",
]

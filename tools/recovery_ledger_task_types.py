"""The task_type spellings the recovery ledger actually lives under.

The recovery contract asks every reconcile pass for "durable queue provenance
for every item". That provenance exists -- and it is split across at least six
different `coordination_tasks.task_type` values written by different tools, none
of which can see the others:

    chatgpt_local_reconcile_ledger   164570   tools/publish_recovery_ledger.py
    recovery_ledger                  112588   tools/recovery_ledger_publish.py
    recovery-ledger                    3591   (historical)
    codex_recovery_ledger                 4   runner/codex_reconciler.py
    reconcile-ledger                     11   (historical)
    recovery-ledger-summary               2   (historical)

Two of those writers are modules whose names are anagrams of each other --
`publish_recovery_ledger.py` and `recovery_ledger_publish.py` -- publishing the
same ledger under different types.

The consequence is not cosmetic. Each publisher's idempotency check reads only
its OWN task_type, so re-publishing a fingerprint through the other tool writes
a second copy of every item and neither notices. And a query for "what happened
to this evidence item" under-reports unless the caller happens to know all six
spellings, which makes the provenance unqueryable in exactly the way the
contract was written to prevent.

This module does NOT rename anything. Renaming would create a seventh
population and break every existing consumer; the defect is on the read side.
Writers keep their historical type, readers span all of them.
"""

from __future__ import annotations

# What tools/publish_recovery_ledger.py writes. Kept as-is: it holds the
# largest population, and rewriting 164k rows to make a name nicer is not worth
# the migration.
PUBLISH_TASK_TYPE = "chatgpt_local_reconcile_ledger"

# What tools/recovery_ledger_publish.py writes.
LEDGER_TASK_TYPE = "recovery_ledger"

# Every spelling a recovery-ledger record has ever been written under, ordered
# by population. Add to this list rather than renaming rows.
ALL_LEDGER_TASK_TYPES = (
    PUBLISH_TASK_TYPE,
    LEDGER_TASK_TYPE,
    "recovery-ledger",
    "codex_recovery_ledger",
    "reconcile-ledger",
    "recovery-ledger-summary",
)


def dedupe_filter() -> str:
    """A PostgREST `in.(...)` filter covering every ledger spelling.

    Use for any read that asks "has this item already been recorded?" -- a
    dedupe that only sees its own tool's rows is not a dedupe.
    """
    return "in.(%s)" % ",".join(ALL_LEDGER_TASK_TYPES)

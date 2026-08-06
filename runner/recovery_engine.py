"""
recovery_engine.py — intent-preserving recovery, as a standing mechanism.

A branch cut in July may patch a function that has since been rewritten.
Force-applying that diff either conflicts or — worse — silently reverts newer
work, which is exactly the auto-resolve defect already found (6 of 59 merges
discarded branch-original edits). So recovery here is INTENT-FIRST: the diff is
treated as EVIDENCE of intent, never as the intent itself.

Every item is classified into exactly one of four states, each with the evidence
that justified it, so an operator can ask "what happened to improvement X" and
get a straight answer:

  ALREADY_SATISFIED    current master already achieves the intent — close with
                       the commit/lines that satisfy it, do NOT re-apply.
                       Expected to be common; closing cleanly is a success.
  UNCHANGED_CONTEXT    the touched code has not moved — rebase and merge through
                       the normal gates.
  CONTEXT_MOVED        the touched code has changed — RE-IMPLEMENT the intent
                       against current master. Do not port the diff.
  SUPERSEDED_OR_UNSAFE quarantined, superseded, or in conflict with a later
                       deliberate decision — route to the operator with the
                       conflict named. Never silently reverse a prior decision.

Anything that cannot be classified WITH evidence goes to the operator.
Ambiguity is never resolved by guessing.

The classifier and the measurement helpers are pure: every fact about git and
the database is injected, so the decision logic is testable without either.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

# Classifications
ALREADY_SATISFIED = "ALREADY_SATISFIED"
UNCHANGED_CONTEXT = "UNCHANGED_CONTEXT"
CONTEXT_MOVED = "CONTEXT_MOVED"
SUPERSEDED_OR_UNSAFE = "SUPERSEDED_OR_UNSAFE"
NEEDS_OPERATOR = "NEEDS_OPERATOR"

CLASSIFICATIONS = (
    ALREADY_SATISFIED,
    UNCHANGED_CONTEXT,
    CONTEXT_MOVED,
    SUPERSEDED_OR_UNSAFE,
    NEEDS_OPERATOR,
)

DEFAULT_BATCH = int(os.environ.get("ORCH_RECOVERY_BATCH", "25"))
DEFAULT_BREAKER_THRESHOLD = int(os.environ.get("ORCH_RECOVERY_BREAKER_THRESHOLD", "5"))


# ---------------------------------------------------------------------------
# Defensible line counting
# ---------------------------------------------------------------------------
# A naive `git diff --numstat` across the stranded set returns ~1.18M lines,
# which is wrong: it still counts generated and vendored files. These are the
# exclusions, kept as data so the METHOD can be published alongside the number.
EXCLUDED_DIR_PARTS = (
    "node_modules", "vendor", "dist", ".nuxt", ".next", "coverage", "__pycache__",
    ".venv", "venv", "build", "out", ".output", "generated",
)

EXCLUDED_FILENAMES = (
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock",
    "Cargo.lock", "composer.lock", "Gemfile.lock", "go.sum",
)

EXCLUDED_SUFFIXES = (
    ".min.js", ".min.css", ".map", ".snap",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".pdf",
    ".woff", ".woff2", ".ttf", ".eot", ".zip", ".gz", ".tar", ".jar",
    ".so", ".dylib", ".o", ".a", ".pyc", ".class", ".wasm",
)

GENERATED_PATH_HINTS = (
    "database.types.ts", ".generated.", "/__generated__/", "/migrations/",
)


def is_countable_source(path: str) -> bool:
    """True when a path is real source, not generated, vendored or binary.

    This is the published method behind any line-count figure: quote the number
    together with this predicate, and the figure is reproducible.
    """
    if not path:
        return False
    normalised = path.replace("\\", "/").strip()
    lowered = normalised.lower()

    if any(part in normalised.split("/") for part in EXCLUDED_DIR_PARTS):
        return False
    if normalised.rsplit("/", 1)[-1] in EXCLUDED_FILENAMES:
        return False
    if lowered.endswith(EXCLUDED_SUFFIXES):
        return False
    if any(hint in normalised for hint in GENERATED_PATH_HINTS):
        return False
    return True


def measure_real_source_lines(numstat_rows: Iterable[Sequence[Any]]) -> Dict[str, Any]:
    """Sum added+deleted lines over real source files only.

    `numstat_rows` are (added, deleted, path) triples as `git diff --numstat`
    emits them; git writes "-" for binary files, which are skipped rather than
    guessed at. Returns the figure AND the method, so the number is defensible.
    """
    counted = 0
    excluded_files = 0
    counted_files = 0
    binary_files = 0

    for row in numstat_rows:
        if not row or len(row) < 3:
            continue
        added, deleted, path = row[0], row[1], row[2]
        if not is_countable_source(str(path)):
            excluded_files += 1
            continue
        if str(added) == "-" or str(deleted) == "-":
            binary_files += 1          # git marks binaries with "-"; never guess
            continue
        counted += int(added) + int(deleted)
        counted_files += 1

    return {
        "real_source_lines": counted,
        "counted_files": counted_files,
        "excluded_files": excluded_files,
        "binary_files": binary_files,
        "method": (
            "added+deleted from git diff --numstat, excluding lockfiles, "
            "node_modules/vendor/dist/.nuxt/coverage/generated dirs, minified "
            "assets, binaries and generated types (see is_countable_source)"
        ),
    }


# ---------------------------------------------------------------------------
# Intent
# ---------------------------------------------------------------------------
_BOILERPLATE_PREFIXES = (
    "## ORCHESTRATION PIPELINE CONTRACT",
    "AGENTIC-REPAIR DIRECTIVE",
    "PATCH TEMPLATE",
    "PATCH TRANSPLANT",
    "OPERATOR_PHANTOM_RECOVERY",
)

_ACCEPTANCE_RE = re.compile(r"^\s*acceptance[^:]*:\s*(.+)$", re.I | re.M)


@dataclass
class RecoveryIntent:
    """What the change was trying to achieve, recovered from the task prompt."""
    task_id: str
    slug: str
    goal: str
    acceptance: List[str] = field(default_factory=list)

    @property
    def is_recoverable(self) -> bool:
        """False when the prompt carries no stateable goal — operator territory."""
        return bool(self.goal.strip())


def recover_intent(task: Dict[str, Any]) -> RecoveryIntent:
    """Extract the goal and acceptance criteria from the originating task.

    Pipeline-contract preamble, patch-template hex and repair directives are
    machine boilerplate wrapped around the request; they are stripped so the
    goal is the human sentence, not the envelope it arrived in.
    """
    prompt = (task or {}).get("prompt") or ""
    acceptance = [m.strip() for m in _ACCEPTANCE_RE.findall(prompt) if m.strip()]

    lines = []
    for raw in prompt.splitlines():
        line = raw.strip()
        if not line or line.startswith(("- ", "#", "```")) and len(line) < 4:
            continue
        if any(line.startswith(p) for p in _BOILERPLATE_PREFIXES):
            break
        if line.startswith("- ") and ":" in line[:30]:
            continue                      # "- source: x", "- project: y" metadata
        lines.append(line)
        if len(" ".join(lines)) > 400:
            break

    goal = " ".join(lines).strip()
    return RecoveryIntent(
        task_id=str((task or {}).get("id") or ""),
        slug=(task or {}).get("slug") or "",
        goal=goal,
        acceptance=acceptance,
    )


# ---------------------------------------------------------------------------
# World diff + classification
# ---------------------------------------------------------------------------
@dataclass
class WorldDiff:
    """Has the code this branch touched moved since the branch was cut?

    `touched_files` are the paths the branch changed. `moved_files` is the
    subset that master has since changed on its own — compare the branch's
    merge-base against current master for exactly those paths.
    """
    touched_files: List[str] = field(default_factory=list)
    moved_files: List[str] = field(default_factory=list)
    missing_files: List[str] = field(default_factory=list)

    @property
    def context_moved(self) -> bool:
        return bool(self.moved_files or self.missing_files)


@dataclass
class Classification:
    classification: str
    evidence: str
    details: Dict[str, Any] = field(default_factory=dict)


def classify_recovery_item(
    task: Dict[str, Any],
    intent: RecoveryIntent,
    world: WorldDiff,
    *,
    intent_already_satisfied: Optional[bool] = None,
    satisfied_evidence: str = "",
    conflicting_decision: str = "",
) -> Classification:
    """Classify one recoverable item, with the evidence for that call.

    `intent_already_satisfied` is injected rather than inferred: deciding that
    master already achieves an intent requires reading current code, and a guess
    there is exactly the failure mode that silently reverts newer work. None
    means "not determined", which routes to the operator rather than defaulting.
    """
    state = (task or {}).get("state") or ""

    # A later deliberate decision always wins; recovery never reverses one.
    if conflicting_decision:
        return Classification(
            SUPERSEDED_OR_UNSAFE,
            f"conflicts with a later deliberate decision: {conflicting_decision}",
            {"conflict": conflicting_decision},
        )
    if state in ("QUARANTINED", "SUPERSEDED"):
        return Classification(
            SUPERSEDED_OR_UNSAFE,
            f"originating task is {state}; not revived without an operator decision",
            {"state": state},
        )

    if not intent.is_recoverable:
        return Classification(
            NEEDS_OPERATOR,
            "no stateable goal could be recovered from the originating prompt",
            {"slug": intent.slug},
        )

    if not world.touched_files:
        return Classification(
            NEEDS_OPERATOR,
            "no touched files recorded; cannot compare intent against master",
            {"slug": intent.slug},
        )

    if intent_already_satisfied is True:
        if not satisfied_evidence:
            return Classification(
                NEEDS_OPERATOR,
                "claimed already-satisfied without evidence; refusing to close blind",
                {"slug": intent.slug},
            )
        return Classification(
            ALREADY_SATISFIED,
            f"current master already achieves the intent: {satisfied_evidence}",
            {"evidence_ref": satisfied_evidence},
        )

    if intent_already_satisfied is None:
        return Classification(
            NEEDS_OPERATOR,
            "could not determine whether master already satisfies the intent",
            {"touched_files": world.touched_files},
        )

    if world.context_moved:
        return Classification(
            CONTEXT_MOVED,
            "master changed the touched code since the branch was cut; "
            "re-implement the intent rather than porting the diff",
            {"moved_files": world.moved_files, "missing_files": world.missing_files},
        )

    return Classification(
        UNCHANGED_CONTEXT,
        "touched code is unchanged on master; rebase and merge through the normal gates",
        {"touched_files": world.touched_files},
    )


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
def build_ledger_row(
    task: Dict[str, Any],
    intent: RecoveryIntent,
    result: Classification,
    *,
    branch: str = "",
    outcome: str = "classified",
    derived_task_id: str = "",
    derived_commit: str = "",
) -> Dict[str, Any]:
    """One row per item: what it was, what we decided, and why.

    The evidence field is mandatory by construction — every Classification
    carries one — so a row can never say "superseded" without saying why.
    """
    return {
        "original_task_id": intent.task_id or str((task or {}).get("id") or ""),
        "original_slug": intent.slug or (task or {}).get("slug") or "",
        "project_id": (task or {}).get("project_id"),
        "branch": branch or (task or {}).get("artifact_branch") or "",
        "intent_goal": intent.goal[:2000],
        "intent_acceptance": intent.acceptance,
        "classification": result.classification,
        "evidence": result.evidence,
        "details": result.details,
        "outcome": outcome,
        "derived_task_id": derived_task_id or None,
        "derived_commit": derived_commit or None,
    }


def already_processed(task_id: str, existing_rows: Iterable[Dict[str, Any]]) -> bool:
    """Idempotency guard: re-running a cycle never duplicates a ledger row."""
    if not task_id:
        return False
    return any(str(r.get("original_task_id")) == str(task_id) for r in existing_rows or [])


def select_batch(
    candidates: Sequence[Dict[str, Any]],
    existing_rows: Iterable[Dict[str, Any]] = (),
    batch_size: int = DEFAULT_BATCH,
) -> List[Dict[str, Any]]:
    """Oldest-intent-first, bounded, skipping anything already in the ledger."""
    seen = {str(r.get("original_task_id")) for r in (existing_rows or [])}
    fresh = [c for c in candidates if str(c.get("id")) not in seen]
    fresh.sort(key=lambda c: (str(c.get("created_at") or ""), str(c.get("id") or "")))
    return fresh[: max(0, int(batch_size))]


# ---------------------------------------------------------------------------
# Circuit breaker + cycle
# ---------------------------------------------------------------------------
class RecoveryBreaker:
    """Bounded attempts; trips after repeated failure and stops the cycle.

    Deliberately simple and in-process: the breaker exists so a systemic fault
    (git unreachable, DB down) costs one batch, not the whole backlog.
    """

    def __init__(self, threshold: int = DEFAULT_BREAKER_THRESHOLD):
        self.threshold = max(1, int(threshold))
        self.consecutive_failures = 0
        self.tripped = False

    def record_success(self) -> None:
        self.consecutive_failures = 0

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.threshold:
            self.tripped = True

    def allows(self) -> bool:
        return not self.tripped


def run_cycle(
    candidates: Sequence[Dict[str, Any]],
    classify: Callable[[Dict[str, Any]], Classification],
    *,
    existing_rows: Iterable[Dict[str, Any]] = (),
    batch_size: int = DEFAULT_BATCH,
    observe_only: bool = True,
    write_row: Optional[Callable[[Dict[str, Any]], None]] = None,
    breaker: Optional[RecoveryBreaker] = None,
) -> Dict[str, Any]:
    """Process at most `batch_size` items, oldest-intent-first.

    Observe-only is the DEFAULT: the first thing this system does in a new
    environment is describe what it would do. Nothing is written until a caller
    explicitly asks for it, and even then rows are written one at a time — there
    are no bulk state changes here by construction.
    """
    breaker = breaker or RecoveryBreaker()
    rows: List[Dict[str, Any]] = []
    counts = {c: 0 for c in CLASSIFICATIONS}
    errors: List[Dict[str, str]] = []

    for task in select_batch(candidates, existing_rows, batch_size):
        if not breaker.allows():
            break
        try:
            intent = recover_intent(task)
            result = classify(task)
            row = build_ledger_row(
                task, intent, result,
                outcome="observed" if observe_only else "recorded",
            )
            counts[result.classification] = counts.get(result.classification, 0) + 1
            rows.append(row)
            if not observe_only and write_row is not None:
                write_row(row)          # one row at a time; never a bulk update
            breaker.record_success()
        except Exception as exc:        # noqa: BLE001 — one bad item must not end the cycle
            errors.append({"task_id": str(task.get("id") or ""), "error": str(exc)})
            breaker.record_failure()

    return {
        "processed": len(rows),
        "rows": rows,
        "counts": counts,
        "errors": errors,
        "observe_only": observe_only,
        "breaker_tripped": breaker.tripped,
        "needs_operator": counts.get(NEEDS_OPERATOR, 0),
    }

#!/usr/bin/env python3
"""recovery_ledger.py - build and VALIDATE reconciliation recovery ledgers.

A reconciliation pass classifies every piece of local build evidence (agent branches,
rescue refs, stashes, worktrees) against the current base, and writes one ledger record
per evidence item so the disposition is durable and auditable.

WHY THIS MODULE EXISTS RATHER THAN A TWENTIETH HAND-WRITTEN LEDGER
------------------------------------------------------------------
The measurement that funded this work: beethoven carries 19 committed ledgers holding
9,481 rows that cover only 1,279 DISTINCT sources - 7.4x re-classification, the worst in
the fleet. The root cause is structural, not sloppiness: each pass commits its ledger to
its OWN agent branch, so a pass only sees the predecessors it happens to share a ref with,
re-derives what is already known, and the next "reconcile project X" task is queued for
the project that has already been reconciled the most.

So this module reads the UNION of every ledger reachable from the base tree, not just its
own. `known_dispositions()` is the part that makes a pass cheaper than its predecessor
instead of equally expensive, and `validate()` is what makes a ledger's claims checkable
after the fact rather than taken on trust.

Fail-soft throughout, per CLAUDE.md: a git or JSON error answers "cannot tell" (an empty
result or an UNKNOWN classification) with a diagnostic printed, and never raises into a
reconciliation loop. An unreadable ledger must not be silently read as an empty one, so
validate() reports it as an error.

CLI:
    python3 runner/recovery_ledger.py build    --fingerprint <sha256> [--repo .] [--base origin/master]
    python3 runner/recovery_ledger.py validate --ledger .orch/recovery-ledger-<id>.json [--repo .]
"""
import json
import os
import subprocess
import sys

GIT_TIMEOUT = int(os.environ.get("ORCH_GIT_TIMEOUT", "60"))
LEDGER_DIR = os.environ.get("ORCH_LEDGER_DIR", ".orch")

#: The five dispositions a reconciliation pass may reach. UNKNOWN is deliberately NOT one
#: of them: "completion requires zero UNKNOWN items" is the contract, so an unclassifiable
#: item is a validation FAILURE, not a sixth valid outcome.
CLASSIFICATIONS = (
    "ALREADY_PRESENT",
    "SUPERSEDED_BY_NEWER",
    "ACTIVE_IN_ANOTHER_TASK",
    "RECOVERABLE_VALUE",
    "CONFLICTED_NEEDS_FOCUSED_TASK",
)

#: Only this classification asserts that code still needs to move. It is therefore the
#: only one that must carry reachable branch/commit provenance - the others are
#: statements that nothing is owed, which need a reason but not a destination.
NEEDS_PROVENANCE = "RECOVERABLE_VALUE"


def _git(repo, *args):
    """Run git in *repo*. Returns (stdout, ok). Never raises."""
    try:
        r = subprocess.run(["git"] + list(args), cwd=repo, capture_output=True,
                           text=True, timeout=GIT_TIMEOUT)
        return r.stdout.strip(), r.returncode == 0
    except Exception as exc:  # noqa: BLE001 - fail-soft, diagnostic printed
        print(f"recovery_ledger: git {args[0] if args else '?'} failed ({exc}); fail-soft")
        return "", False


def load_ledgers(repo, ledger_dir=LEDGER_DIR):
    """Every ledger under *ledger_dir*, as (path, parsed) pairs.

    An unparseable ledger yields (path, None) rather than being dropped: a ledger that
    cannot be read is a finding, and silently skipping it would let a corrupt file look
    like an absent one.
    """
    out = []
    root = os.path.join(repo, ledger_dir)
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        if not (name.startswith("recovery-ledger") and name.endswith(".json")):
            continue
        path = os.path.join(root, name)
        try:
            with open(path, "r", errors="replace") as fh:
                out.append((path, json.load(fh)))
        except Exception as exc:  # noqa: BLE001 - fail-soft, reported not swallowed
            print(f"recovery_ledger: unreadable ledger {name} ({exc})")
            out.append((path, None))
    return out


def _records(ledger):
    """Records inside one parsed ledger, whatever key this generation used.

    The 19 existing ledgers use at least three shapes ("items", "evidence_items", or a
    bare list). Reading all of them is the whole point - a reader that only understood
    the newest shape would re-derive everything the older passes already knew.
    """
    if isinstance(ledger, list):
        return [r for r in ledger if isinstance(r, dict)]
    if not isinstance(ledger, dict):
        return []
    for key in ("items", "evidence_items", "records"):
        val = ledger.get(key)
        if isinstance(val, list):
            return [r for r in val if isinstance(r, dict)]
    return []


def _source_of(record):
    """The evidence source a record is about, under any of its historical spellings."""
    for key in ("source", "ref", "branch", "path", "sha", "id"):
        val = record.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def known_dispositions(repo, ledger_dir=LEDGER_DIR):
    """source -> classification, unioned across EVERY ledger in the tree.

    This is the anti-duplication primitive: a pass that consults it classifies only what
    no predecessor has, instead of re-deriving the whole corpus. Later ledgers win on a
    conflict, since dispositions are reassessed against a moving base.
    """
    known = {}
    for _path, ledger in load_ledgers(repo, ledger_dir):
        if ledger is None:
            continue
        for rec in _records(ledger):
            source = _source_of(rec)
            cls = rec.get("classification")
            if source and cls:
                known[source] = cls
    return known


def commit_reachable(repo, sha):
    """True only when *sha* names a commit object that exists in *repo*.

    `cat-file -e <sha>^{commit}` and not `rev-parse`: rev-parse happily echoes back a
    40-hex string that is not an object, so a fabricated sha would validate.
    """
    if not sha or not isinstance(sha, str):
        return False
    _out, ok = _git(repo, "cat-file", "-e", f"{sha.strip()}^{{commit}}")
    return ok


def branch_exists(repo, branch):
    """True when *branch* names a ref that exists in *repo*, under any namespace.

    Local, remote-tracking, and non-branch namespaces all count: a local ref proves the
    commits exist here, a remote ref proves they reached anyone else, and provenance is
    satisfied by either. `refs/{branch}` is checked explicitly because rescue-ref evidence
    lives at refs/orch-rescue/<name> — a heads/remotes-only probe reports every rescue ref
    as unreachable, which would fail the provenance check on 402 records that are in fact
    right there in the object store. A false "not reachable" is the dangerous direction:
    it discards recoverable work.
    """
    if not branch or not isinstance(branch, str):
        return False
    branch = branch.strip()
    for pattern in (f"refs/heads/{branch}", f"refs/remotes/*/{branch}",
                    f"refs/{branch}", branch):
        out, ok = _git(repo, "for-each-ref", "--format=%(refname)", pattern)
        if ok and out.strip():
            return True
    return False


def validate(ledger_path, repo=".", manifest_path=None):
    """Check a ledger against the three completion conditions.

    Returns {"ok": bool, "errors": [...], "summary": {classification: count}}.

      1. zero UNKNOWN (or missing) classifications
      2. exactly one record per manifest item, and no record for an item not in it
      3. every RECOVERABLE_VALUE record names a branch AND a commit that exist here

    Returns ok=False with an explanatory error rather than raising, so a caller can
    report the failure instead of dying on it.
    """
    errors = []
    try:
        with open(ledger_path, "r", errors="replace") as fh:
            ledger = json.load(fh)
    except Exception as exc:  # noqa: BLE001 - fail-soft, reported
        return {"ok": False, "errors": [f"ledger unreadable: {exc}"], "summary": {}}

    records = _records(ledger)
    if not records:
        errors.append("ledger contains no records")

    # (1) zero UNKNOWN
    summary = {}
    for rec in records:
        cls = (rec.get("classification") or "UNKNOWN").strip() or "UNKNOWN"
        summary[cls] = summary.get(cls, 0) + 1
        if cls not in CLASSIFICATIONS:
            errors.append(f"{_source_of(rec) or '<no source>'}: classification {cls!r} "
                          "is not one of the five dispositions")
        if not (rec.get("disposition") or "").strip():
            errors.append(f"{_source_of(rec) or '<no source>'}: no disposition recorded")

    # (2) one record per manifest item, both directions
    if manifest_path is None:
        manifest_path = str(ledger_path).replace("recovery-ledger", "evidence_manifest")
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", errors="replace") as fh:
                manifest = json.load(fh)
            wanted = {_source_of(i) if isinstance(i, dict) else str(i)
                      for i in _records(manifest) or (manifest if isinstance(manifest, list) else [])}
            wanted.discard("")
            got = [_source_of(r) for r in records]
            seen = set(got)
            for missing in sorted(wanted - seen):
                errors.append(f"manifest item has no ledger record: {missing}")
            for extra in sorted(seen - wanted):
                errors.append(f"ledger record for an item not in the manifest: {extra}")
            for source in sorted(seen):
                if got.count(source) > 1:
                    errors.append(f"{source}: {got.count(source)} records, expected exactly 1")
        except Exception as exc:  # noqa: BLE001 - fail-soft, reported
            errors.append(f"manifest unreadable: {exc}")
    else:
        errors.append(f"no evidence manifest at {manifest_path}")

    # (3) RECOVERABLE_VALUE must be reachable
    for rec in records:
        if (rec.get("classification") or "") != NEEDS_PROVENANCE:
            continue
        source = _source_of(rec) or "<no source>"
        branch, commit = rec.get("branch"), rec.get("commit")
        if not branch:
            errors.append(f"{source}: RECOVERABLE_VALUE with no branch")
        elif not branch_exists(repo, branch):
            errors.append(f"{source}: branch {branch} is not reachable")
        if not commit:
            errors.append(f"{source}: RECOVERABLE_VALUE with no commit")
        elif not commit_reachable(repo, commit):
            errors.append(f"{source}: commit {commit} is not reachable")

    return {"ok": not errors, "errors": errors, "summary": summary}


#: Task states that still OWN their branch. A branch under one of these must never be
#: classified RECOVERABLE_VALUE: recovering work someone is holding forks one change into
#: two and hands the merge train the conflict reconciliation exists to prevent.
LIVE_STATES = ("QUEUED", "RUNNING", "SHELVED", "BLOCKED")


def live_slugs_from_db(project_id):
    """Slugs of tasks that still own their branch, or an empty set if the queue is unreachable.

    Returns (slugs, reached_db). The second value matters: an empty set because the queue
    is EMPTY and an empty set because the queue could not be READ are opposite facts, and
    conflating them turns held work into recoverable work. Callers must refuse to write a
    ledger when reached_db is False.
    """
    try:
        import db
        rows = db.select("tasks", {"select": "slug", "project_id": f"eq.{project_id}",
                                   "state": f"in.({','.join(LIVE_STATES)})",
                                   "limit": "10000"}) or []
        return {r.get("slug") for r in rows if r.get("slug")}, True
    except Exception as exc:  # noqa: BLE001 - fail-soft, reported not swallowed
        print(f"recovery_ledger: queue unreachable ({exc}); cannot tell which branches are held")
        return set(), False


def merged_refs(repo, base):
    """Every agent ref already contained in *base*, in ONE git call.

    Asking `merge-base --is-ancestor` per ref is correct but costs a subprocess each, and
    beethoven carries ~1,500 agent refs — the per-ref form turned a reconciliation pass
    into a multi-minute one and is a large part of why these passes were expensive enough
    to be abandoned half-finished. `for-each-ref --merged` answers the same question for
    every ref at once. Fail-soft: an empty set on error, which only costs a slower path.
    """
    out, ok = _git(repo, "for-each-ref", f"--merged={base}", "--format=%(refname:short)",
                   "refs/heads/agent/", "refs/remotes/")
    if not ok:
        return set()
    merged = set()
    for line in out.split("\n"):
        line = line.strip()
        if "agent/" in line:
            merged.add("agent/" + line.split("agent/", 1)[-1])
    return merged


def classify_branch(repo, ref, sha, base, live_slugs=(), known=None, merged=None):
    """Classify one agent branch against *base*. Returns (classification, disposition).

    Order is load-bearing and is the cheap-to-expensive order as well as the safe one:
    a branch already IN the base is present no matter what any task record says, and an
    ACTIVE task outranks a recovery because recovering work someone is holding forks it.
    RECOVERABLE_VALUE is reached only after everything cheaper has been ruled out, so the
    expensive answer is never the default.
    """
    known = known or {}
    prior = known.get(ref)

    # The bulk merged-set is consulted FIRST because it is already in memory; falling back
    # to the per-ref ancestor probe only when it is unavailable keeps the answer identical.
    if merged is not None:
        if ref in merged:
            return "ALREADY_PRESENT", f"{sha[:12]} is contained in {base}"
    else:
        if not commit_reachable(repo, sha):
            # Cannot tell rather than "lost": a pruned object here may be intact elsewhere,
            # and calling it recoverable would queue a recovery no one can satisfy.
            return "CONFLICTED_NEEDS_FOCUSED_TASK", (
                f"commit {sha[:12]} is not reachable in this checkout; needs a host that has it")
        _out, is_anc = _git(repo, "merge-base", "--is-ancestor", sha, base)
        if is_anc:
            return "ALREADY_PRESENT", f"{sha[:12]} is an ancestor of {base}"

    diff, ok = _git(repo, "diff", "--name-only", f"{base}...{sha}")
    if ok and not diff.strip():
        return "ALREADY_PRESENT", f"empty diff against {base} (landed by squash or cherry-pick)"

    slug = ref.split("agent/", 1)[-1] if "agent/" in ref else ref
    if slug in live_slugs:
        return "ACTIVE_IN_ANOTHER_TASK", f"a live task still owns {slug}; left in the queue"

    if prior in ("SUPERSEDED_BY_NEWER", "CONFLICTED_NEEDS_FOCUSED_TASK"):
        return prior, f"disposition carried forward from a prior ledger ({prior})"

    files = [f for f in diff.split("\n") if f.strip()]
    route = ("deliver via the agent branch and merge train" if ref.startswith("agent/")
             else "recover into a NEW agent branch; the rescue ref itself is read-only")
    return "RECOVERABLE_VALUE", f"{len(files)} file(s) not in {base}; {route}"


#: The ref namespaces a reconciliation pass can be pointed at. Agent branches are work
#: someone deliberately pushed; rescue refs are sentinel.py's periodic sweep of whatever
#: was sitting in a checkout, so the same classifier applies but the evidence kind — and
#: therefore what a RECOVERABLE_VALUE record MEANS — differs and is recorded per item.
EVIDENCE_KINDS = {
    "agent_branch": ("refs/heads/agent/", "refs/remotes/"),
    "orchestrator_rescue_ref": ("refs/orch-rescue/",),
}


def build(repo=".", fingerprint="", base="origin/master", live_slugs=(), ledger_dir=LEDGER_DIR,
          evidence_kind="agent_branch"):
    """Enumerate evidence of *evidence_kind* and classify each item. Returns (manifest, ledger).

    The live source is enumerated rather than the prompt's sample being trusted, because a
    sample plus a digest cannot be classified item-by-item and the contract requires one
    record per item.
    """
    known = known_dispositions(repo, ledger_dir)
    merged = merged_refs(repo, base)
    namespaces = EVIDENCE_KINDS.get(evidence_kind) or EVIDENCE_KINDS["agent_branch"]
    out, ok = _git(repo, "for-each-ref", "--format=%(refname:short)%09%(objectname)",
                   *namespaces)
    items, records = [], []
    if ok:
        seen = set()
        for line in out.split("\n"):
            if "\t" not in line:
                continue
            ref, sha = line.split("\t", 1)
            ref = ref.strip()
            if evidence_kind == "agent_branch":
                if "agent/" not in ref:
                    continue
                # Normalise origin/agent/x and agent/x to one item: the same work reached
                # by two ref namespaces is one piece of evidence, and counting it twice is
                # the re-classification inflation this module exists to stop.
                norm = "agent/" + ref.split("agent/", 1)[-1]
            else:
                # Rescue refs are NOT normalised. Each is a distinct timestamped snapshot
                # of a checkout — two sweeps of the same branch are two different trees,
                # and collapsing them by name would silently drop whichever the contract
                # ("one record per evidence item") requires to be classified.
                if not ref.startswith("orch-rescue/") and "orch-rescue/" not in ref:
                    continue
                norm = ref
            if norm in seen:
                continue
            seen.add(norm)
            cls, disp = classify_branch(repo, norm, sha.strip(), base, live_slugs,
                                        known, merged)
            items.append({"source": norm, "sha": sha.strip(), "kind": evidence_kind})
            rec = {"source": norm, "kind": evidence_kind, "classification": cls,
                   "disposition": disp}
            if cls == NEEDS_PROVENANCE:
                rec["branch"] = norm
                rec["commit"] = sha.strip()
            records.append(rec)

    summary = {}
    for rec in records:
        summary[rec["classification"]] = summary.get(rec["classification"], 0) + 1
    manifest = {"audit_fingerprint": fingerprint, "base": base, "evidence_kind": evidence_kind,
                "total": len(items), "unknown": 0, "items": items}
    ledger = {"audit_fingerprint": fingerprint, "base": base, "evidence_kind": evidence_kind,
              "total": len(records), "unknown": 0, "summary": summary,
              "prior_ledgers_consulted": len(load_ledgers(repo, ledger_dir)),
              "prior_dispositions_known": len(known), "items": records}
    return manifest, ledger


def _main(argv):
    if len(argv) < 2:
        print(__doc__.strip().rsplit("CLI:", 1)[-1].strip())
        return 2
    cmd = argv[1]
    args = {argv[i]: argv[i + 1] for i in range(2, len(argv) - 1, 2)}
    repo = args.get("--repo", ".")

    if cmd == "build":
        fp = args.get("--fingerprint", "")
        base = args.get("--base", "origin/master")
        short = (fp or "adhoc")[:12]
        # Live slugs come from the caller, not from a DB import here: the classifier must
        # stay usable on a host with no DB credentials, and "I could not reach the queue"
        # must not silently become "no task owns this", which would classify held work as
        # recoverable and fork it.
        live, reached = set(), False
        slug_file = args.get("--live-slugs")
        if slug_file:
            try:
                with open(slug_file, "r", errors="replace") as fh:
                    live = {ln.strip() for ln in fh if ln.strip()}
                reached = True
            except Exception as exc:  # noqa: BLE001 - fail-soft, reported
                print(f"recovery_ledger: live-slug file unreadable ({exc})")
        elif args.get("--project-id"):
            live, reached = live_slugs_from_db(args["--project-id"])
        if not reached:
            # REFUSE rather than write. Without queue state every held branch would be
            # classified RECOVERABLE_VALUE, and a ledger that over-claims recoveries is
            # worse than no ledger: it queues work that forks branches someone still owns.
            print("recovery_ledger: refusing to build without queue state — pass "
                  "--project-id or --live-slugs")
            return 1
        print(f"recovery_ledger: {len(live)} live slug(s) hold their branch")
        kind = args.get("--evidence-kind", "agent_branch")
        if kind not in EVIDENCE_KINDS:
            print(f"recovery_ledger: unknown evidence kind {kind!r}; "
                  f"expected one of {', '.join(sorted(EVIDENCE_KINDS))}")
            return 2
        manifest, ledger = build(repo, fp, base, live_slugs=live, evidence_kind=kind)
        os.makedirs(os.path.join(repo, LEDGER_DIR), exist_ok=True)
        mpath = os.path.join(repo, LEDGER_DIR, f"evidence_manifest-{short}.json")
        lpath = os.path.join(repo, LEDGER_DIR, f"recovery-ledger-{short}.json")
        for path, obj in ((mpath, manifest), (lpath, ledger)):
            with open(path, "w") as fh:
                json.dump(obj, fh, indent=2, sort_keys=True)
                fh.write("\n")
        print(f"recovery_ledger: {ledger['total']} records -> {lpath}")
        print(f"  consulted {ledger['prior_ledgers_consulted']} prior ledger(s), "
              f"{ledger['prior_dispositions_known']} dispositions already known")
        for cls in CLASSIFICATIONS:
            print(f"  {cls}: {ledger['summary'].get(cls, 0)}")
        return 0

    if cmd == "validate":
        lpath = args.get("--ledger", "")
        result = validate(lpath, repo, args.get("--manifest"))
        for cls in CLASSIFICATIONS:
            print(f"  {cls}: {result['summary'].get(cls, 0)}")
        other = {k: v for k, v in result["summary"].items() if k not in CLASSIFICATIONS}
        for cls, n in sorted(other.items()):
            print(f"  {cls}: {n}   <-- not a valid disposition")
        print(f"  TOTAL: {sum(result['summary'].values())}")
        for err in result["errors"][:50]:
            print(f"  ERROR {err}")
        if len(result["errors"]) > 50:
            print(f"  ... and {len(result['errors']) - 50} more")
        print("VALID" if result["ok"] else f"INVALID ({len(result['errors'])} error(s))")
        return 0 if result["ok"] else 1

    print(f"unknown command {cmd!r}")
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))

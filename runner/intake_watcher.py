#!/usr/bin/env python3
"""
intake_watcher.py - auto-ingest dropped task lists into the queue.

A Cowork/Claude Code session (or you) writes a file to ../intake/<anything>.md in the
canonical format below; this watcher parses it into properly-scoped tasks (dependency-linked,
material-flagged, model-routed), inserts them QUEUED, and moves the file to intake/processed/.
That makes intake "drop a file," not "hand-craft DB rows."

Canonical format (the drop-in prompt emits exactly this):

    PROJECT: smarter

    - id: some-slug
      title: one line
      material: yes|no
      model: haiku|sonnet|opus
      submitted-by: operator or system provenance label
      depends: [other-slug, ...]
      proof: `npx vue-tsc --noEmit` exits 0
      prompt: |
        multi-line scope + steps for ONE deliverable.

    OPERATOR:
      - things needing secrets/deploys/legal (logged, never queued)

Idempotent: a task whose slug already exists is skipped (re-dropping a file won't duplicate).

OPERATOR DROP-BOX (2026-07-08): a human/Cowork session can also drop a big FREEFORM prompt as
../PROMPT-<anything>.md (repo root, not intake/) — not in the canonical format above. Any such
file that does NOT already start with a `PROJECT:` line gets auto-decomposed through planner.py
(the same contract-first DAG decomposition prompt_factory.py uses for objectives) and queued the
same as a hand-written canonical file. This is what makes "paste a big prompt, run one manual
Claude Code session" the EXCEPTION rather than the default: going forward, a manual serial
session should be reserved for fleet-down recovery (the fleet can't queue/execute anything, so
there's nothing for intake to route work to yet); routine strategic prompts belong in the
drop-box so they run as a parallel, dependency-linked DAG instead of one long serial session.
A PROMPT-*.md that already IS canonical format is left untouched here (nothing to decompose).
"""
import os, sys, re, glob, json, datetime, shutil, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import intake_gate
import pipeline_contract
import autoclear as _autoclear   # FIX 2026-07-29: _autoclear.load_rules() was called with no
                                 # import -> the operator-card path of the drop-box crashed with
                                 # NameError whenever a freeform prompt carried operator items.
try:
    import branch_bootstrap_injection as _branch_bootstrap
except Exception:                # fail-soft: intake must keep queueing even if the
    _branch_bootstrap = None     # bootstrap-injection module can't load.

HERE = os.path.dirname(os.path.abspath(__file__))
INTAKE = os.path.abspath(os.path.join(HERE, "..", "intake"))
PROCESSED = os.path.join(INTAKE, "processed")
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))


def parse(text):
    """Return (tasks, operator_notes). Hand parser for the canonical format."""
    tasks, operator = [], []
    project, cur, in_prompt, plines, in_operator = None, None, False, [], False

    def flush():
        nonlocal cur, plines
        if cur is not None:
            cur["prompt"] = "\n".join(plines).strip()
            if cur.get("project") and cur.get("slug"):
                tasks.append(cur)
        cur, plines = None, []

    for raw in text.splitlines():
        s = raw.strip()
        mp = re.match(r"^PROJECT:\s*(.+)$", s)
        if mp:
            flush(); project = mp.group(1).strip(); in_operator = False; continue
        if re.match(r"^OPERATOR:\s*$", s):
            flush(); in_operator = True; continue
        if in_operator:
            if s.startswith("-"):
                operator.append(s.lstrip("- ").strip())
            continue
        mid = re.match(r"^-\s*id:\s*(.+)$", s)
        if mid:
            flush()
            cur = {"project": project, "slug": mid.group(1).strip(), "material": False,
                   "model": None, "depends": [], "proof": "", "prompt": ""}
            in_prompt = False; continue
        if cur is None:
            continue
        if in_prompt:
            plines.append(raw); continue
        kv = re.match(
            r"^(title|material|model|submitted-by|submitted_by_label|depends|proof|prompt):\s*(.*)$",
            s,
        )
        if kv:
            k, v = kv.group(1), kv.group(2).strip()
            if k == "prompt":
                in_prompt = True
                if v and v != "|":
                    plines.append(v)
            elif k == "depends":
                cur["depends"] = [x.strip() for x in v.strip("[]").split(",") if x.strip()]
            elif k == "material":
                cur["material"] = v.lower().startswith("y")
            elif k == "model":
                cur["model"] = (v or None)
            elif k in ("submitted-by", "submitted_by_label"):
                cur["submitted_by_label"] = (v or None)
            else:
                cur[k] = v
    flush()
    return tasks, operator


def emit_operator_cards(proj_name, operator, src):
    """Create ONE approval card per operator item so the human can review/approve each
    individually from the app. Idempotent by title (re-runs won't duplicate). Shared by
    the live watcher and operator_backfill.py. Returns count created."""
    if not operator:
        return 0
    existing_titles = {a.get("title") for a in
                       (db.select("approvals", {"select": "title", "project": f"eq.{proj_name}"}) or [])}
    rules = _autoclear.load_rules()
    created = 0
    for o in operator:
        short = (o[:88] + "…") if len(o) > 88 else o
        title = f"[operator] {short}"
        if title in existing_titles:
            continue
        low = o.lower()
        kind = ("legal" if any(k in low for k in ("counsel", "legal", "sign-off", "sign off", "execute"))
                else "secret" if any(k in low for k in ("secret", "env", "api key", "oauth", "token", "credential"))
                else "operator")
        detail = f"{o}\n\n(from intake/{src})"
        card_row = {"project": proj_name, "kind": kind, "title": title, "detail": detail,
                    "approvals_required": 1}
        decision, rule_id = _autoclear.autoclear_decision(card_row, rules)
        row = {
            "project": proj_name, "kind": kind, "title": title,
            "why": "Needs a human — secrets / deploys / OAuth / legal sign-off the runner can't do.",
            "value": "Unblocks dependent tasks once done; Approve = authorized/completed, Deny = not yet.",
            "risk": "Dependent tasks stay blocked until this is approved.",
            "detail": detail,
        }
        if decision == "approved":
            row["status"] = "approved"
            row["decided_by"] = f"auto-rule:{rule_id}"
            row["decided_at"] = datetime.datetime.utcnow().isoformat()
        db.insert("approvals", row)
        existing_titles.add(title)
        created += 1
    return created


_LIVE_TASK_STATES = "in.(QUEUED,RUNNING,RETRY,DONE,MERGED)"


def _existing_live_slugs(slugs):
    """Return live/settled matches for only the intake slugs in this run.

    The old watcher downloaded the fleet-wide live-task window once per intake
    file.  Besides being truncated at PostgREST's 1,000-row cap, a multi-app
    ChatGPT audit could therefore spend minutes repeating the same broad query
    and get reaped before reaching the later manifests.  Intake slugs are
    deterministic identifiers, so server-side, chunked lookups are both faster
    and complete for the pending batch.
    """
    wanted = sorted({str(s).strip() for s in (slugs or []) if str(s).strip()})
    existing = set()
    for offset in range(0, len(wanted), 100):
        chunk = wanted[offset:offset + 100]
        rows = db.select("tasks", {
            "select": "slug",
            "slug": f"in.({','.join(chunk)})",
            "state": _LIVE_TASK_STATES,
            "limit": str(len(chunk)),
        }) or []
        existing.update(str(row.get("slug") or "") for row in rows)
    existing.discard("")
    return existing


def ingest_file(path, projects_by_name, existing=None):
    with open(path, encoding="utf-8", errors="replace") as src:
        text = src.read()
    tasks, operator = parse(text)
    # Only block re-ingestion for tasks in live/completed states. Tasks in failure states
    # (QUARANTINED, DECOMPOSED, SHELVED, BLOCKED, CONFLICT, TESTFAIL, WAITING) allow
    # re-ingestion so branch-creation attempts are not permanently blocked by prior failures.
    if existing is None:
        existing = _existing_live_slugs(t.get("slug") for t in tasks)
    created, skipped = 0, 0
    for t in tasks:
        proj = projects_by_name.get(t["project"])
        if not proj:
            # NEVER silently drop an operator prompt (2026-07-31: a planner-emitted
            # unregistered project name ate a whole initiative with only a log line).
            # Fall back to the orchestrator's home project, tag the mis-route in the
            # prompt so the coder/triage can re-route, and alert loudly.
            fallback = projects_by_name.get(os.environ.get("ORCH_INTAKE_FALLBACK_PROJECT",
                                                           "beethoven"))
            bad_project = str(t.get("project"))
            if fallback:
                print(f"intake: unknown project '{t['project']}' (slug {t['slug']}) — "
                      f"FALLBACK to '{fallback.get('name', 'beethoven')}' + alert")
                t["prompt"] = (f"## INTAKE ROUTING NOTICE: planner emitted unregistered "
                               f"project '{t['project']}'; routed to fallback. If this task "
                               f"belongs in a different repo, define cross-repo contracts "
                               f"here and note the re-route in your summary.\n\n" + t["prompt"])
                t["project"] = fallback.get("name", "beethoven")
                proj = fallback
                try:
                    db.insert("coordination_tasks", {
                        "task_type": "intake_reroute_alert",
                        "payload": json.dumps({"slug": t["slug"],
                                               "bad_project": bad_project,
                                               "at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                    time.gmtime())})[:2000]},
                              upsert=False)
                except Exception:
                    pass
            else:
                print(f"intake: unknown project '{t['project']}' (slug {t['slug']}) — "
                      f"skipped (no fallback registered)")
                skipped += 1; continue
        if t["slug"] in existing:
            skipped += 1; continue
        ok, reason = intake_gate.should_queue(t, proj)
        if not ok:
            print(f"intake: {t['slug']} rejected — {reason}")
            skipped += 1; continue
        raw_prompt = (t["prompt"] + (f"\n\nProof: {t['proof']}" if t["proof"] else ""))
        row = {"project_id": proj["id"], "slug": t["slug"],
               "prompt": pipeline_contract.wrap_prompt(raw_prompt, project=t["project"],
                                                        kind="build", source="intake-file",
                                                        slug=t["slug"], material=bool(t["material"])),
               "base_branch": proj.get("default_base", "main"), "kind": "build",
               "state": "QUEUED", "deps": t["depends"], "material": bool(t["material"]),
               "note": pipeline_contract.note(source="intake-file")}
        # These reconciliation tasks are created only from an explicit operator request to
        # recover ChatGPT local work.  Preserve that provenance so queue-depth and red-release
        # back-pressure cannot silently refuse the owner's recovery directive.
        if t.get("submitted_by_label"):
            row["submitted_by_label"] = t["submitted_by_label"]
        elif str(t["slug"]).startswith("chatgpt-local-reconcile-"):
            row["submitted_by_label"] = "ChatGPT local-build audit (operator-directed)"
        if t.get("model"):
            row["model"] = t["model"]
        if _branch_bootstrap:
            try:  # stage the base branch ahead of the task if it's missing locally
                _branch_bootstrap.inject_bootstrap_if_needed(row, proj)
            except Exception:
                pass
        inserted = db.insert("tasks", row)
        if inserted is None:
            # db.insert deliberately returns None when an admission gate refuses a task.  Moving
            # the source manifest after that result strands the request in processed/ while the
            # watcher falsely reports it as queued.  Leave the manifest in place for a safe retry.
            raise RuntimeError(f"task insert refused or produced no receipt: {t['slug']}")
        existing.add(t["slug"]); created += 1
    # surface each operator-only item as its OWN approval card (per-item, not a lump)
    emit_operator_cards(tasks[0]["project"] if tasks else "intake", operator, os.path.basename(path))
    return created, skipped


def is_canonical(text):
    """A file is canonical format if it has a `PROJECT:` header anywhere — that's the one
    marker every hand-written or machine-generated canonical drop always has."""
    return bool(re.search(r"^PROJECT:\s*\S", text or "", re.M))


def _dropbox_slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:60] or "dropbox"


def _extract_proof_line(prompt_text):
    m = re.search(r"(?:proof|acceptance test|test)\s*:\s*(\S.+)", prompt_text or "", re.I)
    return m.group(1).strip().rstrip(".") if m else ""


def _project_from_filename(filename, projects_by_name):
    """Resolve the project from the operator's FILENAME, which is an explicit declaration.

    The drop-box convention every operator prompt actually uses is `PROMPT-<project>-<topic>.md`
    (PROMPT-apparently-treasury-tab.md, PROMPT-beethoven-madeus-platform.md, ...). Until 2026-08-04
    that declaration was ignored and only the prose heuristic below ran — which mis-routes whenever
    a spec MENTIONS a project with a longer name than the one it targets. Live example: the
    beethoven/madeus prompt talks about surfacing Madeus inside Apparently, so 'apparently' (10
    chars) beat 'beethoven' (9) and a whole beethoven initiative would have been queued against the
    apparently repo. The filename is unambiguous, so it wins; prose stays as the fallback for files
    that carry no project prefix (PROMPT-backlog-blitz.md and friends).
    """
    base = re.sub(r"\.md$", "", os.path.basename(filename or ""), flags=re.I)
    m = re.match(r"^(?:HOLD-)?PROMPT-(.+)$", base, re.I)
    if not m:
        return None
    rest = m.group(1).lower()
    cands = [n for n in projects_by_name
             if n and (rest == n.lower() or rest.startswith(n.lower() + "-"))]
    return max(cands, key=len) if cands else None   # most specific project prefix wins


def _default_project_for_dropbox(text, projects_by_name, filename=None):
    """Heuristic project resolution for freeform prompts, which don't declare PROJECT: by
    definition. Looks for a known project name mentioned early in the text; falls back to
    'beethoven' (the orchestrator's own project) since operator-authored strategic PROMPT-*.md
    drops most commonly target the orchestrator improving itself — the two real examples this
    feature was built for (PROMPT-backlog-blitz.md, PROMPT-meta-optimizer.md) both do.

    An explicit `PROMPT-<project>-*.md` filename beats the prose heuristic — see
    _project_from_filename() for why."""
    by_filename = _project_from_filename(filename, projects_by_name)
    if by_filename:
        return by_filename
    head = (text or "")[:2000].lower()

    # Match project names robustly + prefer the MOST SPECIFIC. Two failure modes this guards:
    #  (1) prefix shadowing: 'apparently' must never shadow 'apparently-law' (longest wins);
    #  (2) separator drift: a hyphenated project name ('apparently-law') rarely appears verbatim
    #      in prose that says "Apparently Law" — so match hyphen/underscore as space too.
    def _variants(n):
        n = n.lower()
        return {n, n.replace("-", " "), n.replace("_", " "), n.replace("-", ""), n.replace("_", "")}

    matches = [name for name in projects_by_name
               if name and any(v and v in head for v in _variants(name))]
    if matches:
        return max(matches, key=len)   # most specific / longest project name wins
    return "beethoven" if "beethoven" in projects_by_name else (next(iter(projects_by_name), None))


def decompose_freeform(text, repo_root, default_project):
    """Contract-first DAG decomposition of a freeform prompt via planner.py (the same engine
    prompt_factory.py uses for objectives). Returns a list of task dicts shaped like parse()'s
    output, ready for the same insertion path ingest_file() uses. Raises on planner failure —
    callers decide how to handle that (planner.plan() itself already falls back to a single
    master-task rather than raising in the common case; this only raises on a harder failure,
    e.g. planner.py itself being unimportable)."""
    import inspect
    import planner
    # `project` is a newer routing hint.  Keep compatibility with installed or
    # test planners that still expose plan(master, repo=None); rejecting those
    # signatures used to claim the dropbox file and queue nothing.
    try:
        parameters = inspect.signature(planner.plan).parameters.values()
        accepts_project = any(
            parameter.name == "project" or
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )
    except (TypeError, ValueError):
        accepts_project = False
    if accepts_project:
        tasks = planner.plan(text, repo=repo_root, project=default_project)
    else:
        tasks = planner.plan(text, repo=repo_root)
    slug_base = _dropbox_slugify((text.strip().splitlines() or [""])[0])
    # Wave-0 attribution (review-gate spec item 4): an optional SUBMITTED-BY: line
    # in the PROMPT-*.md carries through decomposition onto every queued task.
    import re as _re
    _m = _re.search(r"^SUBMITTED-BY:\s*(.+)$", text or "", _re.M | _re.I)
    submitted_by_label = _m.group(1).strip()[:200] if _m else None
    rendered = []
    for t in tasks:
        rendered.append({
            "submitted_by_label": submitted_by_label,
            "project": default_project,
            "slug": f"dropbox-{slug_base}-{t['slug']}",
            # honor the workflow router's materiality stamp (governed_heavy / material work gets
            # gated); default False so non-material coherent/fast work isn't over-gated.
            "material": bool(t.get("material", False)),
            "model": t.get("model_hint"),
            "depends": [f"dropbox-{slug_base}-{d}" for d in (t.get("deps") or [])],
            "proof": _extract_proof_line(t.get("prompt")),
            "prompt": t.get("prompt") or "",
        })
    return rendered


def _queue_dropbox_tasks(rendered, projects_by_name):
    # Same state filter as ingest_file: only live/completed states block re-ingestion.
    existing = {t["slug"] for t in (db.select("tasks", {"select": "slug",
                "state": "in.(QUEUED,RUNNING,RETRY,DONE,MERGED)"}) or [])}
    created, skipped = 0, 0
    for t in rendered:
        proj = projects_by_name.get(t["project"])
        if not proj:
            skipped += 1; continue
        if t["slug"] in existing:
            skipped += 1; continue
        raw_prompt = t["prompt"] + (f"\n\nProof: {t['proof']}" if t["proof"] else "")
        row = {"project_id": proj["id"], "slug": t["slug"],
               "prompt": pipeline_contract.wrap_prompt(raw_prompt, project=t["project"],
                                                        kind="build", source="intake-dropbox",
                                                        slug=t["slug"], material=bool(t["material"])),
               "base_branch": proj.get("default_base", "main"), "kind": "build",
               "state": "QUEUED", "deps": t["depends"], "material": bool(t["material"]),
               "note": pipeline_contract.note(source="intake-dropbox")}
        if t.get("submitted_by_label"):
            row["submitted_by_label"] = t["submitted_by_label"]
        if t.get("model"):
            row["model"] = t["model"]
        if _branch_bootstrap:
            try:  # stage the base branch ahead of the task if it's missing locally
                _branch_bootstrap.inject_bootstrap_if_needed(row, proj)
            except Exception:
                pass
        db.insert("tasks", row)
        existing.add(t["slug"]); created += 1
    return created, skipped


def _flag_dropbox_failure(claimed_path, project, reason):
    """The source file is already claimed (moved) by the time decomposition can fail — unlike
    the canonical intake path, it can't just be 'left in place to retry', because retrying means
    calling planner.plan() again, which is a real (non-deterministic) model call, not a safe
    no-op re-read. File one visible approval card so the objective doesn't silently vanish; this
    is best-effort — if even the approval insert fails, the claimed file itself (still sitting in
    intake/processed/ with its content intact) is the fallback record."""
    try:
        db.insert("approvals", {
            "project": project or "beethoven", "kind": "operator",
            "title": f"[dropbox] decomposition failed for {os.path.basename(claimed_path)}",
            "why": "The operator drop-box claimed this PROMPT-*.md but planner.py's decomposition "
                   "failed before any tasks were queued — nothing was silently lost, but nothing "
                   "was queued either.",
            "value": "Re-run manually once the underlying issue is fixed, or decompose by hand.",
            "risk": "This objective is stalled until someone looks at it.",
            "detail": f"{reason}\n\nClaimed file: {claimed_path}"})
    except Exception:
        pass


def ingest_dropbox_prompts(projects_by_name):
    """Scan repo root for PROMPT-*.md files that are NOT canonical format and auto-decompose
    them.

    Ordering note (2026-07-08): the source file is claimed (moved to intake/processed/) BEFORE
    calling decompose_freeform(), not after. decompose_freeform() calls planner.plan() — a real
    model call whose output is NOT deterministic across calls — so a slug-based idempotency
    check (which works fine for canonical hand-written files, whose slugs are static) cannot
    safely dedupe a re-run of this path. If the file were left in place until decomposition
    finished (the original design), a process killed between decomposition and the move — which
    is exactly what happened once, in production, the day this was fixed — would reprocess it on
    the next tick and queue a second, differently-slugged set of duplicate tasks. Claiming first
    means the worst case on interruption is "this objective didn't get decomposed this tick" —
    auditable and re-triggerable by hand — never silent duplication.
    """
    files = [f for f in glob.glob(os.path.join(REPO_ROOT, "PROMPT-*.md")) if os.path.isfile(f)]
    # PERMISSION SELF-HEAL (2026-07-30): prompts written by sandboxed tools (Cowork sessions) can
    # land mode-600/foreign-owned and be INVISIBLE or unreadable to this process — the drop-box
    # then reports "0 from dropbox" while the operator watches their file sit unclaimed (observed
    # live tonight; chmod 644 released it). Two defenses: try to self-heal perms on anything we CAN
    # see but not read, and loudly log a listdir-vs-glob mismatch so an invisible file is at least
    # detectable in the log instead of silently uncounted.
    try:
        visible = {e for e in os.listdir(REPO_ROOT) if e.startswith("PROMPT-") and e.endswith(".md")}
        globbed = {os.path.basename(f) for f in files}
        for name in sorted(visible - globbed):
            p = os.path.join(REPO_ROOT, name)
            try:
                os.chmod(p, 0o644)
                if os.path.isfile(p):
                    files.append(p)
                    print(f"intake: self-healed permissions on {name} (was invisible to glob)")
            except Exception as e:
                print(f"intake: DROPBOX FILE UNREADABLE — {name} exists but cannot be claimed "
                      f"({type(e).__name__}); operator: chmod 644 it")
    except Exception:
        pass
    total = 0
    for f in sorted(files):
        try:
            text = open(f, encoding="utf-8", errors="replace").read()
        except Exception as e:
            print(f"intake: dropbox read failed on {f}: {e}"); continue
        if is_canonical(text):
            continue  # already canonical — nothing to decompose, leave it for a human to move

        # Claim FIRST — see docstring. Nothing below this point may leave the file in repo root.
        stamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        claimed_path = os.path.join(PROCESSED, f"{stamp}-dropbox-{os.path.basename(f)}")
        try:
            shutil.move(f, claimed_path)
        except Exception as e:
            print(f"intake: dropbox claim failed on {f}: {e}"); continue

        default_project = _default_project_for_dropbox(text, projects_by_name,
                                                        filename=os.path.basename(f))
        if not default_project or default_project not in projects_by_name:
            print(f"intake: dropbox {os.path.basename(f)} — no resolvable project; "
                  f"claimed at {claimed_path} but not decomposed")
            _flag_dropbox_failure(claimed_path, None, "no resolvable project among configured projects")
            continue
        try:
            rendered = decompose_freeform(text, REPO_ROOT, default_project)
        except Exception as e:
            print(f"intake: dropbox decomposition failed on {os.path.basename(f)} "
                  f"(claimed at {claimed_path}): {e}")
            _flag_dropbox_failure(claimed_path, default_project, str(e))
            continue
        if not rendered:
            # SILENT-LOSS FIX (2026-08-04): this used to `continue` with no record at all — the
            # file was already claimed, so the objective vanished with nothing but an absent log
            # line to show for it. Same contract as a decomposition exception: always leave a card.
            print(f"intake: dropbox {os.path.basename(f)} — decomposition returned NO tasks "
                  f"(claimed at {claimed_path})")
            _flag_dropbox_failure(claimed_path, default_project,
                                  "decomposition returned zero tasks")
            continue
        created, skipped = _queue_dropbox_tasks(rendered, projects_by_name)
        print(f"intake: dropbox {os.path.basename(f)} -> {created} queued, {skipped} skipped")
        if created == 0:
            # SILENT-LOSS FIX (2026-08-04): decomposition succeeded but EVERY task was refused at
            # insert time — in production this was release back-pressure (db.insert drops tasks for
            # a project whose last release failed, and every portfolio project was RED), which ate
            # seven activated operator prompts on 2026-08-04 leaving no card, no task and no error.
            # A claimed file that queued nothing is always a visible failure from here on.
            _flag_dropbox_failure(
                claimed_path, default_project,
                f"decomposition produced {len(rendered)} tasks but NONE were queued "
                f"({skipped} skipped/rejected at insert). Most likely cause: release "
                f"back-pressure — project '{default_project}' is RED (see deployment_terminal."
                f"project_accepts_work), or every slug already exists in a live state. "
                f"Re-drop the claimed file once the cause clears.")
        total += created
    return total


def run():
    os.makedirs(PROCESSED, exist_ok=True)
    projects_by_name = {p["name"]: p for p in (db.select("projects") or [])}
    dropbox_total = 0
    try:
        dropbox_total = ingest_dropbox_prompts(projects_by_name)
    except Exception as e:
        print(f"intake: dropbox scan failed: {e}")  # never let dropbox errors block canonical intake
    files = [f for f in glob.glob(os.path.join(INTAKE, "*.md")) if os.path.isfile(f)]
    if not files:
        print(f"intake: nothing to ingest ({dropbox_total} from dropbox)")
        return dropbox_total
    # Resolve idempotency for this batch once.  `existing` is mutated by ingest_file as new
    # tasks are created, so duplicate slugs in later manifests are still skipped deterministically.
    pending_slugs = set()
    for f in files:
        try:
            with open(f, encoding="utf-8", errors="replace") as src:
                pending_tasks, _ = parse(src.read())
            pending_slugs.update(t.get("slug") for t in pending_tasks if t.get("slug"))
        except OSError:
            pass
    existing = _existing_live_slugs(pending_slugs)
    total = 0
    for f in sorted(files):
        try:
            c, s = ingest_file(f, projects_by_name, existing=existing)
            stamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            shutil.move(f, os.path.join(PROCESSED, f"{stamp}-{os.path.basename(f)}"))
            print(f"intake: {os.path.basename(f)} -> {c} queued, {s} skipped")
            total += c
        except Exception as e:
            print(f"intake: failed on {f}: {e}")  # leave the file in place to retry
    return total + dropbox_total


if __name__ == "__main__":
    run()

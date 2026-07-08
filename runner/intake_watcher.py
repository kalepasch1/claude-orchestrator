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
import os, sys, re, glob, json, datetime, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import pipeline_contract

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
        kv = re.match(r"^(title|material|model|depends|proof|prompt):\s*(.*)$", s)
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
        db.insert("approvals", {
            "project": proj_name, "kind": kind, "title": title,
            "why": "Needs a human — secrets / deploys / OAuth / legal sign-off the runner can't do.",
            "value": "Unblocks dependent tasks once done; Approve = authorized/completed, Deny = not yet.",
            "risk": "Dependent tasks stay blocked until this is approved.",
            "detail": f"{o}\n\n(from intake/{src})"})
        existing_titles.add(title)
        created += 1
    return created


def ingest_file(path, projects_by_name):
    text = open(path, encoding="utf-8", errors="replace").read()
    tasks, operator = parse(text)
    existing = {t["slug"] for t in (db.select("tasks", {"select": "slug"}) or [])}
    created, skipped = 0, 0
    for t in tasks:
        proj = projects_by_name.get(t["project"])
        if not proj:
            print(f"intake: unknown project '{t['project']}' (slug {t['slug']}) — skipped")
            skipped += 1; continue
        if t["slug"] in existing:
            skipped += 1; continue
        raw_prompt = (t["prompt"] + (f"\n\nProof: {t['proof']}" if t["proof"] else ""))
        row = {"project_id": proj["id"], "slug": t["slug"],
               "prompt": pipeline_contract.wrap_prompt(raw_prompt, project=t["project"],
                                                        kind="build", source="intake-file",
                                                        slug=t["slug"], material=bool(t["material"])),
               "base_branch": proj.get("default_base", "main"), "kind": "build",
               "state": "QUEUED", "deps": t["depends"], "material": bool(t["material"]),
               "note": pipeline_contract.note(source="intake-file")}
        if t.get("model"):
            row["model"] = t["model"]
        db.insert("tasks", row)
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


def _default_project_for_dropbox(text, projects_by_name):
    """Heuristic project resolution for freeform prompts, which don't declare PROJECT: by
    definition. Looks for a known project name mentioned early in the text; falls back to
    'beethoven' (the orchestrator's own project) since operator-authored strategic PROMPT-*.md
    drops most commonly target the orchestrator improving itself — the two real examples this
    feature was built for (PROMPT-backlog-blitz.md, PROMPT-meta-optimizer.md) both do."""
    head = (text or "")[:2000].lower()
    for name in projects_by_name:
        if name and name.lower() in head:
            return name
    return "beethoven" if "beethoven" in projects_by_name else (next(iter(projects_by_name), None))


def decompose_freeform(text, repo_root, default_project):
    """Contract-first DAG decomposition of a freeform prompt via planner.py (the same engine
    prompt_factory.py uses for objectives). Returns a list of task dicts shaped like parse()'s
    output, ready for the same insertion path ingest_file() uses. Raises on planner failure —
    callers decide how to handle that (planner.plan() itself already falls back to a single
    master-task rather than raising in the common case; this only raises on a harder failure,
    e.g. planner.py itself being unimportable)."""
    import planner
    tasks = planner.plan(text, repo=repo_root)
    slug_base = _dropbox_slugify((text.strip().splitlines() or [""])[0])
    rendered = []
    for t in tasks:
        rendered.append({
            "project": default_project,
            "slug": f"dropbox-{slug_base}-{t['slug']}",
            "material": False,
            "model": t.get("model_hint"),
            "depends": [f"dropbox-{slug_base}-{d}" for d in (t.get("deps") or [])],
            "proof": _extract_proof_line(t.get("prompt")),
            "prompt": t.get("prompt") or "",
        })
    return rendered


def _queue_dropbox_tasks(rendered, projects_by_name):
    existing = {t["slug"] for t in (db.select("tasks", {"select": "slug"}) or [])}
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
        if t.get("model"):
            row["model"] = t["model"]
        db.insert("tasks", row)
        existing.add(t["slug"]); created += 1
    return created, skipped


def ingest_dropbox_prompts(projects_by_name):
    """Scan repo root for PROMPT-*.md files that are NOT canonical format and auto-decompose
    them. Idempotent the same way as ingest_file(): the source file is moved into
    intake/processed/ once handled, so re-running never reprocesses it. Fail-soft per file — one
    bad drop doesn't block the others."""
    files = [f for f in glob.glob(os.path.join(REPO_ROOT, "PROMPT-*.md")) if os.path.isfile(f)]
    total = 0
    for f in sorted(files):
        try:
            text = open(f, encoding="utf-8", errors="replace").read()
        except Exception as e:
            print(f"intake: dropbox read failed on {f}: {e}"); continue
        if is_canonical(text):
            continue  # already canonical — nothing to decompose, leave it for a human to move
        default_project = _default_project_for_dropbox(text, projects_by_name)
        if not default_project or default_project not in projects_by_name:
            print(f"intake: dropbox {os.path.basename(f)} — no resolvable project, skipped")
            continue
        try:
            rendered = decompose_freeform(text, REPO_ROOT, default_project)
        except Exception as e:
            print(f"intake: dropbox decomposition failed on {f}: {e}"); continue
        if not rendered:
            continue
        created, skipped = _queue_dropbox_tasks(rendered, projects_by_name)
        stamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        try:
            shutil.move(f, os.path.join(PROCESSED, f"{stamp}-dropbox-{os.path.basename(f)}"))
        except Exception as e:
            print(f"intake: dropbox move failed on {f}: {e}")
        print(f"intake: dropbox {os.path.basename(f)} -> {created} queued, {skipped} skipped")
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
    total = 0
    for f in sorted(files):
        try:
            c, s = ingest_file(f, projects_by_name)
            stamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            shutil.move(f, os.path.join(PROCESSED, f"{stamp}-{os.path.basename(f)}"))
            print(f"intake: {os.path.basename(f)} -> {c} queued, {s} skipped")
            total += c
        except Exception as e:
            print(f"intake: failed on {f}: {e}")  # leave the file in place to retry
    return total + dropbox_total


if __name__ == "__main__":
    run()

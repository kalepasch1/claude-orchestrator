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
"""
import os, sys, re, glob, json, datetime, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import pipeline_contract

HERE = os.path.dirname(os.path.abspath(__file__))
INTAKE = os.path.abspath(os.path.join(HERE, "..", "intake"))
PROCESSED = os.path.join(INTAKE, "processed")


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


def run():
    os.makedirs(PROCESSED, exist_ok=True)
    files = [f for f in glob.glob(os.path.join(INTAKE, "*.md")) if os.path.isfile(f)]
    if not files:
        print("intake: nothing to ingest"); return 0
    projects_by_name = {p["name"]: p for p in (db.select("projects") or [])}
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
    return total


if __name__ == "__main__":
    run()

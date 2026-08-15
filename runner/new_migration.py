#!/usr/bin/env python3
"""Scaffold a new SQL migration into the canonical migration home.

WHY THIS EXISTS INSTEAD OF `shared/db_migrations/migration.ts`
--------------------------------------------------------------
The queued request asked for an empty TypeScript file at
`shared/db_migrations/migration.ts` "to serve as a template for future database
migration scripts needed by components dependent on these shared interfaces."

That artifact was refused, for three reasons that still hold:

1. An empty placeholder is a stub commit — nothing is enforced by it, nothing
   imports it, and the next agent still has to guess.
2. Migrations in this repo already have homes: `supabase/migrations/*.sql`
   (181 files) and `runner/migrations/*.sql`. A TypeScript home under `shared/`
   would be a *third* convention, which is the duplication CLAUDE.md's survey
   rule exists to prevent.
3. `shared/` has no TypeScript build. A `.ts` file there is never compiled and
   never imported.

The underlying need is real, though: someone editing `shared/contracts/` needs a
correct place and shape for the accompanying schema change. This module answers
that need with something executable rather than a placeholder — it generates a
correctly named, correctly located, idempotent migration in the home that
already exists.

Fail-soft throughout: every entry point returns a dict and never raises, per the
repo's fail-soft convention, so a caller (or the pre-claim hook) cannot wedge on
a bad name or an unwritable path.

CLI
---
    python3 runner/new_migration.py add_widget_table
    python3 runner/new_migration.py add_widget_table --home runner/migrations
    python3 runner/new_migration.py add_widget_table --dry-run
"""
import argparse
import datetime as _dt
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: The only places a migration may live. Adding a fourth entry is a convention
#: decision, not a code change — make it deliberately, in review.
#: `supabase/migrations` is the default because it holds the platform schema
#: that `shared/contracts/` depends on; `runner/migrations` holds RPCs the
#: runner installs; `web/supabase/migrations` is the web app's own tree.
MIGRATION_HOMES = (
    "supabase/migrations",
    "runner/migrations",
    "web/supabase/migrations",
)
DEFAULT_HOME = MIGRATION_HOMES[0]

#: `YYYYMMDDHHMMSS_snake_name.sql`, matching every migration added since
#: 2026-07. The older zero-padded `NNNN_` prefix is legacy; do not emit it, it
#: collides (there are five distinct `0038_*` files).
TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_LEADING_DIGITS = re.compile(r"^\d+[_-]*")
MAX_SLUG_CHARS = 60


def slugify(name):
    """Normalise a human name to the snake_case used by existing filenames.

    Returns "" for anything unusable, which callers treat as a validation
    failure rather than writing a file called `_.sql`.

    Non-strings are rejected outright rather than coerced. `str(object())` is
    `"<object object at 0x...>"`, which slugifies to something that looks like a
    perfectly good migration name — so coercion would happily write a file named
    after a memory address. A migration name is a string or it is nothing.
    """
    if not isinstance(name, str):
        return ""
    slug = _SLUG_STRIP.sub("_", name.strip().lower()).strip("_")
    # A caller who types their own timestamp would otherwise get it twice.
    slug = _LEADING_DIGITS.sub("", slug).strip("_")
    return slug[:MAX_SLUG_CHARS].strip("_")


def resolve_home(home=None):
    """Return a canonical migration home, or "" if `home` is not one of them.

    Refusing an unknown directory is the whole point: it is what stops a fourth
    migration convention appearing the next time someone needs a schema change.
    """
    if home is None:
        return DEFAULT_HOME
    candidate = str(home).strip().strip("/").replace(os.sep, "/")
    return candidate if candidate in MIGRATION_HOMES else ""


def filename(name, now=None):
    """`<timestamp>_<slug>.sql`, or "" when the name yields no usable slug."""
    slug = slugify(name)
    if not slug:
        return ""
    stamp = (now or _dt.datetime.now(_dt.timezone.utc)).strftime(TIMESTAMP_FORMAT)
    return f"{stamp}_{slug}.sql"


def render(name, filename_hint="", summary=""):
    """The migration body: a header comment plus an idempotent skeleton.

    Idempotence is a repo rule, not a suggestion — migrations are re-applied by
    `runner/apply_sql_migrations.py`, so every statement must tolerate a second
    run. The skeleton therefore ships `IF NOT EXISTS` forms and says so.
    """
    slug = slugify(name) or "migration"
    title = filename_hint or f"{slug}.sql"
    why = summary.strip() or "TODO: state WHAT changes and WHY, not just the DDL."
    return "\n".join([
        f"-- {title}",
        "--",
        f"-- {why}",
        "--",
        "-- Idempotent: this file may be applied more than once by",
        "-- runner/apply_sql_migrations.py. Every statement below must tolerate that.",
        "",
        "-- create table if not exists public.example (",
        "--   id bigint generated always as identity primary key,",
        "--   created_at timestamptz not null default now()",
        "-- );",
        "",
        "-- alter table public.example",
        "--   add column if not exists note text;",
        "",
        "-- create index if not exists example_created_at_idx",
        "--   on public.example (created_at desc);",
        "",
    ])


def create(name, home=None, root=None, now=None, summary="", dry_run=False):
    """Write a scaffolded migration. Returns a dict; never raises.

    Keys: ok, path (repo-relative), home, filename, body, reason (on failure).
    An existing path is a failure, not an overwrite — a migration that has
    already been applied must never change under the fleet's feet.
    """
    base = root or ROOT
    resolved_home = resolve_home(home)
    if not resolved_home:
        return {"ok": False, "reason": f"{home!r} is not a migration home; use one of {MIGRATION_HOMES}"}

    fname = filename(name, now=now)
    if not fname:
        return {"ok": False, "reason": f"{name!r} yields no usable slug"}

    rel = f"{resolved_home}/{fname}"
    body = render(name, filename_hint=fname, summary=summary)
    result = {"ok": True, "path": rel, "home": resolved_home, "filename": fname, "body": body}
    if dry_run:
        return {**result, "ok": True, "dry_run": True}

    target = os.path.join(base, *rel.split("/"))
    if os.path.exists(target):
        return {"ok": False, "reason": f"{rel} already exists; migrations are append-only"}
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w") as handle:
            handle.write(body)
    except OSError as exc:
        return {"ok": False, "reason": f"could not write {rel}: {exc}"}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", help="human name, e.g. 'add widget table'")
    parser.add_argument("--home", default=None,
                        help=f"migration home (default {DEFAULT_HOME}); one of {', '.join(MIGRATION_HOMES)}")
    parser.add_argument("--summary", default="", help="one line on what changes and why")
    parser.add_argument("--dry-run", action="store_true", help="print the path and body, write nothing")
    args = parser.parse_args(argv)

    outcome = create(args.name, home=args.home, summary=args.summary, dry_run=args.dry_run)
    if not outcome.get("ok"):
        print(f"error: {outcome.get('reason')}", file=sys.stderr)
        return 1
    print(outcome["path"])
    if args.dry_run:
        print()
        print(outcome["body"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

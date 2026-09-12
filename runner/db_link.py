#!/usr/bin/env python3
"""
db_link.py — the operator CLI for Database Steering: link, test, scan, read.

Linking a database takes one command and never handles the secret value directly — the
command takes a REFERENCE to where the secret lives, exactly like secrets_manager:

    # Supabase: nothing to link — every project the fleet token can see is auto-discovered.
    python3 runner/db_link.py discover

    # AWS RDS / Aurora Postgres, password in the macOS keychain (security add-generic-password -s RDS_PROD_PW -w)
    python3 runner/db_link.py add aws_rds prod-cluster.abc.us-east-1.rds.amazonaws.com \
        --project tomorrow --label "tomorrow prod (RDS)" --region us-east-1 \
        --config database=app --config username=readonly --credential keychain:RDS_PROD_PW

    # AWS via the Data API instead of a network path
    python3 runner/db_link.py add aws_aurora arn:aws:rds:us-east-1:123:cluster:prod \
        --config resource_arn=arn:aws:rds:... --config secret_arn=arn:aws:secretsmanager:... --config engine=postgres

    # Google Cloud SQL (through the auth proxy on localhost, or a public IP)
    python3 runner/db_link.py add gcp_cloudsql myproj:us-central1:main --config host=127.0.0.1 \
        --config port=5433 --config database=app --config username=steering --credential env:CLOUDSQL_STEERING_PW

    # BigQuery with a service-account JSON kept in 1Password
    python3 runner/db_link.py add gcp_bigquery my-gcp-project --credential onepassword:op://Infra/bq-steering/credential

    # Any Postgres / MySQL by DSN reference
    python3 runner/db_link.py add postgres db.example.com --credential env:ANALYTICS_DSN --project smarter

Then:
    python3 runner/db_link.py test <source-id|provider:ref>   # connectivity + capabilities, read-only
    python3 runner/db_link.py scan <source-id|provider:ref> [--tiers cheap,medium,heavy] [--write]
    python3 runner/db_link.py list | pause <id> | resume <id> | remove <id>
    python3 runner/db_link.py brief <project>                  # what coder agents are being told
    python3 runner/db_link.py memos <project> [--render <memo_kind>]

Read-only guarantees: `test` and `scan` send only SELECTs (db_steering_contract.assert_read_only
sits in the adapter); `scan` writes findings to the fleet control plane only with --write.
The web dashboard offers the same linking through Connectors -> Databases, storing the
credential encrypted; the runner resolves it as `vault:<connector-account-id>`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db_registry  # noqa: E402
import db_steering_contract as C  # noqa: E402


def _resolve(ident):
    ident = str(ident or "").strip()
    if ":" in ident and not ident.count("-") >= 4:
        prov, ref = ident.split(":", 1)
        return db_registry.get_source(provider=prov, ref=ref)
    return db_registry.get_source(source_id=ident)


def _kv(pairs):
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise SystemExit("--config expects key=value, got %r" % p)
        k, v = p.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def cmd_list(a):
    rows = db_registry.list_sources(project=a.project)
    if a.json:
        print(json.dumps(rows, indent=2, default=str))
        return 0
    print("%-36s %-13s %-26s %-22s %-11s %-4s %-10s %s" % ("id", "provider", "ref", "project", "status", "on", "cred", "last scan"))
    for s in rows:
        print("%-36s %-13s %-26s %-22s %-11s %-4s %-10s %s" % (
            s.get("id"), s.get("provider"), (s.get("ref") or "")[:26], (s.get("project") or "-")[:22],
            s.get("status"), "yes" if s.get("enabled") else "no",
            (s.get("credential_ref") or "fleet-token").split(":")[0], (s.get("last_scan_at") or "never")[:19]))
    return 0


def cmd_discover(a):
    print(json.dumps(db_registry.discover(force=True), indent=2))
    if a.sync_posture:
        print(json.dumps({"security_posture_added": db_registry.sync_security_posture()}))
    return 0


def cmd_add(a):
    row, err = db_registry.add(a.provider, a.ref, label=a.label, project=a.project,
                               credential_ref=a.credential, region=a.region, config=_kv(a.config),
                               dialect=a.dialect, enabled=not a.paused)
    if err:
        print("error: " + err)
        return 2
    print(json.dumps({"linked": {k: row.get(k) for k in ("id", "provider", "ref", "project", "dialect", "status")}}, indent=2))
    if a.test:
        a.ident = row["id"]
        return cmd_test(a)
    return 0


def cmd_test(a):
    s = _resolve(a.ident)
    if not s:
        print("no such source: %s" % a.ident)
        return 2
    import db_adapters
    try:
        caps = db_adapters.capabilities(s)
        rows = db_adapters.query(s, "select 1 as ok", timeout=15)
        print(json.dumps({"source": db_adapters.describe(s), "reachable": bool(rows), "capabilities": caps}, indent=2, default=str))
        return 0
    except Exception as e:
        print(json.dumps({"source": s.get("label"), "reachable": False, "error": "%s: %s" % (type(e).__name__, str(e)[:300])}, indent=2))
        return 1


def cmd_scan(a):
    s = _resolve(a.ident)
    if not s:
        print("no such source: %s" % a.ident)
        return 2
    import db_steering
    tiers = tuple(t.strip() for t in (a.tiers or "cheap,medium,heavy").split(",") if t.strip())
    for t in tiers:
        if t not in C.PROBE_TIERS:
            print("unknown tier %r" % t)
            return 2
    res = db_steering.scan_source(s, tiers=tiers, dry_run=not a.write)
    findings = res.get("findings") or []
    gaps = [f for f in findings if f.get("direction", "undermines") == "undermines"]
    if a.json:
        print(json.dumps(res, indent=2, default=str))
        return 0
    print("source: %s   ok=%s   probes=%d   findings=%d (gaps %d, positives %d)   %sms%s" % (
        s.get("label"), res.get("ok"), len(res.get("results") or []), len(findings), len(gaps),
        len(findings) - len(gaps), res.get("duration_ms"), "" if a.write else "   [dry run — nothing written]"))
    if res.get("error"):
        print("error: %s" % res["error"])
    for r in res.get("results") or []:
        if not r.get("ok"):
            print("  probe %-32s FAILED %s" % (r.get("probe_id"), str(r.get("error"))[:120]))
    gaps.sort(key=lambda f: -C.SEVERITY_RANK.get(f.get("severity"), 0))
    for f in gaps[: a.limit]:
        obj = ("%s.%s" % (f.get("object_schema") or "", f.get("object_name") or "")).strip(".")
        print("  [%-8s] %-30s %-40s %s" % (f["severity"], f["probe_id"], obj[:40], f["title"][:90]))
    if a.write:
        d = res.get("delta") or {}
        print("written: %d new, %d resolved, %d updated" % (len(d.get("new") or []), len(d.get("resolved") or []), d.get("updated") or 0))
    return 0


def cmd_toggle(a, enabled):
    s = _resolve(a.ident)
    if not s:
        print("no such source: %s" % a.ident)
        return 2
    ok = db_registry.set_enabled(s["id"], enabled)
    print(json.dumps({"id": s["id"], "enabled": enabled, "ok": ok}))
    return 0 if ok else 1


def cmd_remove(a):
    s = _resolve(a.ident)
    if not s:
        print("no such source: %s" % a.ident)
        return 2
    ok = db_registry.remove(s["id"])
    print(json.dumps({"removed": s["id"], "ok": ok}))
    return 0 if ok else 1


def cmd_brief(a):
    import db_steering
    text = db_steering.steering_brief(a.project)
    print(text or "(no brief yet for %s — no open gaps, or the loop has not scanned it)" % a.project)
    return 0


def cmd_memos(a):
    import db_memo
    if a.render:
        import db
        rows = db.select("legal_memo_drafts", {"select": "*", "project": "eq.%s" % a.project,
                                               "memo_kind": "eq.%s" % a.render, "limit": "1"}) or []
        if not rows:
            print("no memo %s for %s" % (a.render, a.project))
            return 2
        ev = db.select_all("legal_memo_evidence", {"select": "*", "memo_id": "eq.%s" % rows[0]["id"]},
                           order="argument_key.asc,id.asc") or []
        print(rows[0].get("body") or db_memo.render_markdown(rows[0], ev))
        return 0
    print(json.dumps(db_memo.memo_summary(a.project), indent=2, default=str))
    return 0


DOCTOR_DRIVERS = (
    # (import name, which providers/dialects it unlocks, install hint)
    ("psycopg", "postgres wire: postgres, aws-rds (wire), gcp-cloudsql, neon, cockroachdb, azure-postgres", "pip install psycopg[binary]"),
    ("psycopg2", "postgres wire (fallback for psycopg)", "pip install psycopg2-binary"),
    ("pymysql", "mysql, planetscale, aws-rds mysql", "pip install pymysql"),
    ("mysql.connector", "mysql (fallback for pymysql)", "pip install mysql-connector-python"),
    ("boto3", "aws-rds through the RDS Data API", "pip install boto3"),
    ("google.cloud.bigquery", "gcp-bigquery", "pip install google-cloud-bigquery"),
    ("snowflake.connector", "snowflake", "pip install snowflake-connector-python"),
)
DOCTOR_CLIS = (
    ("psql", "postgres wire fallback when no python driver is installed"),
    ("mysql", "mysql fallback when no python driver is installed"),
    ("bq", "bigquery fallback when google-cloud-bigquery is absent"),
    ("security", "keychain: credential references (macOS)"),
    ("doppler", "doppler: credential references"),
    ("op", "onepassword: credential references"),
)
DOCTOR_ENV = (
    ("SUPABASE_ACCESS_TOKEN", "Supabase auto-discovery, Management-API queries and advisors"),
    ("CONNECTOR_VAULT_KEY", "decrypting vault: credentials linked through the dashboard"),
    ("ORCH_DB_STEERING_BUDGET_S", "per-cycle wall-clock budget (default 240)"),
    ("ORCH_DB_MEMO_GAUNTLET", "expert-corps gauntlet on material memo changes (default true)"),
)


def cmd_doctor(a):
    """Report which optional drivers, CLIs and env keys are present. Never prints a value."""
    import importlib
    import shutil
    lines, missing = [], 0
    lines.append("python drivers")
    for mod, unlocks, hint in DOCTOR_DRIVERS:
        try:
            importlib.import_module(mod)
            ok = True
        except Exception:
            ok = False
        missing += 0 if ok else 1
        lines.append("  %-4s %-24s %s%s" % ("ok" if ok else "--", mod, unlocks, "" if ok else "  (%s)" % hint))
    lines.append("command-line tools")
    for exe, unlocks in DOCTOR_CLIS:
        ok = bool(shutil.which(exe))
        missing += 0 if ok else 1
        lines.append("  %-4s %-24s %s" % ("ok" if ok else "--", exe, unlocks))
    lines.append("environment (presence only; values are never printed)")
    for key, unlocks in DOCTOR_ENV:
        ok = bool(os.environ.get(key))
        lines.append("  %-4s %-24s %s" % ("set" if ok else "--", key, unlocks))
    lines.append("control plane")
    try:
        import db
        n = db.count("db_sources", {"enabled": "eq.true"})
        lines.append("  ok   db_sources                %s enabled source(s) reachable" % n)
    except Exception as e:
        lines.append("  --   db_sources                unreachable: %s: %s" % (type(e).__name__, str(e)[:80]))
    try:
        import db_probes
        counts = {d: len(db_probes.probes_for(d)) for d in C.DIALECTS}
        lines.append("  ok   probes                    %d registered (%s)" % (
            len(db_probes.PROBES), ", ".join("%s=%d" % (d, n) for d, n in sorted(counts.items()) if n)))
    except Exception as e:
        lines.append("  --   probes                    %s: %s" % (type(e).__name__, str(e)[:80]))
    if a.json:
        print(json.dumps({"lines": lines, "missing_optional": missing}, indent=2))
    else:
        print("\n".join(lines))
        print("Supabase sources need no driver: they use the Management API with SUPABASE_ACCESS_TOKEN.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="db_link", description="Database Steering: link, test, scan, read")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list"); p.add_argument("--project"); p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_list)
    p = sub.add_parser("discover"); p.add_argument("--sync-posture", action="store_true"); p.set_defaults(fn=cmd_discover)
    p = sub.add_parser("add")
    p.add_argument("provider", choices=C.PROVIDERS); p.add_argument("ref")
    p.add_argument("--label"); p.add_argument("--project"); p.add_argument("--region"); p.add_argument("--dialect", choices=C.DIALECTS)
    p.add_argument("--credential", help="reference only: env:NAME | keychain:NAME | doppler:PATH | onepassword:op://... | vault:<id> | file:/path")
    p.add_argument("--config", action="append", default=[], help="key=value (host, port, database, username, engine, resource_arn, secret_arn, project_id, dataset)")
    p.add_argument("--paused", action="store_true"); p.add_argument("--test", action="store_true")
    p.set_defaults(fn=cmd_add)
    p = sub.add_parser("test"); p.add_argument("ident"); p.set_defaults(fn=cmd_test)
    p = sub.add_parser("scan"); p.add_argument("ident"); p.add_argument("--tiers"); p.add_argument("--write", action="store_true")
    p.add_argument("--limit", type=int, default=40); p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_scan)
    p = sub.add_parser("pause"); p.add_argument("ident"); p.set_defaults(fn=lambda a: cmd_toggle(a, False))
    p = sub.add_parser("resume"); p.add_argument("ident"); p.set_defaults(fn=lambda a: cmd_toggle(a, True))
    p = sub.add_parser("remove"); p.add_argument("ident"); p.set_defaults(fn=cmd_remove)
    p = sub.add_parser("brief"); p.add_argument("project"); p.set_defaults(fn=cmd_brief)
    p = sub.add_parser("memos"); p.add_argument("project"); p.add_argument("--render"); p.set_defaults(fn=cmd_memos)
    p = sub.add_parser("doctor", help="report which optional drivers, CLIs and env keys are present")
    p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_doctor)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
db_adapters.py — one READ-ONLY query surface across every database provider the fleet links.

WHY THIS EXISTS. Database Steering (see db_steering_contract) runs a catalog of deterministic
probes against every registered source: Supabase projects reached through the Management
API, plain Postgres / Neon / RDS / Cloud SQL reached with a driver, MySQL, BigQuery,
Snowflake. db_probes must not know how any of them are reached. This module is the seam:
`query(source, sql)` returns rows as a list of dicts, whatever the transport, and every
other public helper here is fail-soft so a broken driver degrades one source, not the loop.

SAFETY. Two rules are non-negotiable and both are enforced here, not left to callers:

  1. Every statement goes through `db_steering_contract.assert_read_only()` BEFORE any
     network I/O. That raises `ReadOnlyViolation` — deliberately loud, because a probe that
     ships a write shape is a programming error we want to fail its own unit test, not a
     runtime condition to absorb. Every other failure (network, driver, bad credential,
     SQL error) is normalised to `AdapterError` with a secret-free message.
  2. Credentials are REFERENCES (`env:NAME`, `keychain:NAME`, `doppler:PATH`,
     `onepassword:op://…`, `file:/abs/path`, `vault:<connector_account_uuid>`). A raw DSN
     or password in `credential_ref` is refused. A resolved value is returned to the
     transport and nowhere else: never logged, never placed in an exception, and scrubbed
     out of driver error text before it becomes an AdapterError.

DRIVERS. Every third-party driver is imported lazily inside the transport that needs it, so
this module imports on a runner with none of them installed. Missing driver -> AdapterError
("driver missing: pip install …") at query time, with a CLI fallback (psql / mysql / bq)
when one is on PATH. Connections are opened per query and closed; the loop runs a few dozen
cheap statements per source per run, pooling would buy nothing and hide leaks.

Tunables (ORCH_ prefix, all optional):
  ORCH_DB_PROBE_TIMEOUT_S   per-statement timeout, also sent as statement_timeout (20)
  ORCH_DB_PROBE_MAX_ROWS    rows returned per statement are truncated to this (500)
  ORCH_DB_BQ_MAX_BYTES      BigQuery maximum_bytes_billed guard (2 GB)
"""
from __future__ import annotations

import base64
import csv
import hashlib
import importlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db  # noqa: E402  (vault: credentials live in connector_accounts)
from db_steering_contract import (  # noqa: E402
    PROVIDER_DEFAULT_DIALECT, ReadOnlyViolation, assert_read_only, credential_ref_is_reference,
)

DEFAULT_TIMEOUT_S = float(os.environ.get("ORCH_DB_PROBE_TIMEOUT_S", "20"))
MAX_ROWS = int(os.environ.get("ORCH_DB_PROBE_MAX_ROWS", "500"))
BQ_MAX_BYTES = int(os.environ.get("ORCH_DB_BQ_MAX_BYTES", "2000000000"))

_MGMT_BASE = "https://api.supabase.com/v1"
# Same transient class rls_guard learned the hard way: 409 while another operation holds
# the project, 429 rate limit, 5xx. Anything else (401/404) is permanent; retrying delays.
_RETRY_STATUS = (409, 429, 500, 502, 503, 504)
_RETRY_BACKOFF_S = (1.0, 2.0, 4.0)

_PG_DIALECT_PROVIDERS = ("postgres", "supabase", "neon", "cockroachdb", "aws_rds", "aws_aurora",
                         "aws_redshift", "gcp_cloudsql", "gcp_alloydb", "azure_postgres")
_UUID_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")


class AdapterError(RuntimeError):
    """A transport/driver/credential failure. Message is secret-free by construction."""


def _log(msg):
    print(f"db_adapters: {msg}")


def _sleep(seconds):
    """Indirection so tests do not wait out the backoff."""
    time.sleep(seconds)


def _import(name):
    """Lazy driver import. None when absent (or when the driver itself explodes on import,
    which some binary wheels do on a mismatched Python — logged, not raised)."""
    try:
        return importlib.import_module(name)
    except ImportError:
        return None
    except Exception as e:
        _log(f"import {name} failed: {type(e).__name__}")
        return None


# ── source helpers ─────────────────────────────────────────────────────────────────────

def dialect_of(source) -> str:
    s = source or {}
    return str(s.get("dialect") or PROVIDER_DEFAULT_DIALECT.get(str(s.get("provider") or ""), "other"))


def describe(source) -> str:
    """Secret-free one-liner for logs: 'supabase:cwmeqq… (apparently-law)'."""
    s = source or {}
    ref = str(s.get("ref") or "")
    short = ref if len(ref) <= 8 else ref[:6] + "…"
    who = s.get("project") or s.get("label") or ""
    return f"{s.get('provider') or '?'}:{short}" + (f" ({who})" if who else "")


def _scrub(text, secrets) -> str:
    """Remove every resolved secret value from driver/CLI error text."""
    out = str(text or "")
    for val in secrets or ():
        v = str(val or "")
        if len(v) >= 4:
            out = out.replace(v, "***")
            try:
                out = out.replace(urllib.parse.quote(v, safe=""), "***")
            except Exception:
                pass
    return out


def _truncate(rows) -> list:
    if not isinstance(rows, list):
        rows = list(rows or [])
    out = []
    for r in rows[:MAX_ROWS]:
        out.append(r if isinstance(r, dict) else {"value": r})
    return out


# ── public: query ──────────────────────────────────────────────────────────────────────

def query(source: dict, sql: str, timeout: float = None) -> list:  # noqa: FAIL_SOFT_ERROR — a read-only guard that fails soft is not a guard; callers catch AdapterError
    """Run ONE read statement against `source`; rows as a list of dicts (<= MAX_ROWS).

    Raises ReadOnlyViolation for a non-read statement (before any I/O) and AdapterError for
    every transport failure. Callers catch AdapterError; nobody should catch the former.
    """
    assert_read_only(sql)  # the chokepoint — deliberately before anything else
    source = source or {}
    timeout = float(timeout or DEFAULT_TIMEOUT_S)
    provider = str(source.get("provider") or "other")
    dialect = dialect_of(source)
    cfg = source.get("config") or {}
    if dialect == "mongodb":
        raise AdapterError("mongodb sources are inventoried but not probed in this version")
    ctx = {"secrets": []}
    try:
        if provider == "supabase":
            rows = _supabase_query(source, sql, timeout)
        elif provider in ("aws_rds", "aws_aurora") and cfg.get("resource_arn") and cfg.get("secret_arn"):
            rows = _rds_data_api_query(source, sql, timeout)
        elif dialect == "postgres":
            rows = _pg_query(source, sql, timeout, ctx)
        elif dialect == "mysql":
            rows = _mysql_query(source, sql, timeout, ctx)
        elif dialect == "bigquery":
            rows = _bigquery_query(source, sql, timeout, ctx)
        elif dialect == "snowflake":
            rows = _snowflake_query(source, sql, timeout, ctx)
        else:
            raise AdapterError(f"unsupported provider/dialect {provider}/{dialect}")
    except AdapterError as e:
        raise AdapterError(_scrub(str(e), ctx["secrets"])[:500]) from None
    except Exception as e:
        # Driver exceptions can echo connection info; scrub and re-type, never re-raise raw.
        raise AdapterError(f"{type(e).__name__}: {_scrub(str(e), ctx['secrets'])[:400]}") from None
    return _truncate(rows)


# ── public: capabilities / advisors ────────────────────────────────────────────────────

def capabilities(source) -> dict:
    """What this source supports, cheaply and fail-soft. Never raises."""
    source = source or {}
    dialect = dialect_of(source)
    caps = {"advisors": False, "pg_stat_statements": False, "dialect": dialect, "version": None}
    try:
        if dialect == "mongodb":
            return caps
        if str(source.get("provider")) == "supabase":
            caps["advisors"] = bool(os.environ.get("SUPABASE_ACCESS_TOKEN"))
        if dialect == "postgres":
            try:
                rows = query(source, "select extname from pg_extension where extname = 'pg_stat_statements'")
                caps["pg_stat_statements"] = len(rows) > 0
            except Exception as e:
                _log(f"capabilities {describe(source)}: pg_stat_statements probe failed ({e})")
            caps["version"] = _first_value(source, ("show server_version", "select version() as version"))
        elif dialect == "mysql":
            caps["version"] = _first_value(source, ("select version() as version",))
        elif dialect == "snowflake":
            caps["version"] = _first_value(source, ("select current_version() as version",))
    except Exception as e:
        _log(f"capabilities {describe(source)}: {type(e).__name__}: {e}")
    return caps


def _first_value(source, statements):
    for sql in statements:
        try:
            rows = query(source, sql)
            if rows and isinstance(rows[0], dict) and rows[0]:
                return str(next(iter(rows[0].values())))
        except Exception as e:
            _log(f"capabilities {describe(source)}: {sql!r} failed ({e})")
    return None


def supabase_advisors(source, kind: str, timeout: float = None) -> list:
    """Supabase advisor lints (security | performance): a FREE, zero-model-cost signal.
    Empty list on any failure (one log line)."""
    source = source or {}
    if kind not in ("security", "performance"):
        _log(f"advisors: unknown kind {kind!r}")
        return []
    token = os.environ.get("SUPABASE_ACCESS_TOKEN")
    if not token:
        _log("advisors: SUPABASE_ACCESS_TOKEN unset; skipping")
        return []
    ref = str(source.get("ref") or "")
    try:
        data = _mgmt_json(f"{_MGMT_BASE}/projects/{ref}/advisors/{kind}", "GET", None, token,
                          float(timeout or DEFAULT_TIMEOUT_S))
    except Exception as e:
        _log(f"advisors {kind} {describe(source)}: {e}")
        return []
    lints = data.get("lints") if isinstance(data, dict) else data
    if not isinstance(lints, list):
        return []
    return [lint for lint in lints if isinstance(lint, dict)]


# ── supabase management api ────────────────────────────────────────────────────────────

def _mgmt_json(url, method, body, token, timeout, retries=_RETRY_BACKOFF_S):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    attempts = len(retries) + 1
    for attempt in range(attempts):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        except urllib.error.HTTPError as e:
            if e.code not in _RETRY_STATUS or attempt == attempts - 1:
                try:
                    snippet = e.read()[:300].decode("utf-8", "replace")
                except Exception:
                    snippet = ""
                raise AdapterError(f"supabase HTTP {e.code} {snippet}".strip())
            delay = retries[attempt]
            _log(f"supabase HTTP {e.code}; retry {attempt + 1}/{len(retries)} in {delay}s")
            _sleep(delay)
        except urllib.error.URLError as e:
            raise AdapterError(f"supabase unreachable: {getattr(e, 'reason', e)}")
        except ValueError as e:
            raise AdapterError(f"supabase returned non-JSON: {e}")
    raise AdapterError("supabase: retries exhausted")  # unreachable, keeps the type checker honest


def _supabase_query(source, sql, timeout):
    token = os.environ.get("SUPABASE_ACCESS_TOKEN")
    if not token:
        raise AdapterError("SUPABASE_ACCESS_TOKEN unset")
    ref = str(source.get("ref") or "")
    if not ref:
        raise AdapterError("supabase source has no project ref")
    res = _mgmt_json(f"{_MGMT_BASE}/projects/{ref}/database/query", "POST", {"query": sql}, token, timeout)
    # The endpoint has answered both as a bare list and as {"result": [...]}.
    if isinstance(res, list):
        return res
    if isinstance(res, dict):
        if isinstance(res.get("result"), list):
            return res["result"]
        if res.get("message") or res.get("error"):
            raise AdapterError(f"supabase query error: {str(res.get('message') or res.get('error'))[:300]}")
    return []


# ── credentials ────────────────────────────────────────────────────────────────────────

def resolve_credential(ref: str):
    """Resolve a credential REFERENCE to its value, or None. The value is never logged."""
    s = str(ref or "").strip()
    if not s:
        return None
    if not credential_ref_is_reference(s):
        _log("credential_ref is not a reference (env:/keychain:/doppler:/onepassword:/vault:/file:); refusing")
        return None
    scheme, _, rest = s.partition(":")
    rest = rest.strip()
    try:
        if scheme == "env":
            return os.environ.get(rest) or None
        if scheme in ("keychain", "doppler", "onepassword"):
            return _read_store(scheme, rest)
        if scheme == "file":
            if not os.path.isabs(rest):
                _log("file: credential reference must be an absolute path")
                return None
            with open(rest, "r", encoding="utf-8") as fh:
                return fh.read().strip() or None
        if scheme == "vault":
            return _vault_resolve(rest)
    except Exception as e:
        # Type only: an OSError message can carry the path, a CLI error could carry anything.
        _log(f"credential {scheme}: resolution failed ({type(e).__name__})")
        return None
    return None


def _read_store(store, name):
    """Delegate to secrets_manager._read (stderr suppressed there); mirror it if absent."""
    sm = _import("secrets_manager")
    if sm is not None and hasattr(sm, "_read"):
        return sm._read(store, name) or None
    argv = {"keychain": ["security", "find-generic-password", "-s", name, "-w"],
            "doppler": ["doppler", "secrets", "get", name, "--plain"],
            "onepassword": ["op", "read", name]}[store]
    try:
        return subprocess.check_output(argv, text=True, stderr=subprocess.DEVNULL).strip() or None
    except Exception:
        return None


def _credential_fields(cred) -> dict:
    """A resolved credential is a DSN, a bare password, or a JSON object of fields."""
    if not cred:
        return {}
    s = str(cred).strip()
    if s.startswith("{"):
        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                return {str(k): v for k, v in obj.items()}
        except ValueError:
            pass
    if "://" in s or re.search(r"\b(host|dbname|user|password)\s*=", s):
        return {"dsn": s}
    return {"password": s}


# ── vault: (web dashboard connector credentials) ───────────────────────────────────────

def _b64url_decode(s: str) -> bytes:
    s = str(s or "").strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def decrypt_vault(ciphertext: str):
    """AES-256-GCM, key = sha256(CONNECTOR_VAULT_KEY), ciphertext = iv.tag.body (base64url,
    unpadded) — the web dashboard's connector vault format. None (one log line) when the
    key or the `cryptography` package is missing or the blob does not authenticate."""
    raw = os.environ.get("CONNECTOR_VAULT_KEY")
    if not raw:
        _log("CONNECTOR_VAULT_KEY unset; vault: credentials unavailable")
        return None
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        _log("cryptography package missing: pip install cryptography")
        return None
    try:
        parts = str(ciphertext or "").split(".")
        if len(parts) != 3:
            _log("vault ciphertext malformed (expected iv.tag.body)")
            return None
        iv, tag, body = (_b64url_decode(p) for p in parts)
        key = hashlib.sha256(raw.encode("utf-8")).digest()
        return AESGCM(key).decrypt(iv, body + tag, None).decode("utf-8")
    except Exception as e:
        _log(f"vault decrypt failed ({type(e).__name__})")
        return None


def _vault_resolve(account_id: str):
    if not _UUID_RE.match(account_id or ""):
        _log("vault: reference is not a connector account id")
        return None
    rows = db.select("connector_accounts", {"select": "access_token_ciphertext,provider,metadata",
                                            "id": f"eq.{account_id}", "limit": "1"}) or []
    if not rows:
        _log(f"vault: connector account {account_id[:8]}… not found")
        return None
    ciphertext = (rows[0] or {}).get("access_token_ciphertext")
    if not ciphertext:
        _log(f"vault: connector account {account_id[:8]}… has no ciphertext")
        return None
    return decrypt_vault(ciphertext)


# ── postgres dialect ───────────────────────────────────────────────────────────────────

def _parse_dsn(dsn: str) -> dict:
    out = {}
    s = str(dsn or "").strip()
    if "://" in s:
        u = urllib.parse.urlsplit(s)
        out = {"host": u.hostname, "port": u.port, "user": urllib.parse.unquote(u.username or ""),
               "password": urllib.parse.unquote(u.password or ""), "dbname": (u.path or "").lstrip("/")}
        for k, v in urllib.parse.parse_qsl(u.query):
            out.setdefault(k, v)
        return {k: v for k, v in out.items() if v not in (None, "")}
    for m in re.finditer(r"(\w+)\s*=\s*('(?:[^'\\]|\\.)*'|\S+)", s):
        v = m.group(2)
        if v.startswith("'"):
            v = re.sub(r"\\(.)", r"\1", v[1:-1])
        out[m.group(1)] = v
    return out


def _conninfo_quote(v) -> str:
    s = str(v)
    if s and not re.search(r"[\s'\\]", s):
        return s
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _conn_params(source, ctx, default_port, dbkey="dbname") -> dict:
    """Merge config + resolved credential into {host, port, user, password, <dbkey>, ...}.
    Records every secret in ctx so error text can be scrubbed."""
    cfg = {k: v for k, v in (source.get("config") or {}).items() if v not in (None, "")}
    cred = resolve_credential(source.get("credential_ref") or "")
    fields = _credential_fields(cred)
    if cred:
        ctx["secrets"].append(cred)
    if fields.get("dsn"):
        parsed = _parse_dsn(fields.pop("dsn"))
        fields = {**parsed, **{k: v for k, v in fields.items() if v not in (None, "")}}
    merged = {**cfg, **{k: v for k, v in fields.items() if v not in (None, "")}}
    if merged.get("password"):
        ctx["secrets"].append(str(merged["password"]))
    params = {
        "host": merged.get("host") or source.get("ref"),
        "port": int(merged.get("port") or default_port),
        "user": merged.get("user") or merged.get("username"),
        "password": merged.get("password"),
        dbkey: merged.get(dbkey) or merged.get("database") or merged.get("dbname"),
        "sslmode": merged.get("sslmode"),
    }
    return params


def _pg_params(source, ctx) -> dict:
    p = _conn_params(source, ctx, 5432, "dbname")
    p["user"] = p["user"] or "postgres"
    p["dbname"] = p["dbname"] or "postgres"
    p["sslmode"] = p["sslmode"] or ("require" if str(source.get("provider")) != "postgres" else None)
    parts = [f"host={_conninfo_quote(p['host'])}", f"port={p['port']}", f"dbname={_conninfo_quote(p['dbname'])}",
             f"user={_conninfo_quote(p['user'])}"]
    if p["password"]:
        parts.append(f"password={_conninfo_quote(p['password'])}")
    if p["sslmode"]:
        parts.append(f"sslmode={p['sslmode']}")
    p["dsn"] = " ".join(parts)
    return p


def _cursor_rows(cur) -> list:
    desc = getattr(cur, "description", None)
    if not desc:
        return []
    cols = [getattr(d, "name", None) or d[0] for d in desc]
    return [dict(zip(cols, r)) for r in cur.fetchmany(MAX_ROWS)]


def _pg_query(source, sql, timeout, ctx):
    p = _pg_params(source, ctx)
    ms = max(1000, int(timeout * 1000))
    options = f"-c statement_timeout={ms} -c default_transaction_read_only=on"
    ctimeout = max(1, int(timeout))
    psycopg = _import("psycopg")
    if psycopg is not None:
        conn = psycopg.connect(p["dsn"], options=options, connect_timeout=ctimeout, autocommit=True)
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                return _cursor_rows(cur)
        finally:
            conn.close()
    psycopg2 = _import("psycopg2")
    if psycopg2 is not None:
        conn = psycopg2.connect(p["dsn"], options=options, connect_timeout=ctimeout)
        try:
            conn.set_session(readonly=True, autocommit=True)
            cur = conn.cursor()
            cur.execute(sql)
            return _cursor_rows(cur)
        finally:
            conn.close()
    if shutil.which("psql"):
        return _psql_cli(p, sql, timeout, options)
    raise AdapterError("driver missing: pip install 'psycopg[binary]' (or psycopg2-binary), or install the psql CLI")


def _psql_cli(p, sql, timeout, options):
    """psql fallback. The password travels in PGPASSWORD, never in argv (argv is visible
    to every process on the host)."""
    env = dict(os.environ)
    env.update({"PGOPTIONS": options, "PGCONNECT_TIMEOUT": str(max(1, int(timeout)))})
    if p.get("password"):
        env["PGPASSWORD"] = str(p["password"])
    if p.get("sslmode"):
        env["PGSSLMODE"] = str(p["sslmode"])
    argv = ["psql", "-h", str(p["host"]), "-p", str(p["port"]), "-U", str(p["user"]), "-d", str(p["dbname"]),
            "-X", "-q", "--csv", "-v", "ON_ERROR_STOP=1", "-c", sql]
    proc = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout + 5)
    if proc.returncode != 0:
        raise AdapterError(f"psql exited {proc.returncode}: {(proc.stderr or '').strip()[:300]}")
    return _csv_rows(proc.stdout)


def _csv_rows(text, delimiter=",") -> list:
    reader = csv.DictReader(io.StringIO(text or ""), delimiter=delimiter)
    return [dict(r) for r in reader]


# ── aws rds data api ───────────────────────────────────────────────────────────────────

def _rds_field(field):
    if not isinstance(field, dict) or field.get("isNull"):
        return None
    for k, v in field.items():
        if k == "arrayValue" and isinstance(v, dict):
            inner = next(iter(v.values()), [])
            return [(_rds_field(x) if isinstance(x, dict) else x) for x in inner]
        return v
    return None


def _rds_data_api_query(source, sql, timeout):
    boto3 = _import("boto3")
    if boto3 is None:
        raise AdapterError("driver missing: pip install boto3 (RDS Data API)")
    cfg = source.get("config") or {}
    region = cfg.get("region") or source.get("region") or os.environ.get("AWS_REGION")
    client = boto3.client("rds-data", region_name=region)
    kwargs = {"resourceArn": cfg["resource_arn"], "secretArn": cfg["secret_arn"], "sql": sql,
              "includeResultMetadata": True, "continueAfterTimeout": False}
    if cfg.get("database"):
        kwargs["database"] = cfg["database"]
    resp = client.execute_statement(**kwargs)
    cols = [c.get("label") or c.get("name") or f"col{i}" for i, c in enumerate(resp.get("columnMetadata") or [])]
    rows = []
    for rec in (resp.get("records") or [])[:MAX_ROWS]:
        vals = [_rds_field(f) for f in rec]
        if not cols:
            cols = [f"col{i}" for i in range(len(vals))]
        rows.append(dict(zip(cols, vals)))
    return rows


# ── mysql dialect ──────────────────────────────────────────────────────────────────────

def _mysql_query(source, sql, timeout, ctx):
    p = _conn_params(source, ctx, 3306, "database")
    p["user"] = p["user"] or "root"
    ms = max(1000, int(timeout * 1000))
    ctimeout = max(1, int(timeout))
    pymysql = _import("pymysql")
    if pymysql is not None:
        conn = pymysql.connect(host=p["host"], port=p["port"], user=p["user"], password=p["password"] or "",
                               database=p["database"], connect_timeout=ctimeout, read_timeout=ctimeout,
                               autocommit=True, cursorclass=pymysql.cursors.DictCursor,
                               init_command=f"SET SESSION max_execution_time={ms}")
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                return [dict(r) for r in cur.fetchmany(MAX_ROWS)]
        finally:
            conn.close()
    connector = _import("mysql.connector")
    if connector is not None:
        conn = connector.connect(host=p["host"], port=p["port"], user=p["user"], password=p["password"] or "",
                                 database=p["database"], connection_timeout=ctimeout, autocommit=True)
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(sql)
            return [dict(r) for r in cur.fetchmany(MAX_ROWS)]
        finally:
            conn.close()
    if shutil.which("mysql"):
        env = dict(os.environ)
        if p.get("password"):
            env["MYSQL_PWD"] = str(p["password"])
        argv = ["mysql", "--batch", "--raw", "-h", str(p["host"]), "-P", str(p["port"]), "-u", str(p["user"]),
                f"--connect-timeout={ctimeout}"]
        if p.get("database"):
            argv += ["-D", str(p["database"])]
        argv += ["-e", sql]
        proc = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout + 5)
        if proc.returncode != 0:
            raise AdapterError(f"mysql exited {proc.returncode}: {(proc.stderr or '').strip()[:300]}")
        rows = _csv_rows(proc.stdout, delimiter="\t")
        return [{k: (None if v == "NULL" else v) for k, v in r.items()} for r in rows]
    raise AdapterError("driver missing: pip install pymysql (or mysql-connector-python), or install the mysql CLI")


# ── bigquery ───────────────────────────────────────────────────────────────────────────

def _bigquery_query(source, sql, timeout, ctx):
    cfg = source.get("config") or {}
    cred = resolve_credential(source.get("credential_ref") or "")
    info = None
    if cred:
        ctx["secrets"].append(cred)
        try:
            info = json.loads(cred)
        except ValueError:
            raise AdapterError("bigquery credential must resolve to a service-account JSON document")
        if isinstance(info, dict) and info.get("private_key"):
            ctx["secrets"].append(str(info["private_key"]))
    project = cfg.get("project_id") or (info or {}).get("project_id") or source.get("ref")
    bigquery = _import("google.cloud.bigquery")
    if bigquery is not None:
        creds = None
        if info:
            sa = _import("google.oauth2.service_account")
            if sa is None:
                raise AdapterError("driver missing: pip install google-auth")
            creds = sa.Credentials.from_service_account_info(info)
        client = bigquery.Client(project=project, credentials=creds) if creds else bigquery.Client(project=project)
        job_config = bigquery.QueryJobConfig(use_query_cache=True, maximum_bytes_billed=BQ_MAX_BYTES)
        job = client.query(sql, job_config=job_config)
        return [dict(r.items()) for r in job.result(timeout=timeout, max_results=MAX_ROWS)]
    if shutil.which("bq"):
        env = dict(os.environ)
        argv = ["bq", "--format=json", "--headless", "-q"]
        if project:
            argv += ["--project_id", str(project)]
        argv += ["query", "--nouse_legacy_sql", f"--maximum_bytes_billed={BQ_MAX_BYTES}", f"--max_rows={MAX_ROWS}", sql]
        proc = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout + 10)
        if proc.returncode != 0:
            raise AdapterError(f"bq exited {proc.returncode}: {(proc.stderr or '').strip()[:300]}")
        try:
            data = json.loads(proc.stdout or "[]")
        except ValueError:
            raise AdapterError("bq returned non-JSON output")
        return data if isinstance(data, list) else []
    raise AdapterError("driver missing: pip install google-cloud-bigquery, or install the bq CLI")


# ── snowflake ──────────────────────────────────────────────────────────────────────────

def _snowflake_query(source, sql, timeout, ctx):
    sf = _import("snowflake.connector")
    if sf is None:
        raise AdapterError("driver missing: pip install snowflake-connector-python")
    cfg = source.get("config") or {}
    p = _conn_params(source, ctx, 443, "database")
    kwargs = {"account": cfg.get("account") or source.get("ref"), "user": p["user"], "password": p["password"],
              "login_timeout": max(1, int(timeout)), "network_timeout": max(1, int(timeout)),
              "session_parameters": {"STATEMENT_TIMEOUT_IN_SECONDS": max(1, int(timeout))}}
    for k in ("warehouse", "database", "schema", "role"):
        if cfg.get(k):
            kwargs[k] = cfg[k]
    conn = sf.connect(**kwargs)
    try:
        cur = conn.cursor(sf.DictCursor)
        cur.execute(sql)
        return [dict(r) for r in cur.fetchmany(MAX_ROWS)]
    finally:
        conn.close()


if __name__ == "__main__":
    print("db_adapters: read-only query surface; run db_probes / db_steering instead.")

#!/usr/bin/env python3
"""db_adapters: the read-only, secret-free query seam in front of every provider.

What must hold, and why each is tested rather than trusted:

* The read-only guard runs BEFORE any I/O. A write shape must raise ReadOnlyViolation
  with no HTTP request made, no driver touched and no credential resolved.
* Supabase transport is shaped like rls_guard learned it: both response shapes are
  normalised, 409/429/5xx are retried with 1s/2s/4s backoff through `_sleep`, 401/404
  are not retried, and every HTTP failure becomes an AdapterError.
* Credentials are references. A raw DSN or password is refused; a resolved value is
  returned to the transport and never printed; driver error text is scrubbed.
* Missing drivers degrade one source (AdapterError) instead of crashing the loop, and
  capabilities()/describe()/supabase_advisors() are fail-soft.

No network, no real database, no third-party driver is needed by any test here.
"""
import base64
import contextlib
import hashlib
import importlib
import io
import json
import os
import sys
import types
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import db_adapters  # noqa: E402
from db_adapters import AdapterError  # noqa: E402
from db_steering_contract import ReadOnlyViolation  # noqa: E402

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402
    HAVE_CRYPTO = True
except ImportError:  # pragma: no cover - environment dependent
    HAVE_CRYPTO = False

SUPA = {"provider": "supabase", "ref": "abcdefghijklmnop", "project": "apparently-law"}
TOKEN_ENV = {"SUPABASE_ACCESS_TOKEN": "sbp_test_token_value"}


def _http_error(code):
    return urllib.error.HTTPError("https://api.supabase.com", code, "boom", {}, None)


def _body(payload):
    return io.BytesIO(json.dumps(payload).encode())


def _sequence(items, calls=None):
    """urlopen stand-in that raises HTTPError items and returns BytesIO items, in order."""
    seq = list(items)

    def fake_urlopen(req, timeout=None):
        if calls is not None:
            calls.append(req)
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
    return fake_urlopen


class Base(unittest.TestCase):
    def setUp(self):
        self.slept = []
        self.enterContext(mock.patch.object(db_adapters, "_sleep", self.slept.append))
        self.enterContext(mock.patch.dict(os.environ, TOKEN_ENV))


# ── read-only guard is the chokepoint ──────────────────────────────────────────────────

class TestReadOnlyGuardBeforeIO(Base):
    WRITES = ("update t set a=1", "delete from t", "insert into t values (1)", "drop table t",
              "select 1; select 2", "  ", "begin", "select * from t; --")

    def test_supabase_write_shape_never_reaches_urlopen(self):
        urlopen = mock.Mock(side_effect=AssertionError("network I/O must not happen"))
        with mock.patch.object(db_adapters.urllib.request, "urlopen", urlopen):
            for sql in self.WRITES:
                with self.subTest(sql=sql):
                    with self.assertRaises(ReadOnlyViolation):
                        db_adapters.query(SUPA, sql)
        urlopen.assert_not_called()
        self.assertEqual(self.slept, [])

    def test_violation_is_not_wrapped_as_adapter_error(self):
        with mock.patch.object(db_adapters.urllib.request, "urlopen", mock.Mock()):
            try:
                db_adapters.query(SUPA, "update t set a=1")
            except AdapterError:  # pragma: no cover - the failure we are guarding against
                self.fail("ReadOnlyViolation must propagate, not be normalised to AdapterError")
            except ReadOnlyViolation:
                pass

    def test_postgres_write_shape_touches_no_driver_and_no_credential(self):
        pg = mock.Mock(side_effect=AssertionError("driver must not be reached"))
        cred = mock.Mock(side_effect=AssertionError("credential must not be resolved"))
        src = {"provider": "postgres", "ref": "db.internal", "credential_ref": "env:PG_DSN"}
        with mock.patch.object(db_adapters, "_pg_query", pg), \
                mock.patch.object(db_adapters, "resolve_credential", cred):
            with self.assertRaises(ReadOnlyViolation):
                db_adapters.query(src, "truncate t")
        pg.assert_not_called()
        cred.assert_not_called()

    def test_guard_runs_even_for_unprobed_dialects(self):
        # mongodb is refused with AdapterError for reads, but a write shape is still the
        # louder ReadOnlyViolation: the guard comes first, unconditionally.
        with self.assertRaises(ReadOnlyViolation):
            db_adapters.query({"provider": "mongodb"}, "delete from x")


# ── supabase transport ─────────────────────────────────────────────────────────────────

class TestSupabaseQuery(Base):
    def test_bare_list_response(self):
        calls = []
        with mock.patch.object(db_adapters.urllib.request, "urlopen",
                               _sequence([_body([{"a": 1}, {"a": 2}])], calls)):
            rows = db_adapters.query(SUPA, "select a from t")
        self.assertEqual(rows, [{"a": 1}, {"a": 2}])
        req = calls[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.full_url, f"https://api.supabase.com/v1/projects/{SUPA['ref']}/database/query")
        self.assertEqual(json.loads(req.data), {"query": "select a from t"})
        self.assertEqual(req.get_header("Authorization"), f"Bearer {TOKEN_ENV['SUPABASE_ACCESS_TOKEN']}")

    def test_result_wrapped_response(self):
        with mock.patch.object(db_adapters.urllib.request, "urlopen",
                               _sequence([_body({"result": [{"off": 2, "total": 10}]})])):
            rows = db_adapters.query(SUPA, "select 1")
        self.assertEqual(rows, [{"off": 2, "total": 10}])

    def test_error_envelope_and_odd_shapes(self):
        with mock.patch.object(db_adapters.urllib.request, "urlopen",
                               _sequence([_body({"message": "relation does not exist"})])):
            with self.assertRaises(AdapterError) as cm:
                db_adapters.query(SUPA, "select 1")
        self.assertIn("relation does not exist", str(cm.exception))
        with mock.patch.object(db_adapters.urllib.request, "urlopen", _sequence([_body({"weird": True})])):
            self.assertEqual(db_adapters.query(SUPA, "select 1"), [])
        with mock.patch.object(db_adapters.urllib.request, "urlopen", _sequence([_body("scalar")])):
            self.assertEqual(db_adapters.query(SUPA, "select 1"), [])

    def test_scalar_rows_wrapped_and_truncated(self):
        with mock.patch.object(db_adapters, "MAX_ROWS", 2), \
                mock.patch.object(db_adapters.urllib.request, "urlopen", _sequence([_body([1, 2, 3])])):
            self.assertEqual(db_adapters.query(SUPA, "select 1"), [{"value": 1}, {"value": 2}])

    def test_missing_token_and_missing_ref(self):
        urlopen = mock.Mock()
        with mock.patch.object(db_adapters.urllib.request, "urlopen", urlopen):
            with mock.patch.dict(os.environ, {"SUPABASE_ACCESS_TOKEN": ""}):
                with self.assertRaises(AdapterError) as cm:
                    db_adapters.query(SUPA, "select 1")
            self.assertIn("SUPABASE_ACCESS_TOKEN", str(cm.exception))
            with self.assertRaises(AdapterError):
                db_adapters.query({"provider": "supabase"}, "select 1")
        urlopen.assert_not_called()

    def test_url_error_and_non_json(self):
        def unreachable(req, timeout=None):
            raise urllib.error.URLError("no route to host")

        with mock.patch.object(db_adapters.urllib.request, "urlopen", unreachable):
            with self.assertRaises(AdapterError) as cm:
                db_adapters.query(SUPA, "select 1")
        self.assertIn("unreachable", str(cm.exception))
        with mock.patch.object(db_adapters.urllib.request, "urlopen", _sequence([io.BytesIO(b"<html>")])):
            with self.assertRaises(AdapterError) as cm:
                db_adapters.query(SUPA, "select 1")
        self.assertIn("non-JSON", str(cm.exception))


class TestSupabaseRetry(Base):
    def test_retries_409_then_succeeds(self):
        with mock.patch.object(db_adapters.urllib.request, "urlopen",
                               _sequence([_http_error(409), _http_error(409), _body([{"n": 1}])])):
            self.assertEqual(db_adapters.query(SUPA, "select 1"), [{"n": 1}])
        self.assertEqual(self.slept, [1.0, 2.0], "expected exponential backoff")

    def test_gives_up_after_three_retries_as_adapter_error(self):
        calls = []

        def always_409(req, timeout=None):
            calls.append(1)
            raise _http_error(409)

        with mock.patch.object(db_adapters.urllib.request, "urlopen", always_409):
            with self.assertRaises(AdapterError) as cm:
                db_adapters.query(SUPA, "select 1")
        self.assertIn("HTTP 409", str(cm.exception))
        self.assertEqual(self.slept, [1.0, 2.0, 4.0])
        self.assertEqual(len(calls), 4)

    def test_retries_429_and_5xx(self):
        for code in (429, 500, 502, 503, 504):
            self.slept.clear()
            with mock.patch.object(db_adapters.urllib.request, "urlopen",
                                   _sequence([_http_error(code), _body([{"ok": True}])])):
                self.assertEqual(db_adapters.query(SUPA, "select 1"), [{"ok": True}])
            self.assertEqual(self.slept, [1.0], f"HTTP {code} should be retried once here")

    def test_does_not_retry_auth_errors(self):
        for code in (401, 403, 404):
            self.slept.clear()
            calls = []
            with mock.patch.object(db_adapters.urllib.request, "urlopen",
                                   _sequence([_http_error(code), _body([])], calls)):
                with self.assertRaises(AdapterError) as cm:
                    db_adapters.query(SUPA, "select 1")
            self.assertEqual(len(calls), 1, f"HTTP {code} must not be retried")
            self.assertEqual(self.slept, [])
            self.assertIn(f"HTTP {code}", str(cm.exception))


class TestSupabaseAdvisors(Base):
    LINTS = [{"name": "rls_disabled_in_public", "level": "ERROR", "metadata": {"schema": "public", "name": "users"}},
             "not-a-lint", {"name": "unused_index", "level": "INFO"}]

    def test_success_returns_dict_lints_only(self):
        calls = []
        with mock.patch.object(db_adapters.urllib.request, "urlopen", _sequence([_body({"lints": self.LINTS})], calls)):
            out = db_adapters.supabase_advisors(SUPA, "security")
        self.assertEqual([lint["name"] for lint in out], ["rls_disabled_in_public", "unused_index"])
        self.assertEqual(calls[0].get_method(), "GET")
        self.assertTrue(calls[0].full_url.endswith(f"/projects/{SUPA['ref']}/advisors/security"))
        with mock.patch.object(db_adapters.urllib.request, "urlopen", _sequence([_body(self.LINTS)])):
            self.assertEqual(len(db_adapters.supabase_advisors(SUPA, "performance")), 2)

    def test_http_error_is_empty_list_after_retries(self):
        def always_503(req, timeout=None):
            raise _http_error(503)

        with mock.patch.object(db_adapters.urllib.request, "urlopen", always_503):
            self.assertEqual(db_adapters.supabase_advisors(SUPA, "security"), [])
        self.assertEqual(self.slept, [1.0, 2.0, 4.0])
        with mock.patch.object(db_adapters.urllib.request, "urlopen", _sequence([_http_error(401)])):
            self.assertEqual(db_adapters.supabase_advisors(SUPA, "security"), [])

    def test_unknown_kind_and_missing_token_do_no_io(self):
        urlopen = mock.Mock()
        with mock.patch.object(db_adapters.urllib.request, "urlopen", urlopen):
            self.assertEqual(db_adapters.supabase_advisors(SUPA, "compliance"), [])
            with mock.patch.dict(os.environ, {"SUPABASE_ACCESS_TOKEN": ""}):
                self.assertEqual(db_adapters.supabase_advisors(SUPA, "security"), [])
        urlopen.assert_not_called()

    def test_odd_payloads_are_empty(self):
        for payload in ({"lints": "nope"}, "text", 42, {"other": []}):
            with mock.patch.object(db_adapters.urllib.request, "urlopen", _sequence([_body(payload)])):
                self.assertEqual(db_adapters.supabase_advisors(SUPA, "security"), [])


# ── credentials ────────────────────────────────────────────────────────────────────────

SENTINEL = "s3cret-value-7f3a9c-do-not-print"


class TestResolveCredential(unittest.TestCase):
    def _resolve_capturing(self, ref):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            value = db_adapters.resolve_credential(ref)
        return value, out.getvalue() + err.getvalue()

    def test_raw_dsn_and_password_shaped_values_are_refused(self):
        for raw in ("postgres://u:p@h/db", "postgresql://user:pw@db.example.com:5432/app?sslmode=require",
                    "host=h user=u password=p dbname=d", "hunter2", "sbp_0123456789abcdef",
                    "env:X postgres://u:p@h/db", "keychain:x://u:p@h", "notascheme:NAME"):
            with self.subTest(raw=raw):
                value, printed = self._resolve_capturing(raw)
                self.assertIsNone(value)
                self.assertNotIn(raw.split("://")[-1].split("@")[0], printed.replace("refusing", ""))

    def test_env_ref_resolves_and_never_prints_the_value(self):
        with mock.patch.dict(os.environ, {"DBSTEER_TEST_SECRET": SENTINEL}):
            value, printed = self._resolve_capturing("env:DBSTEER_TEST_SECRET")
        self.assertEqual(value, SENTINEL)
        self.assertNotIn(SENTINEL, printed)
        self.assertEqual(printed, "")

    def test_env_ref_unset_and_empty_ref(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DBSTEER_TEST_MISSING", None)
            self.assertIsNone(db_adapters.resolve_credential("env:DBSTEER_TEST_MISSING"))
        self.assertIsNone(db_adapters.resolve_credential(""))
        self.assertIsNone(db_adapters.resolve_credential(None))

    def test_file_ref_must_be_absolute_and_reads_stripped(self):
        self.assertIsNone(db_adapters.resolve_credential("file:relative/secret"))
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".cred", delete=False) as fh:
            fh.write(SENTINEL + "\n")
        self.addCleanup(os.unlink, fh.name)
        value, printed = self._resolve_capturing(f"file:{fh.name}")
        self.assertEqual(value, SENTINEL)
        self.assertNotIn(SENTINEL, printed)
        value, printed = self._resolve_capturing("/no/such/file/anywhere".join(["file:", ""]))
        self.assertIsNone(value)
        self.assertNotIn("/no/such/file", printed, "an OSError message would carry the path; only the type is logged")

    def test_vault_ref_rejects_non_uuid_without_touching_db(self):
        select = mock.Mock()
        with mock.patch.object(db_adapters.db, "select", select):
            self.assertIsNone(db_adapters.resolve_credential("vault:not-a-uuid!"))
        select.assert_not_called()

    def test_vault_ref_missing_account_or_ciphertext(self):
        with mock.patch.object(db_adapters.db, "select", return_value=[]):
            self.assertIsNone(db_adapters.resolve_credential("vault:0123456789abcdef0123456789abcdef"))
        with mock.patch.object(db_adapters.db, "select", return_value=[{"access_token_ciphertext": None}]):
            self.assertIsNone(db_adapters.resolve_credential("vault:0123456789abcdef0123456789abcdef"))

    def test_store_read_failure_is_none_not_raise(self):
        with mock.patch.object(db_adapters, "_read_store", side_effect=RuntimeError("keychain locked")):
            value, printed = self._resolve_capturing("keychain:fleet-db")
        self.assertIsNone(value)
        self.assertIn("RuntimeError", printed)
        self.assertNotIn("keychain locked", printed)

    def test_credential_fields_shapes(self):
        self.assertEqual(db_adapters._credential_fields(""), {})
        self.assertEqual(db_adapters._credential_fields("postgres://u:p@h/d"), {"dsn": "postgres://u:p@h/d"})
        self.assertEqual(db_adapters._credential_fields("host=h password=p"), {"dsn": "host=h password=p"})
        self.assertEqual(db_adapters._credential_fields("plainpw"), {"password": "plainpw"})
        self.assertEqual(db_adapters._credential_fields('{"user": "u", "password": "p"}'), {"user": "u", "password": "p"})

    def test_parse_dsn_url_and_conninfo(self):
        parsed = db_adapters._parse_dsn("postgresql://us%40er:p%40ss@db.example.com:6543/app?sslmode=require")
        self.assertEqual(parsed, {"host": "db.example.com", "port": 6543, "user": "us@er", "password": "p@ss",
                                  "dbname": "app", "sslmode": "require"})
        parsed = db_adapters._parse_dsn("host=h port=5433 user=u password='a b\\'c' dbname=d")
        self.assertEqual(parsed, {"host": "h", "port": "5433", "user": "u", "password": "a b'c", "dbname": "d"})


class TestScrubbing(Base):
    def test_driver_error_text_is_scrubbed(self):
        pw = "pw-9a8b7c6d5e-scrub-me"

        def connect(dsn, **kw):
            raise RuntimeError(f"FATAL: password authentication failed (dsn was {dsn}, pw {pw})")

        fake_psycopg = types.SimpleNamespace(connect=connect)
        src = {"provider": "neon", "ref": "ep-host.neon.tech", "credential_ref": "env:DBSTEER_PW",
               "config": {"user": "app", "dbname": "app"}}
        with mock.patch.dict(os.environ, {"DBSTEER_PW": pw}), \
                mock.patch.dict(sys.modules, {"psycopg": fake_psycopg}):
            with self.assertRaises(AdapterError) as cm:
                db_adapters.query(src, "select 1")
        msg = str(cm.exception)
        self.assertNotIn(pw, msg)
        self.assertIn("***", msg)
        self.assertIn("RuntimeError", msg)
        self.assertIsNone(cm.exception.__cause__)

    def test_scrub_handles_url_encoding_and_short_values(self):
        self.assertEqual(db_adapters._scrub("x p%40ss y p@ss", ["p@ss"]), "x *** y ***")
        self.assertEqual(db_adapters._scrub("abcd", ["abcd", "ab", None, ""]), "***")
        self.assertEqual(db_adapters._scrub("a1 b", ["a1"]), "a1 b",
                         "values shorter than 4 chars are not scrubbed (they would shred ordinary text)")


# ── vault decrypt ──────────────────────────────────────────────────────────────────────

def _b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


@unittest.skipUnless(HAVE_CRYPTO, "cryptography not installed")
class TestDecryptVault(unittest.TestCase):
    KEY_RAW = "connector-vault-master-key-for-tests"

    def _encrypt(self, plaintext, key_raw=None, iv=None):
        key = hashlib.sha256((key_raw or self.KEY_RAW).encode("utf-8")).digest()
        iv = iv or os.urandom(12)
        ct = AESGCM(key).encrypt(iv, plaintext.encode("utf-8"), None)
        body, tag = ct[:-16], ct[-16:]
        return ".".join((_b64url(iv), _b64url(tag), _b64url(body)))

    def test_round_trip(self):
        blob = self._encrypt(SENTINEL)
        self.assertNotIn("=", blob, "the vault format is unpadded base64url")
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"CONNECTOR_VAULT_KEY": self.KEY_RAW}), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(db_adapters.decrypt_vault(blob), SENTINEL)
        self.assertNotIn(SENTINEL, out.getvalue() + err.getvalue())

    def test_missing_key_is_none(self):
        blob = self._encrypt("x")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CONNECTOR_VAULT_KEY", None)
            self.assertIsNone(db_adapters.decrypt_vault(blob))

    def test_wrong_key_tamper_and_malformed_are_none(self):
        with mock.patch.dict(os.environ, {"CONNECTOR_VAULT_KEY": self.KEY_RAW}):
            self.assertIsNone(db_adapters.decrypt_vault(self._encrypt("x", key_raw="other-key")))
            iv, tag, body = self._encrypt("tamper me please").split(".")
            self.assertIsNone(db_adapters.decrypt_vault(".".join((iv, tag, body[:-2] + ("AA" if body[-2:] != "AA" else "BB")))))
            self.assertIsNone(db_adapters.decrypt_vault("only.two"))
            self.assertIsNone(db_adapters.decrypt_vault(""))
            self.assertIsNone(db_adapters.decrypt_vault(None))

    def test_vault_ref_end_to_end(self):
        blob = self._encrypt("postgres://app:vaultpw@db.internal/app")
        rows = [{"access_token_ciphertext": blob, "provider": "postgres", "metadata": {}}]
        with mock.patch.dict(os.environ, {"CONNECTOR_VAULT_KEY": self.KEY_RAW}), \
                mock.patch.object(db_adapters.db, "select", return_value=rows):
            self.assertEqual(db_adapters.resolve_credential("vault:0123456789abcdef0123456789abcdef"),
                             "postgres://app:vaultpw@db.internal/app")


# ── driver-missing paths ───────────────────────────────────────────────────────────────

BLOCKED = ("psycopg", "psycopg2", "pymysql", "mysql.connector", "google.cloud.bigquery",
           "google.oauth2.service_account", "snowflake.connector", "boto3")


class TestDriverMissing(Base):
    def setUp(self):
        super().setUp()
        real_import = importlib.import_module

        def selective(name, *a, **k):
            if name in BLOCKED or name.split(".")[0] in ("psycopg", "psycopg2", "pymysql", "snowflake", "boto3"):
                raise ImportError(f"No module named {name!r} (blocked by test)")
            return real_import(name, *a, **k)

        self.enterContext(mock.patch.object(db_adapters.importlib, "import_module", selective))
        self.which = mock.Mock(return_value=None)
        self.enterContext(mock.patch.object(db_adapters.shutil, "which", self.which))
        self.run = mock.Mock(side_effect=AssertionError("no subprocess may be spawned"))
        self.enterContext(mock.patch.object(db_adapters.subprocess, "run", self.run))

    def _expect_missing(self, source, *needles):
        with self.assertRaises(AdapterError) as cm:
            db_adapters.query(source, "select 1")
        msg = str(cm.exception)
        self.assertIn("driver missing", msg)
        for n in needles:
            self.assertIn(n, msg)
        self.assertNotIn(SENTINEL, msg)
        return msg

    def test_postgres_family(self):
        for provider in ("postgres", "neon", "aws_rds", "gcp_cloudsql", "cockroachdb"):
            with self.subTest(provider=provider):
                self._expect_missing({"provider": provider, "ref": "h"}, "psycopg", "psql")
        self.assertTrue(any(c.args == ("psql",) for c in self.which.call_args_list))

    def test_mysql_family(self):
        for provider in ("mysql", "planetscale", "azure_mysql"):
            with self.subTest(provider=provider):
                self._expect_missing({"provider": provider, "ref": "h"}, "pymysql", "mysql CLI")
        self.assertTrue(any(c.args == ("mysql",) for c in self.which.call_args_list))

    def test_bigquery(self):
        self._expect_missing({"provider": "gcp_bigquery", "ref": "my-project"}, "google-cloud-bigquery", "bq CLI")
        self.assertTrue(any(c.args == ("bq",) for c in self.which.call_args_list))

    def test_snowflake(self):
        self._expect_missing({"provider": "snowflake", "ref": "acct"}, "snowflake-connector-python")

    def test_rds_data_api_needs_boto3(self):
        src = {"provider": "aws_aurora", "ref": "cluster",
               "config": {"resource_arn": "arn:aws:rds:us-east-1:1:cluster:x", "secret_arn": "arn:aws:secretsmanager:x"}}
        self._expect_missing(src, "boto3")

    def test_secret_never_appears_in_missing_driver_message(self):
        with mock.patch.dict(os.environ, {"DBSTEER_PW": SENTINEL}):
            src = {"provider": "postgres", "ref": "h", "credential_ref": "env:DBSTEER_PW"}
            self._expect_missing(src, "psycopg")
        self.run.assert_not_called()

    def test_bigquery_credential_must_be_service_account_json(self):
        with mock.patch.dict(os.environ, {"DBSTEER_BQ": "not json at all"}):
            with self.assertRaises(AdapterError) as cm:
                db_adapters.query({"provider": "gcp_bigquery", "ref": "p", "credential_ref": "env:DBSTEER_BQ"}, "select 1")
        self.assertIn("service-account JSON", str(cm.exception))


class TestUnsupported(Base):
    def test_mongodb_raises_adapter_error(self):
        with self.assertRaises(AdapterError) as cm:
            db_adapters.query({"provider": "mongodb", "ref": "cluster0"}, "select 1")
        self.assertIn("mongodb", str(cm.exception))

    def test_other_dialect_is_adapter_error(self):
        with self.assertRaises(AdapterError) as cm:
            db_adapters.query({"provider": "other", "dialect": "other"}, "select 1")
        self.assertIn("unsupported", str(cm.exception))

    def test_dialect_of_defaults(self):
        self.assertEqual(db_adapters.dialect_of({"provider": "supabase"}), "postgres")
        self.assertEqual(db_adapters.dialect_of({"provider": "planetscale"}), "mysql")
        self.assertEqual(db_adapters.dialect_of({"provider": "postgres", "dialect": "mysql"}), "mysql")
        self.assertEqual(db_adapters.dialect_of({}), "other")
        self.assertEqual(db_adapters.dialect_of(None), "other")


# ── capabilities / describe ────────────────────────────────────────────────────────────

class TestCapabilities(Base):
    def test_query_raising_is_fail_soft(self):
        with mock.patch.object(db_adapters, "query", side_effect=RuntimeError("driver exploded")):
            caps = db_adapters.capabilities({"provider": "postgres", "ref": "h"})
        self.assertEqual(caps, {"advisors": False, "pg_stat_statements": False, "dialect": "postgres", "version": None})
        with mock.patch.object(db_adapters, "query", side_effect=AdapterError("SUPABASE_ACCESS_TOKEN unset")):
            caps = db_adapters.capabilities({**SUPA})
        self.assertEqual(caps["dialect"], "postgres")
        self.assertTrue(caps["advisors"], "advisors need only the fleet token, not a working query")

    def test_supabase_unreachable_is_fail_soft_and_reports_dialect(self):
        def unreachable(req, timeout=None):
            raise urllib.error.URLError("offline")

        with mock.patch.object(db_adapters.urllib.request, "urlopen", unreachable):
            caps = db_adapters.capabilities(SUPA)
        self.assertEqual(caps["dialect"], "postgres")
        self.assertFalse(caps["pg_stat_statements"])
        self.assertIsNone(caps["version"])

    def test_success_path_reads_extension_and_version(self):
        answers = {"pg_stat_statements": [{"extname": "pg_stat_statements"}], "server_version": [{"server_version": "15.6"}]}

        def fake_query(source, sql, timeout=None):
            for k, v in answers.items():
                if k in sql:
                    return v
            return []

        with mock.patch.object(db_adapters, "query", fake_query):
            caps = db_adapters.capabilities({"provider": "postgres", "ref": "h"})
        self.assertEqual(caps, {"advisors": False, "pg_stat_statements": True, "dialect": "postgres", "version": "15.6"})

    def test_mongodb_and_none_do_no_query(self):
        q = mock.Mock()
        with mock.patch.object(db_adapters, "query", q):
            self.assertEqual(db_adapters.capabilities({"provider": "mongodb"})["dialect"], "mongodb")
            self.assertEqual(db_adapters.capabilities(None)["dialect"], "other")
        q.assert_not_called()

    def test_mysql_and_snowflake_version(self):
        with mock.patch.object(db_adapters, "query", return_value=[{"version": "8.0.36"}]):
            self.assertEqual(db_adapters.capabilities({"provider": "mysql"})["version"], "8.0.36")
            self.assertEqual(db_adapters.capabilities({"provider": "snowflake"})["version"], "8.0.36")


class TestDescribe(unittest.TestCase):
    def test_contains_no_credential_text(self):
        src = {"provider": "postgres", "ref": "db.internal.example.com", "project": "apparently",
               "credential_ref": "env:PG_DSN_SECRET_NAME",
               "config": {"user": "app_user", "password": "hunter2-not-a-ref", "host": "10.0.0.5"}}
        text = db_adapters.describe(src)
        self.assertTrue(text.startswith("postgres:db.int…"), text)
        self.assertIn("(apparently)", text)
        for leak in ("hunter2", "PG_DSN_SECRET_NAME", "app_user", "10.0.0.5", "env:"):
            self.assertNotIn(leak, text)

    def test_short_ref_label_and_empty(self):
        self.assertEqual(db_adapters.describe({"provider": "supabase", "ref": "abcdefgh", "label": "site"}),
                         "supabase:abcdefgh (site)")
        self.assertEqual(db_adapters.describe({}), "?:")
        self.assertEqual(db_adapters.describe(None), "?:")


if __name__ == "__main__":
    unittest.main()

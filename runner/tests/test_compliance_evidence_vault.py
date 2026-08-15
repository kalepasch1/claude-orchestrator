#!/usr/bin/env python3
"""Coverage for compliance_evidence_vault.

Required by the queue task: staging, tamper detection, redaction, traversal rejection.
Plus retention/legal-hold and the fail-soft surface.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import compliance_evidence_vault as vault  # noqa: E402


class _NullCollector:
    """Stands in for EvidenceCollector so tests don't write to the evidence bus."""
    def __init__(self):
        self.calls = []

    def collect(self, app_id, kind, subject, *, file_path=None, metadata=None):
        self.calls.append((app_id, kind, subject, file_path, metadata))
        return {"receipt": "test", "app_id": app_id}


@pytest.fixture
def root(tmp_path):
    return str(tmp_path / "vault")


@pytest.fixture
def collector():
    return _NullCollector()


def _stage(root, collector, **kw):
    params = dict(app_id="apparently", kind="policy_snapshot", subject="q3 policy",
                  content={"policy": "v1"}, root=root, collector=collector)
    params.update(kw)
    return vault.stage(**params)


# ── staging ─────────────────────────────────────────────────────────────────

def test_stage_writes_content_and_manifest(root, collector):
    res = _stage(root, collector)
    assert res["ok"], res
    assert os.path.isfile(res["path"])
    assert os.path.isfile(res["manifest_path"])
    assert res["content_sha256"] and res["manifest_sha256"]


def test_stage_is_content_addressed_under_app_and_kind(root, collector):
    res = _stage(root, collector)
    rel = os.path.relpath(res["path"], vault.vault_root(root))
    assert rel == os.path.join("apparently", "policy_snapshot", res["content_sha256"])


def test_stage_deduplicates_identical_bytes(root, collector):
    first = _stage(root, collector)
    second = _stage(root, collector)
    assert second["ok"]
    assert second["deduplicated"] is True
    assert second["content_sha256"] == first["content_sha256"]


def test_stage_json_hash_is_key_order_stable(root, collector):
    a = _stage(root, collector, content={"a": 1, "b": 2})
    b = _stage(root, collector, content={"b": 2, "a": 1})
    assert a["content_sha256"] == b["content_sha256"]


@pytest.mark.parametrize("kind", vault.CAPTURE_KINDS)
def test_all_four_capture_kinds_are_supported(root, collector, kind):
    res = _stage(root, collector, kind=kind, content=f"evidence for {kind}")
    assert res["ok"], res


def test_stage_rejects_unknown_kind(root, collector):
    res = _stage(root, collector, kind="random_blob")
    assert res["ok"] is False
    assert "unsupported capture kind" in res["error"]


def test_stage_rejects_empty_and_oversize(root, collector, monkeypatch):
    assert _stage(root, collector, content="")["ok"] is False
    monkeypatch.setattr(vault, "MAX_BYTES", 10)
    res = _stage(root, collector, content="x" * 100)
    assert res["ok"] is False
    assert "exceeds" in res["error"]


def test_stage_calls_the_collector_for_the_audit_receipt(root, collector):
    res = _stage(root, collector)
    assert collector.calls, "the audit receipt must still be produced"
    assert collector.calls[0][3] == res["path"]


def test_collector_failure_does_not_lose_evidence(root):
    class Exploding:
        def collect(self, *a, **k):
            raise RuntimeError("bus down")

    res = _stage(root, Exploding())
    assert res["ok"] is True
    assert os.path.isfile(res["path"])
    assert "bus down" in str(res["receipt"])


def test_stage_bytes_and_str_payloads(root, collector):
    assert _stage(root, collector, content=b"raw bytes here")["ok"]
    assert _stage(root, collector, content="a string")["ok"]


def test_stage_rejects_unserialisable_content(root, collector):
    assert _stage(root, collector, content=object())["ok"] is False


# ── redaction ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("secret,rule", [
    ("AKIAIOSFODNN7EXAMPLE", "aws_access_key"),
    ("ghp_abcdefghijklmnopqrstuvwxyz0123456789", "github_token"),
    ("xoxb-1234567890-abcdefghij", "slack_token"),
    ("password = hunter2secret", "secret_assignment"),
    ("123-45-6789", "ssn"),
    ("someone@example.com", "email"),
])
def test_redact_catches_each_shape(secret, rule):
    out, found = vault.redact(f"prefix {secret} suffix")
    assert any(f["rule"] == rule for f in found), found
    assert "REDACTED" in out


def test_redact_leaves_clean_text_alone():
    text = "The policy was approved on 2026-01-01 by the risk committee."
    out, found = vault.redact(text)
    assert out == text
    assert found == []


def test_redact_allowlists_the_owner_address():
    out, _ = vault.redact("contact kalepasch@gmail.com for filings")
    assert "kalepasch@gmail.com" in out


def test_redact_fail_soft_on_non_string():
    out, found = vault.redact(None)
    assert out == "" and found == []


def test_staged_content_never_holds_the_cleartext(root, collector):
    """The vault must not contain the secret at any point, not even briefly."""
    res = _stage(root, collector,
                 content="api_key = ghp_abcdefghijklmnopqrstuvwxyz0123456789\n")
    assert res["ok"]
    with open(res["path"]) as fh:
        stored = fh.read()
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in stored
    assert "REDACTED" in stored
    assert res["redactions"]


def test_redaction_is_recorded_on_the_manifest(root, collector):
    res = _stage(root, collector, content="ssn 123-45-6789")
    with open(res["manifest_path"]) as fh:
        manifest = json.load(fh)
    assert any(r["rule"] == "ssn" for r in manifest["redactions"])


def test_binary_payloads_are_flagged_not_mangled(root, collector):
    blob = b"\x00\x01\x02binary\xff"
    res = _stage(root, collector, content=blob)
    assert res["ok"]
    with open(res["path"], "rb") as fh:
        assert fh.read() == blob
    assert res["redactions"] == [{"rule": "skipped_binary", "count": 0}]


# ── tamper detection ────────────────────────────────────────────────────────

def test_verify_passes_on_untouched_evidence(root, collector):
    res = _stage(root, collector)
    assert vault.verify(res["manifest_path"], root=root)["ok"] is True


def test_verify_detects_edited_content(root, collector):
    res = _stage(root, collector)
    os.chmod(res["path"], 0o640)
    with open(res["path"], "w") as fh:
        fh.write("tampered")
    checked = vault.verify(res["manifest_path"], root=root)
    assert checked["ok"] is False
    assert checked["content_ok"] is False
    assert "content digest mismatch" in checked["error"]


def test_verify_detects_edited_manifest(root, collector):
    res = _stage(root, collector)
    with open(res["manifest_path"]) as fh:
        manifest = json.load(fh)
    manifest["subject"] = "a different subject entirely"
    with open(res["manifest_path"], "w") as fh:
        json.dump(manifest, fh)
    checked = vault.verify(res["manifest_path"], root=root)
    assert checked["ok"] is False
    assert checked["manifest_ok"] is False
    assert "manifest has been altered" in checked["error"]


def test_verify_detects_deleted_evidence(root, collector):
    res = _stage(root, collector)
    os.chmod(res["path"], 0o640)
    os.unlink(res["path"])
    checked = vault.verify(res["manifest_path"], root=root)
    assert checked["ok"] is False
    assert "missing" in checked["error"]


def test_verify_fail_soft_on_missing_manifest(root):
    checked = vault.verify(os.path.join(vault.vault_root(root).as_posix(), "nope.json"),
                           root=root)
    assert checked["ok"] is False
    assert checked["error"]


# ── traversal rejection ─────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [
    "../escape", "..", ".", "a/b", "a\\b", "/absolute", "", "   ",
    "..%2Fescape", "app\0null",
])
def test_stage_rejects_traversal_shaped_app_ids(root, collector, bad):
    res = _stage(root, collector, app_id=bad)
    assert res["ok"] is False
    assert res["error"]


def test_stage_traversal_never_creates_files_outside_root(tmp_path, collector):
    root = str(tmp_path / "vault")
    outside = tmp_path / "outside"
    outside.mkdir()
    res = _stage(root, collector, app_id="../outside")
    assert res["ok"] is False
    assert list(outside.iterdir()) == []


def test_read_manifest_rejects_paths_outside_root(root, collector, tmp_path):
    _stage(root, collector)
    stray = tmp_path / "stray.manifest.json"
    stray.write_text(json.dumps({"app_id": "x", "path": "/etc/passwd"}))
    out = vault.read_manifest(str(stray), root=root)
    assert out["ok"] is False
    assert "escapes" in out["error"]


def test_retrieve_rejects_manifest_pointing_outside_root(root, collector, tmp_path):
    res = _stage(root, collector)
    with open(res["manifest_path"]) as fh:
        manifest = json.load(fh)
    manifest["path"] = "/etc/passwd"
    manifest["manifest_sha256"] = vault.manifest_digest(manifest)
    with open(res["manifest_path"], "w") as fh:
        json.dump(manifest, fh)
    out = vault.retrieve(res["manifest_path"], scope="apparently", root=root,
                         verify_first=False)
    assert out["ok"] is False
    assert "escapes" in out["error"]


# ── retention / legal hold ──────────────────────────────────────────────────

def test_retention_default_is_not_yet_purgeable(root, collector):
    _stage(root, collector)
    assert vault.purgeable(root) == []


def test_expired_retention_becomes_purgeable(root, collector):
    _stage(root, collector, retain_days=0)
    due = vault.purgeable(root)
    assert len(due) == 1


def test_legal_hold_outranks_expired_retention(root, collector):
    _stage(root, collector, retain_days=0, legal_hold=True)
    assert vault.purgeable(root) == []


def test_legal_hold_can_be_placed_and_lifted(root, collector):
    res = _stage(root, collector, retain_days=0)
    assert len(vault.purgeable(root)) == 1

    held = vault.set_legal_hold(res["manifest_path"], True, root=root, reason="litigation")
    assert held["ok"]
    assert vault.purgeable(root) == []

    lifted = vault.set_legal_hold(res["manifest_path"], False, root=root, reason="closed")
    assert lifted["ok"]
    assert len(vault.purgeable(root)) == 1


def test_legal_hold_change_reseals_the_digest(root, collector):
    res = _stage(root, collector)
    vault.set_legal_hold(res["manifest_path"], True, root=root)
    assert vault.verify(res["manifest_path"], root=root)["manifest_ok"] is True


def test_legal_hold_history_is_recorded(root, collector):
    res = _stage(root, collector)
    vault.set_legal_hold(res["manifest_path"], True, root=root, reason="subpoena")
    out = vault.read_manifest(res["manifest_path"], root=root)
    history = out["manifest"]["legal_hold_history"]
    assert history[-1]["reason"] == "subpoena" and history[-1]["held"] is True


def test_list_manifests_scopes_by_app(root, collector):
    _stage(root, collector, app_id="apparently")
    _stage(root, collector, app_id="tomorrow", content={"other": True})
    assert len(vault.list_manifests(root)) == 2
    assert len(vault.list_manifests(root, app_id="tomorrow")) == 1


def test_list_manifests_on_missing_vault_is_empty(tmp_path):
    assert vault.list_manifests(str(tmp_path / "nothing-here")) == []


# ── restricted retrieval ────────────────────────────────────────────────────

def test_retrieve_with_owning_scope(root, collector):
    res = _stage(root, collector, content="policy body")
    out = vault.retrieve(res["manifest_path"], scope="apparently", root=root)
    assert out["ok"] is True
    assert out["content"] == b"policy body"


def test_retrieve_rejects_empty_scope(root, collector):
    res = _stage(root, collector)
    out = vault.retrieve(res["manifest_path"], scope="", root=root)
    assert out["ok"] is False
    assert "explicit scope" in out["error"]


def test_retrieve_rejects_foreign_scope(root, collector):
    res = _stage(root, collector, app_id="apparently")
    out = vault.retrieve(res["manifest_path"], scope="tomorrow", root=root)
    assert out["ok"] is False
    assert "not permitted" in out["error"]


def test_audit_wildcard_scope_may_read_any_app(root, collector):
    res = _stage(root, collector, app_id="apparently")
    assert vault.retrieve(res["manifest_path"], scope="*", root=root)["ok"] is True


def test_retrieve_refuses_tampered_evidence(root, collector):
    res = _stage(root, collector)
    os.chmod(res["path"], 0o640)
    with open(res["path"], "w") as fh:
        fh.write("swapped out")
    out = vault.retrieve(res["manifest_path"], scope="apparently", root=root)
    assert out["ok"] is False
    assert "unverified" in out["error"]

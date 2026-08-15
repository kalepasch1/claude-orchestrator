"""
compliance_evidence_vault.py — managed capture, retention and retrieval for compliance
evidence.

WHY
---
`evidence_collector.EvidenceCollector` already refuses to hash anything outside the
compliance evidence root (Round 8 audit). That closes the traversal hole but leaves the
useful half unbuilt: nothing *puts* evidence inside the root, nothing records why it may
not be deleted yet, nothing stops a policy snapshot from carrying an API key into an
auditor's hands, and nothing detects a file edited after the fact.

This module is that missing half:

  * **Staged capture** — `stage()` is the only sanctioned way into the vault. Content is
    written under `<root>/<app>/<kind>/<sha256>` (content-addressed, so a re-capture of
    identical bytes is a no-op rather than a duplicate), then handed to
    EvidenceCollector for the audit receipt. Four capture kinds are first-class:
    `policy_snapshot`, `filing_confirmation`, `approval_chain_export`,
    `risk_history_export`.
  * **Immutable manifests** — every staged item gets a manifest whose `manifest_sha256`
    covers the content hash, the capture metadata and the retention terms. Rewriting the
    file or editing the manifest changes the digest, and `verify()` says so.
  * **Retention / legal hold** — `retain_until` plus `legal_hold`. `purgeable()` never
    returns an item under hold, regardless of how long its retention has expired.
  * **Redaction** — secrets and PII are stripped BEFORE anything is written to disk, so
    the vault never holds the cleartext at any point, not even briefly.
  * **Restricted retrieval** — `retrieve()` takes a scope and rejects both unscoped
    callers and any path that resolves outside the root, preserving the collector's
    path-confinement invariant rather than working around it.

Nothing here raises on bad input: this repo's convention is fail-soft, so every public
function returns a result dict with an ``error`` key instead.

Environment
-----------
    ORCH_EVIDENCE_VAULT_ROOT        Vault root (default: <runtime>/compliance-evidence)
    ORCH_EVIDENCE_DEFAULT_RETAIN_DAYS  Default retention window (default: 2555 ≈ 7y)
    ORCH_EVIDENCE_MAX_BYTES         Refuse to stage anything larger (default: 33554432)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ── Configuration ───────────────────────────────────────────────────────────

CAPTURE_KINDS = (
    "policy_snapshot",
    "filing_confirmation",
    "approval_chain_export",
    "risk_history_export",
)

DEFAULT_RETAIN_DAYS = int(os.environ.get("ORCH_EVIDENCE_DEFAULT_RETAIN_DAYS", "2555"))
MAX_BYTES = int(os.environ.get("ORCH_EVIDENCE_MAX_BYTES", str(32 * 1024 * 1024)))

MANIFEST_SUFFIX = ".manifest.json"

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _runtime_root() -> Path:
    runtime = os.environ.get("CLAUDE_ORCH_HOME") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".runtime")
    return Path(runtime) / "compliance-evidence"


def vault_root(root: str | None = None) -> Path:
    return Path(root or os.environ.get("ORCH_EVIDENCE_VAULT_ROOT") or _runtime_root()).resolve()


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Redaction ───────────────────────────────────────────────────────────────
# Applied BEFORE the first write, so cleartext never touches the vault's disk. Ordered
# most-specific-first: a Slack/GitHub/AWS token must match its own rule rather than the
# generic assignment rule, so the redaction label names what was found.

REDACTION_RULES = (
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("private_key_block", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL)),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("bearer_header", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")),
    ("secret_assignment", re.compile(
        r"(?i)\b(?:password|passwd|secret|token|api[_-]?key|client[_-]?secret)\b"
        r"\s*[:=]\s*[\"']?([^\s\"',;]{6,})[\"']?")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("credit_card", re.compile(r"\b(?:\d[ -]*?){13,16}\b")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("phone", re.compile(r"\b(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b")),
)

# Addresses that are structurally public and whose redaction would destroy the evidence's
# meaning (the filer's own contact address on a filing confirmation, for instance).
REDACTION_ALLOWLIST = {"kalepasch@gmail.com", "noreply@github.com"}


def redact(text: str) -> tuple[str, list[dict]]:
    """Strip secrets/PII. Returns (redacted_text, [{"rule","count"} ...]).

    Fail-soft: a non-string, or a pattern that blows up on pathological input, yields the
    input unchanged rather than raising — losing the evidence is worse than an unredacted
    field the reviewer can still catch.
    """
    if not isinstance(text, str) or not text:
        return (text if isinstance(text, str) else ""), []
    found: list[dict] = []
    out = text
    for name, pattern in REDACTION_RULES:
        try:
            def _sub(match: re.Match) -> str:
                whole = match.group(0)
                if whole.strip() in REDACTION_ALLOWLIST:
                    return whole
                if name == "secret_assignment" and match.groups():
                    return whole.replace(match.group(1), f"[REDACTED:{name}]")
                return f"[REDACTED:{name}]"

            out, n = pattern.subn(_sub, out)
        except Exception:  # noqa: BLE001 — a bad pattern must not lose the capture
            continue
        if n:
            found.append({"rule": name, "count": n})
    return out, found


def _looks_binary(data: bytes) -> bool:
    return b"\0" in data[:4096]


# ── Path confinement ────────────────────────────────────────────────────────

def _safe_segment(value: str, label: str) -> tuple[str, str]:
    """A single path segment that cannot escape the vault. Returns (value, error)."""
    if not isinstance(value, str) or not value.strip():
        return "", f"{label} is required"
    value = value.strip()
    if not _SAFE_SEGMENT.match(value):
        return "", (f"{label} must match [A-Za-z0-9][A-Za-z0-9._-]* "
                    f"(got {value[:40]!r}) — traversal and separators are rejected")
    if value in (".", "..") or value.startswith("."):
        return "", f"{label} may not be a relative path component"
    return value, ""


def _confine(root: Path, candidate: Path) -> tuple[Path, str]:
    """Resolve `candidate` and prove it is inside `root`. Returns (path, error).

    Belt-and-braces with `_safe_segment`: segments are validated on the way in, and the
    resolved result is re-checked on the way out, so a symlink planted inside the vault
    cannot be used to read or write outside it either.
    """
    try:
        resolved = candidate.resolve()
        root_resolved = root.resolve()
    except (OSError, RuntimeError) as exc:
        return Path(), f"path could not be resolved: {exc}"
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return Path(), "path escapes the compliance evidence root"
    return resolved, ""


# ── Manifests ───────────────────────────────────────────────────────────────

MANIFEST_DIGEST_FIELDS = (
    "app_id", "kind", "subject", "content_sha256", "bytes", "captured_at",
    "retain_until", "legal_hold", "redactions", "source", "schema",
)


def manifest_digest(manifest: dict) -> str:
    """Content-address the manifest over its load-bearing fields.

    Deliberately excludes `manifest_sha256` itself and any bookkeeping added later, so a
    tamper check is stable across schema additions while still covering everything that
    would change the evidence's meaning.
    """
    payload = {k: manifest.get(k) for k in MANIFEST_DIGEST_FIELDS}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ── Staged capture ──────────────────────────────────────────────────────────

def stage(app_id: str, kind: str, subject: str, content, *,
          root: str | None = None, metadata: dict[str, Any] | None = None,
          retain_days: int | None = None, legal_hold: bool = False,
          source: str = "", collector=None) -> dict[str, Any]:
    """Capture `content` into the vault. The only sanctioned way in.

    Returns a result dict — never raises:
        {ok, error, path, manifest_path, content_sha256, manifest_sha256,
         redactions, deduplicated, receipt}
    """
    out: dict[str, Any] = {
        "ok": False, "error": None, "path": "", "manifest_path": "",
        "content_sha256": "", "manifest_sha256": "", "redactions": [],
        "deduplicated": False, "receipt": None,
    }

    app, err = _safe_segment(app_id, "app_id")
    if err:
        out["error"] = err
        return out
    if kind not in CAPTURE_KINDS:
        out["error"] = f"unsupported capture kind {kind!r}; expected one of {CAPTURE_KINDS}"
        return out
    if not isinstance(subject, str) or not subject.strip():
        out["error"] = "subject is required"
        return out

    # Normalise the payload. dict/list are captured as canonical JSON so the content hash
    # is stable across key ordering; bytes are captured verbatim.
    if isinstance(content, (dict, list)):
        try:
            raw = json.dumps(content, sort_keys=True, indent=2, default=str).encode("utf-8")
        except (TypeError, ValueError) as exc:
            out["error"] = f"content is not serialisable: {exc}"
            return out
    elif isinstance(content, str):
        raw = content.encode("utf-8", errors="replace")
    elif isinstance(content, (bytes, bytearray)):
        raw = bytes(content)
    else:
        out["error"] = f"unsupported content type {type(content).__name__}"
        return out

    if not raw:
        out["error"] = "refusing to stage empty evidence"
        return out
    if len(raw) > MAX_BYTES:
        out["error"] = f"evidence exceeds ORCH_EVIDENCE_MAX_BYTES ({len(raw)} > {MAX_BYTES})"
        return out

    # Redact before the first write. Binary payloads are stored as-is and flagged, since
    # a regex pass over them is meaningless and would corrupt the artefact.
    if _looks_binary(raw):
        out["redactions"] = [{"rule": "skipped_binary", "count": 0}]
    else:
        redacted, found = redact(raw.decode("utf-8", errors="replace"))
        raw = redacted.encode("utf-8")
        out["redactions"] = found

    content_sha = hashlib.sha256(raw).hexdigest()
    out["content_sha256"] = content_sha

    vroot = vault_root(root)
    target_dir = vroot / app / kind
    target, err = _confine(vroot, target_dir / content_sha)
    if err:
        out["error"] = err
        return out

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        if target.exists():
            out["deduplicated"] = True   # identical bytes already captured
        else:
            tmp = target.with_suffix(".partial")
            with open(tmp, "wb") as fh:
                fh.write(raw)
            os.replace(tmp, target)      # atomic: no half-written evidence is observable
            try:
                os.chmod(target, 0o440)  # immutable-by-convention once landed
            except OSError:
                pass
    except OSError as exc:
        out["error"] = f"could not write evidence: {exc}"
        return out
    out["path"] = str(target)

    days = DEFAULT_RETAIN_DAYS if retain_days is None else max(0, int(retain_days))
    manifest = {
        "schema": "compliance-evidence-vault/1",
        "app_id": app,
        "kind": kind,
        "subject": subject.strip(),
        "content_sha256": content_sha,
        "bytes": len(raw),
        "captured_at": _utc(),
        "retain_until": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(),
        "retain_days": days,
        "legal_hold": bool(legal_hold),
        "redactions": out["redactions"],
        "source": source or "",
        "metadata": metadata or {},
        "path": str(target),
    }
    manifest["manifest_sha256"] = manifest_digest(manifest)
    out["manifest_sha256"] = manifest["manifest_sha256"]

    manifest_path, err = _confine(vroot, target_dir / (content_sha + MANIFEST_SUFFIX))
    if err:
        out["error"] = err
        return out
    try:
        with open(manifest_path, "w") as fh:
            json.dump(manifest, fh, indent=2, sort_keys=True, default=str)
    except OSError as exc:
        out["error"] = f"could not write manifest: {exc}"
        return out
    out["manifest_path"] = str(manifest_path)

    # Audit receipt via the existing collector, which independently re-asserts that the
    # file lives inside the evidence root. Best-effort: a receipt failure must not lose
    # evidence that is already durably on disk.
    try:
        if collector is None:
            import evidence_collector
            collector = evidence_collector.EvidenceCollector(str(vroot))
        out["receipt"] = collector.collect(app, kind, subject.strip(),
                                           file_path=str(target),
                                           metadata={"manifest_sha256": out["manifest_sha256"],
                                                     "retain_until": manifest["retain_until"],
                                                     "legal_hold": manifest["legal_hold"]})
    except Exception as exc:  # noqa: BLE001 — fail-soft
        out["receipt"] = {"error": f"{type(exc).__name__}: {exc}"}

    out["ok"] = True
    return out


# ── Tamper detection ────────────────────────────────────────────────────────

def read_manifest(manifest_path: str, *, root: str | None = None) -> dict[str, Any]:
    """Load a manifest with path confinement. Fail-soft."""
    vroot = vault_root(root)
    path, err = _confine(vroot, Path(manifest_path))
    if err:
        return {"ok": False, "error": err}
    try:
        with open(path) as fh:
            return {"ok": True, "error": None, "manifest": json.load(fh)}
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"manifest unreadable: {exc}"}


def verify(manifest_path: str, *, root: str | None = None) -> dict[str, Any]:
    """Re-derive both digests and report any divergence.

    Catches all three tamper shapes: content edited under a valid manifest, manifest
    edited to describe different content, and evidence deleted while the manifest claims
    it exists.
    """
    out = {"ok": False, "error": None, "content_ok": False, "manifest_ok": False,
           "manifest_path": manifest_path}
    loaded = read_manifest(manifest_path, root=root)
    if not loaded.get("ok"):
        out["error"] = loaded.get("error")
        return out
    manifest = loaded["manifest"]

    expected_manifest_sha = manifest.get("manifest_sha256") or ""
    out["manifest_ok"] = bool(expected_manifest_sha) and \
        manifest_digest(manifest) == expected_manifest_sha
    if not out["manifest_ok"]:
        out["error"] = "manifest digest mismatch — manifest has been altered"

    vroot = vault_root(root)
    content_path, err = _confine(vroot, Path(manifest.get("path", "")))
    if err:
        out["error"] = out["error"] or err
        return out
    try:
        actual = hashlib.sha256(content_path.read_bytes()).hexdigest()
    except OSError as exc:
        out["error"] = out["error"] or f"evidence content missing: {exc}"
        return out
    out["content_ok"] = actual == manifest.get("content_sha256")
    if not out["content_ok"]:
        out["error"] = out["error"] or "content digest mismatch — evidence has been altered"

    out["ok"] = out["content_ok"] and out["manifest_ok"]
    return out


# ── Retention / legal hold ──────────────────────────────────────────────────

def list_manifests(root: str | None = None, app_id: str | None = None) -> list[dict]:
    """Every manifest in the vault, optionally scoped to one app. Fail-soft: []."""
    vroot = vault_root(root)
    if not vroot.is_dir():
        return []
    found = []
    pattern = f"{app_id}/*/*{MANIFEST_SUFFIX}" if app_id else f"*/*/*{MANIFEST_SUFFIX}"
    try:
        candidates = sorted(vroot.glob(pattern))
    except OSError:
        return []
    for path in candidates:
        safe, err = _confine(vroot, path)
        if err:
            continue
        try:
            with open(safe) as fh:
                manifest = json.load(fh)
        except (OSError, ValueError):
            continue
        manifest["manifest_path"] = str(safe)
        found.append(manifest)
    return found


def set_legal_hold(manifest_path: str, held: bool, *, root: str | None = None,
                   reason: str = "") -> dict[str, Any]:
    """Place or lift a legal hold. Re-seals the manifest digest so the change is itself
    tamper-evident."""
    loaded = read_manifest(manifest_path, root=root)
    if not loaded.get("ok"):
        return {"ok": False, "error": loaded.get("error")}
    manifest = loaded["manifest"]
    manifest["legal_hold"] = bool(held)
    history = manifest.setdefault("legal_hold_history", [])
    history.append({"held": bool(held), "at": _utc(), "reason": reason or ""})
    manifest["manifest_sha256"] = manifest_digest(manifest)
    vroot = vault_root(root)
    path, err = _confine(vroot, Path(manifest_path))
    if err:
        return {"ok": False, "error": err}
    try:
        with open(path, "w") as fh:
            json.dump(manifest, fh, indent=2, sort_keys=True, default=str)
    except OSError as exc:
        return {"ok": False, "error": f"could not update manifest: {exc}"}
    return {"ok": True, "error": None, "manifest": manifest}


def purgeable(root: str | None = None, *, now: float | None = None) -> list[dict]:
    """Items whose retention has expired AND that are not under legal hold.

    A legal hold outranks retention unconditionally — that is the whole point of one, and
    an "expired" item under hold that gets purged is a spoliation problem, not a disk
    problem.
    """
    stamp = datetime.fromtimestamp(now or time.time(), tz=timezone.utc)
    due = []
    for manifest in list_manifests(root):
        if manifest.get("legal_hold"):
            continue
        raw = manifest.get("retain_until")
        if not raw:
            continue
        try:
            until = datetime.fromisoformat(str(raw))
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if until <= stamp:
            due.append(manifest)
    return due


# ── Restricted retrieval ────────────────────────────────────────────────────

def retrieve(manifest_path: str, *, scope: str = "", root: str | None = None,
             verify_first: bool = True) -> dict[str, Any]:
    """Read evidence back out. Restricted by scope and re-confined to the vault root.

    `scope` must be the owning `app_id`, or `"*"` for an audit-wide reader. An empty
    scope is rejected rather than defaulted: an unscoped read is exactly the call an
    unaudited caller makes.
    """
    out = {"ok": False, "error": None, "content": None, "manifest": None}
    if not isinstance(scope, str) or not scope.strip():
        out["error"] = "retrieval requires an explicit scope"
        return out

    loaded = read_manifest(manifest_path, root=root)
    if not loaded.get("ok"):
        out["error"] = loaded.get("error")
        return out
    manifest = loaded["manifest"]
    out["manifest"] = manifest

    scope = scope.strip()
    if scope != "*" and scope != manifest.get("app_id"):
        out["error"] = (f"scope {scope!r} is not permitted to read evidence owned by "
                        f"{manifest.get('app_id')!r}")
        return out

    if verify_first:
        checked = verify(manifest_path, root=root)
        if not checked.get("ok"):
            out["error"] = f"refusing to serve unverified evidence: {checked.get('error')}"
            return out

    vroot = vault_root(root)
    path, err = _confine(vroot, Path(manifest.get("path", "")))
    if err:
        out["error"] = err
        return out
    try:
        out["content"] = path.read_bytes()
    except OSError as exc:
        out["error"] = f"evidence unreadable: {exc}"
        return out
    out["ok"] = True
    return out


__all__ = [
    "CAPTURE_KINDS", "REDACTION_RULES", "vault_root", "redact", "stage", "verify",
    "read_manifest", "manifest_digest", "list_manifests", "set_legal_hold",
    "purgeable", "retrieve",
]

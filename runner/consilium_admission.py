"""Pure proposed export admission contract; no I/O, model calls, or activation.

The caller MUST provide a trusted verifier for commission_review, counsel_authorization,
and revocation_snapshot receipts. It must authenticate provenance, issuer authority,
current counsel role, scope, and signature over the complete supplied object. This
module does not turn caller-supplied booleans or database state labels into authority.
There is deliberately no default verifier. Existing production rows lack the new
content-binding/authorization receipts and therefore cannot pass this contract.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import uuid

SCHEMA = "consilium-admission/v1"
DESTINATION = "apparently-canonical"  # Law consumes through the same signed gateway.
MAX_BYTES = 131072
MAX_NODES = 10000
CARD_MAX_AGE = 30 * 86400
REVIEW_MAX_AGE = 7 * 86400
AUTH_MAX_AGE = 86400
REVOCATION_MAX_AGE = 300
FIELDS = (
    "id", "docket_id", "vertical", "question", "position", "verdict", "confidence",
    "citations", "assumptions", "dissent", "authority_chain", "minted_at",
    "flips_if", "conditions", "unsettled",
)
WEIGHTS = {"rigor": .24, "evidence": .24, "novelty": .18, "utility": .18, "risk": .16}


class InvalidReceipt(ValueError):
    pass


def canonical_bytes(value):
    """Versioned Python JSON canonicalization; no truncation or NaN/Infinity.

    Cross-language adapters must match sort_keys/ASCII escaping/compact separators
    exactly. Unknown internal card fields are excluded by artifact_payload first.
    """
    remaining = MAX_NODES
    remaining_chars = MAX_BYTES

    def visit(node, depth=0):
        nonlocal remaining, remaining_chars
        remaining -= 1
        if remaining < 0 or depth > 16:
            raise InvalidReceipt("receipt_bounds")
        if isinstance(node, dict):
            if any(not isinstance(k, str) or len(k) > 256 for k in node):
                raise InvalidReceipt("receipt_shape")
            remaining_chars -= sum(len(k) for k in node)
            for child in node.values():
                visit(child, depth + 1)
        elif isinstance(node, list):
            for child in node:
                visit(child, depth + 1)
        elif isinstance(node, str):
            remaining_chars -= len(node)
        elif node is not None and type(node) not in (bool, int, float):
            raise InvalidReceipt("receipt_shape")
        elif type(node) is float and not math.isfinite(node):
            raise InvalidReceipt("receipt_shape")
        elif type(node) is int and node.bit_length() > 128:
            raise InvalidReceipt("receipt_bounds")
        if remaining_chars < 0:
            raise InvalidReceipt("receipt_bounds")
    visit(value)
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                             allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise InvalidReceipt("receipt_shape") from None
    if len(encoded) > MAX_BYTES:
        raise InvalidReceipt("receipt_bounds")
    return encoded


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def artifact_payload(card):
    if not isinstance(card, dict) or any(key not in card for key in FIELDS):
        raise InvalidReceipt("artifact_shape")
    # Mutable status/publication state are checked separately, not reviewed content:
    # moving attorney_review -> published must not invalidate unchanged reasoning.
    # Copy through bounded serialization: callers cannot mutate an admitted envelope
    # by subsequently changing source objects. No original evidence is sliced.
    return json.loads(canonical_bytes({key: card[key] for key in FIELDS}))


def _uuid(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def _time(value):
    if not isinstance(value, str) or len(value) > 40:
        raise InvalidReceipt("timestamp_invalid")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.timestamp()
    except (ValueError, OverflowError):
        raise InvalidReceipt("timestamp_invalid") from None


def _fresh(value, now, ttl):
    at = _time(value)
    return at <= now < at + ttl


def admit(card, review, authorization, revocations, *, now, purpose, verify_receipt):
    """Return an export candidate + receipt, never evidence of export/use/value.

    `now` must be an aware datetime from a trusted server clock. The receipt expires
    with the earliest input. Consumers MUST revalidate revocations and expiry at use;
    a build-time snapshot alone cannot implement revocation. Public publication is
    a separate purpose from internal steering, each explicitly human-authorized.
    """
    base = {"schema": SCHEMA, "admitted": False, "destination": DESTINATION,
            "exported": False, "absorbed": False, "value": "unverified"}

    def deny(reason):
        return {**base, "reason": reason, "card": None}

    try:
        if not isinstance(now, dt.datetime) or now.tzinfo is None:
            return deny("clock_invalid")
        stamp = now.timestamp()
        if not math.isfinite(stamp) or purpose not in ("internal_steering", "publication"):
            return deny("scope_invalid")
        if not callable(verify_receipt):
            return deny("verifier_missing")
        payload = artifact_payload(card)
        for obj in (review, authorization, revocations):
            if not isinstance(obj, dict):
                return deny("receipt_missing")
            canonical_bytes(obj)
        if not _uuid(payload["id"]) or not all(isinstance(payload[k], str) and payload[k].strip()
                                                for k in ("question", "position", "vertical", "verdict")):
            return deny("artifact_shape")
        if card.get("status") != "fresh" or card.get("publication_state") != "published":
            return deny("artifact_not_admitted")
        if not _fresh(payload["minted_at"], stamp, CARD_MAX_AGE):
            return deny("artifact_expired")
        citations = payload["citations"]
        if not isinstance(citations, list) or not citations or any(not isinstance(c, dict) or not c for c in citations):
            return deny("evidence_invalid")
        artifact_hash, evidence_hash = digest(payload), digest(citations)
        if not _uuid(review.get("id")) or review.get("artifact_id") != payload["id"] or review.get("artifact_type") != "verdict_card":
            return deny("review_identity_mismatch")
        detail = review.get("detail")
        if not isinstance(detail, dict) or detail.get("artifact_sha256") != artifact_hash or detail.get("evidence_sha256") != evidence_hash:
            return deny("review_content_unbound")
        if detail.get("requires_rereview") is not False or detail.get("veto") is not None:
            return deny("review_unsettled")
        if review.get("decision") not in (("publish",) if purpose == "publication" else ("publish", "steer_only")):
            return deny("review_not_accepted")
        scores = detail.get("scores")
        if not isinstance(scores, dict) or any(type(scores.get(k)) not in (int, float) or not 0 <= scores[k] <= 1 for k in WEIGHTS):
            return deny("review_scores_invalid")
        composite = sum(scores[k] * weight for k, weight in WEIGHTS.items())
        try:
            reported = float(review.get("composite"))
        except (TypeError, ValueError):
            return deny("review_scores_invalid")
        floor = .78 if review["decision"] == "publish" else .62
        if (not math.isfinite(reported) or type(review.get("composite")) is bool or
                abs(reported - round(composite, 4)) > .00001 or composite < floor or
                scores["evidence"] < .4 or scores["risk"] < .4):
            return deny("review_scores_invalid")
        if not _fresh(detail.get("reviewed_at"), stamp, REVIEW_MAX_AGE) or _time(detail["reviewed_at"]) < _time(payload["minted_at"]):
            return deny("review_expired")
        review_hash = digest(review)
        expected = {"schema": "consilium-counsel-authorization/v1", "decision": "approved",
                    "artifact_id": payload["id"], "artifact_sha256": artifact_hash,
                    "evidence_sha256": evidence_hash, "review_id": review["id"],
                    "review_sha256": review_hash, "destination": DESTINATION, "purpose": purpose}
        if any(authorization.get(k) != v for k, v in expected.items()) or not _uuid(authorization.get("id")) or not _uuid(authorization.get("reviewer_id")):
            return deny("authorization_unbound")
        if (not _fresh(authorization.get("approved_at"), stamp, AUTH_MAX_AGE) or
                _time(authorization["approved_at"]) < _time(detail["reviewed_at"]) or
                _time(authorization.get("expires_at")) <= stamp):
            return deny("authorization_expired")
        if (revocations.get("schema") != "consilium-revocations/v1" or
                revocations.get("destination") != DESTINATION or revocations.get("complete") is not True):
            return deny("revocation_state_unknown")
        if not _fresh(revocations.get("checked_at"), stamp, REVOCATION_MAX_AGE) or _time(revocations.get("expires_at")) <= stamp:
            return deny("revocation_state_stale")
        for key, identifier in (("artifact_ids", payload["id"]), ("review_ids", review["id"]), ("authorization_ids", authorization["id"])):
            ids = revocations.get(key)
            if not isinstance(ids, list) or len(ids) > 1000 or any(not _uuid(i) for i in ids):
                return deny("revocation_state_unknown")
            if identifier in ids:
                return deny("revoked")
        for kind, obj in (("commission_review", review), ("counsel_authorization", authorization), ("revocation_snapshot", revocations)):
            # Pass defensive copies so a buggy verifier cannot mutate the envelope.
            if verify_receipt(kind, json.loads(canonical_bytes(obj))) is not True:
                return deny("provenance_unverified")
        expiry = min(_time(payload["minted_at"]) + CARD_MAX_AGE,
                     _time(detail["reviewed_at"]) + REVIEW_MAX_AGE,
                     _time(authorization["approved_at"]) + AUTH_MAX_AGE,
                     _time(authorization["expires_at"]),
                     _time(revocations["checked_at"]) + REVOCATION_MAX_AGE,
                     _time(revocations["expires_at"]))
        receipt = {**base, "admitted": True, "reason": "admitted_for_export_only", "purpose": purpose,
                   "artifact_id": payload["id"], "artifact_sha256": artifact_hash,
                   "evidence_sha256": evidence_hash, "review_id": review["id"], "review_sha256": review_hash,
                   "authorization_id": authorization["id"], "authorization_sha256": digest(authorization),
                   "revocations_sha256": digest(revocations), "checked_at": now.isoformat(),
                   "expires_at": dt.datetime.fromtimestamp(expiry, dt.timezone.utc).isoformat()}
        return {**receipt, "card": payload}
    except InvalidReceipt as exc:
        return deny(str(exc))
    except Exception:
        return deny("admission_verification_failed")

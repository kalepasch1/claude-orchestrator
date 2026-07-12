#!/usr/bin/env python3
"""
cx_proofpack_anchor.py - Rolling external anchor for the proof-hash chain.

Computes a rolling anchor over the latest determinations' proof_hash chain
(sha256 of the concatenated tail hashes + a timestamp) and stages it as an
inbox item (kind='proof_anchor') the owner can forward/sign externally.
Does NOT send anything itself (no secrets); just prepares the digest.
Read-only except the digest; does not edit committees.py.
"""
import os, sys, hashlib, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

TAIL_SIZE = int(os.environ.get("PROOF_ANCHOR_TAIL", "20"))


def run():
    """Compute a rolling anchor and stage it as an inbox digest."""
    dets = db.select("determinations", {
        "select": "id,proof_hash,created_at",
        "order": "created_at.desc",
        "limit": str(TAIL_SIZE),
    }) or []

    if not dets:
        return {"skipped": True, "reason": "no determinations found"}

    hashes = [d.get("proof_hash") or "" for d in dets]
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"
    payload = "".join(hashes) + timestamp
    anchor = hashlib.sha256(payload.encode()).hexdigest()

    body = (
        f"Rolling proof-chain anchor ({len(dets)} tail hashes)\n"
        f"Anchor: {anchor}\n"
        f"Timestamp: {timestamp}\n"
        f"Tail range: {dets[-1].get('created_at', '?')} .. {dets[0].get('created_at', '?')}\n\n"
        f"Forward this digest to your external timestamping service to anchor the chain."
    )

    db.insert("inbox", {
        "kind": "proof_anchor",
        "title": f"Proof-chain anchor {timestamp[:10]}",
        "body": body,
    })

    return {"created": True, "anchor": anchor, "tail_size": len(dets)}


if __name__ == "__main__":
    print(run())

#!/usr/bin/env python3
"""
db_docket_seed.py — the standing legal docket for the expert corps "data" vertical.

WHY. The Consilium answers questions on the `legal_docket`; the memo engine (db_memo)
argues six internal memos from database evidence. Until the data vertical has questions
docketed, the corps has nothing to seat experts against and no verdict cards to mint, so
the memos' positions (row-level isolation, contemporaneous records, retention, AI-call
logging, change control, resilience) never get an expert answer to lean on. Each question
below is phrased so its answer is a memo-grade POSITION one of db_memo.MEMO_KINDS can
cite: it names the legal standard and the concrete database fact the probes observe.

WRITES. Only `legal_docket` (control plane), one row per question, status 'pending',
unique on (vertical, question) so re-running is a no-op. Never an application database.
No model call: seeding is a fixed list. `ensure_seeded()` never raises.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DOCKET_TABLE = "legal_docket"
VERTICAL = "data"

#: {topic, priority, question}. `topic` is for reports and logs; only vertical, question,
#: priority and status are written. Keep questions stable: the unique key is the text.
DATA_DOCKET = [
    {"topic": "RLS enabled without policies",
     "priority": "high",
     "question": ("When does row-level security enabled without policies constitute reasonable "
                  "access control under GDPR Art. 32 and the ABA Model Rule 1.6(c) duty to "
                  "safeguard client information?")},
    {"topic": "RLS disabled on personal-data tables",
     "priority": "high",
     "question": ("Does a production table holding client or personal data with row-level security "
                  "disabled, reachable through a shared service role, satisfy the 'appropriate "
                  "technical and organisational measures' standard of GDPR Art. 32(1) and the "
                  "'reasonable security procedures' threshold of Cal. Civ. Code §1798.150, absent "
                  "evidence of actual unauthorised access?")},
    {"topic": "anon / public grants",
     "priority": "high",
     "question": ("Under what conditions do SELECT or INSERT grants to the anon or public database "
                  "roles on tables containing personal data amount to an unauthorised disclosure "
                  "under GDPR Art. 4(12) or a reportable breach under state breach-notification "
                  "statutes, when no access by an outsider has been shown?")},
    {"topic": "created_at / audit columns as business records",
     "priority": "high",
     "question": ("What must a database's created_at and updated_at columns, triggers and audit "
                  "tables demonstrate for its rows to qualify as records kept in the course of a "
                  "regularly conducted activity under FRE 803(6) and as contemporaneous business "
                  "records for spoliation and litigation-hold purposes?")},
    {"topic": "audit log without acting principal",
     "priority": "medium",
     "question": ("Does an audit trail that records what changed and when, but not the acting "
                  "principal (user, role or service), satisfy the accountability principle of GDPR "
                  "Art. 5(2) and the monitoring expectations of SOC 2 CC7.2, and what evidentiary "
                  "weight does such a log carry?")},
    {"topic": "soft-delete without purge / retention",
     "priority": "high",
     "question": ("When does retaining soft-deleted personal data indefinitely with no scheduled "
                  "purge breach the storage-limitation principle of GDPR Art. 5(1)(e) and the "
                  "retention disclosure duty of Cal. Civ. Code §1798.100(a)(3), and what purge "
                  "cadence evidenced by a scheduled job would a regulator accept?")},
    {"topic": "PII column inventory / minimisation",
     "priority": "medium",
     "question": ("What schema-level inventory of personal-data columns is required to support a "
                  "record of processing activities under GDPR Art. 30 and a data-subject access "
                  "request answered within the Art. 12(3) one-month window, and does the absence "
                  "of such an inventory itself evidence a failure of data minimisation under "
                  "Art. 5(1)(c)?")},
    {"topic": "AI model-call logging and disclosure",
     "priority": "high",
     "question": ("What per-call record (model, prompt provenance, timestamp, requesting principal, "
                  "output) must a firm keep for AI-assisted legal work to meet the disclosure and "
                  "supervision duties described in ABA Formal Opinion 512 and Model Rules 5.1 and "
                  "5.3, and does a model-call log table lacking timestamps defeat those duties?")},
    {"topic": "schema drift and change control",
     "priority": "medium",
     "question": ("Does production schema that has drifted from version-controlled migrations, or DDL "
                  "applied outside a reviewed migration, undermine the change-management control "
                  "expected under SOC 2 CC8.1 and ISO/IEC 27001:2022 Annex A 8.32, and how is that "
                  "argued from database catalog evidence alone?")},
    {"topic": "backups, PITR and operational resilience",
     "priority": "high",
     "question": ("What backup and point-in-time-recovery posture is required for a store of client "
                  "data to satisfy the restore-capability requirement of GDPR Art. 32(1)(c) and the "
                  "technology-competence duty of ABA Model Rule 1.1 Comment [8], and what recovery "
                  "point objective would be defensible for a legal-services provider?")},
    {"topic": "unindexed foreign keys as a reliability duty",
     "priority": "medium",
     "question": ("Can unindexed foreign keys and unvalidated constraints in a production database be "
                  "characterised as a breach of a reliability duty in negligence or under a "
                  "contractual service-level commitment when they cause an outage or a data-integrity "
                  "failure, and what evidence of foreseeability would a claimant need?")},
    {"topic": "SECURITY DEFINER functions and least privilege",
     "priority": "high",
     "question": ("When does a SECURITY DEFINER function that bypasses row-level security amount to an "
                  "unbounded privileged path that defeats a least-privilege claim under GDPR Art. 25 "
                  "data protection by design and NIST SP 800-53 control AC-6?")},
    {"topic": "e-discovery readiness",
     "priority": "medium",
     "question": ("What database-level properties (immutable timestamps, retention of resolved and "
                  "deleted records, exportable audit logs) make client data 'reasonably accessible' "
                  "for e-discovery under FRCP 26(b)(2)(B) and satisfy the litigation-hold duty "
                  "articulated in Zubulake v. UBS Warburg?")},
]


def docket_rows() -> list:
    """The legal_docket rows the seed writes (vertical, question, priority, status)."""
    return [{"vertical": VERTICAL, "question": q["question"], "priority": q["priority"],
             "status": "pending"} for q in DATA_DOCKET]


def ensure_seeded(db=None) -> dict:
    """Insert every DATA_DOCKET question for the data vertical; a None echo from
    `db.insert` (PostgREST 409 on the unique (vertical, question) key) means the row is
    already present. Idempotent, never raises, one insert per question and nothing else.
    Returns {"inserted": n, "present": m}; a control-plane failure yields zeros."""
    out = {"inserted": 0, "present": 0}
    try:
        if db is None:
            import db as _db
            db = _db
        for row in docket_rows():
            try:
                res = db.insert(DOCKET_TABLE, row)
            except Exception as e:
                print(f"db_docket_seed: insert failed for '{row['question'][:60]}...': "
                      f"{type(e).__name__}: {str(e)[:120]}")
                continue
            if res is None:
                out["present"] += 1
            else:
                out["inserted"] += 1
    except Exception as e:
        print(f"db_docket_seed: ensure_seeded aborted: {type(e).__name__}: {str(e)[:120]}")
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(ensure_seeded(), indent=2))

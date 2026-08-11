"""PROPRIETARY -- Apparently Inc. Trade Secret. Protected under DTSA (18 U.S.C. 1836).

Proof for the idempotent enqueue chokepoint (ranks 5+7 core). Pure; injected
store; deterministic; no DB.
"""
from runner.enqueue import normalize_slug, intent_key, enqueue_task


def test_normalize_collapses_fanout_and_version_suffixes():
    assert normalize_slug('foo-slice-3') == 'foo'
    assert normalize_slug('foo-item-2') == 'foo'
    assert normalize_slug('foo-group-1') == 'foo'
    assert normalize_slug('foo-chunk-10') == 'foo'
    assert normalize_slug('foo-v2') == 'foo'
    assert normalize_slug('foo-slice-3-slice-4') == 'foo'  # stacked
    assert normalize_slug('plain-intent') == 'plain-intent'


def test_intent_key_scopes_by_project_and_target_path():
    a = intent_key('p1', 'foo-slice-1', 'server/a.ts')
    b = intent_key('p1', 'foo-slice-2', 'server/a.ts')
    c = intent_key('p1', 'foo-slice-3', 'server/b.ts')
    assert a == b            # same base + target -> coalesce
    assert a != c            # distinct target -> do NOT over-collapse


class _Store:
    def __init__(self):
        self.rows = {}      # intent_key -> record
        self.inserts = 0
        self.bumps = []

    def find(self, key):
        return self.rows.get(key)

    def insert(self, record, key):
        self.inserts += 1
        rid = 'id-%d' % self.inserts
        self.rows[key] = {'id': rid, 'attempt': 0, **record}
        return rid

    def bump(self, existing):
        existing['attempt'] = existing.get('attempt', 0) + 1
        self.bumps.append(existing['id'])


def test_first_arrival_creates_then_duplicate_coalesces():
    s = _Store()
    r1 = enqueue_task({'project_id': 'p1', 'slug': 'do-thing-slice-1', 'target_path': 'x.ts'},
                      find_open_by_intent=s.find, insert=s.insert, bump=s.bump)
    r2 = enqueue_task({'project_id': 'p1', 'slug': 'do-thing-slice-2', 'target_path': 'x.ts'},
                      find_open_by_intent=s.find, insert=s.insert, bump=s.bump)
    assert r1.action == 'created'
    assert r2.action == 'coalesced'
    assert r1.intent_key == r2.intent_key
    assert s.inserts == 1                 # only ONE row minted for the two slices
    assert s.bumps == ['id-1']            # the second arrival bumped the first


def test_distinct_target_paths_both_persist():
    s = _Store()
    enqueue_task({'project_id': 'p1', 'slug': 'do-thing', 'target_path': 'a.ts'},
                 find_open_by_intent=s.find, insert=s.insert, bump=s.bump)
    r = enqueue_task({'project_id': 'p1', 'slug': 'do-thing', 'target_path': 'b.ts'},
                     find_open_by_intent=s.find, insert=s.insert, bump=s.bump)
    assert r.action == 'created'
    assert s.inserts == 2                 # distinct targets are not over-collapsed


def test_reads_target_path_from_assumptions_ledger():
    s = _Store()
    enqueue_task({'project_id': 'p1', 'slug': 'x-slice-1', 'assumptions': {'target_path': 't.ts'}},
                 find_open_by_intent=s.find, insert=s.insert, bump=s.bump)
    r = enqueue_task({'project_id': 'p1', 'slug': 'x-slice-9', 'assumptions': {'target_path': 't.ts'}},
                     find_open_by_intent=s.find, insert=s.insert, bump=s.bump)
    assert r.action == 'coalesced'
    assert s.inserts == 1
